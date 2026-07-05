import asyncio
import logging

from telegram import Update
from telegram.ext import ContextTypes

from goofish_parser.config import TELEGRAM_USER_ID
from goofish_parser.bot.qr_login import get_qr_code, poll_login
from goofish_parser.scraper.session import get_token

logger = logging.getLogger(__name__)


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = str(update.effective_user.id)
    if TELEGRAM_USER_ID and user_id != TELEGRAM_USER_ID:
        await update.message.reply_text(
            "❌ Только владелец бота может войти в 闲鱼.\n"
            "Поиск работает для всех после авторизации."
        )
        return

    msg = await update.message.reply_text("🔄 Генерирую QR-код для входа в 闲鱼...")

    def _get_qr():
        return get_qr_code()

    result = await asyncio.to_thread(_get_qr)
    if result is None:
        await msg.edit_text("❌ Не удалось получить QR-код. Попробуй позже.")
        return

    qr_bytes, code_content, session = result

    await msg.delete()
    await update.message.reply_photo(
        photo=qr_bytes,
        caption=(
            "📱 *Вход в Goofish (闲鱼)*\n\n"
            "1. Открой приложение 闲鱼 на телефоне\n"
            "2. Нажми `+` → `扫一扫`\n"
            "3. Отсканируй этот QR-код\n"
            "4. Подтверди вход на телефоне\n\n"
            "⏳ Ожидаю сканирования... (до 2 минут)"
        ),
        parse_mode="Markdown",
    )

    status_msg = await update.message.reply_text("🔄 Ожидаю сканирования QR-кода...")

    last_status = ""

    def on_status(s):
        nonlocal last_status
        if s == "scanned" and last_status != "scanned":
            last_status = "scanned"

    async def poll():
        return await asyncio.to_thread(poll_login, session, on_status)

    poll_task = asyncio.create_task(poll())

    while not poll_task.done():
        await asyncio.sleep(3)
        if last_status == "scanned":
            await status_msg.edit_text("✅ QR отсканирован! Теперь подтверди вход на телефоне...")
            last_status = "confirmed"

    success = poll_task.result()

    if success:
        await status_msg.edit_text(
            "✅ *Вход выполнен успешно!*\n\n"
            "Теперь бот может искать товары на Goofish.\n"
            "Используй /search чтобы начать.",
            parse_mode="Markdown",
        )
        logger.info("QR login completed successfully")
    else:
        await status_msg.edit_text(
            "❌ *Время вышло.*\n\n"
            "Попробуй снова: /login\n"
            "Убедись что:\n"
            "• У тебя установлено приложение 闲鱼\n"
            "• Ты подтвердил вход на телефоне",
            parse_mode="Markdown",
        )
