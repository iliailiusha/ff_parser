import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from goofish_parser.analyzer.market import calculate_market_price
from goofish_parser.analyzer.scoring import score_items
from goofish_parser.bot.messages import format_search_result, HELP_TEXT
from goofish_parser.scraper.search import search_by_brand_type
from goofish_parser.scraper.session import ensure_session
from goofish_parser.services.exchange_rate import get_cny_to_rub, fetch_cny_rate
from goofish_parser.storage.db import save_search, save_items, save_scored_items, get_recent_deals

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 Привет! Я бот для поиска выгодных товаров на Goofish (闲鱼).\n\n"
        "Используй /help для списка команд."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args
    if len(args) < 2:
        await update.message.reply_text(
            "❓ Использование: `/search <бренд> <тип> [мин_цена] [макс_цена]`\n"
            "Пример: `/search Nike кроссовки 500 2000`",
            parse_mode="Markdown",
        )
        return

    brand = args[0]
    item_type = args[1]
    price_min: Optional[float] = None
    price_max: Optional[float] = None

    if len(args) >= 3:
        try:
            price_min = float(args[2])
        except ValueError:
            pass
    if len(args) >= 4:
        try:
            price_max = float(args[3])
        except ValueError:
            pass

    msg = await update.message.reply_text(
        f"🔍 Ищу *{brand} {item_type}* на Goofish...\n"
        f"💰 Цена: {price_min or '?'}–{price_max or '?'} ¥\n"
        "⏳ Это может занять 15–30 секунд...",
        parse_mode="Markdown",
    )

    try:
        await ensure_session()
        items = await search_by_brand_type(
            brand=brand,
            item_type=item_type,
            price_min=price_min,
            price_max=price_max,
            limit=40,
        )

        if not items:
            await msg.edit_text(
                f"😕 Ничего не найдено по запросу *{brand} {item_type}*.\n"
                f"Попробуйте изменить параметры поиска.",
                parse_mode="Markdown",
            )
            return

        save_search(brand, item_type, price_min, price_max)
        save_items(items, f"{brand} {item_type}")

        market = calculate_market_price(items)
        scored = score_items(items, market)

        save_scored_items(scored)
        result = format_search_result(scored, brand, item_type)

        for chunk in _chunk_text(result, 4000):
            await msg.edit_text(chunk, parse_mode="Markdown")
            if len(chunk) < len(result):
                msg = await update.message.reply_text("...")

    except Exception as e:
        logger.exception("Search error")
        await msg.edit_text(
            f"❌ Ошибка при поиске: {e}\n\n"
            f"Возможно, Goofish заблокировал запрос. Попробуйте позже."
        )


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
