"""Orchestrator — параллельный парсинг Goofish с гибридным обходом блокировок.

Fast Path: curl_cffi (MtopClient) — высокоскоростные запросы.
Safe Path: Playwright evaluate (MtopPlaywrightClient) — fallback при RGV587.

Режимы работы:
  - run() — разовый парсинг списка itemId.
  - start_realtime_monitoring() — бесконечный онлайн-мониторинг
    по кастомным фильтрам пользователей.
"""
import asyncio
import csv
import logging
import random
import time as time_module
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from goofish_parser.config import DATA_DIR, H5_CONCURRENCY
from goofish_parser.h5_scraper.browser_auth import BrowserAuthenticator
from goofish_parser.h5_scraper.cookie_manager import CookieManager
from goofish_parser.h5_scraper.filters_manager import FiltersManager
from goofish_parser.h5_scraper.item_tracker import ItemTracker
from goofish_parser.h5_scraper.mtop_client import MtopClient
from goofish_parser.h5_scraper.mtop_playwright_client import MtopPlaywrightClient

logger = logging.getLogger(__name__)

CSV_PATH = DATA_DIR / "goofish_results.csv"
CSV_FIELDS = [
    "item_id",
    "title",
    "price",
    "url",
    "timestamp",
]

SAFE_PATH_RESTART_THRESHOLD = 100


