import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, ConversationHandler, CommandHandler

from goofish_parser.scraper.models import PLATFORM_INFO, COUNTRY_PLATFORMS, ALL_PLATFORMS
from goofish_parser.storage.db import (
    get_disabled_platforms,
    set_disabled_platforms,
    get_disabled_countries,
    set_disabled_countries,
)

logger = logging.getLogger(__name__)

MAIN_MENU, PLATFORM_TOGGLE, COUNTRY_TOGGLE = range(3)


def _build_main_menu(user_id: int) -> InlineKeyboardMarkup:
    disabled_platforms = get_disabled_platforms(user_id)
    disabled_countries = get_disabled_countries(user_id)

    # Count platforms disabled either directly or via country
    effectively_disabled = set(disabled_platforms)
    for country, plats in COUNTRY_PLATFORMS.items():
        if country in disabled_countries:
            effectively_disabled.update(plats)

    active = len(ALL_PLATFORMS) - len(effectively_disabled)
    all_active = active == len(ALL_PLATFORMS)
    all_disabled = active == 0
    status = "✅ ВСЕ ВКЛ" if all_active else "❌ ВСЕ ВЫКЛ" if all_disabled else f"⚡ {active}/{len(ALL_PLATFORMS)}"

    buttons = [
        [InlineKeyboardButton(f"🌐 Площадки ({status})", callback_data="settings:platforms")],
        [InlineKeyboardButton(f"🌍 По странам", callback_data="settings:countries")],
        [InlineKeyboardButton("❌ Закрыть", callback_data="settings:close")],
    ]
    return InlineKeyboardMarkup(buttons)


