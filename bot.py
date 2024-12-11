import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_API_BASE
from handlers.command_handlers import start, tasks, unknown_command
from handlers.message_handlers import handle_download
from handlers.callback_handlers import button_callback
from telegram.ext import ContextTypes

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """处理错误"""
    logging.error(f"更新时发生错误: {context.error}")

def main() -> None:
    """启动机器人"""
    # 配置日志
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    # 创建应用
    if TELEGRAM_API_BASE:
        # 如果设置了自定义API地址，使用代理
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).base_url(f"{TELEGRAM_API_BASE}/bot").build()
    else:
        # 否则使用默认API
        application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # 添加处理器
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("tasks", tasks))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_download))
    application.add_handler(CallbackQueryHandler(button_callback))
    # 添加未知命令处理器（必须放在所有命令处理器之后）
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))
    
    # 添加错误处理器
    application.add_error_handler(error_handler)

    # 启动机器人
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main() 