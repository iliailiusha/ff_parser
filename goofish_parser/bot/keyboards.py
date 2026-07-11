from telegram import InlineKeyboardButton, InlineKeyboardMarkup

BRANDS = [
    "Nike", "Adidas", "New Balance", "Jordan", "Yeezy",
    "Supreme", "Stüssy", "Palace", "Fear of God", "Essentials",
    "Carhartt", "The North Face", "Patagonia", "Arc‘teryx", "Stone Island",
    "Off-White", "Balenciaga", "Gucci", "Louis Vuitton", "Dior",
    "Ralph Lauren", "Tommy Hilfiger", "Levi‘s", "Champion", "Vans",
    "Converse", "Timberland", "Dr. Martens", "Asics", "Salomon",
]

from goofish_parser.bot.translation import CLOTHING_RU_TO_KO
from goofish_parser.storage.db import get_top_brands, get_top_types, get_saved_models
import logging
logger = logging.getLogger(__name__)


def build_brand_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for b in BRANDS:
        row.append(InlineKeyboardButton(b, callback_data=f"brand:{b}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if user_id:
        top = []
        try:
            top = get_top_brands(user_id)
        except Exception as e:
            logger.error(f"get_top_brands error: {e}")
        if top:
            freq_row = []
            for b in top:
                freq_row.append(InlineKeyboardButton(f"★ {b}", callback_data=f"brand:{b}"))
                if len(freq_row) == 3:
                    buttons.append(freq_row)
                    freq_row = []
            if freq_row:
                buttons.append(freq_row)

    buttons.append([InlineKeyboardButton("✏️ Свой бренд", callback_data="brand:custom")])
    return InlineKeyboardMarkup(buttons)


def build_type_keyboard(user_id: int = 0) -> InlineKeyboardMarkup:
    types = list(CLOTHING_RU_TO_KO.keys())
    buttons = []
    row = []
    for t in types:
        row.append(InlineKeyboardButton(t, callback_data=f"type:{t}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if user_id:
        top = []
        try:
            top = get_top_types(user_id)
        except Exception as e:
            logger.error(f"get_top_types error: {e}")
        if top:
            freq_row = []
            for t in top:
                freq_row.append(InlineKeyboardButton(f"★ {t}", callback_data=f"type:{t}"))
                if len(freq_row) == 2:
                    buttons.append(freq_row)
                    freq_row = []
            if freq_row:
                buttons.append(freq_row)

    buttons.append([InlineKeyboardButton("← Назад", callback_data="type:back")])
    return InlineKeyboardMarkup(buttons)


def build_price_keyboard(find_mode: bool = False) -> InlineKeyboardMarkup:
    back_button = [InlineKeyboardButton("← Назад", callback_data="price:back")]
    if find_mode:
        buttons = [
            [InlineKeyboardButton("⏭ Без цены", callback_data="price:skip")],
            [
                InlineKeyboardButton("💰 В рублях (₽)", callback_data="price:rub"),
                InlineKeyboardButton("💰 В вонах (₩)", callback_data="price:krw"),
            ],
            back_button,
        ]
    else:
        buttons = [
            [InlineKeyboardButton("⏭ Без цены", callback_data="price:skip")],
            [InlineKeyboardButton("💰 Указать цену (₩)", callback_data="price:set")],
            back_button,
        ]
    return InlineKeyboardMarkup(buttons)


def build_model_keyboard(
    user_id: int,
    brand: str,
    item_type: str,
    popular_models: list[tuple[str, str]] = None,
) -> InlineKeyboardMarkup:
    buttons = []

    if popular_models:
        for model, source in popular_models:
            buttons.append([
                InlineKeyboardButton(f"🔥 {model}", callback_data=f"model:select:{model}"),
                InlineKeyboardButton("✕", callback_data=f"model:hide_brand:{model}"),
            ])

    saved = []
    try:
        saved = get_saved_models(user_id, brand, item_type)
    except Exception as e:
        logger.error(f"get_saved_models error: {e}")
    for m in saved:
        buttons.append([
            InlineKeyboardButton(f"📁 {m}", callback_data=f"model:select:{m}"),
            InlineKeyboardButton("✕", callback_data=f"model:del:{m}"),
        ])

    buttons.append([InlineKeyboardButton("✏️ Своя модель", callback_data="model:custom")])
    buttons.append([InlineKeyboardButton("→ Искать без модели", callback_data="model:skip")])
    buttons.append([InlineKeyboardButton("← Назад", callback_data="model:back")])
    return InlineKeyboardMarkup(buttons)