def _build_platform_menu(user_id: int) -> InlineKeyboardMarkup:
    disabled = get_disabled_platforms(user_id)
    disabled_countries = get_disabled_countries(user_id)
    buttons = []
    for p in ALL_PLATFORMS:
        info = PLATFORM_INFO.get(p, {})
        name = f"{info.get('country', '')} {info.get('name', p)}"
        # Check if platform is effectively disabled (directly or via country)
        platform_country = None
        for country, plats in COUNTRY_PLATFORMS.items():
            if p in plats:
                platform_country = country
                break
        via_country = platform_country and platform_country in disabled_countries
        if via_country or p in disabled:
            icon = "⬜"
        else:
            icon = "✅"
        label = f"{icon} {name}"
        if via_country:
            label += " 🌍"
        buttons.append([InlineKeyboardButton(label, callback_data=f"platform:toggle:{p}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)


def _build_country_menu(user_id: int) -> InlineKeyboardMarkup:
    disabled_countries = get_disabled_countries(user_id)
    buttons = []
    for country_name in sorted(COUNTRY_PLATFORMS.keys()):
        platforms = COUNTRY_PLATFORMS[country_name]
        country_disabled = country_name in disabled_countries
        icon = "⬜" if country_disabled else "✅"
        platform_names = ", ".join(PLATFORM_INFO[p]["name"] for p in platforms if p in PLATFORM_INFO)
        buttons.append([InlineKeyboardButton(f"{icon} {country_name} ({platform_names})", callback_data=f"country:toggle:{country_name}")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="settings:back")])
    return InlineKeyboardMarkup(buttons)


async def settings_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = (
        "⚙️ *Настройки парсинга*\n\n"
        "Выбери какие площадки должны участвовать в поиске.\n"
        "Можно отключить отдельные площадки или целые страны."
    )
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=_build_main_menu(user_id))
    return MAIN_MENU


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data == "settings:platforms":
        await query.edit_message_text(
            "🌐 *Площадки*\n\n✅ — включена\n⬜ — отключена\n\nНажми чтобы переключить:",
            parse_mode="Markdown",
            reply_markup=_build_platform_menu(user_id),
        )
        return PLATFORM_TOGGLE

    if data == "settings:countries":
        await query.edit_message_text(
            "🌍 *Страны*\n\n✅ — включены\n⬜ — отключены\n\nОтключение страны отключает все её площадки:",
            parse_mode="Markdown",
            reply_markup=_build_country_menu(user_id),
        )
        return COUNTRY_TOGGLE

    if data == "settings:back":
        await query.edit_message_text(
            "⚙️ *Настройки парсинга*\n\nВыбери какие площадки должны участвовать в поиске.",
            parse_mode="Markdown",
            reply_markup=_build_main_menu(user_id),
        )
        return MAIN_MENU

    if data == "settings:close":
        await query.message.delete()
        return ConversationHandler.END

    return MAIN_MENU


async def platform_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data.startswith("platform:toggle:"):
        platform = data.split(":", 2)[2]
        disabled = get_disabled_platforms(user_id)
        if platform in disabled:
            disabled.discard(platform)
        else:
            disabled.add(platform)
        set_disabled_platforms(user_id, disabled)

        await query.edit_message_text(
            "🌐 *Площадки*\n\n✅ — включена\n⬜ — отключена\n\nНажми чтобы переключить:",
            parse_mode="Markdown",
            reply_markup=_build_platform_menu(user_id),
        )
        return PLATFORM_TOGGLE

    if data == "settings:back":
        user_id = update.effective_user.id
        await query.edit_message_text(
            "⚙️ *Настройки парсинга*\n\nВыбери какие площадки должны участвовать в поиске.",
            parse_mode="Markdown",
            reply_markup=_build_main_menu(user_id),
        )
        return MAIN_MENU

    if data == "settings:close":
        await query.message.delete()
        return ConversationHandler.END

    return PLATFORM_TOGGLE


async def country_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    data = query.data

    if data.startswith("country:toggle:"):
        country = data.split(":", 2)[2]
        disabled_countries = get_disabled_countries(user_id)
        disabled_platforms = get_disabled_platforms(user_id)
        platforms_in_country = COUNTRY_PLATFORMS.get(country, [])

        if country in disabled_countries:
            # Enable the country: remove from disabled_countries
            # and also clear individual platform disabled flags
            disabled_countries.discard(country)
            for p in platforms_in_country:
                disabled_platforms.discard(p)
        else:
            disabled_countries.add(country)
            # Optionally also disable individual platforms as a visual cue
            for p in platforms_in_country:
                disabled_platforms.add(p)

        set_disabled_countries(user_id, disabled_countries)
        set_disabled_platforms(user_id, disabled_platforms)

        await query.edit_message_text(
            "🌍 *Страны*\n\n✅ — включены\n⬜ — отключены",
            parse_mode="Markdown",
            reply_markup=_build_country_menu(user_id),
        )
        return COUNTRY_TOGGLE

    if data == "settings:back":
        user_id = update.effective_user.id
        await query.edit_message_text(
            "⚙️ *Настройки парсинга*\n\nВыбери какие площадки должны участвовать в поиске.",
            parse_mode="Markdown",
            reply_markup=_build_main_menu(user_id),
        )
        return MAIN_MENU

    if data == "settings:close":
        await query.message.delete()
        return ConversationHandler.END

    return COUNTRY_TOGGLE


async def settings_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Настройки закрыты.")
    return ConversationHandler.END


def settings_conversation() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("settings", settings_start)],
        states={
            MAIN_MENU: [CallbackQueryHandler(settings_callback, pattern=r"^settings:")],
            PLATFORM_TOGGLE: [
                CallbackQueryHandler(platform_toggle, pattern=r"^platform:"),
                CallbackQueryHandler(platform_toggle, pattern=r"^settings:"),
            ],
            COUNTRY_TOGGLE: [
                CallbackQueryHandler(country_toggle, pattern=r"^country:"),
                CallbackQueryHandler(country_toggle, pattern=r"^settings:"),
            ],
        },
        fallbacks=[CommandHandler("cancel", settings_cancel)],
        allow_reentry=True,
    )
