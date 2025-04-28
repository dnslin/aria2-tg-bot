import logging
import asyncio
import traceback
from typing import Dict, Any

from telegram import Update, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ApplicationBuilder, # Use ApplicationBuilder
)
from telegram.constants import ParseMode

# 导入项目模块
from .config import Config
from .aria2_client import Aria2Client
from .history import HistoryManager
from .state.page_state import PageStateManager, get_page_state_manager
from . import utils
from .handlers import command_handlers, callback_handlers, conversation_handlers

# 设置日志记录器
logger = logging.getLogger(__name__)

# --- 错误处理函数 ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理程序运行时发生的错误"""
    logger.error("发生异常:", exc_info=context.error)

    # 获取异常的可读描述
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb_string = "".join(tb_list)

    # 简短的异常描述
    error_message = f"发生错误: {context.error}"

    # 对于 Update 对象，我们可以向用户发送消息
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text(
                f"🆘 <b>系统错误</b>\n\n发生了一个内部错误，请稍后再试或联系管理员。\n错误详情: <code>{utils.escape_html(str(context.error))}</code>",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            logger.error(f"发送错误消息给用户失败: {e}")
    elif isinstance(update, Update) and update.callback_query:
         try:
            await update.callback_query.answer(f"🆘 系统错误: {str(context.error)[:150]}", show_alert=True)
         except Exception as e:
            logger.error(f"发送回调错误提示失败: {e}")

# --- Bot 应用运行器 ---
class BotApplicationRunner:
    """负责设置、运行和管理 Telegram Bot Application"""

    def __init__(self, config: Config, aria2_client: Aria2Client, history_manager: HistoryManager, page_state_manager: PageStateManager):
        """
        初始化 BotApplicationRunner

        Args:
            config: 配置对象
            aria2_client: Aria2 客户端实例
            history_manager: 历史记录管理器实例
            page_state_manager: 分页状态管理器实例
        """
        self.config = config
        self.aria2_client = aria2_client
        self.history_manager = history_manager
        self.page_state_manager = page_state_manager
        self.application: Application = None # type: ignore
        logger.info("BotApplicationRunner 初始化...")

    async def setup(self) -> None:
        """
        设置 Bot Application, 包括构建、添加处理器和设置 bot_data
        """
        logger.info("开始设置 Telegram Application...")
        # 创建 Application Builder
        builder = Application.builder().token(self.config.telegram_token)

        # 检查并应用自定义 API 接入点
        api_base_url = self.config.telegram_api_base_url
        if api_base_url:
            logger.info(f"使用自定义 Telegram API 接入点: {api_base_url}")
            builder = builder.base_url(api_base_url)
        else:
            logger.info("使用官方 Telegram API 接入点")

        # 构建 Application
        self.application = builder.build()

        # 将依赖项存入 bot_data
        self.application.bot_data['config'] = self.config
        self.application.bot_data['aria2_client'] = self.aria2_client
        self.application.bot_data['history_manager'] = self.history_manager
        self.application.bot_data['page_state_manager'] = self.page_state_manager
        # 初始化一个空的 states 字典，以防万一旧代码引用（最好是移除所有旧引用）
        self.application.bot_data.setdefault('states', {})
        logger.debug("依赖项已添加到 bot_data")

        # --- 注册处理器 ---
        # 注册命令处理器
        command_mapping = {
            "start": command_handlers.cmd_start,
            "help": command_handlers.cmd_help,
            "add": command_handlers.cmd_add,
            "status": command_handlers.cmd_status,
            "pause": command_handlers.cmd_pause,
            "unpause": command_handlers.cmd_unpause,
            "remove": command_handlers.cmd_remove,
            "pauseall": command_handlers.cmd_pauseall,
            "unpauseall": command_handlers.cmd_unpauseall,
            "history": command_handlers.cmd_history,
            "globalstatus": command_handlers.cmd_globalstatus,
            "searchhistory": command_handlers.cmd_searchhistory,
            # 注意: clearhistory 是会话入口点，不在这里单独注册
        }
        for name, handler_func in command_mapping.items():
            self.application.add_handler(CommandHandler(name, handler_func))
            logger.debug(f"注册命令处理器: /{name}")

        # 注册回调查询处理器 (非会话)
        self.application.add_handler(
            CallbackQueryHandler(callback_handlers.handle_callback, pattern="^(?!clear_history_)")
        )
        logger.debug("注册通用回调查询处理器")

        # 注册会话处理器
        self.application.add_handlers(conversation_handlers.conversation_handlers)
        logger.debug(f"注册了 {len(conversation_handlers.conversation_handlers)} 个会话处理器")

        # 注册错误处理器
        self.application.add_error_handler(error_handler)
        logger.debug("注册错误处理器")
        # --- 处理器注册完毕 ---

        # 设置命令列表
        bot_commands = [
            BotCommand("add", "添加下载任务 - /add <url_or_magnet>"),
            BotCommand("status", "查看任务状态 - /status [gid]"),
            BotCommand("pause", "暂停指定任务 - /pause <gid>"),
            BotCommand("unpause", "恢复指定任务 - /unpause <gid>"),
            BotCommand("remove", "删除指定任务 - /remove <gid>"),
            BotCommand("pauseall", "暂停所有任务 - /pauseall"),
            BotCommand("unpauseall", "恢复所有任务 - /unpauseall"),
            BotCommand("history", "浏览下载历史 - /history"),
            BotCommand("clearhistory", "清空下载历史 - /clearhistory"),
            BotCommand("globalstatus", "查看全局状态 - /globalstatus"),
            BotCommand("searchhistory", "搜索下载历史 - /searchhistory <keyword>"),
            BotCommand("help", "显示帮助 - /help")
        ]
        try:
            await self.application.bot.set_my_commands(bot_commands)
            logger.info("Bot 命令列表设置成功")
        except Exception as e:
             logger.error(f"设置 Bot 命令列表失败: {e}")


        logger.info("Telegram Application 设置完成")

    async def run(self) -> None:
        """启动 Bot 应用"""
        if not self.application:
            await self.setup()

        logger.info("启动 Telegram Bot polling...")
        try:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()
            logger.info("Telegram Bot 启动成功，开始接收消息...")
            # 保持运行，直到被外部取消
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            logger.info("Bot run task cancelled.")
        except Exception as e:
             logger.error(f"Bot 运行期间发生致命错误: {e}", exc_info=True)
        finally:
            logger.info("正在关闭 Telegram Bot...")
            if self.application and self.application.updater and self.application.updater.running:
                 await self.application.updater.stop()
            if self.application:
                await self.application.stop()
                await self.application.shutdown()
            logger.info("Telegram Bot 已关闭")