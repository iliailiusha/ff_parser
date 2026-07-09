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


def build_brand_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for b in BRANDS:
        row.append(InlineKeyboardButton(b, callback_data=f"brand:{b}"))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton("✏️ Свой бренд", callback_data="brand:custom")])
    return InlineKeyboardMarkup(buttons)


def build_type_keyboard() -> InlineKeyboardMarkup:
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
    return InlineKeyboardMarkup(buttons)


def build_price_keyboard(find_mode: bool = False) -> InlineKeyboardMarkup:
    if find_mode:
        buttons = [
            [InlineKeyboardButton("⏭ Без цены", callback_data="price:skip")],
            [
                InlineKeyboardButton("💰 В рублях (₽)", callback_data="price:rub"),
                InlineKeyboardButton("💰 В вонах (₩)", callback_data="price:krw"),
            ],
        ]
    else:
        buttons = [
            [InlineKeyboardButton("⏭ Без цены", callback_data="price:skip")],
            [InlineKeyboardButton("💰 Указать цену (₩)", callback_data="price:set")],
        ]
    return InlineKeyboardMarkup(buttons)
