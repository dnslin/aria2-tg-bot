"""
Telegram Bot 核心模块 - 实现命令处理、回调处理和用户交互
"""

import logging
import os
import asyncio
import re
import traceback
import time
from typing import Dict, List, Any, Optional, Tuple, Union, cast

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    filters,
    MessageHandler,
)
from telegram.constants import ParseMode

from .config import get_config
from .aria2_client import get_aria2_client, Aria2Error, Aria2TaskNotFoundError
from .history import get_history_manager, DatabaseError
from . import utils

# 设置日志记录器
logger = logging.getLogger(__name__)

# 会话状态定义（用于 ConversationHandler）
CONFIRM_CLEAR = 1

class TelegramBot:
    """Telegram Bot 类，实现命令处理、回调处理和用户交互"""

    # Applying Dependency Injection: Injecting dependencies via constructor
    def __init__(self, aria2_client: 'Aria2Client', history_manager: 'HistoryManager'):
        """
        初始化 Telegram Bot

        Args:
            aria2_client: Aria2 客户端实例
            history_manager: 历史记录管理器实例
        """
        self.config = get_config()
        self.application = None
        self.conversation_handlers = {}
        self.aria2_client = aria2_client # Injected dependency
        self.history_manager = history_manager # Injected dependency
        self.commands = {} # Command Registry

        # 用于存储会话状态的字典
        self.states = {
            "history_pages": {},  # 结构: {user_id: {"page": current_page, "total": total_pages}}
            "search_pages": {},   # 结构: {user_id: {"page": current_page, "total": total_pages, "keyword": keyword}}
            "status_pages": {}    # 结构: {user_id: {"page": current_page, "total": total_pages}}
        }

        logger.info("Telegram Bot 初始化中...")

    # Applying Command Pattern (Registry): Decorator to register commands
    def command(self, name: str):
        """装饰器：注册命令处理函数"""
        def decorator(func):
            self.commands[name] = func
            return func
        return decorator

    async def setup(self) -> None:
        """
        设置 Bot Application

        初始化 Application、命令处理器、回调处理器等
        """
        # 创建 Application Builder
        builder = Application.builder().token(self.config.telegram_token)

        # 检查并应用自定义 API 接入点
        api_base_url = self.config.telegram_api_base_url
        if api_base_url:
            logger.info(f"使用自定义 Telegram API 接入点: {api_base_url}")
            builder = builder.base_url(api_base_url)
        else:
            logger.info("使用官方 Telegram API 接入点")

        # 构建 Application
        self.application = builder.build()

        # Applying Command Pattern (Registry): Register commands dynamically
        # 注册所有通过 @self.command 装饰器标记的命令
        for name, handler in self.commands.items():
            self.application.add_handler(CommandHandler(name, handler))
            logger.debug(f"Registered command: /{name}")

        # 添加清空历史记录的会话处理器 (ConversationHandler 入口点仍需单独添加)
        clear_history_handler = ConversationHandler(
            entry_points=[CommandHandler("clearhistory", self.cmd_clearhistory_start)],
            states={
                CONFIRM_CLEAR: [
                    # 使用 CallbackQueryHandler 处理按钮点击
                    CallbackQueryHandler(self.cmd_clearhistory_confirm, pattern="^clear_history_confirm$"),
                    CallbackQueryHandler(self.cmd_clearhistory_cancel, pattern="^clear_history_cancel$"),
                ],
            },
            fallbacks=[CommandHandler("cancel", self.cmd_clearhistory_cancel_command)], # 添加命令 fallback
            conversation_timeout=60 # 设置超时时间
        )
        self.application.add_handler(clear_history_handler)

        # 添加可选功能的命令处理器 (如果配置启用了)
        if self.config.notification_enabled:
            logger.info("下载通知功能已启用")

        # 搜索命令已通过装饰器注册
        # self.application.add_handler(CommandHandler("searchhistory", self.cmd_searchhistory))

        # 添加内联键盘回调处理器 (处理非会话的回调)
        self.application.add_handler(CallbackQueryHandler(self.handle_callback, pattern="^(?!clear_history_)")) # 排除会话处理的回调

        # 添加错误处理器
        self.application.add_error_handler(self.error_handler)

        # 设置命令列表
        bot_commands = [
            BotCommand("add", "添加下载任务 - /add <url_or_magnet>"),
            BotCommand("status", "查看任务状态 - /status [gid]"),
            BotCommand("pause", "暂停指定任务 - /pause <gid>"),
            BotCommand("unpause", "恢复指定任务 - /unpause <gid>"),
            BotCommand("remove", "删除指定任务 - /remove <gid>"),
            BotCommand("pauseall", "暂停所有任务 - /pauseall"),
            BotCommand("unpauseall", "恢复所有任务 - /unpauseall"),
            BotCommand("history", "浏览下载历史 - /history"),
            BotCommand("clearhistory", "清空下载历史 - /clearhistory"),
            BotCommand("globalstatus", "查看全局状态 - /globalstatus"),
            BotCommand("searchhistory", "搜索下载历史 - /searchhistory <keyword>"),
            BotCommand("help", "显示帮助 - /help")
        ]

        await self.application.bot.set_my_commands(bot_commands)

        logger.info("Telegram Bot 设置完成")

    async def run(self) -> None:
        """启动 Bot 应用"""
        # 确保设置已完成
        if not self.application:
            await self.setup()

        # 启动 Bot
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        logger.info("Telegram Bot 启动成功，开始接收消息...")

        # 保持运行状态
        try:
            # 这里不需要 wait_until_stopped()，因为主程序会处理
            while True:
                await asyncio.sleep(3600) # 保持运行
        except asyncio.CancelledError:
            logger.info("Bot run task cancelled.")
        finally:
            logger.info("正在关闭 Telegram Bot...")
            if self.application and self.application.updater.running:
                 await self.application.updater.stop()
            if self.application:
                await self.application.stop()
                await self.application.shutdown()

    async def check_authorized(self, update: Update) -> bool:
        """
        检查用户是否有权限使用 Bot

        Args:
            update: 收到的更新消息

        Returns:
            是否有权限
        """
        user_id = update.effective_user.id

        # 检查用户 ID 是否在授权列表中
        if user_id in self.config.authorized_users:
            return True

        # 不在授权列表中，发送拒绝消息
        logger.warning(f"未授权用户尝试访问: {user_id} ({update.effective_user.username})")

        if update.callback_query:
            await update.callback_query.answer("您没有权限使用此 Bot", show_alert=True)
        elif update.effective_message:
            await update.effective_message.reply_text("🚫 您没有权限使用此 Bot")

        return False

    # 基础命令处理器
    @command("start") # Register command using decorator
    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /start 命令"""
        if not await self.check_authorized(update):
            return

        welcome_text = (
            "🎉 <b>欢迎使用 Aria2 Telegram Bot!</b>\n\n"
            "此机器人可以帮助您管理 Aria2 下载任务。\n"
            "使用 /help 查看所有可用命令。"
        )

        await update.message.reply_text(welcome_text, parse_mode=ParseMode.HTML)

    @command("help") # Register command using decorator
    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /help 命令"""
        if not await self.check_authorized(update):
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

    @command("add") # Register command using decorator
    async def cmd_add(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /add 命令，添加下载任务"""
        if not await self.check_authorized(update):
            return

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
            gid = await self.aria2_client.add_download(url)

            # 获取任务信息 (添加一点延迟确保Aria2有时间处理)
            await asyncio.sleep(1)
            task_info = await self.aria2_client.get_download(gid)

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

    @command("status") # Register command using decorator
    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /status 命令，查询任务状态"""
        if not await self.check_authorized(update):
            return

        message = await update.message.reply_text("📊 正在查询任务状态...", parse_mode=ParseMode.HTML)

        try:
            # 使用注入的 Aria2 客户端实例
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
                    task_info = await self.aria2_client.get_download(gid)

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
                    # 使用注入的 HistoryManager 实例
                    history_record = await self.history_manager.get_history_by_gid(gid)

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
                active_tasks = await self.aria2_client.get_active_downloads()
                waiting_tasks = await self.aria2_client.get_waiting_downloads()

                all_tasks = active_tasks + waiting_tasks
                total_tasks = len(all_tasks)

                if total_tasks == 0:
                    await message.edit_text(
                        "📭 <b>没有活动或等待中的下载任务</b>",
                        parse_mode=ParseMode.HTML
                    )
                    return

                # 配置分页
                items_per_page = self.config.items_per_page
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

                # 保存分页状态
                user_id = update.effective_user.id
                self.states["status_pages"][user_id] = {
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

    @command("pause") # Register command using decorator
    async def cmd_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /pause 命令，暂停任务"""
        if not await self.check_authorized(update):
            return

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
            # 使用注入的 Aria2 客户端实例
            result = await self.aria2_client.pause_download(gid)

            if result:
                await update.message.reply_text(
                    f"⏸ <b>任务已暂停</b>\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                # 尝试获取任务状态，看是否已经是暂停状态
                try:
                    task_info = await self.aria2_client.get_download(gid)
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

    @command("unpause") # Register command using decorator
    async def cmd_unpause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /unpause 命令，恢复任务"""
        if not await self.check_authorized(update):
            return

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
            # 使用注入的 Aria2 客户端实例
            result = await self.aria2_client.resume_download(gid)

            if result:
                await update.message.reply_text(
                    f"▶️ <b>任务已恢复</b>\n"
                    f"GID: <code>{gid}</code>",
                    parse_mode=ParseMode.HTML
                )
            else:
                 # 尝试获取任务状态，看是否已经是活动状态
                try:
                    task_info = await self.aria2_client.get_download(gid)
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

    @command("remove") # Register command using decorator
    async def cmd_remove(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /remove 命令，删除任务"""
        if not await self.check_authorized(update):
            return

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
            # 使用注入的 Aria2 客户端实例
            # 先尝试获取任务信息（用于后面添加到历史记录）
            task_info = None
            try:
                task_info = await self.aria2_client.get_download(gid)
            except Aria2TaskNotFoundError:
                logger.info(f"尝试删除的任务 {gid} 在Aria2中未找到，可能已被移除或不存在")
            except Aria2Error as e:
                 logger.warning(f"获取待删除任务 {gid} 信息时出错: {e}")


            result = await self.aria2_client.remove_download(gid)

            if result:
                # 将删除的任务添加到历史记录
                if task_info:
                    # 使用注入的 HistoryManager 实例
                    await self.history_manager.add_history(
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

    @command("pauseall") # Register command using decorator
    async def cmd_pauseall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /pauseall 命令，暂停所有任务"""
        if not await self.check_authorized(update):
            return

        try:
            message = await update.message.reply_text(
                "⚙️ 正在暂停所有下载任务...",
                parse_mode=ParseMode.HTML
            )

            # 使用注入的 Aria2 客户端实例
            # 获取暂停前的活动任务数量
            active_tasks = await self.aria2_client.get_active_downloads()
            active_count = len(active_tasks)

            if active_count == 0:
                await message.edit_text(
                    "ℹ️ <b>当前没有活动的下载任务</b>",
                    parse_mode=ParseMode.HTML
                )
                return

            # 暂停所有任务
            result = await self.aria2_client.pause_all()

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

    @command("unpauseall") # Register command using decorator
    async def cmd_unpauseall(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /unpauseall 命令，恢复所有任务"""
        if not await self.check_authorized(update):
            return

        try:
            message = await update.message.reply_text(
                "⚙️ 正在恢复所有下载任务...",
                parse_mode=ParseMode.HTML
            )

            # 使用注入的 Aria2 客户端实例
            # 获取恢复前的暂停任务数量（更准确的方式是直接调用 unpauseAll）
            # paused_count = sum(1 for task in waiting_tasks if task.get('is_paused', False)) # 这个不准确

            # 恢复所有任务
            result = await self.aria2_client.resume_all()

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

    @command("history") # Register command using decorator
    async def cmd_history(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /history 命令，浏览下载历史记录"""
        if not await self.check_authorized(update):
            return

        try:
            message = await update.message.reply_text(
                "📜 正在加载下载历史记录...",
                parse_mode=ParseMode.HTML
            )

            # 获取历史记录
            # 使用注入的 HistoryManager 实例
            page = 1
            items_per_page = self.config.items_per_page

            histories, total = await self.history_manager.get_history(
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

            # 保存分页状态
            user_id = update.effective_user.id
            self.states["history_pages"][user_id] = {
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

    # Note: ConversationHandler entry points are handled separately in setup()
    async def cmd_clearhistory_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理 /clearhistory 命令，启动清空历史记录确认流程"""
        if not await self.check_authorized(update):
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

    async def cmd_clearhistory_confirm(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理确认清空历史记录 (CallbackQueryHandler)"""
        query = update.callback_query
        await query.answer() # 响应按钮点击

        if not await self.check_authorized(update):
            return ConversationHandler.END

        try:
            # 编辑原消息，显示正在处理
            await query.edit_message_text(
                "⚙️ 正在清空历史记录...",
                parse_mode=ParseMode.HTML
            )

            # 使用注入的 HistoryManager 实例
            count = await self.history_manager.clear_history()

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

    async def cmd_clearhistory_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理取消清空历史记录 (CallbackQueryHandler)"""
        query = update.callback_query
        await query.answer() # 响应按钮点击

        await query.edit_message_text(
            "🚫 <b>操作已取消</b>\n"
            "历史记录未被清空",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END # 结束会话

    async def cmd_clearhistory_cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """处理 /cancel 命令来取消清空历史记录"""
        await update.message.reply_text(
            "🚫 <b>操作已取消</b>\n"
            "清空历史记录操作已取消。",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END # 结束会话


    @command("globalstatus") # Register command using decorator
    async def cmd_globalstatus(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /globalstatus 命令，显示 Aria2 全局状态"""
        if not await self.check_authorized(update):
            return

        try:
            message = await update.message.reply_text(
                "🌐 正在获取 Aria2 全局状态...",
                parse_mode=ParseMode.HTML
            )

            # 使用注入的 Aria2 客户端实例
            status = await self.aria2_client.get_global_status()

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

    @command("searchhistory") # Register command using decorator
    async def cmd_searchhistory(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理 /searchhistory 命令，搜索历史记录"""
        if not await self.check_authorized(update):
            return

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
            # 使用注入的 HistoryManager 实例
            page = 1
            items_per_page = self.config.items_per_page

            histories, total = await self.history_manager.search_history(
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

            # 保存分页状态
            user_id = update.effective_user.id
            self.states["search_pages"][user_id] = {
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

    # 回调查询处理
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理内联键盘按钮的回调查询 (非会话)"""
        query = update.callback_query

        # 权限检查
        if not await self.check_authorized(update):
            # query.answer 已经在 check_authorized 中调用
            return

        # 解析回调数据
        action, value = utils.parse_callback_data(query.data)
        user_id = update.effective_user.id

        try:
            await query.answer() # 先响应回调，避免超时

            # 处理任务操作回调
            if action == "pause":
                await self._handle_pause_callback(query, value)
            elif action == "resume":
                await self._handle_resume_callback(query, value)
            elif action == "remove":
                await self._handle_remove_callback(query, value)

            # 处理分页回调
            elif action == "history_page":
                await self._handle_history_page_callback(query, value, user_id)
            elif action == "search_page":
                await self._handle_search_page_callback(query, value, user_id)
            elif action == "status_page":
                await self._handle_status_page_callback(query, value, user_id)

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


    # 回调处理辅助方法
    async def _handle_pause_callback(self, query, gid):
        """处理暂停任务回调"""
        try:
            # 使用注入的 Aria2 客户端实例
            result = await self.aria2_client.pause_download(gid)

            if result:
                # 更新消息中的任务信息
                await asyncio.sleep(0.5) # 给Aria2一点时间更新状态
                task_info = await self.aria2_client.get_download(gid)
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


    async def _handle_resume_callback(self, query, gid):
        """处理恢复任务回调"""
        try:
            # 使用注入的 Aria2 客户端实例
            result = await self.aria2_client.resume_download(gid)

            if result:
                # 更新消息中的任务信息
                await asyncio.sleep(0.5) # 给Aria2一点时间更新状态
                task_info = await self.aria2_client.get_download(gid)
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

    async def _handle_remove_callback(self, query, gid):
        """处理删除任务回调"""
        try:
            # 使用注入的 Aria2 客户端实例
            # 先获取任务信息
            task_info = None
            try:
                task_info = await self.aria2_client.get_download(gid)
            except Aria2TaskNotFoundError:
                 logger.info(f"尝试删除的任务 {gid} 在Aria2中未找到")
            except Aria2Error as e:
                 logger.warning(f"获取待删除任务 {gid} 信息时出错: {e}")


            result = await self.aria2_client.remove_download(gid)

            if result:
                # 将删除的任务添加到历史记录
                if task_info:
                    # 使用注入的 HistoryManager 实例
                    await self.history_manager.add_history(
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
                await query.answer("✅ 任务已删除") # 在编辑消息后响应
            else:
                 # 如果 remove 返回 false，但之前获取信息时任务不存在，则认为已删除
                if task_info is None:
                    await query.edit_message_text(
                        f"ℹ️ <b>任务已被删除或不存在</b>\n"
                        f"GID: <code>{gid}</code>",
                        parse_mode=ParseMode.HTML
                    )
                    await query.answer("ℹ️ 任务已被删除或不存在")
                else:
                    await query.answer("❌ 删除任务失败", show_alert=True)

        except Aria2TaskNotFoundError: # 这个异常理论上不应该在这里触发
            await query.answer("❓ 任务不存在或已完成", show_alert=True)
            await query.edit_message_text(f"❌ 任务 <code>{gid}</code> 不存在或已完成。", parse_mode=ParseMode.HTML)
        except Aria2Error as e:
            await query.answer(f"❌ 删除失败: {str(e)[:200]}", show_alert=True)
        except Exception as e:
            logger.error(f"处理删除回调时发生错误: {e}", exc_info=True)
            await query.answer(f"🆘 发生系统错误: {str(e)[:200]}", show_alert=True)

    async def _handle_history_page_callback(self, query, value, user_id):
        """处理历史记录分页回调"""
        try:
            page = int(value)

            # 获取历史记录
            # 使用注入的 HistoryManager 实例
            items_per_page = self.config.items_per_page

            histories, total = await self.history_manager.get_history(
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

            # 更新分页状态
            self.states["history_pages"][user_id] = {
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

    async def _handle_search_page_callback(self, query, value, user_id):
        """处理搜索结果分页回调"""
        try:
            page = int(value)

            # 获取搜索关键词
            if user_id not in self.states["search_pages"]:
                await query.answer("⏳ 搜索会话已过期，请重新搜索", show_alert=True)
                return

            keyword = self.states["search_pages"][user_id]["keyword"]

            # 搜索历史记录
            # 使用注入的 HistoryManager 实例
            items_per_page = self.config.items_per_page

            histories, total = await self.history_manager.search_history(
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

            # 更新分页状态
            self.states["search_pages"][user_id] = {
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

    async def _handle_status_page_callback(self, query, value, user_id):
        """处理任务状态分页回调"""
        try:
            page = int(value)

            # 获取任务列表
            if user_id not in self.states["status_pages"]:
                # 如果状态丢失，重新获取任务列表
                # 使用注入的 Aria2 客户端实例
                active_tasks = await self.aria2_client.get_active_downloads()
                waiting_tasks = await self.aria2_client.get_waiting_downloads()
                all_tasks = active_tasks + waiting_tasks
            else:
                all_tasks = self.states["status_pages"][user_id]["tasks"]

            total_tasks = len(all_tasks)

            if total_tasks == 0:
                await query.answer("ℹ️ 没有任务", show_alert=True)
                # 可以选择编辑消息
                await query.edit_message_text("📭 <b>没有活动或等待中的下载任务</b>", parse_mode=ParseMode.HTML)
                return

            # 配置分页
            items_per_page = self.config.items_per_page
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

            # 更新分页状态
            self.states["status_pages"][user_id] = {
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

    # _handle_clear_history_confirm_callback 和 _handle_clear_history_cancel_callback
    # 已经在 ConversationHandler 中定义，这里不需要重复定义

    # 错误处理
    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """处理程序运行时发生的错误"""
        # 打印错误堆栈跟踪
        logger.error("发生异常:", exc_info=context.error)

        # 获取异常的可读描述
        tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
        tb_string = "".join(tb_list)

        # 简短的异常描述
        error_message = f"发生错误: {context.error}"

        # 对于 Update 对象，我们可以向用户发送消息
        if isinstance(update, Update) and update.effective_message:
            try:
                await update.effective_message.reply_text(
                    f"🆘 <b>系统错误</b>\n\n发生了一个内部错误，请稍后再试或联系管理员。\n错误详情: <code>{utils.escape_html(str(context.error))}</code>",
                    parse_mode=ParseMode.HTML
                )
            except Exception as e:
                logger.error(f"发送错误消息给用户失败: {e}")
        elif isinstance(update, Update) and update.callback_query:
             try:
                await update.callback_query.answer(f"🆘 系统错误: {str(context.error)[:150]}", show_alert=True)
             except Exception as e:
                logger.error(f"发送回调错误提示失败: {e}")


# 处理下载任务通知的类
class NotificationService:
    """
    处理下载任务完成/失败通知的服务类
    需要在主程序中定期调用 check_and_notify 方法
    """
    # Applying Dependency Injection: Injecting dependencies via constructor
    def __init__(self, bot_app: Application, history_manager: 'HistoryManager'):
        """
        初始化通知服务

        Args:
            bot_app: Telegram Bot Application 实例
            history_manager: 历史记录管理器实例
        """
        self.bot_app = bot_app
        self.config = get_config()
        self.history_manager = history_manager # Injected dependency
        self.notify_users = self.config.notify_users

        logger.info(f"通知服务已初始化，通知用户: {self.notify_users}")

    async def check_and_notify(self) -> None:
        """检查新完成/出错的下载任务并发送通知"""
        if not self.config.notification_enabled:
            return # 如果配置中禁用了通知，则直接返回

        try:
            # 获取未通知的完成/出错任务
            # 使用注入的 HistoryManager 实例
            unnotified_tasks = await self.history_manager.get_unnotified_completed()

            if not unnotified_tasks:
                return

            logger.info(f"发现 {len(unnotified_tasks)} 个未通知的任务")

            # 对每个任务发送通知并标记为已通知
            for task in unnotified_tasks:
                # 增加一点延迟，避免短时间内发送过多消息触发 Telegram 限制
                await asyncio.sleep(1)
                await self._send_notification(task)
                await self.history_manager.mark_as_notified(task['gid'])

        except Exception as e:
            logger.error(f"检查和发送通知时发生错误: {e}", exc_info=True)

    async def _send_notification(self, task: Dict[str, Any]) -> None:
        """
        发送单个任务的通知

        Args:
            task: 任务信息字典
        """
        try:
            # 根据任务状态准备通知内容
            status = task['status']

            if status == 'completed':
                icon = "✅"
                status_text = "下载完成"
            elif status == 'error':
                icon = "❌"
                status_text = "下载失败"
            else:
                return  # 忽略其他状态

            # 格式化通知消息
            name = task['name']
            gid = task['gid']
            size = utils.format_size(task['size'] or 0)
            datetime_str = task['datetime']

            message_text = (
                f"{icon} <b>{status_text}</b>\n\n"
                f"<b>文件名:</b> {utils.escape_html(name)}\n"
                f"<b>GID:</b> <code>{gid}</code>\n"
                f"<b>大小:</b> {size}\n"
                f"<b>时间:</b> {datetime_str}"
            )

            if status == 'error' and task.get('error_message'):
                message_text += f"\n<b>错误:</b> {utils.escape_html(task['error_message'])}"

            # 向所有配置的通知用户发送消息
            for user_id in self.notify_users:
                try:
                    await self.bot_app.bot.send_message(
                        chat_id=user_id,
                        text=message_text,
                        parse_mode=ParseMode.HTML
                    )
                    logger.info(f"已向用户 {user_id} 发送 GID={gid} 的通知")
                except Exception as send_error:
                    logger.error(f"向用户 {user_id} 发送通知失败: {send_error}")

        except Exception as e:
            logger.error(f"发送通知时发生错误 (GID={task.get('gid', '未知')}): {e}", exc_info=True)
