import asyncio
import logging
from typing import Dict, Tuple, Any, Set
from telegram import Bot
from telegram.ext import Application
from telegram.constants import ParseMode
from telegram.error import TelegramError, RetryAfter, BadRequest
from .aria2_client import Aria2Client, Aria2TaskNotFoundError, Aria2Error
from . import utils

logger = logging.getLogger(__name__)

# 类型别名，提高可读性
# (chat_id, message_id) -> gid
MonitoredTasks = Dict[Tuple[int, int], str]
# (chat_id, message_id) -> last_text (用于比较避免重复编辑)
LastMessageContent = Dict[Tuple[int, int], str]

class TaskMonitor:
    """负责监控活动下载任务并更新其在 Telegram 中的消息状态"""

    def __init__(self, application: Application, update_interval: int = 5):
        """
        初始化 TaskMonitor

        Args:
            application: Telegram Bot Application 实例
            update_interval: 更新检查的时间间隔（秒）
        """
        self.application = application
        self.bot: Bot = application.bot
        # 确保依赖项已在 bot_data 中设置
        if 'aria2_client' not in application.bot_data:
             raise ValueError("Aria2Client not found in application.bot_data. Ensure it's set during setup.")
        self.aria2_client: Aria2Client = application.bot_data['aria2_client']

        # 从 bot_data 获取或初始化监控列表和最后内容缓存
        # 这允许在 Bot 重启时（如果 bot_data 被持久化）可能恢复监控状态
        self.monitored_tasks: MonitoredTasks = application.bot_data.setdefault('active_monitors', {})
        self.last_content: LastMessageContent = application.bot_data.setdefault('last_message_content', {})

        self.update_interval = update_interval
        self._monitor_task: asyncio.Task | None = None
        self._running = False
        logger.info("TaskMonitor initialized.")

    async def start(self):
        """启动后台监控循环"""
        if self._running:
            logger.warning("TaskMonitor is already running.")
            return
        if not self.aria2_client:
             logger.error("Aria2Client is not available. TaskMonitor cannot start.")
             return

        self._running = True
        # 创建后台任务来运行 _monitor_loop
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"TaskMonitor started with update interval: {self.update_interval} seconds.")

    async def stop(self):
        """停止后台监控循环"""
        self._running = False
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                # 等待任务实际完成取消
                await self._monitor_task
            except asyncio.CancelledError:
                logger.info("TaskMonitor task successfully cancelled.")
            except Exception as e:
                # 记录在等待取消过程中可能出现的其他异常
                logger.error(f"Error occurred while waiting for TaskMonitor task cancellation: {e}", exc_info=True)
        self._monitor_task = None # 清理任务引用
        logger.info("TaskMonitor stopped.")

    def register_task(self, chat_id: int, message_id: int, gid: str):
        """
        注册一个任务消息进行监控

        Args:
            chat_id: 消息所在的聊天 ID
            message_id: 要监控的消息 ID
            gid: 任务的 GID
        """
        key = (chat_id, message_id)
        if key in self.monitored_tasks and self.monitored_tasks[key] == gid:
             logger.debug(f"Task {gid} (chat={chat_id}, msg={message_id}) is already registered.")
             return

        self.monitored_tasks[key] = gid
        # 清除旧的缓存内容，确保第一次检查时会尝试更新
        if key in self.last_content:
            del self.last_content[key]
        logger.info(f"Registered task for monitoring: chat={chat_id}, msg={message_id}, gid={gid}")

    def unregister_task(self, chat_id: int, message_id: int):
        """
        取消对一个任务消息的监控

        Args:
            chat_id: 消息所在的聊天 ID
            message_id: 要取消监控的消息 ID
        """
        key = (chat_id, message_id)
        removed_gid = self.monitored_tasks.pop(key, None)
        if removed_gid:
            logger.info(f"Unregistered task from monitoring: chat={chat_id}, msg={message_id}, gid={removed_gid}")
        # 同时清理内容缓存
        self.last_content.pop(key, None)


    async def _monitor_loop(self):
        """后台监控循环，定期检查并更新任务状态"""
        while self._running:
            start_time = asyncio.get_event_loop().time()
            try:
                # 复制当前监控的任务列表进行操作，避免在迭代时修改
                current_monitors = list(self.monitored_tasks.items())

                if not current_monitors:
                    # 没有任务需要监控，等待下一个周期
                    await asyncio.sleep(self.update_interval)
                    continue

                logger.debug(f"TaskMonitor loop: Checking {len(current_monitors)} tasks.")

                # --- 并发获取所有任务状态 ---
                tasks_to_fetch = [self.aria2_client.get_download(gid) for _, gid in current_monitors]
                # 使用 return_exceptions=True 来处理单个任务查询失败的情况
                results = await asyncio.gather(*tasks_to_fetch, return_exceptions=True)

                # --- 处理查询结果 ---
                for i, result in enumerate(results):
                    key, gid = current_monitors[i]
                    chat_id, message_id = key

                    # 确保任务仍然在监控列表中（可能在 gather 期间被 unregister）
                    if key not in self.monitored_tasks:
                        logger.debug(f"Task {gid} (chat={chat_id}, msg={message_id}) was unregistered during fetch. Skipping update.")
                        continue

                    if isinstance(result, Aria2TaskNotFoundError):
                        # 任务在 Aria2 中找不到了，通常意味着已完成或被手动移除
                        logger.info(f"Task {gid} (chat={chat_id}, msg={message_id}) not found in Aria2. Assuming finished/removed. Unregistering.")
                        # 发送最终状态（无按钮）并取消注册
                        await self._update_message_final(chat_id, message_id, f"ℹ️ 任务 <code>{gid}</code> 已完成或被移除。", None)
                        self.unregister_task(chat_id, message_id)
                        continue
                    elif isinstance(result, Aria2Error):
                        # 获取状态时发生 Aria2 相关错误（非找不到）
                        logger.warning(f"Aria2Error getting status for task {gid} (chat={chat_id}, msg={message_id}): {result}. Keeping monitor active for now.")
                        # 可以选择性地更新消息提示错误，但暂时保持监控，可能只是临时网络问题
                        # await self._update_message_live(chat_id, message_id, f"⚠️ 查询任务 {gid} 状态时出错: {utils.escape_html(str(result))}", utils.create_task_control_keyboard(gid))
                        continue
                    elif isinstance(result, Exception):
                        # 发生了其他未预料的异常
                        logger.error(f"Unexpected error getting status for task {gid} (chat={chat_id}, msg={message_id}): {result}", exc_info=result)
                        # 发生未知错误，暂时不取消监控，避免丢失状态
                        continue

                    # --- 成功获取 task_info ---
                    task_info: Dict[str, Any] = result

                    # 检查任务是否已结束 (完成、错误、移除)
                    is_finished = task_info.get('is_complete') or task_info.get('is_removed') or task_info.get('status') == 'error'

                    if is_finished:
                        logger.info(f"Task {gid} (chat={chat_id}, msg={message_id}) finished with status: {task_info['status']}. Unregistering.")
                        final_text = utils.format_task_info_html(task_info)
                        # 发送最终状态（无按钮）并取消注册
                        await self._update_message_final(chat_id, message_id, f"📝 <b>任务详情 (GID: {gid})</b>\n\n{final_text}", None)
                        self.unregister_task(chat_id, message_id)
                    else:
                        # --- 任务进行中，更新消息 ---
                        new_text = utils.format_task_info_html(task_info)
                        full_message_text = f"📝 <b>任务详情 (GID: {gid})</b>\n\n{new_text}"
                        keyboard = utils.create_task_control_keyboard(gid)

                        # 优化：仅在内容变化时编辑消息
                        last_text = self.last_content.get(key)
                        if full_message_text != last_text:
                            updated = await self._update_message_live(chat_id, message_id, full_message_text, keyboard)
                            if updated:
                                # 更新成功，缓存新内容
                                self.last_content[key] = full_message_text
                            else:
                                # 如果更新失败（例如消息被删除），则取消监控
                                logger.warning(f"Failed to update message for task {gid} (chat={chat_id}, msg={message_id}). Unregistering.")
                                self.unregister_task(chat_id, message_id)
                        else:
                             logger.debug(f"Task {gid} (chat={chat_id}, msg={message_id}) content unchanged. Skipping update.")

            except asyncio.CancelledError:
                logger.info("TaskMonitor loop cancelled.")
                # 当循环被取消时，退出循环
                break
            except Exception as e:
                # 捕获循环中的其他未知错误，记录日志并继续
                logger.error(f"Critical error in TaskMonitor loop: {e}", exc_info=True)
                # 防止因临时错误导致循环完全停止，等待一段时间后重试
                await asyncio.sleep(self.update_interval * 2)

            # --- 计算本次循环耗时并调整睡眠时间 ---
            elapsed_time = asyncio.get_event_loop().time() - start_time
            sleep_duration = max(0, self.update_interval - elapsed_time)
            if sleep_duration > 0:
                await asyncio.sleep(sleep_duration)


    async def _update_message_live(self, chat_id: int, message_id: int, text: str, reply_markup) -> bool:
        """
        尝试更新活动任务的消息，处理潜在的 Telegram API 错误。

        Args:
            chat_id: 聊天 ID
            message_id: 消息 ID
            text: 新的消息文本
            reply_markup: 新的内联键盘

        Returns:
            bool: 更新是否成功（或消息未修改）
        """
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML
            )
            logger.debug(f"Updated message: chat={chat_id}, msg={message_id}")
            return True
        except RetryAfter as e:
            # 处理速率限制
            logger.warning(f"Rate limit hit when updating message (chat={chat_id}, msg={message_id}). Retrying after {e.retry_after}s.")
            await asyncio.sleep(e.retry_after)
            # 简单重试一次
            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )
                logger.info(f"Successfully updated message after retry: chat={chat_id}, msg={message_id}")
                return True
            except TelegramError as e_retry:
                 logger.error(f"Failed to update message after retry (chat={chat_id}, msg={message_id}): {e_retry}")
                 return False # 重试失败，认为更新失败
        except BadRequest as e:
            # 处理特定 BadRequest 错误
            error_text = str(e).lower()
            if "message is not modified" in error_text:
                # 消息未修改不是真正的错误，只是无需更新
                logger.debug(f"Message not modified (chat={chat_id}, msg={message_id}). Skipping.")
                return True # 返回 True，因为消息仍然存在且状态一致
            elif "message to edit not found" in error_text or "chat not found" in error_text:
                # 消息或聊天已被删除
                logger.warning(f"Message or chat not found (chat={chat_id}, msg={message_id}). Assuming deleted.")
                return False # 返回 False，以便调用者取消监控
            else:
                # 其他未处理的 BadRequest
                logger.error(f"Unhandled BadRequest updating message (chat={chat_id}, msg={message_id}): {e}")
                return False # 认为更新失败
        except TelegramError as e:
            # 处理其他 Telegram API 错误
            logger.error(f"TelegramError updating message (chat={chat_id}, msg={message_id}): {e}")
            return False # 认为更新失败
        except Exception as e:
             # 捕获其他意外错误
             logger.error(f"Unexpected error updating message (chat={chat_id}, msg={message_id}): {e}", exc_info=True)
             return False # 认为更新失败

    async def _update_message_final(self, chat_id: int, message_id: int, text: str, reply_markup):
        """
        尝试更新任务结束时的消息，忽略大多数错误，因为这只是最终状态。

        Args:
            chat_id: 聊天 ID
            message_id: 消息 ID
            text: 最终的消息文本
            reply_markup: 最终的键盘布局（通常为 None）
        """
        try:
            await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=reply_markup, # 通常为 None 来移除按钮
                parse_mode=ParseMode.HTML
            )
            logger.debug(f"Updated final message state: chat={chat_id}, msg={message_id}")
        except TelegramError as e:
            # 结束时更新失败通常不影响核心功能，记录警告即可
            if "message to edit not found" not in str(e).lower() and "message is not modified" not in str(e).lower():
                 logger.warning(f"Failed to update final message (chat={chat_id}, msg={message_id}): {e}")
        except Exception as e:
             logger.error(f"Unexpected error updating final message (chat={chat_id}, msg={message_id}): {e}", exc_info=True)

# --- 单例模式 (可选，取决于你如何在应用中管理它) ---
_task_monitor_instance: TaskMonitor | None = None

def get_task_monitor(application: Application | None = None, update_interval: int = 5) -> TaskMonitor:
    """
    获取 TaskMonitor 的单例实例。

    Args:
        application: Telegram Bot Application 实例 (首次调用时必须提供)
        update_interval: 更新间隔 (仅在首次创建实例时生效)

    Returns:
        TaskMonitor 实例

    Raises:
        ValueError: 如果首次调用时未提供 application 实例
    """
    global _task_monitor_instance
    if _task_monitor_instance is None:
        if application is None:
            raise ValueError("Application instance must be provided when creating the TaskMonitor for the first time.")
        _task_monitor_instance = TaskMonitor(application, update_interval)
    return _task_monitor_instance