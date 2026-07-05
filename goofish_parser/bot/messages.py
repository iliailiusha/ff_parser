from goofish_parser.scraper.models import ScoredItem


def format_scored_item(s: ScoredItem, rank: int) -> str:
    deal_emoji = "🔥" if s.discount_pct > 30 else "✅" if s.discount_pct > 15 else "👍"
    return (
        f"{deal_emoji} *{rank}.* {s.item.title}\n"
        f"💰 *{s.item.price_cny:.0f} ¥* (~{s.price_rub:.0f} ₽)\n"
        f"📊 Рынок: {s.market_avg_cny:.0f} ¥ (~{s.market_avg_rub:.0f} ₽)\n"
        f"📉 *Скидка {s.discount_pct:.1f}%*\n"
        f"📍 {s.item.location or '?'}\n"
        f"🔗 {s.item.url}\n"
    )


def format_search_result(scored: list[ScoredItem], brand: str, item_type: str) -> str:
    if not scored:
        return (
            f"😕 Ничего не найдено по запросу *{brand} {item_type}*\n\n"
            f"Возможные причины:\n"
            f"• Сайт Goofish запросил авторизацию\n"
            f"• Сработала защита от ботов\n"
            f"• Нет подходящих товаров\n\n"
            f"Попробуйте позже."
        )

    deals = [s for s in scored if s.is_deal]
    parts = [
        f"🔍 *{brand} {item_type}* — найдено {len(scored)} шт.\n",
    ]

    if deals:
        parts.append(f"🔥 *Выгодные ({len(deals)} шт.):*\n\n")
        for i, s in enumerate(deals[:10], 1):
            parts.append(format_scored_item(s, i))

    if len(scored) > 10:
        parts.append(f"\n...и ещё {len(scored) - 10} товаров\n")

    parts.append(f"\n💡 *Справка:* /help")
    return "\n".join(parts)


HELP_TEXT = """
🔍 *Goofish Parser Bot*

Поиск выгодных товаров на Goofish (闲鱼).

*Команды:*
`/search <бренд> <тип> [мин_цена] [макс_цена]`
Пример: `/search Nike кроссовки 500 2000`

`/rate` — текущий курс CNY/RUB (ЦБ РФ)

`/recent` — последние выгодные находки

`/help` — эта справка

*Параметры поиска:*
• Цены указываются в юанях (CNY ¥)
• Результаты сортируются по выгодности
• Выгодным считается товар с ценой ниже рыночной на 10%+
• Курс юаня обновляется ежедневно с сайта ЦБ РФ
"""
