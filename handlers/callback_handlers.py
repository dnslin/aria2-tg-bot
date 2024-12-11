import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.aria2_client import aria2
from handlers.message_handlers import download_messages
from utils.formatters import format_progress_bar, format_size, format_time, get_seconds_from_timedelta

def get_control_buttons(gid: str, is_paused: bool = False) -> InlineKeyboardMarkup:
    """获取控制按钮"""
    buttons = []
    if is_paused:
        buttons.append(InlineKeyboardButton("▶️ 继续", callback_data=f"resume_{gid}"))
    else:
        buttons.append(InlineKeyboardButton("⏸ 暂停", callback_data=f"pause_{gid}"))
    
    buttons.extend([
        InlineKeyboardButton("⏹ 停止", callback_data=f"stop_{gid}"),
        InlineKeyboardButton("重试", callback_data=f"retry_{gid}")
    ])
    
    return InlineKeyboardMarkup([buttons])

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """更新下载进度"""
    # ... (保持原来的代码不变)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理按钮回调"""
    # ... (保持原来的代码不变) 