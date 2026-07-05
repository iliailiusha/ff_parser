import asyncio
import logging
from datetime import time

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from goofish_parser.config import TELEGRAM_BOT_TOKEN
from goofish_parser.bot.handlers import start, search_command, recent_command, help_command, rate_command
from goofish_parser.services.exchange_rate import update_rate_daily

logger = logging.getLogger(__name__)


async def daily_rate_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    rate = update_rate_daily()
    logger.info(f"Daily CNY rate update: {rate:.2f} RUB")


def run_bot() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("search", search_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("rate", rate_command))
    app.add_handler(CommandHandler("help", help_command))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_rate_update, time=time(10, 0, 0))
        logger.info("Daily CNY rate update scheduled at 10:00 MSK")

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
