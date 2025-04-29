import logging
import asyncio
from typing import Dict, Any

from telegram import Update, InlineKeyboardMarkup # Added InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# 导入项目模块时，使用相对导入
from .. import utils
from .. import auth
from ..aria2_client import Aria2Error, Aria2TaskNotFoundError
from ..history import DatabaseError, HistoryManager # Added HistoryManager import
from ..config import Config # Added Config import
from ..task_monitor import get_task_monitor # 新增导入

# 设置日志记录器
logger = logging.getLogger(__name__)

# 注意：以下函数中的 self.xxx 引用将在后续步骤中修改为 context.bot_data['xxx'] 或类似方式

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理内联键盘按钮的回调查询 (非会话)"""
    query = update.callback_query

    # 权限检查
    if not await auth.check_authorized(update):
        # query.answer 已经在 check_authorized 中调用
        return

    # 解析回调数据
    action, value = utils.parse_callback_data(query.data)
    user_id = update.effective_user.id

    try:
        await query.answer() # 先响应回调，避免超时

        # 处理任务操作回调
        if action == "pause":
            await _handle_pause_callback(query, value, context) # Pass context
        elif action == "resume":
            await _handle_resume_callback(query, value, context) # Pass context
        elif action == "remove":
            await _handle_remove_callback(query, value, context) # Pass context

        # 处理分页回调
        elif action == "history_page":
            await _handle_history_page_callback(query, value, user_id, context) # Pass context
        elif action == "search_page":
            await _handle_search_page_callback(query, value, user_id, context) # Pass context
        elif action == "status_page":
            await _handle_status_page_callback(query, value, user_id, context) # Pass context

        # 忽略页码信息按钮的点击
        elif action == "page_info":
            # 已经在上面 answer() 了，这里不需要再做操作
            pass

        else:
            logger.warning(f"收到未知回调操作: {action}")
            # 可以选择性地通知用户
            # await query.answer(f"未知操作: {action}")

    except Exception as e:
        logger.error(f"处理回调查询时发生错误: {e}", exc_info=True)
        try:
            await query.answer(f"⚠️ 发生错误: {str(e)[:200]}", show_alert=True)
        except Exception as answer_err:
             logger.error(f"发送回调错误提示失败: {answer_err}")


# 回调处理辅助方法 (Added context parameter to all helpers)
async def _handle_pause_callback(query, gid, context: ContextTypes.DEFAULT_TYPE):
    """处理暂停任务回调"""
    aria2_client = context.bot_data['aria2_client']
    try:
        result = await aria2_client.pause_download(gid)

        if result:
            # 更新消息中的任务信息
            await asyncio.sleep(0.5) # 给Aria2一点时间更新状态
            task_info = await aria2_client.get_download(gid)
            task_text = utils.format_task_info_html(task_info)
            await query.edit_message_text(
                f"📝 <b>任务详情 (GID: {gid})</b>\n\n{task_text}",
                reply_markup=utils.create_task_control_keyboard(gid),
                parse_mode=ParseMode.HTML
            )
            await query.answer("✅ 任务已暂停") # 在编辑消息后响应
        else:
            await query.answer("❌ 暂停任务失败", show_alert=True)

    except Aria2TaskNotFoundError:
        await query.answer("❓ 任务不存在或已完成", show_alert=True)
        # 可以选择编辑消息提示任务已消失
        await query.edit_message_text(f"❌ 任务 <code>{gid}</code> 不存在或已完成。", parse_mode=ParseMode.HTML)
    except Aria2Error as e:
        await query.answer(f"❌ 暂停失败: {str(e)[:200]}", show_alert=True)
    except Exception as e:
        logger.error(f"处理暂停回调时发生错误: {e}", exc_info=True)
        await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)


async def _handle_resume_callback(query, gid, context: ContextTypes.DEFAULT_TYPE):
    """处理恢复任务回调"""
    aria2_client = context.bot_data['aria2_client']
    try:
        result = await aria2_client.resume_download(gid)

        if result:
            # 更新消息中的任务信息
            await asyncio.sleep(0.5) # 给Aria2一点时间更新状态
            task_info = await aria2_client.get_download(gid)
            task_text = utils.format_task_info_html(task_info)
            await query.edit_message_text(
                f"📝 <b>任务详情 (GID: {gid})</b>\n\n{task_text}",
                reply_markup=utils.create_task_control_keyboard(gid),
                parse_mode=ParseMode.HTML
            )
            await query.answer("✅ 任务已恢复") # 在编辑消息后响应
        else:
            await query.answer("❌ 恢复任务失败", show_alert=True)

    except Aria2TaskNotFoundError:
        await query.answer("❓ 任务不存在或已完成", show_alert=True)
        await query.edit_message_text(f"❌ 任务 <code>{gid}</code> 不存在或已完成。", parse_mode=ParseMode.HTML)
    except Aria2Error as e:
        await query.answer(f"❌ 恢复失败: {str(e)[:200]}", show_alert=True)
    except Exception as e:
        logger.error(f"处理恢复回调时发生错误: {e}", exc_info=True)
        await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)

async def _handle_remove_callback(query, gid, context: ContextTypes.DEFAULT_TYPE):
    """处理删除任务回调"""
    aria2_client = context.bot_data['aria2_client']
    history_manager: HistoryManager = context.bot_data['history_manager']
    try:
        # 先获取任务信息
        task_info = None
        try:
            task_info = await aria2_client.get_download(gid)
        except Aria2TaskNotFoundError:
             logger.info(f"尝试删除的任务 {gid} 在Aria2中未找到")
        except Aria2Error as e:
             logger.warning(f"获取待删除任务 {gid} 信息时出错: {e}")


        result = await aria2_client.remove_download(gid)

        if result:
            # 将删除的任务添加到历史记录
            if task_info:
                await history_manager.add_history(
                    gid=gid,
                    name=task_info.get('name', '未知'),
                    status='removed',
                    size=task_info.get('total_length', 0),
                    files=task_info.get('files', [])
                )

            # 更新消息
            await query.edit_message_text(
                f"🗑️ <b>任务已删除</b>\n"
                f"GID: <code>{gid}</code>\n\n"
                f"文件名: {utils.escape_html(task_info.get('name', '未知') if task_info else '未知')}",
                parse_mode=ParseMode.HTML
            )
            # await query.answer("✅ 任务已删除") # 移除冗余调用

            # 任务已删除，取消监控
            try:
                task_monitor = get_task_monitor()
                if task_monitor and query.message: # 确保 query.message 存在
                    task_monitor.unregister_task(query.message.chat_id, query.message.message_id)
            except Exception as monitor_err:
                logger.error(f"Failed to unregister task {gid} from TaskMonitor after removal: {monitor_err}", exc_info=True)

        else:
             # 如果 remove 返回 false，但之前获取信息时任务不存在，则认为已删除
            if task_info is None:
                await query.edit_message_text(
                    f"ℹ️ <b>任务已被删除或不存在</b>\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )
                # await query.answer("ℹ️ 任务已被删除或不存在") # 移除冗余调用
                # 任务不存在，也尝试取消监控（以防万一）
                try:
                    task_monitor = get_task_monitor()
                    if task_monitor and query.message:
                        task_monitor.unregister_task(query.message.chat_id, query.message.message_id)
                except Exception as monitor_err:
                    logger.error(f"Failed to unregister non-existent task {gid} from TaskMonitor: {monitor_err}", exc_info=True)
            else:
                # await query.answer("❌ 删除任务失败", show_alert=True) # 移除冗余调用
                await query.edit_message_text(f"❌ 删除任务 <code>{gid}</code> 失败。", parse_mode=ParseMode.HTML)

    except Aria2TaskNotFoundError: # 这个异常理论上不应该在这里触发
        await query.answer("❓ 任务不存在或已完成", show_alert=True)
        await query.edit_message_text(f"❌ 任务 <code>{gid}</code> 不存在或已完成。", parse_mode=ParseMode.HTML)
        # 任务不存在，也尝试取消监控
        try:
            task_monitor = get_task_monitor()
            if task_monitor and query.message:
                task_monitor.unregister_task(query.message.chat_id, query.message.message_id)
        except Exception as monitor_err:
            logger.error(f"Failed to unregister non-existent task {gid} from TaskMonitor: {monitor_err}", exc_info=True)
    except Aria2Error as e:
        await query.answer(f"❌ 删除失败: {str(e)[:200]}", show_alert=True)
    except Exception as e:
        logger.error(f"处理删除回调时发生错误: {e}", exc_info=True)
        await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)

async def _handle_history_page_callback(query, value, user_id, context: ContextTypes.DEFAULT_TYPE):
    """处理历史记录分页回调"""
    history_manager: HistoryManager = context.bot_data['history_manager']
    config: Config = context.bot_data['config']
    states = context.bot_data.setdefault('states', {"history_pages": {}}) # 临时处理
    try:
        page = int(value)

        # 获取历史记录
        items_per_page = config.items_per_page

        histories, total = await history_manager.get_history(
            page=page,
            page_size=items_per_page
        )

        # 计算总页数
        total_pages = utils.calculate_total_pages(total, items_per_page)

        # 格式化历史记录列表
        histories_text = utils.format_history_list_html(histories)

        # 创建分页按钮
        reply_markup = utils.create_pagination_keyboard(
            page, total_pages, "history_page"
        )

        # 更新分页状态 (需要调整)
        states["history_pages"][user_id] = {
            "page": page,
            "total": total_pages
        }

        # 更新消息
        await query.edit_message_text(
            f"📜 <b>下载历史记录</b> (共 {total} 条)\n\n{histories_text}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        # await query.answer(f"第 {page}/{total_pages} 页") # Answer 已经在 handle_callback 中调用

    except ValueError:
        await query.answer("⚠️ 无效的页码", show_alert=True)
    except DatabaseError as e:
        await query.answer(f"❌ 查询历史记录失败: {str(e)[:200]}", show_alert=True)
    except Exception as e:
        logger.error(f"处理历史分页回调时发生错误: {e}", exc_info=True)
        await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)

async def _handle_search_page_callback(query, value, user_id, context: ContextTypes.DEFAULT_TYPE):
    """处理搜索结果分页回调"""
    history_manager: HistoryManager = context.bot_data['history_manager']
    config: Config = context.bot_data['config']
    states = context.bot_data.setdefault('states', {"search_pages": {}}) # 临时处理
    try:
        page = int(value)

        # 获取搜索关键词
        if user_id not in states["search_pages"]:
            await query.answer("⏳ 搜索会话已过期，请重新搜索", show_alert=True)
            return

        keyword = states["search_pages"][user_id]["keyword"]

        # 搜索历史记录
        items_per_page = config.items_per_page

        histories, total = await history_manager.search_history(
            keyword=keyword,
            page=page,
            page_size=items_per_page
        )

        # 计算总页数
        total_pages = utils.calculate_total_pages(total, items_per_page)

        # 格式化历史记录列表
        histories_text = utils.format_history_list_html(histories)

        # 创建分页按钮
        reply_markup = utils.create_pagination_keyboard(
            page, total_pages, "search_page"
        )

        # 更新分页状态 (需要调整)
        states["search_pages"][user_id] = {
            "page": page,
            "total": total_pages,
            "keyword": keyword
        }

        # 更新消息
        await query.edit_message_text(
            f"🔍 <b>搜索结果:</b> {utils.escape_html(keyword)} (共 {total} 条)\n\n{histories_text}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        # await query.answer(f"第 {page}/{total_pages} 页") # Answer 已经在 handle_callback 中调用

    except ValueError:
        await query.answer("⚠️ 无效的页码", show_alert=True)
    except DatabaseError as e:
        await query.answer(f"❌ 搜索历史记录失败: {str(e)[:200]}", show_alert=True)
    except Exception as e:
        logger.error(f"处理搜索分页回调时发生错误: {e}", exc_info=True)
        await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)

async def _handle_status_page_callback(query, value, user_id, context: ContextTypes.DEFAULT_TYPE):
    """处理任务状态分页回调"""
    aria2_client = context.bot_data['aria2_client']
    config: Config = context.bot_data['config']
    states = context.bot_data.setdefault('states', {"status_pages": {}}) # 临时处理
    try:
        page = int(value)

        # 获取任务列表
        if user_id not in states["status_pages"]:
            # 如果状态丢失，重新获取任务列表
            active_tasks = await aria2_client.get_active_downloads()
            waiting_tasks = await aria2_client.get_waiting_downloads()
            all_tasks = active_tasks + waiting_tasks
        else:
            all_tasks = states["status_pages"][user_id]["tasks"]

        total_tasks = len(all_tasks)

        if total_tasks == 0:
            await query.answer("ℹ️ 没有任务", show_alert=True)
            # 可以选择编辑消息
            await query.edit_message_text("📭 <b>没有活动或等待中的下载任务</b>", parse_mode=ParseMode.HTML)
            return

        # 配置分页
        items_per_page = config.items_per_page
        total_pages = utils.calculate_total_pages(total_tasks, items_per_page)

        # 确保页码有效
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages

        # 计算切片索引
        start_idx = (page - 1) * items_per_page
        end_idx = start_idx + items_per_page

        # 获取当前页的任务
        current_tasks = all_tasks[start_idx:end_idx]

        # 格式化任务列表
        tasks_text = utils.format_task_list_html(current_tasks)

        # 创建分页按钮
        reply_markup = utils.create_pagination_keyboard(
            page, total_pages, "status_page"
        )

        # 更新分页状态 (需要调整)
        states["status_pages"][user_id] = {
            "page": page,
            "total": total_pages,
            "tasks": all_tasks
        }

        # 更新消息
        await query.edit_message_text(
            f"📋 <b>下载任务列表</b> (共 {total_tasks} 个)\n\n{tasks_text}",
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        # await query.answer(f"第 {page}/{total_pages} 页") # Answer 已经在 handle_callback 中调用

    except ValueError:
        await query.answer("⚠️ 无效的页码", show_alert=True)
    except Aria2Error as e:
        await query.answer(f"❌ 查询任务失败: {str(e)[:200]}", show_alert=True)
    except Exception as e:
        logger.error(f"处理状态分页回调时发生错误: {e}", exc_info=True)
        await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)