from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import ContextTypes
from utils.keyboard_utils import get_task_list_buttons
import subprocess
import shutil
import logging

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
        "/tasks - 查看任务列表\n"
        "/rclone - 安装 rclone\n"
        "/unrclone - 卸载 rclone"
    )
    await update.message.reply_text(
        f"❌ 未知命令：{update.message.text}\n\n{available_commands}"
    )

async def rclone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /rclone 命令"""
    try:
        # 检查 rclone 是否已安装
        if shutil.which('rclone'):
            await update.message.reply_text(
                "✅ rclone 已经安装在系统中\n"
                "你可以直接使用 rclone 命令"
            )
            return

        # 发送开始安装消息
        status_message = await update.message.reply_text(
            "⏳ 正在安装 rclone...\n"
            "这可能需要几分钟时间，请耐心等待"
        )

        # 执行安装命令
        process = subprocess.Popen(
            "sudo -v ; curl https://rclone.org/install.sh | sudo bash",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            await status_message.edit_text(
                "✅ rclone 安装成功！\n"
                "现在你可以使用 rclone 命令了"
            )
        else:
            error_output = stderr.decode() if stderr else stdout.decode()
            await status_message.edit_text(
                f"❌ rclone 安装失败\n"
                f"错误信息：{error_output[:1000]}"  # 限制错误消息长度
            )
    except Exception as e:
        await update.message.reply_text(f"❌ 安装过程中出错：{str(e)}")

async def unrclone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理 /unrclone 命令"""
    try:
        # 检查 rclone 是否已安装
        if not shutil.which('rclone'):
            await update.message.reply_text(
                "❌ rclone 未安装在系统中\n"
                "无需卸载"
            )
            return

        # 发送开始卸载消息
        status_message = await update.message.reply_text(
            "⏳ 正在卸载 rclone...\n"
            "请稍候..."
        )

        # 执行卸载命令
        process = subprocess.Popen(
            "sudo rm -v $(which rclone) && sudo rm -rf /usr/local/share/man/man1/rclone.1",
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            await status_message.edit_text(
                "✅ rclone 卸载成功！\n"
                "所有 rclone 相关文件已被移除"
            )
        else:
            error_output = stderr.decode() if stderr else stdout.decode()
            await status_message.edit_text(
                f"❌ rclone 卸载失败\n"
                f"错误信息：{error_output[:1000]}"  # 限制错误消息长度
            )
    except Exception as e:
        await update.message.reply_text(f"❌ 卸载过程中出错：{str(e)}")