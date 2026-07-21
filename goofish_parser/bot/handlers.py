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
from goofish_parser.bot.keyboards import build_brand_keyboard, build_type_keyboard, build_price_keyboard, build_model_keyboard
from goofish_parser.bot.translation import CLOTHING_RU_TO_KO
from goofish_parser.ff_scraper.search import search_products_free_text
from goofish_parser.services.multi_search import search_all_platforms, search_all_platforms_free_text, merge_platform_results
from goofish_parser.services.exchange_rate import get_krw_to_rub, get_rate_to_rub
from goofish_parser.services.rate_limit import get_search_limiter, get_rate_limiter
from goofish_parser.services.validators import FindInput, SearchInput
from goofish_parser.storage.db import save_search, save_items, save_scored_items, get_recent_deals, increment_brand_freq, increment_type_freq, save_model, delete_model, get_disabled_brand_recs
from goofish_parser.scraper.models import PLATFORM_INFO

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

BRAND_SELECT, TYPE_SELECT, PRICE_SELECT, PRICE_INPUT_MIN, PRICE_INPUT_MAX, BRAND_INPUT, MODEL_SELECT, FREETEXT_INPUT = range(8)
FIND_ITEMS_PER_PAGE = 5


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def search_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = _bump_gen(context, update.effective_user.id)
    context.user_data["_entry_gen"] = gen
    context.user_data.pop("find_mode", None)

    # Rate limiting check
    search_limiter = get_search_limiter()
    user_id = update.effective_user.id
    if not await search_limiter.check(user_id):
        wait_time = await search_limiter.wait_time(user_id)
        await update.message.reply_text(
            f"⏳ Слишком много запросов. Подождите {wait_time:.0f} сек. перед следующим поиском."
        )
        return ConversationHandler.END

    welcome = (
        "👋 Привет! Я бот для поиска выгодных товаров на азиатских площадках б/у.\n\n"
        "🇰🇷 FruitsFamily + Bunjang | 🇸🇬 Carousell | 🇯🇵 Mercari JP\n\n"
        "Выбери бренд чтобы начать:\n\n"
        "💡 /settings — настроить площадки"
    )
    await update.message.reply_text(
        welcome,
        reply_markup=build_brand_keyboard(user_id=update.effective_user.id),
    )
    return BRAND_SELECT


