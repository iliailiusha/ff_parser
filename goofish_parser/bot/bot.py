import asyncio
import logging
import random
import threading
import time as time_module
from datetime import time
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

from goofish_parser.config import TELEGRAM_BOT_TOKEN, API_BASE_URL
from telegram.ext import CallbackQueryHandler
from goofish_parser.bot.handlers import search_conversation, recent_command, help_command, rate_command, status_command, find_nav_callback
from goofish_parser.bot.settings import settings_conversation
from goofish_parser.services.exchange_rate import update_rate_daily
from goofish_parser.services.rate_limit import init_rate_limiters, close_rate_limiters
from goofish_parser.services.cache import close_cache
from goofish_parser.services.resilience import get_parser_registry, init_parser_registry
from goofish_parser.ff_scraper.client import close_http_client

logger = logging.getLogger(__name__)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        pass


def _start_health_server():
    port = 7860
    try:
        server = HTTPServer(("0.0.0.0", port), _HealthHandler)
        logger.info("Health check server listening on 0.0.0.0:%s", port)
        server.serve_forever()
    except Exception:
        logger.exception("Health check server failed to start on port %s", port)


async def daily_rate_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    rate = await update_rate_daily()
    logger.info(f"Daily KRW rate update: {rate:.4f} RUB")


def _build_app():
    async def _post_init(app: Application) -> None:
        # Initialize rate limiters
        from goofish_parser.config import (
            RATE_LIMIT_DEFAULT_RATE, RATE_LIMIT_DEFAULT_BURST,
            SEARCH_RATE_LIMIT_WINDOW, SEARCH_RATE_LIMIT_MAX,
            REDIS_URL, REDIS_DEFAULT_TTL,
            CIRCUIT_BREAKER_FAILURE_THRESHOLD, CIRCUIT_BREAKER_RECOVERY_TIMEOUT,
        )
        await init_rate_limiters(
            default_rate=RATE_LIMIT_DEFAULT_RATE,
            default_burst=RATE_LIMIT_DEFAULT_BURST,
            search_window=SEARCH_RATE_LIMIT_WINDOW,
            search_max=SEARCH_RATE_LIMIT_MAX,
        )
        
        # Initialize Redis cache
        from goofish_parser.services.cache import init_cache
        await init_cache(url=REDIS_URL, default_ttl=REDIS_DEFAULT_TTL)
        
        # Initialize parser registry with circuit breakers
        await init_parser_registry()

        await app.bot.set_my_commands([
            BotCommand("search", "🔍 Поиск товаров"),
            BotCommand("find", "🔍 Быстрый поиск"),
            BotCommand("settings", "⚙️ Настройки площадок"),
            BotCommand("status", "📊 Статус"),
            BotCommand("rate", "💱 Курсы валют"),
            BotCommand("recent", "🔥 Находки"),
            BotCommand("help", "📖 Справка"),
        ])
        logger.info("Bot commands registered")

    async def _post_shutdown(app: Application) -> None:
        await close_rate_limiters()
        await close_cache()
        await close_http_client()
        logger.info("Services cleaned up")

    builder = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(_post_init).post_shutdown(_post_shutdown)

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
    app.add_handler(settings_conversation())
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("recent", recent_command))
    app.add_handler(CommandHandler("rate", rate_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(find_nav_callback, pattern=r"^find_pg:"))

    job_queue = app.job_queue
    if job_queue:
        job_queue.run_daily(daily_rate_update, time=time(10, 0, 0))
        logger.info("Daily KRW rate update scheduled at 10:00 MSK")

    threading.Thread(target=_start_health_server, daemon=True).start()

    delay = random.uniform(5, 15)
    logger.info("Delaying polling start by %.1fs to avoid 409 conflict", delay)
    time_module.sleep(delay)

    logger.info("Bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)
