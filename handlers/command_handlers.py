from telegram import Update
from telegram.ext import ContextTypes

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令"""
    await update.message.reply_text(
        "👋 欢迎使用下载机器人！\n\n"
        "你可以发送以下类型的链接：\n"
        "- HTTP/HTTPS 链接\n"
        "- 磁力链接\n"
        "- 种子文件\n\n"
        "我会帮你下载并显示实时进度。"
    ) 