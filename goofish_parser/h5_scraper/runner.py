"""
Основной раннер H5-парсера Goofish (Xianyu).

Принимает список ID товаров или share-ссылок, асинхронно парсит
публичные H5-страницы без авторизации, сохраняет результаты.

Использование (из кода):
    import asyncio
    from goofish_parser.h5_scraper import run_h5_parser

    links = [
        "https://www.goofish.com/item?id=123456789",
        "https://m.tb.cn/h.xxxxx",
    ]
    items = asyncio.run(run_h5_parser(links))

Использование (из командной строки):
    python -m goofish_parser.h5_scraper.runner \\
        --links "https://m.tb.cn/h.xxxxx,https://goofish.com/item?id=123" \\
        --output csv
"""

import argparse
import asyncio
import logging
import re
import sys
from typing import Optional

from goofish_parser.config import H5_CONCURRENCY, H5_DELAY_MIN, H5_DELAY_MAX
from goofish_parser.h5_scraper.client import H5Client
from goofish_parser.h5_scraper.parser import H5ItemData, parse_h5_page
from goofish_parser.h5_scraper.storage import save_results

logger = logging.getLogger(__name__)


# ── хелперы для преобразования входных данных ──────────────

_SHARE_LINK_PATTERN = re.compile(
    r"https?://(?:www\.)?(?:m\.tb\.cn|goofish\.com|market\.m\.taobao\.com|xianyu\.)"
    r"\S*",
)


def normalize_input(raw: str) -> list[str]:
    """Преобразует строку со списком ID/ссылок в список URL.

    Поддерживаемые форматы:
      - item_id (число от 10 цифр) → https://www.goofish.com/item?id={id}
      - https://m.tb.cn/h.xxxxx     → как есть
      - https://www.goofish.com/... → как есть
    """
    parts = [p.strip() for p in raw.replace("\n", ",").split(",") if p.strip()]
    urls: list[str] = []
    for part in parts:
        if re.match(r"^\d{10,}$", part):
            urls.append(f"https://www.goofish.com/item?id={part}")
        elif _SHARE_LINK_PATTERN.match(part):
            urls.append(part)
        else:
            logger.warning("Unrecognized input skipped: %s", part)
    return urls


def _resolve_item_id(url: str) -> str:
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)
    m2 = re.search(r"/(\d{10,})", url)
    if m2:
        return m2.group(1)
    return ""


# ── основная логика ────────────────────────────────────────


async def run_h5_parser(
    links: list[str],
    *,
    output: Optional[str] = None,
    csv_path: Optional[str] = None,
    sqlite_path: Optional[str] = None,
    concurrency: Optional[int] = None,
) -> list[H5ItemData]:
    """Запускает H5-парсер для списка ссылок.

    Args:
        links: Список URL или ID товаров.
        output: "csv" | "sqlite" | "both" (по умолчанию из config).
        csv_path: Путь для CSV (по умолчанию из config).
        sqlite_path: Путь для SQLite (по умолчанию из config).
        concurrency: Максимум одновременных запросов.

    Returns:
        Список распарсенных H5ItemData.
    """
    semaphore = asyncio.Semaphore(concurrency or H5_CONCURRENCY)

    async def _fetch_one(client: H5Client, url: str) -> Optional[H5ItemData]:
        async with semaphore:
            html = await client.fetch(url)
            if html is None:
                logger.error("Failed to fetch %s", url)
                return None
            item = parse_h5_page(html, url=url)
            await H5Client.jitter(H5_DELAY_MIN, H5_DELAY_MAX)
            return item

    async with H5Client() as client:
        tasks = [_fetch_one(client, link) for link in links]
        results = await asyncio.gather(*tasks)

    items = [r for r in results if r is not None and r.price_cny > 0]

    logger.info(
        "Parsed %d/%d items successfully",
        len(items), len(links),
    )

    if items:
        await save_results(
            items,
            csv_path=csv_path,
            sqlite_path=sqlite_path,
            output=output,
        )

    return items


# ── CLI entry point ─────────────────────────────────────────


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="H5 Parser для Goofish (Xianyu) — без авторизации",
    )
    parser.add_argument(
        "--links",
        required=True,
        help=(
            "Ссылки или ID товаров через запятую. "
            "Пример: --links \"12345678901,https://m.tb.cn/h.xxxx\""
        ),
    )
    parser.add_argument(
        "--output",
        choices=["csv", "sqlite", "both"],
        default=None,
        help="Формат вывода (по умолчанию из config.py H5_OUTPUT)",
    )
    parser.add_argument(
        "--csv-path",
        default=None,
        help="Путь для CSV-файла",
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help="Путь для SQLite-файла",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="Количество одновременных запросов",
    )

    args = parser.parse_args()
    links = normalize_input(args.links)

    if not links:
        logger.error("No valid links or IDs provided.")
        sys.exit(1)

    logger.info("Starting H5 parser for %d link(s)", len(links))
    items = asyncio.run(
        run_h5_parser(
            links,
            output=args.output,
            csv_path=args.csv_path,
            sqlite_path=args.sqlite_path,
            concurrency=args.concurrency,
        ),
    )

    if not items:
        logger.warning("No items were parsed successfully.")
        sys.exit(1)

    logger.info("Done. Parsed %d item(s).", len(items))


if __name__ == "__main__":
    main()
