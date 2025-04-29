"""
Aria2 Telegram Bot 主程序入口
"""

import asyncio
import logging
import logging.handlers
import os
import signal
import sys

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from src.config import get_config, ConfigError
from src.aria2_client import get_aria2_client, Aria2ConnectionError
from src.history import get_history_manager, HistoryError
# 更新导入以反映重构
from src.bot_app import BotApplicationRunner
from src.notification_service import NotificationService
from src.state.page_state import get_page_state_manager
from src.task_monitor import get_task_monitor, TaskMonitor # 新增导入

# 配置日志记录器
logger = logging.getLogger() # 获取根 logger

def setup_logging():
    """根据配置设置日志记录"""
    try:
        config = get_config()
        log_config = config.logging_config

        log_level_str = log_config.get("level", "INFO").upper()
        log_level = getattr(logging, log_level_str, logging.INFO)
        log_format = log_config.get("format", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        log_file = log_config.get("file") # 可选

        formatter = logging.Formatter(log_format)

        # 配置根 logger
        logger.setLevel(log_level)

        # 配置控制台输出
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

        # 配置文件输出（如果指定了路径）
        if log_file:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)

            max_size = log_config.get("max_size", 10 * 1024 * 1024) # 默认 10MB
            backup_count = log_config.get("backup_count", 3)

            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=max_size,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
            logger.info(f"日志将记录到文件: {log_file}")

        else:
            logger.info("未配置文件日志，日志仅输出到控制台")

        # 设置第三方库的日志级别（可选，减少冗余信息）
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
        logging.getLogger("telegram").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("aria2p").setLevel(logging.INFO) # aria2p 的日志可能有用

        logger.info(f"日志级别设置为: {log_level_str}")

    except Exception as e:
        # 在日志系统设置失败时，使用基本配置打印错误
        logging.basicConfig(level=logging.ERROR)
        logger.error(f"设置日志记录失败: {e}", exc_info=True)
        sys.exit(1)


