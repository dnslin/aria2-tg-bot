import logging
import asyncio
import re
from typing import Dict, Any

from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

# 导入项目模块时，使用相对导入
from .. import utils
from .. import auth
from ..aria2_client import Aria2Error, Aria2TaskNotFoundError
from ..history import DatabaseError

# 设置日志记录器
logger = logging.getLogger(__name__)

# 注意：以下函数中的 self.xxx 引用将在后续步骤中修改为 context.bot_data['xxx'] 或类似方式
# 注意：@command 装饰器已被移除，注册将在 bot_app.py 中处理

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /start 命令"""
    if not await auth.check_authorized(update):
        return

    welcome_text = (
        "🎉 <b>欢迎使用 Aria2 Telegram Bot!</b>\n\n"
        "此机器人可以帮助您管理 Aria2 下载任务。\n"
        "使用 /help 查看所有可用命令。"
    )

    await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /help 命令"""
    if not await auth.check_authorized(update):
        return

    help_text = (
        "❓ <b>Aria2 Telegram Bot 帮助</b>\n\n"
        "<b>基本命令：</b>\n"
        "/add <url_or_magnet> - ➕ 添加下载任务\n"
        "/status - 显示所有任务的状态摘要\n"
        "/status <gid> - 显示指定任务的详细状态\n"
        "/pause <gid> - 暂停指定任务\n"
        "/unpause <gid> - 恢复指定任务\n"
        "/remove <gid> - 删除指定任务\n"
        "/pauseall - 暂停所有任务\n"
        "/unpauseall - 恢复所有任务\n"
        "/history - 浏览下载历史记录\n"
        "/clearhistory - 清空所有历史记录\n"
        "/globalstatus - 显示 Aria2 全局状态\n"
        "/searchhistory <keyword> - 搜索下载历史\n"
        "/help - 显示此帮助信息\n\n"
        "<b>提示：</b>\n"
        "- 在查看单个任务状态时，可以使用内联按钮进行操作\n"
        "- GID 是 Aria2 分配给每个下载任务的唯一 ID\n"
        "- 状态查询和历史记录支持分页浏览"
    )

    await update.message.reply_text(help_text, parse_mode=ParseMode.HTML)