class Orchestrator:
    """Оркестратор: параллельные корутины + гибридный обход блокировок.

    Flow (run):
      1. Загружает куки из CookieManager.
      2. Создаёт MtopClient (Fast Path) без refresh_callback.
      3. Запускает N воркеров (asyncio.gather).
      4. Воркер: Fast Path → при RGV587 → Lock → Safe Path (Playwright).
      5. После Safe Path: синхронизация кук, ретрай Fast Path.
      6. Если Safe Path тоже блокируют → BrowserAuthenticator.

    Flow (start_realtime_monitoring):
      1. Загружает куки, создаёт MtopClient, FiltersManager, ItemTracker.
      2. Бесконечный цикл: по фильтру → Fast Path → Safe Path → Tracker → dispatch.
      3. Между фильтрами рваная пауза 3.5–5.5с.
      4. В конце полного круга — лог времени и здоровья сессии.
      5. Memory guard: перезапуск Playwright браузера после 100 Safe Path вызовов.
    """

    def __init__(
        self,
        headless: bool = True,
        concurrency: Optional[int] = None,
        csv_path: Optional[Path] = None,
    ) -> None:
        self._headless = headless
        self._concurrency = concurrency or H5_CONCURRENCY
        self._csv_path = csv_path or CSV_PATH

        self._cookie_manager = CookieManager()
        self._session_lock = asyncio.Lock()
        self._client: Optional[MtopClient] = None
        self._playwright_client: Optional[MtopPlaywrightClient] = None
        self._safe_path_call_count = 0

    # ── публичный запуск (разовый парсинг) ─────────────────

    async def run(self, item_ids: list[str]) -> list[dict]:
        """Запускает парсинг списка ID товаров."""
        cookies = self._cookie_manager.load()
        if not self._cookie_manager.is_valid(cookies):
            logger.info("Session invalid, running BrowserAuthenticator...")
            cookies = await self._run_browser_auth()
            self._cookie_manager.save(cookies)
        else:
            logger.info("Session loaded from cache (%d cookies)", len(cookies))

        self._client = MtopClient(cookies=cookies)

        sem = asyncio.Semaphore(self._concurrency)

        async def worker(item_id: str) -> Optional[dict]:
            async with sem:
                return await self._fetch_item(item_id)

        tasks = [worker(iid) for iid in item_ids]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        parsed = []
        for r in results:
            if isinstance(r, dict) and r.get("item_id"):
                parsed.append(r)
            elif isinstance(r, Exception):
                logger.error("Worker error: %s", r)

        if parsed:
            await self._save_csv(parsed)

        return parsed

    # ── онлайн-мониторинг ──────────────────────────────────

    async def start_realtime_monitoring(self) -> None:
        """Бесконечный цикл онлайн-мониторинга по кастомным фильтрам."""
        # Инициализация сессии
        cookies = self._cookie_manager.load()
        if not self._cookie_manager.is_valid(cookies):
            logger.info("Session invalid, running BrowserAuthenticator...")
            cookies = await self._run_browser_auth()
            self._cookie_manager.save(cookies)

        self._client = MtopClient(cookies=cookies)

        filters_manager = FiltersManager()
        item_tracker = ItemTracker()

        logger.info("[MONITOR] Starting real-time monitoring loop")

        round_num = 0
        consecutive_errors = 0

        while True:
            round_num += 1
            round_start = time_module.monotonic()
            filters = filters_manager.get_all_active_filters()

            if not filters:
                logger.info("[MONITOR] No active filters, waiting 30s...")
                await asyncio.sleep(30)
                continue

            for target in filters:
                keyword = target.get("keyword", "?")
                try:
                    ok = await self._process_filter(target, item_tracker)
                    consecutive_errors = 0 if ok else (consecutive_errors + 1)
                except Exception as exc:
                    consecutive_errors += 1
                    logger.error(
                        "[MONITOR] Error processing filter %s: %s",
                        keyword,
                        exc,
                    )

                # Guard-rail: exponential backoff при серийных ошибках
                if consecutive_errors > 5:
                    backoff = random.uniform(30, 60)
                    logger.critical(
                        "[CRITICAL] Обнаружен жесткий бан сети. "
                        "Замедление темпа на %.0fс...",
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    consecutive_errors = max(consecutive_errors - 1, 5)

                # Рваная пауза между фильтрами (антифрод)
                await asyncio.sleep(random.uniform(3.5, 5.5))

            # Полный круг завершён
            elapsed = time_module.monotonic() - round_start
            cookie_count = len(self._client._cookies) if self._client else 0
            cookies_valid = (
                self._cookie_manager.is_valid(self._cookie_manager.load())
                if self._cookie_manager
                else False
            )
            cookie_status = "Валидны" if cookies_valid else "Требуется обновление"
            logger.info(
                "[MONITOR] Круг #%d завершен за %.2f сек. "
                "Активных фильтров: %d. Сплю перед следующим кругом.",
                round_num,
                elapsed,
                len(filters),
            )
            logger.info(
                "[MONITOR] Статус кук: %s (%d шт). Seen items: %d. "
                "Safe Path вызовы: %d/%d.",
                cookie_status,
                cookie_count,
                item_tracker.count(),
                self._safe_path_call_count,
                SAFE_PATH_RESTART_THRESHOLD,
            )

    async def _process_filter(
        self,
        target: dict[str, Any],
        tracker: ItemTracker,
    ) -> bool:
        """Обрабатывает один фильтр: Fast Path → Safe Path → Tracker.

        Возвращает True при успешном получении ответа (даже если 0 айтемов),
        False при полной ошибке запроса.
        """
        keyword = target.get("keyword", "")
        price_min = target.get("min_price", 0.0)
        price_max = target.get("max_price", 1_000_000.0)
        user_id = target.get("user_id", 0)

        payload: dict[str, Any] = {
            "keyword": keyword,
            "pageNumber": 1,
            "pageSize": 20,
            "sort": "realtime",
            "searchFrom": "h5",
            "priceMin": int(price_min * 100),
            "priceMax": int(price_max * 100),
        }

        # Fast Path
        start_ts = time_module.monotonic()
        assert self._client is not None
        result = await self._client.request(
            "mtop.taobao.idlemtopsearch.search",
            data=payload,
            version="1.0",
        )
        elapsed = time_module.monotonic() - start_ts
        used_safe_path = False

        ret = result.get("ret", [])
        ret_str = str(ret)

        if "RGV587_ERROR" in ret_str or "挤爆" in ret_str:
            logger.info(
                "[SAFE PATH] RGV587 on filter '%s', switching to Safe Path",
                keyword,
            )
            start_ts = time_module.monotonic()
            result = await self._safe_path_request(
                "mtop.taobao.idlemtopsearch.search",
                payload,
            )
            if not result:
                return False
            elapsed = time_module.monotonic() - start_ts
            used_safe_path = True

        # Валидация структуры ответа
        data = result.get("data")
        if data is None or not isinstance(data, dict):
            logger.error(
                "[DEBUG] Нетипичная структура ответа API для фильтра '%s'. "
                "Весь ответ: %s",
                keyword,
                result,
            )
            return False

        items = data.get("items") or data.get("itemList") or []
        if not isinstance(items, list):
            return False

        path_label = "SAFE PATH" if used_safe_path else "FAST PATH"
        logger.info(
            "[%s] Ответ за %.2f сек для фильтра '%s'",
            path_label,
            elapsed,
            keyword,
        )

        logger.info(
            "[TRACKER] Filter '%s': found %d items",
            keyword,
            len(items),
        )

        new_items = tracker.filter_new_items(items)
        for item in new_items:
            await self.dispatch_notification(user_id, item)

        return True

    async def dispatch_notification(self, user_id: int, item: dict[str, Any]) -> None:
        """Заглушка отправки уведомления пользователю.

        В будущем: вызов Telegram/Slack/Webhook.
        """
        item_id = item.get("itemId") or item.get("item_id") or "?"
        title = (item.get("title") or "")[:60]
        logger.debug(
            "[NOTIFY] user=%d item=%s title=%s",
            user_id,
            item_id,
            title,
        )

    # ── воркер (для run) ────────────────────────────────────

    async def _fetch_item(self, item_id: str) -> Optional[dict]:
        """Fast Path → Safe Path при RGV587."""
        assert self._client is not None

        for attempt in range(1, 4):
            try:
                result = await self._client.get_item_detail(item_id)
                ret = result.get("ret", [])
                ret_str = str(ret)

                if "SUCCESS" in ret_str:
                    return self._parse_detail(result, item_id)

                if "RGV587_ERROR" in ret_str or "挤爆" in ret_str:
                    logger.info(
                        "[SAFE PATH] RGV587 on %s attempt %d/3", item_id, attempt
                    )

                    pw_result = await self._safe_path_request(
                        "mtop.taobao.idle.pc.detail",
                        {"itemId": item_id},
                    )
                    if pw_result:
                        return pw_result

                    if attempt < 3:
                        await self._refresh_session()
                        continue
                    return None

                logger.warning("API error for %s: %s", item_id, ret)
                return None

            except Exception as exc:
                logger.error("Fetch error for %s: %s", item_id, exc)
                if attempt < 3:
                    await asyncio.sleep(2**attempt)
                    continue
                return None

        return None

    # ── парсинг ответов ─────────────────────────────────────

    @staticmethod
    def _parse_detail(result: dict[str, Any], item_id: str) -> dict:
        data = result.get("data", {})
        item_do = data.get("itemDO", data)
        title = item_do.get("title", "") or item_do.get("itemTitle", "") or ""
        price = item_do.get("soldPrice", item_do.get("price", "0"))
        try:
            price_f = float(price)
        except (ValueError, TypeError):
            price_f = 0.0

        return {
            "item_id": item_id,
            "title": title,
            "price": price_f,
            "url": f"https://www.goofish.com/item?id={item_id}",
            "timestamp": datetime.now().isoformat(),
        }

    # ── Safe Path ───────────────────────────────────────────

    async def _safe_path_request(
        self,
        api: str,
        data: dict[str, Any],
        version: str = "1.0",
    ) -> Optional[dict]:
        """Generic Safe Path: выполняет MTOP-запрос через Playwright evaluate.

        Захватывает Lock, лениво инициализирует MtopPlaywrightClient.
        При успехе синхронизирует куки обратно в MtopClient и CookieManager.
        При превышении лимита вызовов — перезапускает браузер.
        """
        async with self._session_lock:
            try:
                if self._playwright_client is None:
                    self._playwright_client = MtopPlaywrightClient(
                        headless=self._headless,
                    )

                result = await self._playwright_client.request(
                    api,
                    data=data,
                    version=version,
                )

                self._safe_path_call_count += 1

                # Memory guard: перезапуск браузера каждые N вызовов
                if self._safe_path_call_count >= SAFE_PATH_RESTART_THRESHOLD:
                    logger.info(
                        "[SAFE PATH] Call count %d, restarting browser...",
                        self._safe_path_call_count,
                    )
                    await self._playwright_client.stop()
                    self._playwright_client = MtopPlaywrightClient(
                        headless=self._headless,
                    )
                    self._safe_path_call_count = 0

                ret = result.get("ret", [])
                if "SUCCESS" in str(ret):
                    cookies = await self._playwright_client.get_cookies()
                    if cookies:
                        self._cookie_manager.save(cookies)
                        if self._client:
                            self._client.update_cookies(cookies)
                    return result

                logger.warning(
                    "[SAFE PATH] API %s returned non-SUCCESS: %s", api, ret
                )
                return None

            except Exception as exc:
                logger.error("[SAFE PATH] Error on %s: %s", api, exc)
                return None

    # ── обновление сессии ──────────────────────────────────

    async def _refresh_session(self) -> None:
        """Захватывает Lock, обновляет куки через BrowserAuthenticator."""
        async with self._session_lock:
            logger.info("[SESSION] BrowserAuthenticator refresh...")
            cookies = await self._run_browser_auth()
            self._cookie_manager.save(cookies)

            if self._client:
                self._client.update_cookies(cookies)

            logger.info(
                "[SESSION] Refresh complete (%d cookies)", len(cookies)
            )

    async def _run_browser_auth(self) -> dict[str, str]:
        auth = BrowserAuthenticator(headless=self._headless)
        return await auth.get_cookies()

    # ── CSV ────────────────────────────────────────────────

    async def _save_csv(self, items: list[dict]) -> None:
        file_exists = self._csv_path.exists()
        try:
            with self._csv_path.open("a", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
                if not file_exists:
                    writer.writeheader()
                for row in items:
                    writer.writerow(row)
            logger.info(
                "[CSV] %d items appended to %s", len(items), self._csv_path
            )
        except OSError as exc:
            logger.error("CSV write error: %s", exc)

    # ── close ──────────────────────────────────────────────

    async def close(self) -> None:
        if self._client:
            await self._client.close()
        if self._playwright_client:
            await self._playwright_client.stop()

    async def __aenter__(self) -> "Orchestrator":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# ── CLI entry point ────────────────────────────────────────

async def main() -> None:
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    mode = sys.argv[1] if len(sys.argv) > 1 else "once"
    item_ids = sys.argv[2:] if len(sys.argv) > 2 else ["708353622311"]

    async with Orchestrator(headless=False) as orch:
        if mode == "monitor":
            logger.info("Starting real-time monitoring mode...")
            await orch.start_realtime_monitoring()
        else:
            logger.info("Starting one-shot parse with %d item(s)", len(item_ids))
            results = await orch.run(item_ids)
            logger.info("Done. Parsed %d/%d items.", len(results), len(item_ids))
            for r in results:
                print(
                    f"  {r['item_id']}: {r['title'][:50] if r['title'] else '?'}"
                    f" — {r['price']}"
                )


if __name__ == "__main__":
    asyncio.run(main())