async def main():
    """主异步函数"""
    # 加载配置并设置日志
    try:
        config = get_config()
        setup_logging()
    except ConfigError as e:
        logging.basicConfig(level=logging.ERROR) # 确保错误能打印出来
        logger.error(f"配置文件错误: {e}")
        sys.exit(1)
    except Exception as e:
        logging.basicConfig(level=logging.ERROR)
        logger.error(f"启动时发生未知错误: {e}", exc_info=True)
        sys.exit(1)

    scheduler = None
    history_manager = None
    page_state_manager = None # 添加页面状态管理器
    bot_runner = None # 重命名 bot 实例
    bot_task = None
    task_monitor = None # 新增 TaskMonitor 实例变量

    try:
        # 初始化 Aria2 客户端并检查连接
        logger.info("正在初始化 Aria2 客户端...")
        try:
            aria2_client = await get_aria2_client()
            # 尝试获取版本信息以验证连接
            version_info = await aria2_client.get_global_status()
            logger.info(f"成功连接到 Aria2 (版本: {version_info.get('version', '未知')})")
        except Aria2ConnectionError as e:
            logger.error(f"无法连接到 Aria2 RPC 服务器: {e}")
            logger.error("请检查 config.yaml 中的 Aria2 配置以及 Aria2 是否正在运行。")
            sys.exit(1)
        except Exception as e:
            logger.error(f"初始化 Aria2 客户端时出错: {e}", exc_info=True)
            sys.exit(1)

        # 初始化历史记录管理器
        logger.info("正在初始化历史记录管理器...")
        try:
            history_manager = await get_history_manager()
            # init_db 已经在 get_history_manager 中调用
            logger.info("历史记录管理器初始化完成")
        except HistoryError as e:
            logger.error(f"初始化历史记录数据库失败: {e}")
            sys.exit(1)
        except Exception as e:
            logger.error(f"初始化历史记录管理器时出错: {e}", exc_info=True)
            sys.exit(1)

        # 初始化分页状态管理器
        logger.info("正在初始化分页状态管理器...")
        page_state_manager = get_page_state_manager() # 获取实例
        logger.info("分页状态管理器初始化完成")


        # 初始化 BotApplicationRunner
        logger.info("正在初始化 Bot 应用运行器...")
        try:
            # 注入所有依赖项
            bot_runner = BotApplicationRunner(config, aria2_client, history_manager, page_state_manager)
            await bot_runner.setup() # 设置 handlers, bot_data 等
            logger.info("Bot 应用运行器初始化完成")
        except Exception as e:
            logger.error(f"初始化 Bot 应用运行器失败: {e}", exc_info=True)
            sys.exit(1)

        # 初始化并启动调度器（如果启用了通知）
        if config.notification_enabled:
            logger.info("正在初始化通知服务和调度器...")
            try:
                scheduler = AsyncIOScheduler(timezone="Asia/Shanghai") # 可根据需要配置时区
                # 将 Application 实例和 history_manager 注入 NotificationService
                notification_service = NotificationService(bot_runner.application, history_manager)
                interval = config.notification_interval
                scheduler.add_job(
                    notification_service.check_and_notify,
                    'interval',
                    seconds=interval,
                    id='notification_check',
                    name='Download Notification Check'
                )
                scheduler.start()
                logger.info(f"通知检查任务已启动，间隔: {interval} 秒")
            except Exception as e:
                logger.error(f"启动通知调度器失败: {e}", exc_info=True)
                # 不退出，允许 Bot 在没有通知的情况下运行
                scheduler = None # 确保 scheduler 为 None
        else:
            logger.info("下载通知功能已禁用")

        # 初始化并启动 TaskMonitor (在 Bot Runner 设置之后)
        logger.info("正在初始化任务监控器...")
        try:
            # 使用配置的更新间隔，或默认 5 秒
            monitor_interval = config.get('monitor', 'interval', 5)
            task_monitor = get_task_monitor(application=bot_runner.application, update_interval=monitor_interval)
            await task_monitor.start()
            logger.info("任务监控器已启动")
        except Exception as e:
            logger.error(f"启动任务监控器失败: {e}", exc_info=True)
            # 即使监控器失败，也允许 Bot 继续运行
            task_monitor = None

        # 启动 Bot (作为后台任务)
        logger.info("正在启动 Bot 应用运行器...")
        # bot_runner.run() 内部处理了循环和关闭逻辑
        bot_task = asyncio.create_task(bot_runner.run())

        # 等待 Bot 任务完成或被中断
        await bot_task

    except asyncio.CancelledError:
        logger.info("主任务被取消")
    except Exception as e:
        logger.critical(f"主程序发生未捕获的严重错误: {e}", exc_info=True)
    finally:
        logger.info("开始关闭程序...")

        # 停止 TaskMonitor
        if task_monitor and task_monitor._running: # 检查是否正在运行
            logger.info("正在关闭任务监控器...")
            try:
                await task_monitor.stop()
                logger.info("任务监控器已关闭")
            except Exception as e:
                logger.error(f"关闭任务监控器时出错: {e}", exc_info=True)

        # 停止调度器
        if scheduler and scheduler.running:
            logger.info("正在关闭调度器...")
            try:
                logger.info("准备关闭调度器 (wait=False)...")
                scheduler.shutdown(wait=False)
                logger.info("调度器 shutdown() 调用完成")
            except Exception as e:
                logger.error(f"关闭调度器时出错: {e}", exc_info=True)
            finally:
                 # 尝试记录调度器关闭后的状态或线程信息
                 logger.info(f"调度器关闭后状态: running={scheduler.running if scheduler else 'N/A'}")

        # 关闭历史数据库连接
        if history_manager:
            logger.info("正在关闭历史数据库连接...")
            try:
                await history_manager.close()
                logger.info("历史数据库连接已关闭")
            except Exception as e:
                logger.error(f"关闭历史数据库时出错: {e}", exc_info=True)

        # 确保 Bot 任务被取消（如果仍在运行）
        if bot_task and not bot_task.done():
            logger.info("正在取消 Bot 任务...")
            bot_task.cancel()
            try:
                await bot_task # 等待任务实际取消
            except asyncio.CancelledError:
                pass # 预期中的异常
            except Exception as e:
                 logger.error(f"等待 Bot 任务取消时出错: {e}", exc_info=True)

        logger.info("即将完成程序关闭...")
        # 尝试打印活动线程
        try:
            import threading
            active_threads = threading.enumerate()
            logger.info(f"程序关闭前活动线程 ({len(active_threads)}): {[t.name for t in active_threads]}")
        except Exception as e:
            logger.warning(f"获取活动线程列表时出错: {e}")
        logger.info("程序关闭完成")


def handle_signal(sig, frame):
    """处理终止信号"""
    logger.warning(f"收到信号 {sig}, 正在优雅地关闭...")
    # 获取当前运行的事件循环并取消所有任务
    loop = asyncio.get_running_loop()
    for task in asyncio.all_tasks(loop):
        task.cancel()
    # 不需要显式调用 loop.stop()，取消任务会触发 finally 块

if __name__ == "__main__":
    # 设置信号处理程序以实现优雅关闭
    if sys.platform != "win32": # Windows 不支持 SIGTERM
        signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal) # 处理 Ctrl+C

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("通过 KeyboardInterrupt 强制退出")
    except asyncio.CancelledError:
         logger.info("主事件循环被取消")