async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /add 命令，添加下载任务"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']

    # 检查是否提供了参数
    if not context.args or not context.args[0]:
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 缺少 URL 或磁力链接\n"
            "正确用法: <code>/add url_or_magnet</code>",
            parse_mode=ParseMode.HTML
        )
        return

    url = context.args[0]

    # 验证 URL (简单的正则检查，URL 或磁力链接)
    if not re.match(r'^(https?|ftp|magnet):', url, re.IGNORECASE):
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 无效的 URL 或磁力链接，必须以 http://, https://, ftp:// 或 magnet: 开头",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        # 发送等待消息
        message = await update.message.reply_text(
            "⚙️ 正在添加下载任务...",
            parse_mode=ParseMode.HTML
        )

        # 使用注入的 Aria2 客户端实例
        gid = await aria2_client.add_download(url)

        # 获取任务信息 (添加一点延迟确保Aria2有时间处理)
        await asyncio.sleep(1)
        task_info = await aria2_client.get_download(gid)

        # 格式化回复消息
        success_text = (
            f"👍 <b>下载任务已添加!</b>\n\n"
            f"<b>GID:</b> <code>{gid}</code>\n"
            f"<b>文件名:</b> {utils.escape_html(task_info.get('name', '⏳ 获取中...'))}\n"
            f"<b>状态:</b> {task_info.get('status', '未知')}"
        )

        # 更新之前的消息
        await message.edit_text(success_text, parse_mode=ParseMode.HTML)

    except Aria2Error as e:
        error_text = f"❌ <b>添加下载任务失败:</b> {utils.escape_html(str(e))}"
        logger.warning(f"添加下载任务失败 (Aria2Error): {e}")
        # 尝试编辑消息，如果失败则发送新消息
        try:
            await message.edit_text(error_text, parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error(f"添加下载任务时发生未知错误: {e}", exc_info=True)
        error_text = f"🆘 <b>系统错误:</b> 添加任务时发生意外错误。"
        try:
            await message.edit_text(error_text, parse_mode=ParseMode.HTML)
        except:
            await update.message.reply_text(error_text, parse_mode=ParseMode.HTML)

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /status 命令，查询任务状态"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']
    history_manager = context.bot_data['history_manager']
    config = context.bot_data['config']
    # states 字典也需要通过 context.bot_data 或 user_data/chat_data 管理
    states = context.bot_data.setdefault('states', {"status_pages": {}}) # 临时处理

    message = await update.message.reply_text("📊 正在查询任务状态...", parse_mode=ParseMode.HTML)

    try:
        # 如果指定了 GID，显示单个任务详情
        if context.args and context.args[0]:
            gid = context.args[0]

            # 验证 GID 格式
            if not utils.validate_gid(gid):
                await message.edit_text(
                    "⚠️ <b>错误:</b> 无效的 GID 格式\n"
                    "GID 应该是 16 个十六进制字符",
                    parse_mode=ParseMode.HTML
                )
                return

            try:
                # 获取任务信息
                task_info = await aria2_client.get_download(gid)

                # 格式化任务信息
                task_text = utils.format_task_info_html(task_info)

                # 创建任务控制按钮
                reply_markup = utils.create_task_control_keyboard(gid)

                await message.edit_text(
                    f"📝 <b>任务详情 (GID: {gid})</b>\n\n{task_text}",
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML
                )

            except Aria2TaskNotFoundError:
                # 任务不在活动队列中，尝试从历史记录查询
                history_record = await history_manager.get_history_by_gid(gid)

                if history_record:
                    status_map = {'completed': '已完成', 'error': '出错', 'removed': '已删除'}
                    status = status_map.get(history_record['status'], history_record['status'])

                    await message.edit_text(
                        f"📜 <b>历史记录 (GID: {gid})</b>\n\n"
                        f"<b>文件名:</b> {utils.escape_html(history_record['name'])}\n"
                        f"<b>状态:</b> {status}\n"
                        f"<b>完成时间:</b> {history_record['datetime']}\n"
                        f"<b>大小:</b> {utils.format_size(history_record['size'] or 0)}",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await message.edit_text(
                        f"❓ <b>错误:</b> 未找到 GID 为 <code>{gid}</code> 的任务 (活动或历史记录中均无)",
                        parse_mode=ParseMode.HTML
                    )

            except Aria2Error as e:
                logger.warning(f"查询单个任务失败 (Aria2Error): {e}")
                await message.edit_text(
                    f"❌ <b>查询任务失败:</b> {utils.escape_html(str(e))}",
                    parse_mode=ParseMode.HTML
                )
        else:
            # 获取所有活动任务和等待任务
            active_tasks = await aria2_client.get_active_downloads()
            waiting_tasks = await aria2_client.get_waiting_downloads()

            all_tasks = active_tasks + waiting_tasks
            total_tasks = len(all_tasks)

            if total_tasks == 0:
                await message.edit_text(
                    "📭 <b>没有活动或等待中的下载任务</b>",
                    parse_mode=ParseMode.HTML
                )
                return

            # 配置分页
            items_per_page = config.items_per_page
            total_pages = utils.calculate_total_pages(total_tasks, items_per_page)
            current_page = 1  # 初始页码
            start_idx = (current_page - 1) * items_per_page
            end_idx = start_idx + items_per_page

            # 获取当前页的任务
            current_tasks = all_tasks[start_idx:end_idx]

            # 格式化任务列表
            tasks_text = utils.format_task_list_html(current_tasks)

            # 创建分页按钮
            reply_markup = utils.create_pagination_keyboard(
                current_page, total_pages, "status_page"
            )

            # 保存分页状态 (需要调整为使用 context.user_data 或 chat_data 或 state 模块)
            user_id = update.effective_user.id
            states["status_pages"][user_id] = {
                "page": current_page,
                "total": total_pages,
                "tasks": all_tasks # 保存完整列表以供翻页
            }

            await message.edit_text(
                f"📋 <b>下载任务列表</b> (共 {total_tasks} 个, 第 {current_page}/{total_pages} 页)\n\n{tasks_text}",
                reply_markup=reply_markup if total_pages > 1 else None,
                parse_mode=ParseMode.HTML
            )

    except Exception as e:
        logger.error(f"查询任务状态时发生未知错误: {e}", exc_info=True)
        await message.edit_text(
            f"🆘 <b>系统错误:</b> 查询状态时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /pause 命令，暂停任务"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']

    # 检查是否提供了 GID
    if not context.args or not context.args[0]:
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 缺少 GID 参数\n"
            "正确用法: <code>/pause gid</code>",
            parse_mode=ParseMode.HTML
        )
        return

    gid = context.args[0]

    # 验证 GID 格式
    if not utils.validate_gid(gid):
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 无效的 GID 格式\n"
            "GID 应该是 16 个十六进制字符",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        result = await aria2_client.pause_download(gid)

        if result:
            await update.message.reply_text(
                f"⏸ <b>任务已暂停</b>\n"
                f"GID: <code>{gid}</code>",
                parse_mode=ParseMode.HTML
            )
        else:
            # 尝试获取任务状态，看是否已经是暂停状态
            try:
                task_info = await aria2_client.get_download(gid)
                if task_info.get('is_paused'):
                     await update.message.reply_text(
                        f"ℹ️ <b>任务已经是暂停状态</b>\n"
                        f"GID: <code>{gid}</code>",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await update.message.reply_text(
                        f"⚠️ <b>暂停任务失败</b> (未知原因)\n"
                        f"GID: <code>{gid}</code>",
                        parse_mode=ParseMode.HTML
                    )
            except:
                 await update.message.reply_text(
                    f"⚠️ <b>暂停任务失败</b> (无法获取状态)\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )

    except Aria2TaskNotFoundError:
        await update.message.reply_text(
            f"❓ <b>错误:</b> 未找到 GID 为 <code>{gid}</code> 的任务",
            parse_mode=ParseMode.HTML
        )
    except Aria2Error as e:
        logger.warning(f"暂停任务失败 (Aria2Error): {e}")
        await update.message.reply_text(
            f"❌ <b>暂停任务失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"暂停任务时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 暂停任务时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_unpause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /unpause 命令，恢复任务"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']

    # 检查是否提供了 GID
    if not context.args or not context.args[0]:
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 缺少 GID 参数\n"
            "正确用法: <code>/unpause gid</code>",
            parse_mode=ParseMode.HTML
        )
        return

    gid = context.args[0]

    # 验证 GID 格式
    if not utils.validate_gid(gid):
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 无效的 GID 格式\n"
            "GID 应该是 16 个十六进制字符",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        result = await aria2_client.resume_download(gid)

        if result:
            await update.message.reply_text(
                f"▶️ <b>任务已恢复</b>\n"
                f"GID: <code>{gid}</code>",
                parse_mode=ParseMode.HTML
            )
        else:
             # 尝试获取任务状态，看是否已经是活动状态
            try:
                task_info = await aria2_client.get_download(gid)
                if task_info.get('is_active') or task_info.get('is_waiting'):
                     await update.message.reply_text(
                        f"ℹ️ <b>任务已经是活动或等待状态</b>\n"
                        f"GID: <code>{gid}</code>",
                        parse_mode=ParseMode.HTML
                    )
                else:
                    await update.message.reply_text(
                        f"⚠️ <b>恢复任务失败</b> (未知原因)\n"
                        f"GID: <code>{gid}</code>",
                        parse_mode=ParseMode.HTML
                    )
            except:
                 await update.message.reply_text(
                    f"⚠️ <b>恢复任务失败</b> (无法获取状态)\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )

    except Aria2TaskNotFoundError:
        await update.message.reply_text(
            f"❓ <b>错误:</b> 未找到 GID 为 <code>{gid}</code> 的任务",
            parse_mode=ParseMode.HTML
        )
    except Aria2Error as e:
        logger.warning(f"恢复任务失败 (Aria2Error): {e}")
        await update.message.reply_text(
            f"❌ <b>恢复任务失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"恢复任务时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 恢复任务时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /remove 命令，删除任务"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']
    history_manager = context.bot_data['history_manager']

    # 检查是否提供了 GID
    if not context.args or not context.args[0]:
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 缺少 GID 参数\n"
            "正确用法: <code>/remove gid</code>",
            parse_mode=ParseMode.HTML
        )
        return

    gid = context.args[0]

    # 验证 GID 格式
    if not utils.validate_gid(gid):
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 无效的 GID 格式\n"
            "GID 应该是 16 个十六进制字符",
            parse_mode=ParseMode.HTML
        )
        return

    try:
        # 先尝试获取任务信息（用于后面添加到历史记录）
        task_info = None
        try:
            task_info = await aria2_client.get_download(gid)
        except Aria2TaskNotFoundError:
            logger.info(f"尝试删除的任务 {gid} 在Aria2中未找到，可能已被移除或不存在")
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

            await update.message.reply_text(
                f"🗑️ <b>任务已删除</b>\n"
                f"GID: <code>{gid}</code>",
                parse_mode=ParseMode.HTML
            )
        else:
            # 如果 remove 返回 false，但之前获取信息时任务不存在，则认为已删除
            if task_info is None:
                 await update.message.reply_text(
                    f"ℹ️ <b>任务已被删除或不存在</b>\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                await update.message.reply_text(
                    f"⚠️ <b>删除任务失败</b> (未知原因)\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )

    except Aria2TaskNotFoundError: # 这个异常应该在 remove_download 内部处理，但以防万一
        await update.message.reply_text(
            f"❓ <b>错误:</b> 未找到 GID 为 <code>{gid}</code> 的任务",
            parse_mode=ParseMode.HTML
        )
    except Aria2Error as e:
        logger.warning(f"删除任务失败 (Aria2Error): {e}")
        await update.message.reply_text(
            f"❌ <b>删除任务失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"删除任务时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 删除任务时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_pauseall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /pauseall 命令，暂停所有任务"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']

    try:
        message = await update.message.reply_text(
            "⚙️ 正在暂停所有下载任务...",
            parse_mode=ParseMode.HTML
        )

        # 获取暂停前的活动任务数量
        active_tasks = await aria2_client.get_active_downloads()
        active_count = len(active_tasks)

        if active_count == 0:
            await message.edit_text(
                "ℹ️ <b>当前没有活动的下载任务</b>",
                parse_mode=ParseMode.HTML
            )
            return

        # 暂停所有任务
        result = await aria2_client.pause_all()

        if result:
            await message.edit_text(
                f"⏸ <b>已暂停所有下载任务</b>\n"
                f"共暂停了 {active_count} 个任务",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.edit_text(
                "⚠️ <b>暂停所有任务失败</b>",
                parse_mode=ParseMode.HTML
            )

    except Aria2Error as e:
        logger.warning(f"暂停所有任务失败 (Aria2Error): {e}")
        await update.message.reply_text(
            f"❌ <b>暂停所有任务失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"暂停所有任务时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 暂停所有任务时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_unpauseall(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /unpauseall 命令，恢复所有任务"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']

    try:
        message = await update.message.reply_text(
            "⚙️ 正在恢复所有下载任务...",
            parse_mode=ParseMode.HTML
        )

        # 恢复所有任务
        result = await aria2_client.resume_all()

        if result:
            # 无法准确知道恢复了多少个，因为 unpauseAll 不返回数量
            await message.edit_text(
                f"▶️ <b>已尝试恢复所有暂停的任务</b>",
                parse_mode=ParseMode.HTML
            )
        else:
            await message.edit_text(
                "⚠️ <b>恢复所有任务失败</b>",
                parse_mode=ParseMode.HTML
            )

    except Aria2Error as e:
        logger.warning(f"恢复所有任务失败 (Aria2Error): {e}")
        await update.message.reply_text(
            f"❌ <b>恢复所有任务失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"恢复所有任务时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 恢复所有任务时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /history 命令，浏览下载历史记录"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    history_manager = context.bot_data['history_manager']
    config = context.bot_data['config']
    # states 字典也需要通过 context.bot_data 或 user_data/chat_data 管理
    states = context.bot_data.setdefault('states', {"history_pages": {}}) # 临时处理

    try:
        message = await update.message.reply_text(
            "📜 正在加载下载历史记录...",
            parse_mode=ParseMode.HTML
        )

        # 获取历史记录
        page = 1
        items_per_page = config.items_per_page

        histories, total = await history_manager.get_history(
            page=page,
            page_size=items_per_page
        )

        if total == 0:
            await message.edit_text(
                "📭 <b>没有下载历史记录</b>",
                parse_mode=ParseMode.HTML
            )
            return

        # 计算总页数
        total_pages = utils.calculate_total_pages(total, items_per_page)

        # 格式化历史记录列表
        histories_text = utils.format_history_list_html(histories)

        # 创建分页按钮
        reply_markup = utils.create_pagination_keyboard(
            page, total_pages, "history_page"
        )

        # 保存分页状态 (需要调整)
        user_id = update.effective_user.id
        states["history_pages"][user_id] = {
            "page": page,
            "total": total_pages
        }

        await message.edit_text(
            f"📜 <b>下载历史记录</b> (共 {total} 条, 第 {page}/{total_pages} 页)\n\n{histories_text}",
            reply_markup=reply_markup if total_pages > 1 else None,
            parse_mode=ParseMode.HTML
        )

    except DatabaseError as e:
        logger.warning(f"查询历史记录失败 (DatabaseError): {e}")
        await update.message.reply_text(
            f"❌ <b>查询历史记录失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"查询历史记录时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 查询历史记录时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_globalstatus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /globalstatus 命令，显示 Aria2 全局状态"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    aria2_client = context.bot_data['aria2_client']

    try:
        message = await update.message.reply_text(
            "🌐 正在获取 Aria2 全局状态...",
            parse_mode=ParseMode.HTML
        )

        status = await aria2_client.get_global_status()

        # 格式化状态信息
        status_text = (
            f"🌐 <b>Aria2 全局状态</b>\n\n"
            f"<b>⬇️ 下载速度:</b> {utils.format_speed(status['download_speed'])}\n"
            f"<b>⬆️ 上传速度:</b> {utils.format_speed(status['upload_speed'])}\n\n"
            f"<b>活动任务:</b> {status['active_downloads']} 个\n"
            f"<b>等待任务:</b> {status['waiting_downloads']} 个\n"
            f"<b>已停止任务:</b> {status['stopped_downloads']} 个\n"
            f"<b>总任务数:</b> {status['total_downloads']} 个\n\n"
            f"<b>Aria2 版本:</b> {status.get('version', '未知')}"
        )

        await message.edit_text(status_text, parse_mode=ParseMode.HTML)

    except Aria2Error as e:
        logger.warning(f"获取全局状态失败 (Aria2Error): {e}")
        await update.message.reply_text(
            f"❌ <b>获取全局状态失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"获取全局状态时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 获取全局状态时发生意外错误。",
            parse_mode=ParseMode.HTML
        )

async def cmd_searchhistory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /searchhistory 命令，搜索历史记录"""
    if not await auth.check_authorized(update):
        return

    # 依赖项将在后续通过 context 获取
    history_manager = context.bot_data['history_manager']
    config = context.bot_data['config']
    # states 字典也需要通过 context.bot_data 或 user_data/chat_data 管理
    states = context.bot_data.setdefault('states', {"search_pages": {}}) # 临时处理

    # 检查是否提供了搜索关键词
    if not context.args or not context.args[0]:
        await update.message.reply_text(
            "⚠️ <b>错误:</b> 缺少搜索关键词\n"
            "正确用法: <code>/searchhistory 关键词</code>",
            parse_mode=ParseMode.HTML
        )
        return

    keyword = " ".join(context.args)

    try:
        message = await update.message.reply_text(
            f"🔍 正在搜索历史记录: <b>{utils.escape_html(keyword)}</b>...",
            parse_mode=ParseMode.HTML
        )

        # 搜索历史记录
        page = 1
        items_per_page = config.items_per_page

        histories, total = await history_manager.search_history(
            keyword=keyword,
            page=page,
            page_size=items_per_page
        )

        if total == 0:
            await message.edit_text(
                f"🔍 <b>搜索结果为空</b>\n"
                f"未找到包含 <b>{utils.escape_html(keyword)}</b> 的历史记录",
                parse_mode=ParseMode.HTML
            )
            return

        # 计算总页数
        total_pages = utils.calculate_total_pages(total, items_per_page)

        # 格式化历史记录列表
        histories_text = utils.format_history_list_html(histories)

        # 创建分页按钮
        reply_markup = utils.create_pagination_keyboard(
            page, total_pages, "search_page"
        )

        # 保存分页状态 (需要调整)
        user_id = update.effective_user.id
        states["search_pages"][user_id] = {
            "page": page,
            "total": total_pages,
            "keyword": keyword
        }

        await message.edit_text(
            f"🔍 <b>搜索结果:</b> {utils.escape_html(keyword)} (共 {total} 条, 第 {page}/{total_pages} 页)\n\n{histories_text}",
            reply_markup=reply_markup if total_pages > 1 else None,
            parse_mode=ParseMode.HTML
        )

    except DatabaseError as e:
        logger.warning(f"搜索历史记录失败 (DatabaseError): {e}")
        await update.message.reply_text(
            f"❌ <b>搜索历史记录失败:</b> {utils.escape_html(str(e))}",
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        logger.error(f"搜索历史记录时发生未知错误: {e}", exc_info=True)
        await update.message.reply_text(
            f"🆘 <b>系统错误:</b> 搜索历史记录时发生意外错误。",
            parse_mode=ParseMode.HTML
        )