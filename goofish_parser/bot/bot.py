import asyncio
import logging

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from goofish_parser.config import TELEGRAM_BOT_TOKEN
from goofish_parser.bot.handlers import start, search_command, recent_command, help_command

logger = logging.getLogger(__name__)


def run_bot() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("help", help_command))

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
