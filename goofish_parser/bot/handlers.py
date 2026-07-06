import logging
import urllib.parse
from datetime import datetime
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    MessageHandler, filters, CommandHandler,
)

from goofish_parser.analyzer.market import calculate_market_price
from goofish_parser.analyzer.scoring import score_items
from goofish_parser.bot.messages import format_search_result, HELP_TEXT
from goofish_parser.bot.keyboards import build_brand_keyboard, build_type_keyboard, build_price_keyboard
from goofish_parser.bot.translation import CLOTHING_RU_TO_KO
from goofish_parser.ff_scraper.search import search_by_brand_type, search_products_free_text
from goofish_parser.services.exchange_rate import get_krw_to_rub, fetch_krw_rate
from goofish_parser.storage.db import save_search, save_items, save_scored_items, get_recent_deals

logger = logging.getLogger(__name__)

BRAND_SELECT, TYPE_SELECT, PRICE_SELECT, PRICE_INPUT_MIN, PRICE_INPUT_MAX = range(5)
FIND_ITEMS_PER_PAGE = 5


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    welcome = (
        "👋 Привет! Я бот для поиска выгодных товаров на FruitsFamily (韩国二手平台).\n\n"
        "Выбери бренд чтобы начать:"
    )
    await update.message.reply_text(
        welcome,
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
    type_ko = CLOTHING_RU_TO_KO.get(type_ru, type_ru)
    context.user_data["type_ru"] = type_ru
    context.user_data["type_ko"] = type_ko
    brand = context.user_data.get("brand", "?")
    await query.edit_message_text(
        f"Бренд: *{brand}*\nТип: *{type_ru}* → *{type_ko}*\n\n"
        f"Укажи цену в корейских вонах (₩) или пропусти:",
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
            "Введи минимальную цену в вонах (₩):\n"
            "Например: `50000`\n\n"
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
        "Теперь введи максимальную цену в вонах (₩):\n"
        "Например: `300000`\n"
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
    type_ko = context.user_data.get("type_ko", "")
    type_ru = context.user_data.get("type_ru", "")
    price_min = context.user_data.get("price_min")
    price_max = context.user_data.get("price_max")

    label = f"{brand} {type_ru}"

    try:
        result = await search_by_brand_type(
            brand=brand,
            item_type=type_ko,
            price_min=price_min,
            price_max=price_max,
            limit=40,
        )

        items = result.items
        if not items:
            await msg.edit_text(
                f"😕 Ничего не найдено по запросу *{label}*.\n"
                f"Попробуйте изменить параметры.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        save_search(brand, type_ru, price_min, price_max)
        save_items(items, label)

        market = calculate_market_price(items)
        scored = score_items(items, market)

        save_scored_items(scored)
        text = format_search_result(scored, brand, type_ru)

        for chunk in _chunk_text(text, 4000):
            try:
                await msg.edit_text(chunk, parse_mode="Markdown")
            except Exception:
                msg = await update.effective_chat.send_message(chunk, parse_mode="Markdown")
            if len(chunk) < len(text):
                msg = await update.effective_chat.send_message("...")

    except Exception as e:
        logger.exception("Search error")
        error_text = f"❌ Ошибка при поиске: {e}\n\nПопробуйте позже."
        if hasattr(msg, "edit_message_text"):
            await msg.edit_message_text(error_text)
        elif hasattr(msg, "edit_text"):
            await msg.edit_text(error_text)
        else:
            await update.effective_chat.send_message(error_text)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Поиск отменён.", reply_markup=None)
    return ConversationHandler.END


def _format_time(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%d.%m %H:%M")
    except Exception:
        return iso_str[:16]


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = " ".join(context.args) if context.args else ""
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        return

    if not text:
        await context.bot.send_message(
            chat_id=chat_id,
            text="🔍 *Поиск новых товаров*\n\n"
            "Используй: `/find <запрос>`\n"
            "Например: `/find Nike`\n\n"
            "Результаты сортируются по дате (самые свежие).",
            parse_mode="Markdown",
        )
        return

    msg = await context.bot.send_message(chat_id=chat_id, text=f"🔍 Ищу *{text}*...", parse_mode="Markdown")

    try:
        items = search_products_free_text(text, sort="NEW", limit=10)
        if not items:
            await msg.edit_text(
                f"😕 Ничего не найдено по запросу *{text}*.",
                parse_mode="Markdown",
            )
            return

        save_items(items, text)

        key = f"find_{update.effective_user.id}"
        context.user_data[key] = {
            "items": items,
            "total_pages": (len(items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE,
            "query": text,
            "limit": 10,
        }

        await _show_find_page(update, context, msg, key, 0)

    except Exception as e:
        logger.exception("Find error")
        try:
            await msg.edit_text(f"❌ Ошибка: {e}")
        except Exception:
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {e}")


async def _show_find_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    msg,
    key: str,
    page: int,
) -> None:
    data = context.user_data.get(key)
    if not data:
        await msg.edit_text("❌ Результаты поиска устарели. Попробуй /find заново.")
        return

    items = data["items"]
    query = data["query"]

    # Auto-load more when beyond loaded items
    while True:
        start = page * FIND_ITEMS_PER_PAGE
        if start < len(items):
            break
        old_limit = data.get("limit", 10)
        new_limit = old_limit + 30
        new_raw = search_products_free_text(query, sort="NEW", limit=new_limit, auto_detect_clothing=False)
        existing_ids = {i.item_id for i in items}
        new_count = 0
        for i in new_raw:
            if i.item_id not in existing_ids:
                items.append(i)
                new_count += 1
        data["items"] = items
        data["limit"] = new_limit
        if new_count == 0:
            break

    total = (len(items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE
    data["total_pages"] = total
    start = page * FIND_ITEMS_PER_PAGE
    batch = items[start:start + FIND_ITEMS_PER_PAGE]
    rate = get_krw_to_rub()

    # delete old messages from previous page
    old_ids = context.user_data.pop(key + "_msg_ids", [])
    for mid in old_ids:
        try:
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=mid)
        except Exception:
            pass
    try:
        await msg.delete()
    except Exception:
        pass

    new_ids = []
    chat_id = update.effective_chat.id if update.effective_chat else None
    if not chat_id:
        return

    if not batch:
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"😕 Больше товаров по запросу *{query}* нет.",
            parse_mode="Markdown",
        )
        return

    for item in batch:
        price_rub = round(item.price_cny * rate)
        discount = ""
        if item.price_original_cny and item.price_original_cny > item.price_cny:
            d = round((1 - item.price_cny / item.price_original_cny) * 100)
            discount = f" 📉 -{d}%"
        time_str = f" 🕐{_format_time(item.created_at)}" if item.created_at else ""
        brand_str = f"🏷 *{item.location}*\n" if item.location else ""
        search_link = f"https://fruitsfamily.com/search?q={urllib.parse.quote(item.title)}"
        seller_ref = f" | [👤 Продавец]({item.url})" if item.url != "https://fruitsfamily.com" else ""
        link_str = f"[🔍 Искать на FF]({search_link}){seller_ref}"

        caption = (
            f"*{item.title}*\n"
            f"{brand_str}"
            f"💰 {item.price_cny:,.0f}₩ (~{price_rub:.0f}₽){discount}{time_str}\n"
            f"{link_str}"
        )

        if item.images:
            try:
                sent = await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=item.images[0],
                    caption=caption,
                    parse_mode="Markdown",
                )
                new_ids.append(sent.message_id)
                continue
            except Exception:
                pass

        # fallback: text-only if no image or photo send failed
        sent = await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )
        new_ids.append(sent.message_id)

    # navigation message
    buttons = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"find_pg:{key}:{page - 1}"))
    row.append(InlineKeyboardButton(f"{page + 1}/{total}", callback_data="find_pg:noop"))
    if page < total - 1:
        row.append(InlineKeyboardButton("▶️", callback_data=f"find_pg:{key}:{page + 1}"))
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("❌ Закрыть", callback_data="find_pg:close")])

    nav = await context.bot.send_message(
        chat_id=chat_id,
        text=f"🔍 *{query}* — стр. {page + 1}/{total}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    new_ids.append(nav.message_id)

    context.user_data[key + "_msg_ids"] = new_ids


async def find_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "find_pg:noop":
        return
    if data == "find_pg:close":
        await query.message.delete()
        return

    parts = data.split(":", 2)
    if len(parts) != 3:
        return
    _, key, page_str = parts
    page = int(page_str)

    await _show_find_page(update, context, query.message, key, page)


async def recent_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    deals = get_recent_deals(20)
    if not deals:
        await update.message.reply_text("😕 Нет сохранённых находок. Используйте /search для поиска.")
        return

    lines = [f"🔥 *Последние выгодные находки ({len(deals)} шт.):*\n"]
    for i, d in enumerate(deals[:10], 1):
        lines.append(
            f"{'🔥' if d['discount_pct'] > 30 else '✅'} *{i}.* {d['title']}\n"
            f"💰 {d['price_krw']:,.0f} ₩ (~{d['price_rub']:.0f} ₽) | Скидка {d['discount_pct']:.1f}%\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from goofish_parser.ff_scraper.client import graphql
    test = graphql("{ getCategoriesCached(limit: 1) { id name } }")
    ok = "error" not in test
    await update.message.reply_text(
        "✅ *Статус: работает*\n\n"
        "FruitsFamily API доступен.\n"
        "Авторизация не требуется.\n"
        "Используй /search чтобы начать."
        if ok else
        f"❌ *Статус: API недоступен*\n\n"
        f"Ошибка: {test.get('error', 'неизвестно')}",
        parse_mode="Markdown",
    )


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    rate = get_krw_to_rub()
    fresh = fetch_krw_rate()
    if fresh is not None and abs(fresh - rate) > 0.0001:
        rate = fresh

    await update.message.reply_text(
        f"💱 *Курс KRW/RUB*\n\n"
        f"1 ₩ = *{rate:.4f} ₽*\n"
        f"1000 ₩ = *{rate * 1000:.0f} ₽*\n"
        f"Источник: ЦБ РФ (cbr.ru)\n"
        f"Обновляется ежедневно в 10:00 MSK",
        parse_mode="Markdown",
    )


def search_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("search", search_start),
            CommandHandler("start", search_start),
        ],
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
