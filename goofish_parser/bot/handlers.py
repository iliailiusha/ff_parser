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

_GEN_KEY = "ff_gen"


def _bump_gen(context: ContextTypes.DEFAULT_TYPE, user_id: int) -> int:
    bd = context.application.bot_data
    if _GEN_KEY not in bd:
        bd[_GEN_KEY] = {}
    gen = bd[_GEN_KEY].get(user_id, 0) + 1
    bd[_GEN_KEY][user_id] = gen
    return gen


def _is_stale(context: ContextTypes.DEFAULT_TYPE, user_id: int, gen: int | None) -> bool:
    if gen is None:
        return False
    bd = context.application.bot_data
    return bd.get(_GEN_KEY, {}).get(user_id, 0) != gen

BRAND_SELECT, TYPE_SELECT, PRICE_SELECT, PRICE_INPUT_MIN, PRICE_INPUT_MAX = range(5)
FIND_ITEMS_PER_PAGE = 5


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = _bump_gen(context, update.effective_user.id)
    context.user_data["_entry_gen"] = gen
    context.user_data.pop("find_mode", None)
    welcome = (
        "👋 Привет! Я бот для поиска выгодных товаров на FruitsFamily (韩国二手平台).\n\n"
        "Выбери бренд чтобы начать:"
    )
    await update.message.reply_text(
        welcome,
        reply_markup=build_brand_keyboard(),
    )
    return BRAND_SELECT


