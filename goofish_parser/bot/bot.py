import asyncio
import logging
from datetime import time

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

from goofish_parser.config import TELEGRAM_BOT_TOKEN, API_BASE_URL
from telegram.ext import CallbackQueryHandler
from goofish_parser.bot.handlers import search_conversation, recent_command, help_command, rate_command, status_command, find_nav_callback
from goofish_parser.services.exchange_rate import update_rate_daily

logger = logging.getLogger(__name__)


async def daily_rate_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    rate = update_rate_daily()
    logger.info(f"Daily KRW rate update: {rate:.4f} RUB")


def _build_app():
    async def _post_init(app: Application) -> None:
        await app.bot.set_my_commands([
            BotCommand("search", "🔍 Поиск товаров"),
            BotCommand("status", "📊 Статус API"),
            BotCommand("rate", "💱 Курс KRW/RUB"),
            BotCommand("find", "🔍 Быстрый поиск"),
            BotCommand("recent", "🔥 Лучшие находки"),
            BotCommand("help", "📖 Справка"),
        ])
        logger.info("Bot commands registered")

    builder = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init)

    if API_BASE_URL:
        base = API_BASE_URL.strip().rstrip("/")
        if not base.startswith(("http://", "https://")):
            base = "https://" + base
        builder.base_url(f"{base}/api/bot")
        builder.base_file_url(f"{base}/api/file")
        logger.info(f"Using Telegram proxy: {base}")

    return builder.build()


def run_bot() -> None:
    if not TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = _build_app()

    app.add_handler(search_conversation())
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("rate", rate_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(find_nav_callback, pattern=r"^find_pg:"))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_rate_update, time=time(10, 0, 0))
        logger.info("Daily KRW rate update scheduled at 10:00 MSK")

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
