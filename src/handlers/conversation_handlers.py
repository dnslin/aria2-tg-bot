import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    CallbackQueryHandler,
)
from telegram.constants import ParseMode

# 导入项目模块时，使用相对导入
from .. import utils
from .. import auth
from ..history import DatabaseError, HistoryManager # Added HistoryManager import

# 设置日志记录器
logger = logging.getLogger(__name__)

# 会话状态定义
CONFIRM_CLEAR = 1

# --- 会话处理函数 ---

async def cmd_clearhistory_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理 /clearhistory 命令，启动清空历史记录确认流程"""
    if not await auth.check_authorized(update):
        return ConversationHandler.END

    # 使用内联键盘进行确认
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ 是，确认清空", callback_data="clear_history_confirm"),
         InlineKeyboardButton("❌ 否，取消", callback_data="clear_history_cancel")]
    ])

    await update.message.reply_text(
        "🤔 <b>确认清空</b>\n\n"
        "您确定要清空所有下载历史记录吗？\n"
        "<b>此操作无法撤销！</b>",
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )

    return CONFIRM_CLEAR # 进入确认状态

async def cmd_clearhistory_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理确认清空历史记录 (CallbackQueryHandler)"""
    query = update.callback_query
    await query.answer() # 响应按钮点击

    if not await auth.check_authorized(update):
        return ConversationHandler.END

    # 从 context 获取依赖
    history_manager: HistoryManager = context.bot_data['history_manager']

    try:
        # 编辑原消息，显示正在处理
        await query.edit_message_text(
            "⚙️ 正在清空历史记录...",
            parse_mode=ParseMode.HTML
        )

        count = await history_manager.clear_history()

        await query.edit_message_text(
            f"🗑️ <b>历史记录已清空</b>\n"
            f"已删除 {count} 条记录",
            parse_mode=ParseMode.HTML
        )

    except DatabaseError as e:
         logger.warning(f"清空历史记录失败 (DatabaseError): {e}")
         await query.edit_message_text(
            f"❌ <b>清空历史记录失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"清空历史记录时发生未知错误: {e}", exc_info=True)
        await query.edit_message_text(
            f"🆘 <b>系统错误:</b> 清空历史记录时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

    return ConversationHandler.END # 结束会话

async def cmd_clearhistory_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理取消清空历史记录 (CallbackQueryHandler)"""
    query = update.callback_query
    await query.answer() # 响应按钮点击

    await query.edit_message_text(
        "🚫 <b>操作已取消</b>\n"
        "历史记录未被清空",
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END # 结束会话

async def cmd_clearhistory_cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """处理 /cancel 命令来取消清空历史记录"""
    await update.message.reply_text(
        "🚫 <b>操作已取消</b>\n"
        "清空历史记录操作已取消。",
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END # 结束会话

# --- ConversationHandler 定义 ---

clear_history_conv_handler = ConversationHandler(
    entry_points=[CommandHandler("clearhistory", cmd_clearhistory_start)],
    states={
        CONFIRM_CLEAR: [
            CallbackQueryHandler(cmd_clearhistory_confirm, pattern="^clear_history_confirm$"),
            CallbackQueryHandler(cmd_clearhistory_cancel, pattern="^clear_history_cancel$"),
        ],
    },
    fallbacks=[CommandHandler("cancel", cmd_clearhistory_cancel_command)],
    conversation_timeout=60
)

# 可以将所有会话处理器放入一个列表，方便在 bot_app.py 中注册
conversation_handlers = [clear_history_conv_handler]