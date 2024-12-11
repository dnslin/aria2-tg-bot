import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from utils.aria2_client import aria2
from utils.keyboard_utils import get_control_buttons, get_task_list_buttons, format_task_list
from utils.formatters import format_progress_bar, format_size, format_time
from utils.download_state import download_messages

async def update_progress(context: ContextTypes.DEFAULT_TYPE) -> None:
    """更新下载进度"""
    job = context.job
    if not job or not job.data:
        return
    
    chat_id, message_id, gid = job.data
    try:
        download = aria2.get_download(gid)
        if not download:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="❌ 下载任务不存在"
            )
            context.job.remove()  # 停止任务
            return
        
        if download.is_complete:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"✅ 下载完成！\n\n📥 {download.name}\n📦 大小：{format_size(download.total_length)}"
            )
            context.job.remove()  # 停止任务
            return
        
        if download.has_failed:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"❌ 下载失败！\n\n📥 {download.name}\n💬 错误：{download.error_message}"
            )
            context.job.remove()  # 停止任务
            return
        
        # 基本状态信息
        status_text = [
            f"📥 {download.name}",
            f"⏳ 进度：{format_progress_bar(download.progress)} {download.progress:.1f}%",
            f"📦 大小：{format_size(download.completed_length)}/{format_size(download.total_length)}"
        ]
        
        # 根据任务状态添加不同的信息
        if download.status == "paused":
            status_text.append("⏸ 已暂停")
            status_text.append("⏱ 剩余时间：--")
        elif download.status == "removed":
            status_text.append("⏹ 已停止")
            status_text.append("⏱ 剩余时间：--")
        else:
            # 活动状态显示速度和剩余时间
            status_text.append(f"📊 速度：{format_size(download.download_speed)}/s")
            if download.eta and download.download_speed > 0:
                status_text.append(f"⏱ 剩余时间：{format_time(download.eta)}")
            else:
                status_text.append("⏱ 剩余时间：计算中...")
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text="\n".join(status_text),
            reply_markup=get_control_buttons(gid, download.status == "paused")
        )
    except Exception as e:
        logging.error(f"更新进度时出错：{str(e)}")
        if "Message to edit not found" in str(e):
            # 如果消息已被删除，停止更新任务
            context.job.remove()

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理按钮回调"""
    query = update.callback_query
    await query.answer()
    
    try:
        if query.data == "show_tasks":
            await query.message.edit_text(
                "📋 任务管理\n选择要查看的任务类型：",
                reply_markup=get_task_list_buttons()
            )
            return
            
        if query.data.startswith("list_"):
            task_type = query.data.split("_")[1]
            downloads = aria2.get_downloads()
            
            # 打印所有任务的状态，用于调试
            for d in downloads:
                logging.info(f"任务状态 - GID: {d.gid}, 名称: {d.name}, 状态: {d.status}, "
                           f"是否完成: {d.is_complete}, 是否活动: {d.is_active}, "
                           f"是否等待: {d.is_waiting}, 是否暂停: {d.is_paused}, "
                           f"是否错误: {d.has_failed}")
            
            tasks = []
            if task_type == "active":
                tasks = [d for d in downloads if d.is_active]
                status_text = "⏬ 正在下载的任务："
                show_controls = True
            elif task_type == "waiting":
                tasks = [d for d in downloads if d.is_waiting]
                status_text = "⏳ 等待中的任务："
                show_controls = True
            elif task_type == "completed":
                tasks = [d for d in downloads if d.is_complete]
                status_text = "✅ 已完成的任务："
                show_controls = False
            elif task_type == "stopped":
                # 修改已停止任务的判断逻辑
                tasks = [d for d in downloads if (d.status == "error" or 
                                                d.status == "removed" or 
                                                d.has_failed or 
                                                (not d.is_active and not d.is_waiting and not d.is_paused and not d.is_complete))]
                status_text = "❌ 已停止的任务："
                show_controls = True
            elif task_type == "paused":
                tasks = [d for d in downloads if d.is_paused]
                status_text = "⏸ 已暂停的任务："
                show_controls = True
                
            # 打印找到的任务数量
            logging.info(f"找到 {len(tasks)} 个{status_text.strip('：')}")
            
            task_list = format_task_list(tasks)
            
            # 为每个任务添加控制按钮
            keyboard = []
            if tasks and show_controls:
                for task in tasks:
                    row = []
                    if task_type == "paused":
                        row.append(InlineKeyboardButton("▶️ 继续", callback_data=f"resume_{task.gid}"))
                    elif task_type == "stopped":
                        row.append(InlineKeyboardButton("🔄 重试", callback_data=f"retry_{task.gid}"))
                    else:
                        row.append(InlineKeyboardButton("⏸ 暂停", callback_data=f"pause_{task.gid}"))
                        row.append(InlineKeyboardButton("⏹ 停止", callback_data=f"stop_{task.gid}"))
                    row.append(InlineKeyboardButton("🗑️ 删除", callback_data=f"delete_{task.gid}"))
                    keyboard.append(row)
            
            # 添加返回按钮
            keyboard.append([InlineKeyboardButton("📋 返回列表", callback_data="show_tasks")])
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.message.edit_text(
                f"{status_text}\n\n{task_list}",
                reply_markup=reply_markup
            )
            return
            
        if query.data.startswith(("clear_completed", "clear_stopped")):
            is_completed = query.data == "clear_completed"
            downloads = aria2.get_downloads()
            to_remove = []
            
            if is_completed:
                to_remove = [d for d in downloads if d.is_complete]
            else:
                to_remove = [d for d in downloads if d.status == "error" or (d.status == "removed" and not d.is_complete)]
                
            for download in to_remove:
                try:
                    aria2.client.remove_download_result(download.gid)
                    # 停止相关的进度更新任务
                    current_jobs = context.job_queue.get_jobs_by_name(download.gid)
                    for job in current_jobs:
                        job.schedule_removal()
                except Exception as e:
                    logging.error(f"删除任务失败：{str(e)}")
            
            await query.message.edit_text(
                f"已清空{'已完成' if is_completed else '已停止'}的任务",
                reply_markup=get_task_list_buttons()
            )
            return

        # 处理任务控制操作（暂停、继续、停止、重试等）
        gid = query.data.split("_")[1]
        download = aria2.get_download(gid)
        
        if query.data.startswith("pause"):
            aria2.client.pause(gid)
            # 停止进度更新任务
            current_jobs = context.job_queue.get_jobs_by_name(gid)
            for job in current_jobs:
                job.schedule_removal()
            await query.message.edit_text(
                text=f"⏸ 任务已暂停\n你可以在'已暂停'列表中找到此任务",
                reply_markup=get_task_list_buttons()
            )
        elif query.data.startswith("resume"):
            aria2.client.unpause(gid)
            # 重新启动进度更新任务
            context.job_queue.run_repeating(
                update_progress,
                interval=0.5,
                first=0.1,
                data=(query.message.chat_id, query.message.message_id, gid),
                name=str(gid)
            )
            await query.message.edit_text(
                text="▶️ 任务已继续",
                reply_markup=get_control_buttons(gid, is_paused=False)
            )
        elif query.data.startswith("stop"):
            # 使用force_remove来停止任务
            aria2.client.force_remove(gid)
            # 停止进度更新任务
            current_jobs = context.job_queue.get_jobs_by_name(gid)
            for job in current_jobs:
                job.schedule_removal()
            await query.message.edit_text(
                text="⏹ 任务已停止\n你可以在'已停止'列表中找到此任务",
                reply_markup=get_task_list_buttons()
            )
        elif query.data.startswith("retry"):
            try:
                # 获取原始下载链接
                if hasattr(download, 'magnet_uri') and download.magnet_uri:
                    # 磁力链接
                    new_download = aria2.add_magnet(download.magnet_uri)
                else:
                    # HTTP/HTTPS 链接
                    uris = []
                    for file in download.files:
                        if file.uris:
                            for uri in file.uris:
                                if isinstance(uri, dict) and 'uri' in uri:
                                    uris.append(uri['uri'])
                                elif hasattr(uri, 'uri'):
                                    uris.append(uri.uri)
                    
                    if not uris:
                        raise ValueError("无法获取下载链接")
                    
                    new_download = aria2.add_uris(uris)
                
                # 启动进度更新任务
                context.job_queue.run_repeating(
                    update_progress,
                    interval=0.5,
                    first=0.1,
                    data=(query.message.chat_id, query.message.message_id, new_download.gid),
                    name=str(new_download.gid)
                )
                
                await query.message.edit_text(
                    "🔄 任务已重新开始\n"
                    f"📥 {new_download.name}\n"
                    f"📦 大小：{format_size(new_download.total_length)}",
                    reply_markup=get_control_buttons(new_download.gid)
                )
            except Exception as e:
                error_msg = f"重试任务失败：{str(e)}"
                logging.error(error_msg, exc_info=True)
                await query.message.edit_text(f"❌ {error_msg}")
        elif query.data.startswith("delete"):
            try:
                # 先尝试强制移除任务
                try:
                    aria2.client.force_remove(gid)
                except:
                    pass
                
                # 然后移除下载结果
                try:
                    aria2.client.remove_download_result(gid)
                except:
                    pass
                
                # 停止进度更新任务
                current_jobs = context.job_queue.get_jobs_by_name(gid)
                for job in current_jobs:
                    job.schedule_removal()
                
                await query.message.edit_text(
                    text="🗑️ 任务已删除",
                    reply_markup=get_task_list_buttons()
                )
            except Exception as e:
                logging.error(f"删除任务失败（GID: {gid}）：{str(e)}", exc_info=True)
                await query.message.edit_text(f"❌ 删除任务失败：{str(e)}")
    except BadRequest as e:
        error_message = "消息更新失败，请重试"
        logging.error(f"Telegram API错误：{str(e)}")
        try:
            await query.message.edit_text(error_message, reply_markup=get_task_list_buttons())
        except:
            pass
    except Exception as e:
        error_message = f"操作任务时出错：{str(e)}"
        logging.error(error_message)
        try:
            await query.message.edit_text(f"❌ {error_message}")
        except:
            pass