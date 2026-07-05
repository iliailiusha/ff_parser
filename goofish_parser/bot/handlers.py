import logging
from typing import Optional

from telegram import Update, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters, CommandHandler,
)

from goofish_parser.analyzer.market import calculate_market_price
from goofish_parser.analyzer.scoring import score_items
from goofish_parser.bot.messages import format_search_result, HELP_TEXT
from goofish_parser.bot.keyboards import build_brand_keyboard, build_type_keyboard, build_price_keyboard
from goofish_parser.bot.translation import CLOTHING_RU_TO_CN
from goofish_parser.scraper.search import search_by_brand_type
from goofish_parser.scraper.session import ensure_session
from goofish_parser.services.exchange_rate import get_cny_to_rub, fetch_cny_rate
from goofish_parser.storage.db import save_search, save_items, save_scored_items, get_recent_deals

logger = logging.getLogger(__name__)

BRAND_SELECT, TYPE_SELECT, PRICE_SELECT, PRICE_INPUT_MIN, PRICE_INPUT_MAX = range(5)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from goofish_parser.bot.keyboards import build_brand_keyboard
    await update.message.reply_text(
        "👋 Привет! Я бот для поиска выгодных товаров на Goofish (闲鱼).\n\n"
        "Нажми кнопку ниже чтобы начать поиск:",
        reply_markup=build_brand_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "Выбери бренд:",
        reply_markup=build_brand_keyboard(),
    )
    return BRAND_SELECT


async def on_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    brand = query.data.split(":", 1)[1]
    context.user_data["brand"] = brand
    await query.edit_message_text(
        f"Бренд: *{brand}*\n\nТеперь выбери тип одежды:",
        parse_mode="Markdown",
        reply_markup=build_type_keyboard(),
    )
    return TYPE_SELECT


async def on_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    type_ru = query.data.split(":", 1)[1]
    type_cn = CLOTHING_RU_TO_CN.get(type_ru, type_ru)
    context.user_data["type_ru"] = type_ru
    context.user_data["type_cn"] = type_cn
    brand = context.user_data.get("brand", "?")
    await query.edit_message_text(
        f"Бренд: *{brand}*\nТип: *{type_ru}* → *{type_cn}*\n\n"
        f"Укажи цену или пропусти:",
        parse_mode="Markdown",
        reply_markup=build_price_keyboard(),
    )
    return PRICE_SELECT


async def on_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    action = query.data.split(":", 1)[1]
    if action == "skip":
        context.user_data["price_min"] = None
        context.user_data["price_max"] = None
        await query.edit_message_text("🔍 Ищу...")
        return await execute_search(update, context, query)
    else:
        await query.edit_message_text(
            "Введи минимальную цену в юанях (¥):\n"
            "Например: `500`\n\n"
            "Или отправь /cancel чтобы отменить.",
            parse_mode="Markdown",
        )
        return PRICE_INPUT_MIN


async def on_price_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        context.user_data["price_min"] = float(text)
    except ValueError:
        await update.message.reply_text("❌ Введи число. Попробуй снова:")
        return PRICE_INPUT_MIN
    await update.message.reply_text(
        "Теперь введи максимальную цену в юанях (¥):\n"
        "Например: `3000`\n"
        "Или отправь /skip чтобы пропустить.",
        parse_mode="Markdown",
    )
    return PRICE_INPUT_MAX


async def on_price_max(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    if text.lower() in ("/skip", "/s"):
        context.user_data["price_max"] = None
    else:
        try:
            context.user_data["price_max"] = float(text)
        except ValueError:
            await update.message.reply_text("❌ Введи число или /skip:")
            return PRICE_INPUT_MAX
    msg = await update.message.reply_text("🔍 Ищу...")
    return await execute_search(update, context, msg)


async def execute_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    msg,
) -> int:
    brand = context.user_data.get("brand", "")
    type_cn = context.user_data.get("type_cn", "")
    type_ru = context.user_data.get("type_ru", "")
    price_min = context.user_data.get("price_min")
    price_max = context.user_data.get("price_max")

    label = f"{brand} {type_ru}"

    try:
        await ensure_session()
        items = await search_by_brand_type(
            brand=brand,
            item_type=type_cn,
            price_min=price_min,
            price_max=price_max,
            limit=40,
        )

        if not items:
            await msg.edit_text(
                f"😕 Ничего не найдено по запросу *{label}*.\n"
                f"Попробуйте изменить параметры.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        save_search(brand, type_cn, price_min, price_max)
        save_items(items, label)

        market = calculate_market_price(items)
        scored = score_items(items, market)

        save_scored_items(scored)
        result = format_search_result(scored, label, type_cn)

        for chunk in _chunk_text(result, 4000):
            try:
                await msg.edit_text(chunk, parse_mode="Markdown")
            except Exception:
                msg = await update.effective_chat.send_message(chunk, parse_mode="Markdown")
            if len(chunk) < len(result):
                msg = await update.effective_chat.send_message("...")

    except Exception as e:
        logger.exception("Search error")
        await msg.edit_text(
            f"❌ Ошибка при поиске: {e}\n\n"
            f"Возможно, Goofish заблокировал запрос. Попробуйте позже."
        )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Поиск отменён.", reply_markup=None)
    return ConversationHandler.END


async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deals = get_recent_deals(20)
    if not deals:
        await update.message.reply_text("😕 Нет сохранённых находок. Используйте /search для поиска.")
        return

    lines = [f"🔥 *Последние выгодные находки ({len(deals)} шт.):*\n"]
    for i, d in enumerate(deals[:10], 1):
        lines.append(
            f"{'🔥' if d['discount_pct'] > 30 else '✅'} *{i}.* {d['title']}\n"
            f"💰 {d['price_cny']:.0f} ¥ (~{d['price_rub']:.0f} ₽) | Скидка {d['discount_pct']:.1f}%\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rate = get_cny_to_rub()
    fresh = fetch_cny_rate()
    if fresh is not None and abs(fresh - rate) > 0.01:
        rate = fresh

    await update.message.reply_text(
        f"💱 *Курс CNY/RUB*\n\n"
        f"1 ¥ = *{rate:.2f} ₽*\n"
        f"Источник: ЦБ РФ (cbr.ru)\n"
        f"Обновляется ежедневно в 10:00 MSK",
        parse_mode="Markdown",
    )


def search_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("search", search_start)],
        states={
            BRAND_SELECT: [CallbackQueryHandler(on_brand, pattern=r"^brand:")],
            TYPE_SELECT: [CallbackQueryHandler(on_type, pattern=r"^type:")],
            PRICE_SELECT: [CallbackQueryHandler(on_price, pattern=r"^price:")],
            PRICE_INPUT_MIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_price_min),
                CommandHandler("cancel", cancel),
            ],
            PRICE_INPUT_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_price_max),
                CommandHandler("skip", on_price_max),
                CommandHandler("cancel", cancel),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )


def _chunk_text(text: str, max_len: int) -> list[str]:
    if len(text) <= max_len:
        return [text]
    chunks = []
    while text:
        idx = text.rfind("\n", 0, max_len)
        if idx == -1:
            idx = max_len
        chunks.append(text[:idx])
        text = text[idx:].lstrip()
    return chunks
