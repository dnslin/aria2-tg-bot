import logging
import asyncio
from typing import Dict, Any

from telegram.ext import Application
from telegram.constants import ParseMode

from .config import get_config
from .history import HistoryManager # Assuming HistoryManager is imported directly in history.py
from . import utils

# 设置日志记录器
logger = logging.getLogger(__name__)

# 处理下载任务通知的类
class NotificationService:
    """
    处理下载任务完成/失败通知的服务类
    需要在主程序中定期调用 check_and_notify 方法
    """
    # Applying Dependency Injection: Injecting dependencies via constructor
    def __init__(self, bot_app: Application, history_manager: HistoryManager):
        """
        初始化通知服务

        Args:
            bot_app: Telegram Bot Application 实例
            history_manager: 历史记录管理器实例
        """
        self.bot_app = bot_app
        self.config = get_config()
        self.history_manager = history_manager # Injected dependency
        self.notify_users = self.config.notify_users

        logger.info(f"通知服务已初始化，通知用户: {self.notify_users}")

    async def check_and_notify(self) -> None:
        """检查新完成/出错的下载任务并发送通知"""
        if not self.config.notification_enabled:
            return # 如果配置中禁用了通知，则直接返回

        try:
            # 获取未通知的完成/出错任务
            # 使用注入的 HistoryManager 实例
            unnotified_tasks = await self.history_manager.get_unnotified_completed()

            if not unnotified_tasks:
                return

            logger.info(f"发现 {len(unnotified_tasks)} 个未通知的任务")

            # 对每个任务发送通知并标记为已通知
            for task in unnotified_tasks:
                # 增加一点延迟，避免短时间内发送过多消息触发 Telegram 限制
                await asyncio.sleep(1)
                await self._send_notification(task)
                await self.history_manager.mark_as_notified(task['gid'])

        except Exception as e:
            logger.error(f"检查和发送通知时发生错误: {e}", exc_info=True)

    async def _send_notification(self, task: Dict[str, Any]) -> None:
        """
        发送单个任务的通知

        Args:
            task: 任务信息字典
        """
        try:
            # 根据任务状态准备通知内容
            status = task['status']

            if status == 'completed':
                icon = "✅"
                status_text = "下载完成"
            elif status == 'error':
                icon = "❌"
                status_text = "下载失败"
            else:
                return  # 忽略其他状态

            # 格式化通知消息
            name = task['name']
            gid = task['gid']
            size = utils.format_size(task['size'] or 0)
            datetime_str = task['datetime']

            message_text = (
                f"{icon} <b>{status_text}</b>\n\n"
                f"<b>文件名:</b> {utils.escape_html(name)}\n"
                f"<b>GID:</b> <code>{gid}</code>\n"
                f"<b>大小:</b> {size}\n"
                f"<b>时间:</b> {datetime_str}"
            )

            if status == 'error' and task.get('error_message'):
                message_text += f"\n<b>错误:</b> {utils.escape_html(task['error_message'])}"

            # 向所有配置的通知用户发送消息
            for user_id in self.notify_users:
                try:
                    await self.bot_app.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"已向用户 {user_id} 发送 GID={gid} 的通知")
                except Exception as send_error:
                    logger.error(f"向用户 {user_id} 发送通知失败: {send_error}")

        except Exception as e:
            logger.error(f"发送通知时发生错误 (GID={task.get('gid', '未知')}): {e}", exc_info=True)