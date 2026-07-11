from goofish_parser.scraper.models import ScoredItem, PLATFORM_INFO


def _source_tag(item) -> str:
    info = PLATFORM_INFO.get(item.source, {})
    c = info.get("country", "")
    n = info.get("name", item.source)
    return f"{c} {n}"


def format_scored_item(s: ScoredItem, rank: int) -> str:
    deal_emoji = "🔥" if s.discount_pct > 30 else "✅" if s.discount_pct > 15 else "👍"
    source = _source_tag(s.item)
    return (
        f"{deal_emoji} *{rank}.* {s.item.title}\n"
        f"{source} | 💰 *{s.item.price_cny:,.0f} {s.item.currency}* (~{s.price_rub:.0f} ₽)\n"
        f"📊 Рынок: {s.market_avg_cny:,.0f} {s.item.currency} (~{s.market_avg_rub:.0f} ₽)\n"
        f"📉 *Скидка {s.discount_pct:.1f}%*\n"
        f"🏷 {s.item.location or '?'}\n"
        f"🔗 {s.item.url}\n"
    )


def format_search_result(scored: list[ScoredItem], brand: str, item_type: str, platform_summary: str = "") -> str:
    if not scored:
        return (
            f"😕 Ничего не найдено по запросу *{brand} {item_type}*\n\n"
            f"Возможные причины:\n"
            f"• Нет подходящих товаров\n"
            f"• Измените параметры поиска\n\n"
            f"Попробуйте другой бренд или категорию."
        )

    deals = [s for s in scored if s.is_deal]
    parts = [
        f"🔍 *{brand} {item_type}* — найдено {len(scored)} шт.\n",
    ]

    if platform_summary:
        parts.append(f"📡 {platform_summary}\n")

    if deals:
        parts.append(f"🔥 *Выгодные ({len(deals)} шт.):*\n\n")
        for i, s in enumerate(deals[:10], 1):
            parts.append(format_scored_item(s, i))

    if len(scored) > 10:
        parts.append(f"\n...и ещё {len(scored) - 10} товаров\n")

    parts.append(f"\n💡 *Справка:* /help | ⚙️ /settings")
    return "\n".join(parts)


HELP_TEXT = """
🔍 *Multi-Platform Parser Bot*

Поиск выгодных товаров на азиатских площадках б/у:

🇰🇷 FruitsFamily (Корея)
🇰🇷 Bunjang (Корея)
🇸🇬 Carousell (Сингапур/ЮВА)
🇯🇵 Mercari JP (Япония)

*Команды:*
`/start` или `/search` — меню поиска (бренд → тип → цена)
`/find <текст>` — 🔍 быстрый поиск по тексту
`/settings` — ⚙️ включить/выключить площадки и страны
`/rate` — 💱 курс KRW/RUB
`/recent` — 🔥 последние находки
`/help` — 📖 справка
`/cancel` — ❌ отменить

*Как это работает:*
1. Поиск идёт по ВСЕМ включённым площадкам одновременно
2. Результаты объединяются, дубликаты удаляются
3. Для каждого товара указана площадка-источник
4. Цены конвертируются в рубли по курсу ЦБ РФ

*Выгодным* считается товар с ценой ниже рыночной на 10%+
"""
