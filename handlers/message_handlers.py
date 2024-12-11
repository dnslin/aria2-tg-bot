import logging
import validators
from telegram import Update
from telegram.ext import ContextTypes
from utils.aria2_client import aria2
from utils.keyboard_utils import get_task_list_buttons, format_task_list
from utils.download_state import download_messages
from handlers.callback_handlers import update_progress

async def handle_download(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理下载请求"""
    text = update.message.text
    
    # 处理自定义键盘按钮
    if text.startswith(("📥", "⏸", "▶️", "⏹", "🗑️", "📋")):
        await handle_keyboard_button(update, context)
        return
        
    # 处理下载链接
    if text.startswith(("http://", "https://", "magnet:", "thunder:")):
        # 验证URL
        if not validators.url(text) and not text.startswith("magnet:"):
            await update.message.reply_text("❌ 请发送有效的URL或磁力链接")
            return

        try:
            # 发送初始状态消息
            status_message = await update.message.reply_text(
                "⏳ 正在获取下载信息...\n"
                "请稍候..."
            )
            
            # 添加下载任务
            download = aria2.add_uris([text])
            download_messages[download.gid] = status_message.message_id
            
            # 启动进度更新任务（每0.5秒更新一次）
            context.job_queue.run_repeating(
                update_progress,
                interval=0.5,
                first=0.1,
                data=(update.effective_chat.id, status_message.message_id, download.gid),
                name=str(download.gid)
            )
            
        except Exception as e:
            await update.message.reply_text(f"❌ 添加下载任务失败：{str(e)}") 
    else:
        await update.message.reply_text(
            "❌ 不支持的链接类型！\n"
            "请发送 HTTP/HTTPS 链接、磁力链接或种子文件。"
        )

async def handle_keyboard_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理自定义键盘按钮"""
    text = update.message.text
    
    if text == "📋 任务列表":
        await update.message.reply_text(
            "📋 任务管理\n选择要查看的任务类型：",
            reply_markup=get_task_list_buttons()
        )
        return
        
    try:
        downloads = aria2.get_downloads()
    except Exception as e:
        logging.error(f"获取下载列表失败：{str(e)}", exc_info=True)
        await update.message.reply_text("❌ 获取任务列表失败")
        return
    
    if text == "📥 下载任务":
        active_tasks = [d for d in downloads if d.is_active]
        task_list = format_task_list(active_tasks)
        await update.message.reply_text(f"⏬ 正在下载的任务：\n\n{task_list}")
        
    elif text == "⏸ 暂停任务":
        active_tasks = [d for d in downloads if d.is_active]
        if not active_tasks:
            await update.message.reply_text("❌ 当前没有正在下载的任务")
            return
            
        success_count = 0
        for task in active_tasks:
            try:
                aria2.client.pause(task.gid)
                success_count += 1
            except Exception as e:
                logging.error(f"暂停任务失败（GID: {task.gid}）：{str(e)}", exc_info=True)
        await update.message.reply_text(f"已暂停 {success_count} 个下载任务")
        
    elif text == "▶️ 继续任务":
        paused_tasks = [d for d in downloads if d.status == "paused"]
        if not paused_tasks:
            await update.message.reply_text("❌ 当前没有已暂停的任务")
            return
            
        success_count = 0
        for task in paused_tasks:
            try:
                aria2.client.unpause(task.gid)
                success_count += 1
            except Exception as e:
                logging.error(f"继续任务失败（GID: {task.gid}）：{str(e)}", exc_info=True)
        await update.message.reply_text(f"已继续 {success_count} 个下载任务")
        
    elif text == "⏹ 停止任务":
        active_tasks = [d for d in downloads if d.is_active]
        if not active_tasks:
            await update.message.reply_text("❌ 当前没有正在下载的任务")
            return
            
        success_count = 0
        for task in active_tasks:
            try:
                aria2.client.force_pause(task.gid)
                aria2.client.remove(task.gid)
                # 停止进度更新任务
                current_jobs = context.job_queue.get_jobs_by_name(task.gid)
                for job in current_jobs:
                    job.schedule_removal()
                success_count += 1
            except Exception as e:
                logging.error(f"停止任务失败（GID: {task.gid}）：{str(e)}", exc_info=True)
        await update.message.reply_text(f"已停止 {success_count} 个下载任务")
        
    elif text == "🗑️ 清理任务":
        try:
            # 打印任务状态以便调试
            for d in downloads:
                logging.info(f"任务状态 - GID: {d.gid}, 名称: {d.name}, 状态: {d.status}, 是否完成: {d.is_complete}")
            
            completed_tasks = [d for d in downloads if d.is_complete]
            error_tasks = [d for d in downloads if d.status == "error"]
            tasks_to_remove = completed_tasks + error_tasks
            
            if not tasks_to_remove:
                await update.message.reply_text("❌ 当前没有可清理的任务")
                return
            
            logging.info(f"准备清理 {len(tasks_to_remove)} 个任务")
            success_count = 0
            
            for task in tasks_to_remove:
                try:
                    logging.info(f"正在清理任务 - GID: {task.gid}, 名称: {task.name}")
                    # 根据任务状态使用不同的删除方法
                    if task.is_complete or task.status == "error":
                        # 已完成或出错的任务使用 remove_download_result
                        result = aria2.client.remove_download_result(task.gid)
                    else:
                        # 其他状态的任务使用 forcePause 和 remove
                        aria2.client.force_pause(task.gid)
                        result = aria2.client.remove(task.gid)
                    
                    # 停止进度更新任务
                    current_jobs = context.job_queue.get_jobs_by_name(task.gid)
                    for job in current_jobs:
                        job.schedule_removal()
                        
                    logging.info(f"清理结果: {result}")
                    success_count += 1
                except Exception as e:
                    logging.error(f"删除任务失败（GID: {task.gid}）：{str(e)}", exc_info=True)
            
            await update.message.reply_text(f"已清理 {success_count} 个任务")
            
        except Exception as e:
            error_msg = f"清理任务时出错：{str(e)}"
            logging.error(error_msg, exc_info=True)
            await update.message.reply_text(f"❌ {error_msg}")