async def find_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = _bump_gen(context, update.effective_user.id)
    context.user_data["_entry_gen"] = gen
    if context.args:
        text = " ".join(context.args)
        chat_id = update.effective_chat.id
        msg = await context.bot.send_message(chat_id=chat_id, text=f"🔍 Ищу *{text}*...", parse_mode="Markdown")
        try:
            items = await search_products_free_text(text, sort="NEW", limit=100)
            if not items:
                await msg.edit_text(f"😕 Ничего не найдено по запросу *{text}*.", parse_mode="Markdown")
                return ConversationHandler.END
            save_items(items, text)
            key = f"find_{update.effective_user.id}"
            context.user_data[key] = {
                "items": items,
                "total_pages": (len(items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE,
                "query": text,
            }
            await _show_find_page(update, context, msg, key, 0, gen=gen)
        except Exception as e:
            logger.exception("Find error")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {e}")
        return ConversationHandler.END

    context.user_data["find_mode"] = True
    await update.message.reply_text(
        "👋 Выбери бренд для поиска новых товаров:",
        reply_markup=build_brand_keyboard(),
    )
    return BRAND_SELECT


async def on_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    brand = query.data.split(":", 1)[1]
    context.user_data["brand"] = brand
    await query.edit_message_text(
        f"Бренд: *{brand}*\n\nТеперь выбери тип одежды:",
        parse_mode="Markdown",
        reply_markup=build_type_keyboard(),
    )
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return TYPE_SELECT


async def on_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    type_ru = query.data.split(":", 1)[1]
    type_ko = CLOTHING_RU_TO_KO.get(type_ru, type_ru)
    context.user_data["type_ru"] = type_ru
    context.user_data["type_ko"] = type_ko
    brand = context.user_data.get("brand", "?")
    is_find = context.user_data.get("find_mode")
    price_prompt = (
        "Укажи цену в рублях (₽) или пропусти:" if is_find
        else "Укажи цену в корейских вонах (₩) или пропусти:"
    )
    await query.edit_message_text(
        f"Бренд: *{brand}*\nТип: *{type_ru}* → *{type_ko}*\n\n{price_prompt}",
        parse_mode="Markdown",
        reply_markup=build_price_keyboard(find_mode=is_find),
    )
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return PRICE_SELECT


async def on_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    action = query.data.split(":", 1)[1]
    if action == "skip":
        context.user_data["price_min"] = None
        context.user_data["price_max"] = None
        sent = await query.edit_message_text("🔍 Ищу...")
        if _is_stale(context, user_id, gen):
            return ConversationHandler.END
        return await execute_search(update, context, query.message, gen=gen)

    if action == "rub":
        context.user_data["price_currency"] = "RUB"
        prompt = (
            "Введи минимальную цену в рублях (₽):\n"
            "Например: `1000`\n\n"
            "Или отправь /cancel чтобы отменить."
        )
    elif action == "krw":
        context.user_data["price_currency"] = "KRW"
        prompt = (
            "Введи минимальную цену в вонах (₩):\n"
            "Например: `50000`\n\n"
            "Или отправь /cancel чтобы отменить."
        )
    else:
        prompt = (
            "Введи минимальную цену в вонах (₩):\n"
            "Например: `50000`\n\n"
            "Или отправь /cancel чтобы отменить."
        )
    await query.edit_message_text(prompt, parse_mode="Markdown")
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return PRICE_INPUT_MIN


async def on_price_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    text = update.message.text.strip()
    try:
        context.user_data["price_min"] = float(text)
    except ValueError:
        await update.message.reply_text("❌ Введи число. Попробуй снова:")
        return PRICE_INPUT_MIN
    cur = context.user_data.get("price_currency", "KRW")
    currency = "рублях (₽)" if cur == "RUB" else "вонах (₩)"
    example = "`3000`" if cur == "RUB" else "`300000`"
    await update.message.reply_text(
        f"Теперь введи максимальную цену в {currency}:\n"
        f"Например: {example}\n"
        "Или отправь /skip чтобы пропустить.",
        parse_mode="Markdown",
    )
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
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
    gen = context.user_data.get("_entry_gen")
    return await execute_search(update, context, msg, gen=gen)


async def execute_search(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    msg,
    gen: int | None = None,
) -> int:
    user_id = update.effective_user.id
    brand = context.user_data.get("brand", "")
    type_ko = context.user_data.get("type_ko", "")
    type_ru = context.user_data.get("type_ru", "")
    price_min = context.user_data.get("price_min")
    price_max = context.user_data.get("price_max")

    label = f"{brand} {type_ru}"

    def cancelled():
        return gen is not None and _is_stale(context, user_id, gen)

    try:
        is_find = context.user_data.pop("find_mode", None)
        if is_find:
            price_currency = context.user_data.pop("price_currency", None)
            if price_currency == "RUB":
                rate = get_krw_to_rub()
                if price_min is not None:
                    price_min = int(float(price_min) / rate)
                if price_max is not None:
                    price_max = int(float(price_max) / rate)
            raw = await search_products_free_text(
                f"{brand} {type_ko}".strip(), sort="NEW", limit=100,
                price_min=int(price_min) if price_min else None,
                price_max=int(price_max) if price_max else None,
                auto_detect_clothing=False,
            )
            if cancelled():
                return ConversationHandler.END
            items = raw
            if not items:
                text = f"😕 Ничего не найдено по запросу *{label}*.\nПопробуйте изменить параметры."
                if hasattr(msg, "edit_message_text"):
                    await msg.edit_message_text(text, parse_mode="Markdown")
                elif hasattr(msg, "edit_text"):
                    await msg.edit_text(text, parse_mode="Markdown")
                else:
                    await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")
                return ConversationHandler.END
            save_items(items, label)
            key = f"find_conv_{update.effective_user.id}"
            context.user_data[key] = {
                "items": items,
                "total_pages": (len(items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE,
                "query": label,
            }
            await _show_find_page(update, context, msg, key, 0, gen=gen)
            return ConversationHandler.END

        result = await search_by_brand_type(
            brand=brand,
            item_type=type_ko,
            price_min=price_min,
            price_max=price_max,
            limit=40,
        )
        if cancelled():
            return ConversationHandler.END
        items = result.items if result else []
        if not items:
            text = f"😕 Ничего не найдено по запросу *{label}*.\nПопробуйте изменить параметры."
            if hasattr(msg, "edit_message_text"):
                await msg.edit_message_text(text, parse_mode="Markdown")
            elif hasattr(msg, "edit_text"):
                await msg.edit_text(text, parse_mode="Markdown")
            else:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")
            return ConversationHandler.END

        save_search(brand, type_ru, price_min, price_max)
        save_items(items, label)

        market = calculate_market_price(items)
        scored = score_items(items, market)

        save_scored_items(scored)
        text = format_search_result(scored, brand, type_ru)
        chat_id = update.effective_chat.id

        # send summary text
        if hasattr(msg, "edit_message_text"):
            await msg.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        elif hasattr(msg, "edit_text"):
            await msg.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", disable_web_page_preview=True)
        if cancelled():
            return ConversationHandler.END

        # send photos for top 5 deals
        rate = get_krw_to_rub()
        for s in scored[:5]:
            if cancelled():
                return ConversationHandler.END
            item = s.item
            time_str = f" 🕐{_format_time(item.created_at)}" if item.created_at else ""
            link = f"[🔍 Искать на FF](https://fruitsfamily.com/search?q={urllib.parse.quote(item.title)})"
            seller = f" | [👤 Продавец]({item.url})" if item.url != "https://fruitsfamily.com" else ""
            caption = (
                f"*{item.title}*\n"
                f"💰 {item.price_cny:,.0f}₩ (~{round(item.price_cny * rate):.0f}₽){time_str}\n"
                f"{link}{seller}"
            )
            if item.images:
                try:
                    await context.bot.send_photo(chat_id=chat_id, photo=item.images[0], caption=caption, parse_mode="Markdown")
                except Exception:
                    pass

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

async def _show_find_page(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    msg,
    key: str,
    page: int,
    gen: int | None = None,
) -> None:
    user_id = update.effective_user.id

    def cancelled():
        return gen is not None and _is_stale(context, user_id, gen)

    data = context.user_data.get(key)
    if not data:
        await msg.edit_text("❌ Результаты поиска устарели. Попробуй /find заново.")
        return

    items = data["items"]
    query = data.get("korean_query") or data["query"]
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
        await context.bot.send_message(chat_id=chat_id, text="😕 Больше товаров по запросу нет.")
        return

    for item in batch:
        if cancelled():
            return
        price_rub = round(item.price_cny * rate)
        discount = ""
        if item.price_original_cny and item.price_original_cny > item.price_cny:
            d = round((1 - item.price_cny / item.price_original_cny) * 100)
            discount = f" 📉 -{d}%"
        time_str = f" 🕐{_format_time(item.created_at)}" if item.created_at else ""
        brand_str = f"🏷 *{item.location}*\n" if item.location else ""
        search_link = f"https://fruitsfamily.com/search?q={urllib.parse.quote(item.title)}"
        sel_url = item.url if item.url and item.url not in ("https://fruitsfamily.com", "https://fruitsfamily.com/") else None
        seller_ref = f" | [👤 Продавец]({sel_url})" if sel_url else ""
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

    if cancelled():
        return

    # navigation message
    buttons = []
    row = []
    if page > 0:
        row.append(InlineKeyboardButton("◀️", callback_data=f"find_pg:{key}:{page - 1}"))
    row.append(InlineKeyboardButton(f"{page + 1}/{total}", callback_data="find_pg:noop"))
    if page < total - 1:
        row.append(InlineKeyboardButton("▶️", callback_data=f"find_pg:{key}:{page + 1}"))
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


def _created_at_dt(item) -> datetime:
    if item.created_at:
        try:
            return datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
        except Exception:
            pass
    return datetime.min


async def find_nav_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return
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

    await _show_find_page(update, context, query.message, key, page, gen=gen)


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
    test = await graphql("{ getCategoriesCached(limit: 1) { id name } }")
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
            CommandHandler("find", find_start),
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
        allow_reentry=True,
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
