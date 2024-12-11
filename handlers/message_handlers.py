import logging
import validators
from telegram import Update
from telegram.ext import ContextTypes
from utils.aria2_client import aria2

# 存储下载任务和对应的消息ID
download_messages = {}

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理下载请求"""
    url = update.message.text.strip()
    
    # 验证URL
    if not validators.url(url) and not url.startswith("magnet:"):
        await update.message.reply_text("❌ 请发送有效的URL或磁力链接")
        return

    try:
        # 发送初始状态消息
        status_message = await update.message.reply_text(
            "⏳ 正在获取下载信息...\n"
            "请稍候..."
        )
        
        # 添加下载任务
        download = aria2.add_uris([url])
        download_messages[download.gid] = status_message.message_id
        
        # 启动进度更新任务（每2秒更新一次）
        context.job_queue.run_repeating(
            update_progress,
            interval=2,
            first=1,
            chat_id=update.effective_chat.id,
            name=str(download.gid)
        )
        
    except Exception as e:
        await update.message.reply_text(f"❌ 添加下载任务失败：{str(e)}") 