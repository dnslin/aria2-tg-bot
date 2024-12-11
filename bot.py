import os
import logging
from typing import Dict
import validators
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
import aria2p

# 配置日志
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# 加载环境变量
load_dotenv()

# 初始化 aria2 客户端
aria2 = aria2p.API(
    aria2p.Client(
        host=os.getenv("ARIA2_HOST", "http://localhost"),
        port=int(os.getenv("ARIA2_PORT", 6800)),
        secret=os.getenv("ARIA2_SECRET", "")
    )
)

# 存储下载任务和对应的消息ID
download_messages: Dict[str, int] = {}

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

def format_progress_bar(progress: float, width: int = 10) -> str:
    """生成进度条，使用更短的宽度适配手机屏幕"""
    if not 0 <= progress <= 100:
        progress = 0
    filled = int(width * progress / 100)
    bar = '█' * filled + '░' * (width - filled)
    return bar

def format_size(size: float) -> str:
    """格式化文件大小"""
    if not size or size < 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"

def format_time(seconds: int) -> str:
    """格式化时间"""
    if not seconds or seconds < 0 or seconds > 86400 * 365:  # 超过1年或无效值
        return "计算中..."
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}分{seconds}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}时{minutes}分"

def get_seconds_from_timedelta(td) -> int:
    """将timedelta转换为秒数"""
    if not td:
        return 0
    try:
        return int(td.total_seconds())
    except (AttributeError, TypeError):
        return 0

def get_control_buttons(gid: str, is_paused: bool = False) -> InlineKeyboardMarkup:
    """获取控制按钮"""
    buttons = []
    if is_paused:
        buttons.append(InlineKeyboardButton("▶️ 继续", callback_data=f"resume_{gid}"))
    else:
        buttons.append(InlineKeyboardButton("⏸ 暂停", callback_data=f"pause_{gid}"))
    
    buttons.extend([
        InlineKeyboardButton("⏹ 停止", callback_data=f"stop_{gid}"),
        InlineKeyboardButton("🔄 重试", callback_data=f"retry_{gid}")
    ])
    
    return InlineKeyboardMarkup([buttons])

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """更新下载进度"""
    for gid, message_id in list(download_messages.items()):
        try:
            download = aria2.get_download(gid)
            if not download:
                # 如果下载任务不存在，清理相关资源
                if gid in download_messages:
                    del download_messages[gid]
                # 停止当前的定时任务
                current_jobs = context.job_queue.get_jobs_by_name(str(gid))
                for job in current_jobs:
                    job.schedule_removal()
                continue

            if download.is_complete:
                await context.bot.edit_message_text(
                    chat_id=context.job.chat_id,
                    message_id=message_id,
                    text=f"✅ 下载完成！\n\n"
                         f"📁 {download.name}\n"
                         f"💾 {format_size(download.total_length)}\n"
                         f"📂 {download.dir}"
                )
                # 清理资源
                del download_messages[gid]
                # 停止当前的定时任务
                current_jobs = context.job_queue.get_jobs_by_name(str(gid))
                for job in current_jobs:
                    job.schedule_removal()
            elif download.has_failed:
                await context.bot.edit_message_text(
                    chat_id=context.job.chat_id,
                    message_id=message_id,
                    text=f"❌ 下载失败：{download.error_message}",
                    reply_markup=get_control_buttons(gid)
                )
            else:
                progress = download.progress if download.progress <= 100 else 0
                speed = download.download_speed if download.download_speed >= 0 else 0
                eta_seconds = get_seconds_from_timedelta(download.eta)
                downloaded = download.completed_length if download.completed_length >= 0 else 0
                total = download.total_length if download.total_length >= 0 else 0
                
                # 如果还在获取信息
                if total == 0 or downloaded == 0:
                    await context.bot.edit_message_text(
                        chat_id=context.job.chat_id,
                        message_id=message_id,
                        text=f"⏳ 正在连接...\n\n"
                             f"📁 {download.name}",
                        reply_markup=get_control_buttons(gid)
                    )
                    continue
                
                # 计算实际进度
                progress = min(downloaded * 100 / total, 100) if total > 0 else 0
                progress_bar = format_progress_bar(progress)
                speed_text = format_size(speed) + '/s' if speed > 0 else "等待中..."
                
                # 确定下载状态
                if download.status == 'paused':
                    status = "⏸ 已暂停"
                    time_text = "已暂停"
                elif speed == 0:
                    status = "⏳ 等待中..."
                    time_text = "等待中..."
                else:
                    status = "⏬ 正在下载..."
                    time_text = format_time(eta_seconds)
                
                await context.bot.edit_message_text(
                    chat_id=context.job.chat_id,
                    message_id=message_id,
                    text=f"{status}\n\n"
                         f"📁 {download.name}\n"
                         f"⏳ 进度: {progress:.1f}% {progress_bar}\n"
                         f"📊 {format_size(downloaded)} / {format_size(total)}\n"
                         f"📶 速度: {speed_text}\n"
                         f"🕒 预计: {time_text}",
                    reply_markup=get_control_buttons(gid, download.status == 'paused')
                )
        except Exception as e:
            logging.error(f"更新进度时出错: {str(e)}")
            # 如果出现错误，也清理相关资源
            if gid in download_messages:
                del download_messages[gid]
            current_jobs = context.job_queue.get_jobs_by_name(str(gid))
            for job in current_jobs:
                job.schedule_removal()

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

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()
    
    try:
        action, gid = query.data.split('_')
        download = aria2.get_download(gid)
        
        if not download:
            await query.edit_message_text("❌ 下载任务不存在")
            # 清理相关资源
            if gid in download_messages:
                del download_messages[gid]
            current_jobs = context.job_queue.get_jobs_by_name(str(gid))
            for job in current_jobs:
                job.schedule_removal()
            return
            
        if action == "pause":
            download.pause()
            await query.answer("已暂停下载")
        elif action == "resume":
            download.resume()
            await query.answer("已继续下载")
        elif action == "stop":
            download.remove()
            await query.edit_message_text("⏹ 下载已停止")
            # 清理相关资源
            if gid in download_messages:
                del download_messages[gid]
            current_jobs = context.job_queue.get_jobs_by_name(str(gid))
            for job in current_jobs:
                job.schedule_removal()
        elif action == "retry":
            # 获取原始URI并重新下载
            uris = download.files[0].uris
            if uris:
                new_download = aria2.add_uris([uri.uri for uri in uris])
                download_messages[new_download.gid] = query.message.message_id
                await query.answer("已重新开始下载")
            else:
                await query.answer("❌ 无法重试：找不到下载地址")
    except Exception as e:
        logging.error(f"处理按钮回调时出错: {str(e)}")
        await query.answer("❌ 操作失败")

def main() -> None:
    """启动机器人"""
    # 获取配置
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    base_url = os.getenv("TELEGRAM_API_BASE")

    # 创建应用
    if base_url:
        # 如果设置了自定义API地址，使用代理
        application = Application.builder().token(token).base_url(f"{base_url}/bot").build()
    else:
        # 否则使用默认API
        application = Application.builder().token(token).build()

    # 添加处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_download))
    application.add_handler(CallbackQueryHandler(button_callback))

    # 启动机器人
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main() 