from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from utils.keyboard_utils import get_task_list_buttons

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """获取主键盘按钮"""
    keyboard = [
        [KeyboardButton("📥 下载任务"), KeyboardButton("⏸ 暂停任务")],
        [KeyboardButton("▶️ 继续任务"), KeyboardButton("⏹ 停止任务")],
        [KeyboardButton("🗑️ 清理任务"), KeyboardButton("📋 任务列表")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令"""
    await update.message.reply_text(
        "👋 欢迎使用下载机器人！\n\n"
        "你可以发送以下类型的链接：\n"
        "- HTTP/HTTPS 链接\n"
        "- 磁力链接\n"
        "- 种子文件\n\n"
        "我会帮你下载并显示实时进度。\n\n"
        "你也可以使用下方按钮来管理下载任务：",
        reply_markup=get_main_keyboard()
    )

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /tasks 命令"""
    await update.message.reply_text(
        "📋 任务管理\n选择要查看的任务类型：",
        reply_markup=get_task_list_buttons()
    )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理未知命令"""
    available_commands = (
        "可用命令列表：\n"
        "/start - 开始使用\n"
        "/tasks - 查看任务列表"
    )
    await update.message.reply_text(
        f"❌ 未知命令：{update.message.text}\n\n{available_commands}"
    )