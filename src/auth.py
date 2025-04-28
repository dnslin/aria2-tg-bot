import logging
from telegram import Update
from .config import get_config

# 设置日志记录器
logger = logging.getLogger(__name__)

async def check_authorized(update: Update) -> bool:
    """
    检查用户是否有权限使用 Bot

    Args:
        update: 收到的更新消息

    Returns:
        是否有权限
    """
    config = get_config() # 获取配置
    user_id = update.effective_user.id

    # 检查用户 ID 是否在授权列表中
    if user_id in config.authorized_users:
        return True

    # 不在授权列表中，发送拒绝消息
    logger.warning(f"未授权用户尝试访问: {user_id} ({update.effective_user.username})")

    if update.callback_query:
        await update.callback_query.answer("您没有权限使用此 Bot", show_alert=True)
    elif update.effective_message:
        await update.effective_message.reply_text("🚫 您没有权限使用此 Bot")

    return False