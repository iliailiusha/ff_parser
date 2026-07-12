"""Стресс-тест гибридного мониторинга Goofish.

Заполняет FiltersManager тестовыми запросами,
запускает start_realtime_monitoring() на 10 кругов,
собирает базовую статистику.
"""
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from goofish_parser.h5_scraper.filters_manager import FiltersManager
from goofish_parser.h5_scraper.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("stress_test")

TEST_FILTERS: list[dict] = [
    {"keyword": "iPhone 15", "min_price": 0, "max_price": 80000},
    {"keyword": "AirPods Pro 2", "min_price": 0, "max_price": 25000},
    {"keyword": "RTX 4060", "min_price": 0, "max_price": 50000},
    {"keyword": "Gucci bag", "min_price": 0, "max_price": 100000},
    {"keyword": "iPad Air", "min_price": 0, "max_price": 60000},
    {"keyword": "PS5", "min_price": 0, "max_price": 50000},
    {"keyword": "MacBook Pro", "min_price": 0, "max_price": 150000},
    {"keyword": "Samsung S24", "min_price": 0, "max_price": 70000},
]


def _prepare_filters() -> FiltersManager:
    fm = FiltersManager()
    fm._filters = []
    for i, f in enumerate(TEST_FILTERS):
        fm.add_filter(
            user_id=i + 1,
            keyword=f["keyword"],
            min_price=f["min_price"],
            max_price=f["max_price"],
        )
    logger.info(
        "Initialized %d test filters: %s",
        len(TEST_FILTERS),
        [f["keyword"] for f in TEST_FILTERS],
    )
    return fm


def _backup_and_clear_seen() -> None:
    seen_path = Path(__file__).parent / "goofish_parser" / "data" / "seen_items.json"
    if seen_path.exists():
        backup = seen_path.with_suffix(".json.bak")
        seen_path.rename(backup)
        logger.info("Backed up %s → %s", seen_path.name, backup.name)
    logger.info("Cleared seen_items.json — all items will be 'new'")


async def main() -> None:
    _backup_and_clear_seen()
    fm = _prepare_filters()

    orchestrator = Orchestrator(headless=True)

    logger.info("=" * 60)
    logger.info("STRESS TEST START")
    logger.info("=" * 60)
    logger.info("Filters: %d", len(TEST_FILTERS))
    logger.info("Max rounds: unlimited (Ctrl+C to stop)")
    logger.info("=" * 60)

    try:
        await orchestrator.start_realtime_monitoring()
    except KeyboardInterrupt:
        logger.info("Stress test interrupted by user")
    finally:
        await orchestrator.close()

    logger.info("=" * 60)
    logger.info("STRESS TEST FINISHED")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