async def find_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = _bump_gen(context, update.effective_user.id)
    context.user_data["_entry_gen"] = gen

    # Rate limiting check
    search_limiter = get_search_limiter()
    user_id = update.effective_user.id
    if not await search_limiter.check(user_id):
        wait_time = await search_limiter.wait_time(user_id)
        await update.message.reply_text(
            f"⏳ Слишком много запросов. Подождите {wait_time:.0f} сек. перед следующим поиском."
        )
        return ConversationHandler.END

    if context.args:
        text = " ".join(context.args)
        # Validate input
        try:
            validated = FindInput(query=text)
            text = validated.query
        except Exception as e:
            await update.message.reply_text(f"❌ Некорректный запрос: {e}")
            return ConversationHandler.END

        chat_id = update.effective_chat.id
        msg = await context.bot.send_message(chat_id=chat_id, text=f"🔍 Умный поиск *{text}* по всем площадкам...", parse_mode="Markdown")
        try:
            from goofish_parser.services.multi_search import search_all_platforms_smart
            platform_results = await search_all_platforms_smart(text, user_id=user_id, limit_per_platform=100)
            items = merge_platform_results(platform_results, sort_by="date")
            if not items:
                await msg.edit_text(f"😕 Ничего не найдено по запросу *{text}*.", parse_mode="Markdown")
                return ConversationHandler.END
            save_items(items, text)
            platform_summary = " | ".join(
                f"{PLATFORM_INFO.get(p, {}).get('country', p)} {len(its)}шт"
                for p, its in platform_results.items() if its
            )
            key = f"find_{update.effective_user.id}"
            context.user_data[key] = {
                "items": items,
                "total_pages": (len(items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE,
                "query": text,
                "platform_summary": platform_summary,
            }
            await _show_find_page(update, context, msg, key, 0, gen=gen)
        except Exception as e:
            logger.exception("Find error")
            await context.bot.send_message(chat_id=chat_id, text=f"❌ Ошибка: {e}")
        return ConversationHandler.END

    context.user_data["find_mode"] = True
    await update.message.reply_text(
        "👋 Поиск по FruitsFamily + Bunjang + Carousell + Mercari JP. /settings чтобы настроить.",
        reply_markup=build_brand_keyboard(user_id=update.effective_user.id),
    )
    return BRAND_SELECT


async def on_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    action = query.data.split(":", 1)[1]
    if action == "freetext":
        await query.edit_message_text(
            "✏️ Напиши любой поисковый запрос:\n\n"
            "Например: `Adidas Raf Simons кроссовки`, `Nike Air Force 1`, `Rick Owens`\n\n"
            "Или /cancel чтобы отменить.",
            parse_mode="Markdown",
        )
        return FREETEXT_INPUT
    brand = action
    context.user_data["brand"] = brand
    await query.edit_message_text(
        f"Бренд: *{brand}*\n\nТеперь выбери тип одежды:",
        parse_mode="Markdown",
        reply_markup=build_type_keyboard(user_id=user_id),
    )
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return TYPE_SELECT


async def on_brand_custom(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    await query.edit_message_text(
        "✏️ Напиши название своего бренда:\n\n"
        "Например: `Marni`, `Margiela`, `Raf Simons`\n\n"
        "Или /back чтобы вернуться к выбору, /cancel чтобы отменить.",
        parse_mode="Markdown",
    )
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return BRAND_INPUT


async def on_brand_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() in ("/back", "/b"):
        await update.message.reply_text(
            "👋 Выбери бренд:",
            reply_markup=build_brand_keyboard(user_id=user_id),
        )
        return BRAND_SELECT
    brand = text
    context.user_data["brand"] = brand
    await update.message.reply_text(
        f"Бренд: *{brand}*\n\nТеперь выбери тип одежды:",
        parse_mode="Markdown",
        reply_markup=build_type_keyboard(user_id=user_id),
    )
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return TYPE_SELECT


async def on_freetext_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text.lower() in ("/back", "/b", "/cancel", "/c"):
        await update.message.reply_text(
            "👋 Выбери бренд:",
            reply_markup=build_brand_keyboard(user_id=user_id),
        )
        return BRAND_SELECT
    msg = await update.message.reply_text(f"🔍 Ищу *{text}* по всем площадкам...", parse_mode="Markdown")
    try:
        from goofish_parser.services.multi_search import search_all_platforms_smart
        platform_results = await search_all_platforms_smart(text, user_id=user_id, limit_per_platform=100)
        items = merge_platform_results(platform_results, sort_by="date")
        if not items:
            await msg.edit_text(f"😕 Ничего не найдено по запросу *{text}*.", parse_mode="Markdown")
            return ConversationHandler.END
        save_items(items, text)
        platform_summary = " | ".join(
            f"{PLATFORM_INFO.get(p, {}).get('country', p)} {len(its)}шт"
            for p, its in platform_results.items() if its
        )
        key = f"find_{update.effective_user.id}"
        context.user_data[key] = {
            "items": items,
            "total_pages": (len(items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE,
            "query": text,
            "platform_summary": platform_summary,
        }
        await _show_find_page(update, context, msg, key, 0, gen=gen)
    except Exception as e:
        logger.exception("Free text search error")
        await context.bot.send_message(chat_id=update.effective_chat.id, text=f"❌ Ошибка: {e}")
    return ConversationHandler.END


async def on_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    action = query.data.split(":", 1)[1]
    if action == "back":
        brand = context.user_data.get("brand", "?")
        await query.edit_message_text(
            f"👋 Выбери бренд:\n\nТекущий: *{brand}*",
            parse_mode="Markdown",
            reply_markup=build_brand_keyboard(user_id=user_id),
        )
        return BRAND_SELECT
    type_ru = action
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


async def on_type_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    text = update.message.text.strip()
    if text.lower() in ("/back", "/b"):
        brand = context.user_data.get("brand", "?")
        await update.message.reply_text(
            f"👋 Выбери бренд:\n\nТекущий: *{brand}*",
            parse_mode="Markdown",
            reply_markup=build_brand_keyboard(user_id=user_id),
        )
        return BRAND_SELECT
    type_ru = text
    type_ko = CLOTHING_RU_TO_KO.get(type_ru, type_ru)
    context.user_data["type_ru"] = type_ru
    context.user_data["type_ko"] = type_ko
    brand = context.user_data.get("brand", "?")
    is_find = context.user_data.get("find_mode")
    price_prompt = (
        "Укажи цену в рублях (₽) или пропусти:" if is_find
        else "Укажи цену в корейских вонах (₩) или пропусти:"
    )
    await update.message.reply_text(
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
    if action == "back":
        type_ru = context.user_data.get("type_ru", "")
        type_ko = context.user_data.get("type_ko", "")
        brand = context.user_data.get("brand", "?")
        if type_ru:
            await query.edit_message_text(
                f"Бренд: *{brand}*\nТекущий тип: *{type_ru}* → *{type_ko}*\n\nВыбери тип одежды:",
                parse_mode="Markdown",
                reply_markup=build_type_keyboard(user_id=user_id),
            )
            return TYPE_SELECT
        await query.edit_message_text(
            f"👋 Выбери бренд:\n\nТекущий: *{brand}*",
            parse_mode="Markdown",
            reply_markup=build_brand_keyboard(user_id=user_id),
        )
        return BRAND_SELECT

    if action == "skip":
        context.user_data["price_min"] = None
        context.user_data["price_max"] = None
        return await _show_model_menu(update, context, query.message)

    if action == "rub":
        context.user_data["price_currency"] = "RUB"
        prompt = (
            "Введи минимальную цену в рублях (₽):\n"
            "Например: `1000`\n\n"
            "Или /back чтобы вернуться, /cancel чтобы отменить."
        )
    elif action == "krw":
        context.user_data["price_currency"] = "KRW"
        prompt = (
            "Введи минимальную цену в вонах (₩):\n"
            "Например: `50000`\n\n"
            "Или /back чтобы вернуться, /cancel чтобы отменить."
        )
    else:
        prompt = (
            "Введи минимальную цену в вонах (₩):\n"
            "Например: `50000`\n\n"
            "Или /back чтобы вернуться, /cancel чтобы отменить."
        )
    await query.edit_message_text(prompt, parse_mode="Markdown")
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return PRICE_INPUT_MIN


async def on_price_min(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text.lower() in ("/back", "/b"):
        brand = context.user_data.get("brand", "?")
        type_ru = context.user_data.get("type_ru", "")
        is_find = context.user_data.get("find_mode")
        price_prompt = (
            "Укажи цену в рублях (₽) или пропусти:" if is_find
            else "Укажи цену в корейских вонах (₩) или пропусти:"
        )
        summary = f"Бренд: *{brand}*"
        if type_ru:
            type_ko = context.user_data.get("type_ko", type_ru)
            summary += f"\nТип: *{type_ru}* → *{type_ko}*"
        await update.message.reply_text(
            f"{summary}\n\n{price_prompt}",
            parse_mode="Markdown",
            reply_markup=build_price_keyboard(find_mode=is_find),
        )
        return PRICE_SELECT
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
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text.lower() in ("/skip", "/s"):
        context.user_data["price_max"] = None
    elif text.lower() in ("/back", "/b"):
        cur = context.user_data.get("price_currency", "KRW")
        currency = "рублях (₽)" if cur == "RUB" else "вонах (₩)"
        example = "`3000`" if cur == "RUB" else "`300000`"
        await update.message.reply_text(
            f"Введи минимальную цену в {currency}:\n"
            f"Например: {example}\n"
            "Или /back чтобы вернуться к цене.",
            parse_mode="Markdown",
        )
        return PRICE_INPUT_MIN
    else:
        try:
            context.user_data["price_max"] = float(text)
        except ValueError:
            await update.message.reply_text("❌ Введи число или /skip:")
            return PRICE_INPUT_MAX
    return await _show_model_menu(update, context, None, is_message=True)


async def _show_model_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, msg, is_message: bool = False) -> int:
    user_id = update.effective_user.id
    gen = context.user_data.get("_entry_gen")
    brand = context.user_data.get("brand", "")
    type_ru = context.user_data.get("type_ru", "")
    text = f"Бренд: *{brand}*"
    if type_ru:
        text += f"\nТип: *{type_ru}*"
    text += "\n\nТеперь укажи модель или пропусти:"

    popular = []
    try:
        disabled = get_disabled_brand_recs(user_id)
    except Exception:
        disabled = set()
    popular = [(m, "auto") for m in [brand] if brand and brand not in disabled]

    keyboard = build_model_keyboard(user_id, brand, type_ru, popular_models=popular)
    if is_message:
        sent = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await msg.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    return MODEL_SELECT


async def on_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    query = update.callback_query
    await query.answer()
    if _is_stale(context, user_id, gen):
        return ConversationHandler.END
    action = query.data.split(":", 1)[1]
    if action == "skip":
        context.user_data["model"] = ""
        await query.edit_message_text("🔍 Ищу...")
        return await execute_search(update, context, query.message, gen=gen)
    if action == "back":
        brand = context.user_data.get("brand", "?")
        type_ru = context.user_data.get("type_ru", "")
        is_find = context.user_data.get("find_mode")
        price_prompt = (
            "Укажи цену в рублях (₽) или пропусти:" if is_find
            else "Укажи цену в корейских вонах (₩) или пропусти:"
        )
        summary = f"Бренд: *{brand}*"
        if type_ru:
            type_ko = context.user_data.get("type_ko", type_ru)
            summary += f"\nТип: *{type_ru}* → *{type_ko}*"
        await query.edit_message_text(
            f"{summary}\n\n{price_prompt}",
            parse_mode="Markdown",
            reply_markup=build_price_keyboard(find_mode=is_find),
        )
        return PRICE_SELECT
    if action == "custom":
        await query.edit_message_text(
            "✏️ Напиши название модели:\n\n"
            "Например: `Air Force 1`, `990v5`, `Speed Trainer`\n\n"
            "Или /back чтобы вернуться, /cancel чтобы отменить.",
            parse_mode="Markdown",
        )
        return MODEL_SELECT
    if action.startswith("select:"):
        model = action.split(":", 1)[1]
        context.user_data["model"] = model
        await query.edit_message_text("🔍 Ищу...")
        return await execute_search(update, context, query.message, gen=gen)
    if action.startswith("del:"):
        model = action.split(":", 1)[1]
        brand = context.user_data.get("brand", "")
        type_ru = context.user_data.get("type_ru", "")
        try:
            delete_model(user_id, brand, type_ru, model)
        except Exception:
            pass
        return await _show_model_menu(update, context, query.message)
    if action.startswith("hide_brand:"):
        model = action.split(":", 1)[1]
        try:
            disabled = get_disabled_brand_recs(user_id)
            disabled.add(model)
            from goofish_parser.storage.db import set_disabled_brand_recs
            set_disabled_brand_recs(user_id, disabled)
        except Exception:
            pass
        return await _show_model_menu(update, context, query.message)
    await query.edit_message_text("🔍 Ищу...")
    return await execute_search(update, context, query.message, gen=gen)


async def on_model_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    gen = context.user_data.get("_entry_gen")
    user_id = update.effective_user.id
    text = update.message.text.strip()
    if text.lower() in ("/back", "/b"):
        brand = context.user_data.get("brand", "?")
        type_ru = context.user_data.get("type_ru", "")
        is_find = context.user_data.get("find_mode")
        price_prompt = (
            "Укажи цену в рублях (₽) или пропусти:" if is_find
            else "Укажи цену в корейских вонах (₩) или пропусти:"
        )
        summary = f"Бренд: *{brand}*"
        if type_ru:
            type_ko = context.user_data.get("type_ko", type_ru)
            summary += f"\nТип: *{type_ru}* → *{type_ko}*"
        await update.message.reply_text(
            f"{summary}\n\n{price_prompt}",
            parse_mode="Markdown",
            reply_markup=build_price_keyboard(find_mode=is_find),
        )
        return PRICE_SELECT
    context.user_data["model"] = text
    msg = await update.message.reply_text("🔍 Ищу...")
    return await execute_search(update, context, msg, gen=gen)


def _source_tag(item) -> str:
    info = PLATFORM_INFO.get(item.source, {})
    c = info.get("country", item.country)
    n = info.get("name", item.source)
    return f"{c} {n}"


def _format_price(item) -> str:
    currency_symbols: dict[str, str] = {"₩": "₩", "¥": "¥", "SGD": "SGD$", "JPY": "¥"}
    sym = currency_symbols.get(item.currency, item.currency)
    if item.currency == "SGD":
        return f"SGD${item.price_cny:,.0f}"
    return f"{item.price_cny:,.0f}{sym}"


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
    model = context.user_data.get("model", "")
    price_min = context.user_data.get("price_min")
    price_max = context.user_data.get("price_max")

    search_brand = brand
    search_type = type_ru
    if model:
        search_type = f"{type_ru} {model}".strip()
    label = f"{brand} {search_type}"

    def cancelled():
        return gen is not None and _is_stale(context, user_id, gen)

    try:
        is_find = context.user_data.pop("find_mode", None)

        if cancelled():
            return ConversationHandler.END

        await msg.edit_text("🔍 Поиск по всем площадкам...")

        price_currency = context.user_data.get("price_currency", "KRW")
        platform_results = await search_all_platforms(
            brand=brand,
            item_type_ru=type_ru,
            user_id=user_id,
            model=model,
            price_min=price_min,
            price_max=price_max,
            price_currency=price_currency,
            limit_per_platform=50,
        )

        if cancelled():
            return ConversationHandler.END

        all_items = merge_platform_results(platform_results, sort_by="date")

        if not all_items:
            text = f"😕 Ничего не найдено по запросу *{label}*.\nПопробуйте изменить параметры или проверьте /settings."
            try:
                await msg.edit_text(text, parse_mode="Markdown")
            except AttributeError:
                await context.bot.send_message(chat_id=update.effective_chat.id, text=text, parse_mode="Markdown")
            return ConversationHandler.END

        platform_summary = " | ".join(
            f"{PLATFORM_INFO.get(p, {}).get('country', p)} {len(its)}шт"
            for p, its in platform_results.items() if its
        )

        try:
            increment_brand_freq(user_id, brand)
            if type_ru:
                increment_type_freq(user_id, type_ru)
            if model:
                save_model(user_id, brand, type_ru, model)
        except Exception:
            pass

        if is_find:
            save_items(all_items, label)
            key = f"find_conv_{update.effective_user.id}"
            context.user_data[key] = {
                "items": all_items,
                "total_pages": (len(all_items) + FIND_ITEMS_PER_PAGE - 1) // FIND_ITEMS_PER_PAGE,
                "query": label,
                "platform_summary": platform_summary,
            }
            await _show_find_page(update, context, msg, key, 0, gen=gen)
            return ConversationHandler.END

        save_search(brand, type_ru, price_min, price_max)
        save_items(all_items, label)

        market = calculate_market_price(all_items)
        scored = score_items(all_items, market)

        save_scored_items(scored)
        text = format_search_result(scored, brand, type_ru, platform_summary)
        chat_id = update.effective_chat.id

        if hasattr(msg, "edit_message_text"):
            await msg.edit_message_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        elif hasattr(msg, "edit_text"):
            await msg.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown", disable_web_page_preview=True)
        if cancelled():
            return ConversationHandler.END

        for s in scored[:5]:
            if cancelled():
                return ConversationHandler.END
            item = s.item
            rate = get_rate_to_rub(item.currency)
            source_name = _source_tag(item)
            if item.alt_sources:
                source_name += "+" + "+".join(item.alt_sources)
            time_str = f" 🕐{_format_time(item.created_at)}" if item.created_at else ""
            prod_link = f"[🔍 Товар]({item.url})" if item.url else ""
            if item.alt_urls:
                for alt_url in item.alt_urls:
                    prod_link += f" | [🔄]({alt_url})"
            price_str = _format_price(item)
            caption = (
                f"{source_name}\n"
                f"*{item.title}*\n"
                f"💰 {price_str} (~{round(item.price_cny * rate):.0f}₽){time_str}\n"
                f"{prod_link}"
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


def _parse_dt(iso_str: str) -> datetime | None:
    if not iso_str:
        return None
    try:
        return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    except Exception:
        return None


def _seller_url(seller_id: str, source: str = "") -> str:
    if not seller_id:
        return ""
    base_urls = {
        "fruitsfamily": "https://fruitsfamily.co/seller",
        "mercari": "https://www.mercari.com/u",
        "bunjang": "https://m.bunjang.co.kr/users",
        "carousell": "https://www.carousell.sg/u",
        "mercari_jp": "https://jp.mercari.com/user/profile",
    }
    base = base_urls.get(source, "")
    if base:
        return f"{base}/{seller_id}"
    return ""


def _deduplicate_by_seller(items: list) -> list:
    groups: dict[str, list] = {}
    for item in items:
        sid = item.seller_id or ""
        groups.setdefault(sid, []).append(item)

    for sid, group in groups.items():
        logger.debug("Dedup: seller=%s count=%d", sid or "?", len(group))
        for it in group:
            logger.debug("  item %s created_at=%s", it.item_id, it.created_at)

    result = []
    for sid, same_seller in groups.items():
        same_seller.sort(key=lambda x: _parse_dt(x.created_at) or datetime.min, reverse=True)
        best = same_seller[0]
        best_time = _parse_dt(best.created_at)
        count_1h = 0
        if best_time and sid:
            for other in same_seller:
                t = _parse_dt(other.created_at)
                if t and abs((best_time - t).total_seconds()) <= 3600:
                    count_1h += 1
        best.seller_extra_1h = max(0, count_1h - 1)
        logger.debug("Dedup: selected item %s, extra_1h=%d", best.item_id, best.seller_extra_1h)
        result.append(best)

    result.sort(key=lambda x: _parse_dt(x.created_at) or datetime.min, reverse=True)
    logger.debug("Dedup: %d items -> %d items", len(items), len(result))
    return result

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
        rate = get_rate_to_rub(item.currency)
        price_rub = round(item.price_cny * rate)
        discount = ""
        if item.price_original_cny and item.price_original_cny > item.price_cny:
            d = round((1 - item.price_cny / item.price_original_cny) * 100)
            discount = f" 📉 -{d}%"
        time_str = f" 🕐{_format_time(item.created_at)}" if item.created_at else ""
        brand_str = f"🏷 *{item.location}*\n" if item.location else ""
        prod_link = f"[🔍 Товар]({item.url})" if item.url else ""
        sel_url = _seller_url(item.seller_id, item.source)
        sel_ref = f" | [👤 Продавец]({sel_url})" if sel_url else ""
        extra_str = f" | +{item.seller_extra_1h} за 1ч" if item.seller_extra_1h else ""
        source_name = _source_tag(item)
        price_str = _format_price(item)

        logger.debug("Caption: prod_link=%s sel_url=%s extra=%d created_at=%s", item.url, sel_url, item.seller_extra_1h, item.created_at)
        caption = (
            f"{source_name}\n"
            f"*{item.title}*\n"
            f"{brand_str}"
            f"💰 {price_str} (~{price_rub:.0f}₽){discount}{time_str}\n"
            f"{prod_link}{sel_ref}{extra_str}"
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

    platform_summary = data.get("platform_summary", "")
    nav_text = f"🔍 *{query}* — стр. {page + 1}/{total}"
    if platform_summary:
        nav_text += f"\n📡 {platform_summary}"

    nav = await context.bot.send_message(
        chat_id=chat_id,
        text=nav_text,
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
        source = d.get("source", "fruitsfamily")
        info = PLATFORM_INFO.get(source, {})
        country = info.get("country", "")
        lines.append(
            f"{'🔥' if d['discount_pct'] > 30 else '✅'} *{i}.* {d['title']}\n"
            f"{country} | 💰 {d['price_krw']:,.0f} {d.get('currency', '₩')} (~{d['price_rub']:.0f} ₽) | Скидка {d['discount_pct']:.1f}%\n"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from goofish_parser.scraper.models import ALL_PLATFORMS, PLATFORM_INFO
    lines = ["📊 *Статус площадок*\n"]
    for p in ALL_PLATFORMS:
        info = PLATFORM_INFO.get(p, {})
        name = f"{info.get('country', '')} {info.get('name', p)}"
        lines.append(f"• {name} — ✅ активен")
    lines.append("\n💡 /settings — настроить площадки")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def rate_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    krw_rate = get_krw_to_rub()
    sgd_rate = get_rate_to_rub("SGD")
    jpy_rate = get_rate_to_rub("JPY")

    lines = [
        "💱 *Курсы валют к RUB*\n",
        f"🇰🇷 1 ₩ (KRW) = *{krw_rate:.4f} ₽*  |  1000 ₩ = *{krw_rate * 1000:.0f} ₽*",
        f"🇸🇬 1 SGD = *{sgd_rate:.2f} ₽*",
        f"🇯🇵 1 ¥ (JPY) = *{jpy_rate:.4f} ₽*  |  100 ¥ = *{jpy_rate * 100:.0f} ₽*",
        "",
        "Источник: ЦБ РФ (cbr.ru)",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def search_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            CommandHandler("search", search_start),
            CommandHandler("start", search_start),
            CommandHandler("find", find_start),
        ],
        states={
            BRAND_SELECT: [
                CallbackQueryHandler(on_brand_custom, pattern=r"^brand:custom$"),
                CallbackQueryHandler(on_brand, pattern=r"^brand:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_brand_text),
            ],
            BRAND_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_brand_text),
                CommandHandler("cancel", cancel),
                CommandHandler("back", on_brand_text),
            ],
            TYPE_SELECT: [
                CallbackQueryHandler(on_type, pattern=r"^type:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_type_text),
                CommandHandler("cancel", cancel),
            ],
            PRICE_SELECT: [CallbackQueryHandler(on_price, pattern=r"^price:")],
            PRICE_INPUT_MIN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_price_min),
                CommandHandler("cancel", cancel),
                CommandHandler("back", on_price_min),
            ],
            PRICE_INPUT_MAX: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_price_max),
                CommandHandler("skip", on_price_max),
                CommandHandler("cancel", cancel),
                CommandHandler("back", on_price_max),
            ],
            MODEL_SELECT: [
                CallbackQueryHandler(on_model, pattern=r"^model:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_model_text),
                CommandHandler("cancel", cancel),
                CommandHandler("back", on_model_text),
            ],
            FREETEXT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, on_freetext_text),
                CommandHandler("cancel", cancel),
                CommandHandler("back", on_freetext_text),
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
