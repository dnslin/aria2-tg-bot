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
from src.bot import TelegramBot, NotificationService

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
    bot_task = None

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

        # 初始化 Telegram Bot
        logger.info("正在初始化 Telegram Bot...")
        try:
            # Pass dependencies to TelegramBot constructor
            bot = TelegramBot(aria2_client, history_manager)
            await bot.setup() # 设置 handlers 等
            logger.info("Telegram Bot 初始化完成")
        except Exception as e:
            logger.error(f"初始化 Telegram Bot 失败: {e}", exc_info=True)
            sys.exit(1)

        # 初始化并启动调度器（如果启用了通知）
        if config.notification_enabled:
            logger.info("正在初始化通知服务和调度器...")
            try:
                scheduler = AsyncIOScheduler(timezone="Asia/Shanghai") # 可根据需要配置时区
                # Pass history_manager dependency to NotificationService constructor
                notification_service = NotificationService(bot.application, history_manager)
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

        # 启动 Bot (作为后台任务)
        logger.info("正在启动 Telegram Bot...")
        bot_task = asyncio.create_task(bot.run())

        # 等待 Bot 任务完成或被中断
        await bot_task

    except asyncio.CancelledError:
        logger.info("主任务被取消")
    except Exception as e:
        logger.critical(f"主程序发生未捕获的严重错误: {e}", exc_info=True)
    finally:
        logger.info("开始关闭程序...")

        # 停止调度器
        if scheduler and scheduler.running:
            logger.info("正在关闭调度器...")
            try:
                scheduler.shutdown(wait=False)
                logger.info("调度器已关闭")
            except Exception as e:
                logger.error(f"关闭调度器时出错: {e}", exc_info=True)

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