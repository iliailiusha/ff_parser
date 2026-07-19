# Аудит Telegram-бота для парсинга азиатских маркетплейсов

> **Роль:** Senior Backend Developer, эксперт по информационной безопасности и системный архитектор high-load систем  
> **Стек:** Python 3.11, aiogram/telebot, requests/aiohttp/playwright, PostgreSQL (SQLite в dev)  
> **Площадки:** FruitsFamily, Bunjang, Carousell, Mercari JP, Goofish (闲鱼)

---

## 1. Оптимизация и нагрузка (20+ одновременных пользователей)

### Критические проблемы

| Проблема | Файл/Строка | Описание | Риск |
|----------|-------------|----------|------|
| **Блокирующий HTTP-клиент (httpx.AsyncClient — синглтон)** | `ff_scraper/client.py:9-17` | Глобальный `_http_client` используется всеми запросами. При нагрузке создается очередь на одном соединении. | Высокий — head-of-line blocking |
| **Отсутствие connection pooling / limits** | `ff_scraper/client.py:9-17` | Нет `httpx.Limits(max_connections=..., max_keepalive_connections=...)`. По умолчанию 100 соединений, но без keep-alive tuning. | Средний |
| **Playwright браузер — синглтон без пула** | `h5_scraper/search.py:20-22`, `orchestrator.py` | `_pw_client` и `_client` — глобальные переменные. При 20+ пользователях Playwright-страницы будут сериализованы через `asyncio.Lock`. | Критический — Playwright не thread-safe, потребляет 200-500 Мб RAM/экземпляр |
| **Отсутствие rate limiting per-user / per-IP** | `bot/bot.py`, `bot/handlers.py` | Нет throttling'а. Один пользователь может запустить N поисков параллельно. | Высокий — риск бана IP на маркетплейсах |
| **БД: SQLite + threading.local без WAL-оптимизаций** | `storage/db.py:13-19` | `PRAGMA journal_mode=WAL` есть, но нет `PRAGMA busy_timeout`, `synchronous=NORMAL`, `cache_size`. При 20+ параллельных записях — lock contention. | Средний |
| **Нет кэширования результатов поиска** | `services/multi_search.py` | Каждый запрос — холодный поиск по всем площадкам. Нет TTL-кэша для популярных брендов/типов. | Высокий — избыточная нагрузка на парсеры |
| **Отсутствие circuit breaker / retry с backoff** | `services/multi_search.py:180-190` | Только `asyncio.wait_for(timeout=90)`. Нет экспоненциального backoff, нет circuit breaker для упавших площадок. | Средний |

### Узкие места (Bottlenecks)

1. **Playwright (Goofish)** — самый тяжёлый компонент. Один экземпляр браузера ~300-500 Мб RAM. При 20 пользователях, ищущих одновременно, очередь на `_pw_client` будет огромной.
2. **GraphQL (FruitsFamily)** — синглтон `httpx.AsyncClient` без пула. Все запросы идут через одно соединение.
3. **Bunjang / Carousell / Mercari** — используют `aiohttp`/`requests` внутри своих клиентов (проверить `*_scraper/client.py`), скорее всего тоже без пулов.
4. **Синхронная запись в БД** — `sqlite3` в `storage/db.py` блокирует event loop при `conn.commit()` (нет `await`).

### Сводка компромиссов (Trade-offs)

| Оптимизация | Что теряем | Альтернативы |
|-------------|------------|--------------|
| **Переход на aiohttp + connection pooling** | Сложнее дебажить curl-логи | Оставить httpx, но добавить `Limits(max_connections=100, max_keepalive=20)` |
| **Playwright pool (несколько браузеров)** | +RAM (x3-5 браузеров = 1.5-2.5 Гб) | **Рекомендую:** Go/Node.js микросервис для Goofish (playwright в отдельном процессе, gRPC/HTTP API) |
| **Redis кэш поиска (TTL 5-15 мин)** | Устаревшие цены/наличие | Инвалидация по `created_at` товара; warmup популярных брендов кроном |
| **Rate limiting (token bucket per user)** | Пользователь ждёт | Sliding window log + burst allowance; бан за спам |
| **PostgreSQL + asyncpg** | Миграция, инфраструктура | **Must have** для продакшена 20+ пользователей. SQLite не выдержит concurrent writes. |
| **Вынос парсеров в отдельные воркеры (Celery/RQ/arq)** | Сложность деплоя | **Best practice:** API Gateway (FastAPI) + Worker Pool. Бот только принимает запросы, кладёт в очередь, отдаёт job_id. |

### Примерные требования к железу (для 20 одновременных heavy-парсингов)

| Компонент | CPU | RAM | Примечание |
|-----------|-----|-----|------------|
| Telegram Bot (aiogram) | 1 vCPU | 256 Мб | Статeless, горизонтально масштабируется |
| Parser Workers (x4-6) | 4-6 vCPU | 4-8 Гб | Playwright x3 + API parsers |
| Redis (cache/queue) | 1 vCPU | 1-2 Гб | Кэш + Celery broker |
| PostgreSQL | 2 vCPU | 2-4 Гб | Connection pool (PgBouncer) |
| **Итого (min)** | **8 vCPU** | **8-16 Гб** | Рекомендую 16 Гб RAM для запаса |

---

## 2. Архитектура «Умного поиска» и обработка ошибок

### Требование из ТЗ
```
Шаг A: Точный поиск → 0 результатов →
Шаг B: Fuzzy matching (опечатки) → 0 результатов →
Шаг C: Синонимы / семантический поиск + подсчёт по синонимам
```

### Реальность в коде

| Шаг | Реализация | Статус |
|-----|------------|--------|
| **A — Точный поиск** | `search_all_platforms()` → `search_by_brand_type()` | ✅ Есть |
| **B — Fuzzy / опечатки** | `ff_scraper/search.py:72-102` — `SIMILAR_WORDS` (hardcoded dict) | ⚠️ **Частично** — только для FruitsFamily, только жёсткий словарь, нет Levenshtein |
| **C — Синонимы / семантика** | `multi_search.py:38-113` — `CLOTHING_RU_TO_KO`, `CLOTHING_EN`, `translate_model()` | ⚠️ **Частично** — только статичные словари, нет эмбеддингов |

### Проблемы текущей реализации

1. **Fuzzy matching только для FruitsFamily** (`ff_scraper/search.py:_find_similar`). Bunjang, Carousell, Mercari, Goofish — не имеют fallback'а.
2. **Словарь `SIMILAR_WORDS` — хардкод** (строки 72-86). Не масштабируется, не учитывает частотность, нет ранжирования.
3. **Нет цепочки A→B→C** в `multi_search.py`. Функция `search_all_platforms` просто параллельно опрашивает площадки. Fallback-логика размазана по скрейперам.
4. **`translate_model()`** (стр. 104-113) — только exact match по словарю, нет fuzzy.

### Архитектурное решение: Unified Smart Search Pipeline

```python
# goofish_parser/services/smart_search.py (НОВЫЙ ФАЙЛ)

from dataclasses import dataclass
from typing import Protocol
from rapidfuzz import fuzz, process
# from sentence_transformers import SentenceTransformer  # опционально для семантики

@dataclass
class SearchStepResult:
    items: list[GoofishItem]
    strategy: str  # "exact" | "fuzzy" | "synonym" | "semantic"
    corrected_query: str | None = None
    synonyms_used: list[str] | None = None

class SearchStrategy(Protocol):
    async def search(self, query: str, platforms: list[str], **kwargs) -> SearchStepResult: ...

class ExactSearch:
    async def search(self, query: str, platforms: list[str], **kw) -> SearchStepResult:
        results = await search_all_platforms_free_text(query, platforms=platforms, **kw)
        items = merge_platform_results(results)
        return SearchStepResult(items=items, strategy="exact")

class FuzzySearch:
    def __init__(self, known_terms: list[str], threshold: int = 80):
        self.known_terms = known_terms
        self.threshold = threshold

    async def search(self, query: str, platforms: list[str], **kw) -> SearchStepResult:
        # RapidFuzz: находим ближайшие известные термины
        matches = process.extract(query, self.known_terms, scorer=fuzz.WRatio, limit=3)
        corrected = [m[0] for m in matches if m[1] >= self.threshold]
        if not corrected:
            return SearchStepResult(items=[], strategy="fuzzy")
        
        all_items = []
        for cq in corrected:
            results = await search_all_platforms_free_text(cq, platforms=platforms, **kw)
            items = merge_platform_results(results)
            all_items.extend(items)
        
        # дедуп по item_id
        seen = set()
        uniq = [i for i in all_items if not (i.item_id in seen or seen.add(i.item_id))]
        return SearchStepResult(items=uniq, strategy="fuzzy", corrected_query=corrected[0])

class SynonymSearch:
    def __init__(self, synonym_map: dict[str, list[str]]):
        self.synonym_map = synonym_map  # {"кроссовки": ["кеды", "сникерсы", ...]}

    async def search(self, query: str, platforms: list[str], **kw) -> SearchStepResult:
        # извлекаем типы одежды из запроса
        types = extract_clothing_types(query)  # используем существующий _find_clothing_keywords
        synonyms = []
        for t in types:
            synonyms.extend(self.synonym_map.get(t, []))
        
        if not synonyms:
            return SearchStepResult(items=[], strategy="synonym")
        
        all_items = []
        for syn in synonyms:
            new_query = query.replace(t, syn, 1)
            results = await search_all_platforms_free_text(new_query, platforms=platforms, **kw)
            items = merge_platform_results(results)
            all_items.extend(items)
        
        # подсчёт по синонимам
        counts = {syn: len([i for i in all_items if syn in i.title.lower()]) for syn in synonyms}
        seen = set()
        uniq = [i for i in all_items if not (i.item_id in seen or seen.add(i.item_id))]
        return SearchStepResult(items=uniq, strategy="synonym", synonyms_used=list(counts.keys()))

class SmartSearchPipeline:
    def __init__(self, strategies: list[SearchStrategy]):
        self.strategies = strategies

    async def execute(self, query: str, platforms: list[str], **kw) -> list[SearchStepResult]:
        results = []
        for strategy in self.strategies:
            res = await strategy.search(query, platforms, **kw)
            results.append(res)
            if res.items:
                break  # нашли — останавливаемся
        return results
```

### Интеграция в `multi_search.py`

```python
# В search_all_platforms_free_text заменяем прямой вызов на:
pipeline = SmartSearchPipeline([
    ExactSearch(),
    FuzzySearch(known_terms=ALL_KNOWN_BRANDS_TYPES, threshold=80),
    SynonymSearch(synonym_map=EXPANDED_SIMILAR_WORDS),  # расширить SIMILAR_WORDS
])
step_results = await pipeline.execute(query, enabled_platforms, ...)
# Берём первый непустой, логируем цепочку для аналитики
```

### Библиотеки для внедрения
- **RapidFuzz** — быстрый Levenshtein/Jaro-Winkler (C-расширение, в 10x быстрее `difflib`/`fuzzywuzzy`)
- **NLTK / spaCy** — токенизация, лемматизация (если нужен NLP)
- **sentence-transformers** (опционально) — семантический поиск через эмбеддинги (требует GPU/CPU inference, можно вынести в отдельный сервис)

---

## 3. Безопасность и «дыры» в коде

### Критические уязвимости

| Уязвимость | Файл/Строка | Описание | Эксплойт |
|------------|-------------|----------|----------|
| **Hardcoded/коммиченные секреты** | `config.py:11-18` | Токены, ключи API, курсы валют в `.env` (но `.env` может уйти в git). Нет проверки на `git-secrets`. | Утечка бота, прокси, API ключей |
| **SQL Injection (теоретически)** | `storage/db.py:103-108`, `116-126` | Используются параметризованные запросы (`?`) — **OK**. Но `f-string` в `save_items` (стр. 120) для `search_query` — если приходит от пользователя без санитизации. | Низкий риск (параметризация есть), но `search_query` не экранируется в логике |
| **Отсутствие валидации входных данных** | `bot/handlers.py:145-166`, `296-360` | `brand`, `model`, `price_min/max` — принимаются как есть. Нет лимита длины, нет санитизации Markdown/HTML. | XSS в Markdown (Telegram парсит), DoS через огромные строки, инъекции в SQL (если параметризация сломается) |
| **API ключи / токены в памяти без защиты** | `h5_scraper/cookie_manager.py`, `h5_scraper/browser_auth.py` | Куки Goofish (сессионные токены) хранятся в JSON файле в plaintext. Нет шифрования at-rest. | Компрометация аккаунта Goofish при утечке файла |
| **Rate limiting — отсутствует** | `bot/bot.py`, `bot/handlers.py` | Один пользователь может спамить `/find` или кнопками. Нет per-user bucket. | Бот упадет от 429 от Telegram API или забанят IP на маркетплейсах |
| **SSRF / Injection в прокси** | `config.py:38-40` | `H5_PROXIES` из env парсится как есть. Если злоумышленник контролирует env — может указать `http://internal-service:80`. | Низкий (env на сервере), но плохая практика |
| **Playwright — запуск браузера с пользовательскими данными** | `h5_scraper/browser_auth.py` | Браузер авторизуется под реальным аккаунтом. Нет изоляции профилей. | Утечка сессии, если контейнер скомпрометирован |

### Рекомендации по безопасности (Best Practices)

1. **Secrets Management**
   - Использовать **HashiCorp Vault / AWS Secrets Manager / Doppler** или хотя бы `sops` + age для шифровки `.env`.
   - Добавить `.env` в `.gitignore` (проверить!).
   - Ротация токенов бота и прокси раз в 30 дней.

2. **Input Validation**
   ```python
   # bot/validators.py
   from pydantic import BaseModel, field_validator
   
   class SearchInput(BaseModel):
       brand: str
       item_type: str = ""
       model: str = ""
       price_min: float | None = None
       price_max: float | None = None
       
       @field_validator("brand", "item_type", "model")
       @classmethod
       def sanitize(cls, v: str) -> str:
           v = v.strip()[:100]  # max length
           # Убираем Markdown спецсимволы
           return v.replace("*", "").replace("_", "").replace("`", "").replace("[", "")
       
       @field_validator("price_min", "price_max")
       @classmethod
       def validate_price(cls, v: float | None) -> float | None:
           if v is not None and (v < 0 or v > 10_000_000):
               raise ValueError("Price out of range")
           return v
   ```

3. **Rate Limiting (Token Bucket per User)**
   ```python
   # bot/middleware/rate_limit.py
   from collections import defaultdict
   import time
   
   class TokenBucket:
       def __init__(self, rate: float, burst: int):
           self.rate = rate      # tokens/sec
           self.burst = burst    # max tokens
           self.buckets: dict[int, tuple[float, float]] = defaultdict(lambda: (burst, time.time()))
       
       async def take(self, user_id: int, tokens: int = 1) -> bool:
           now = time.time()
           available, last = self.buckets[user_id]
           available = min(self.burst, available + (now - last) * self.rate)
           if available >= tokens:
               self.buckets[user_id] = (available - tokens, now)
               return True
           return False
   
   # В handlers.py: в начале каждого хендлера
   if not await rate_limiter.take(user_id):
       await update.message.reply_text("⏳ Слишком много запросов. Подождите...")
       return
   ```

4. **Encryption at Rest для куки**
   ```python
   # h5_scraper/cookie_manager.py
   from cryptography.fernet import Fernet
   
   KEY = Fernet.generate_key()  # хранить в env/secrets
   f = Fernet(KEY)
   
   def save(self, cookies: dict) -> None:
       encrypted = f.encrypt(json.dumps(cookies).encode())
       self.path.write_bytes(encrypted)
   
   def load(self) -> dict:
       if not self.path.exists():
           return {}
       return json.loads(f.decrypt(self.path.read_bytes()))
   ```

5. **Circuit Breaker для парсеров**
   ```python
   # services/circuit_breaker.py
   import asyncio
   from dataclasses import dataclass, field
   from time import time
   
   @dataclass
   class CircuitBreaker:
       failure_threshold: int = 5
       recovery_timeout: float = 60.0
       failures: int = 0
       last_failure: float = 0
       state: str = "closed"  # closed, open, half-open
       
       async def call(self, func, *args, **kwargs):
           if self.state == "open":
               if time() - self.last_failure > self.recovery_timeout:
                   self.state = "half-open"
               else:
                   raise CircuitOpenError()
           
           try:
               result = await func(*args, **kwargs)
               self.on_success()
               return result
           except Exception as e:
               self.on_failure()
               raise
       
       def on_success(self):
           self.failures = 0
           self.state = "closed"
       
       def on_failure(self):
           self.failures += 1
           self.last_failure = time()
           if self.failures >= self.failure_threshold:
               self.state = "open"
   ```

---

## 4. Кроссплатформенность и отказоустойчивость парсеров

### Матрица поддержки площадок

| Площадка | Клиент | Парсинг | Auth | Fallback при ошибке | Catch-all |
|----------|--------|---------|------|---------------------|-----------|
| **FruitsFamily** | GraphQL (httpx) | API | Не нужна | ❌ Нет | ❌ Только `try/except` → `[]` |
| **Bunjang** | aiohttp (предположительно) | API | Не нужна | ❌ Нет | ❌ |
| **Carousell** | aiohttp | API | Не нужна | ❌ Нет | ❌ |
| **Mercari JP** | aiohttp/curl_cffi | API | Не нужна | ❌ Нет | ❌ |
| **Goofish** | MTOP (curl_cffi) + Playwright | API + Browser | Cookies (browser auth) | ✅ Safe Path (Playwright) | ⚠️ Частично |

### Проблемы отказоустойчивости

1. **Нет единого интерфейса ошибок** — каждый скрейпер возвращает `SearchResult(blocked=False, requires_auth=False, error="")`, но код в `multi_search.py` игнорирует эти флаги, просто логирует и возвращает `[]`.
2. **403 / Captcha / DOM change** — обрабатываются только в Goofish (RGV587 → Playwright). Для остальных площадок — молчавый возврат пустого списка.
3. **Catch-all отсутствует** — если падает один парсер, `asyncio.gather(..., return_exceptions=True)` ловит исключение, но пользователь не узнает, какая площадка упала.
4. **Нет retry с ротацией прокси/UA** — только у Goofish есть `H5_PROXIES` и `MOBILE_USER_AGENTS`. Остальные платформы используют статичные заголовки.
5. **Нет health-check эндпоинтов для парсеров** — только `/health` для бота (стр. 21-28 `bot.py`).

### Архитектурное решение: Unified Parser Resilience Layer

```python
# goofish_parser/services/resilience.py (НОВЫЙ ФАЙЛ)

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Awaitable, TypeVar
import asyncio
import logging

logger = logging.getLogger(__name__)

class PlatformErrorType(Enum):
    RATE_LIMITED = "rate_limited"      # 429, 403
    CAPTCHA = "captcha"                # challenge
    AUTH_REQUIRED = "auth_required"    # 401, expired cookies
    PARSING_FAILED = "parsing_failed"  # DOM/API changed
    NETWORK_ERROR = "network_error"    # timeout, dns, connection
    UNKNOWN = "unknown"

@dataclass
class ParserResult:
    items: list[GoofishItem]
    error: PlatformErrorType | None = None
    error_msg: str = ""
    platform: str = ""
    fallback_used: bool = False

T = TypeVar("T")

class ResilientParser:
    def __init__(
        self,
        platform: str,
        primary: Callable[..., Awaitable[ParserResult]],
        fallbacks: list[Callable[..., Awaitable[ParserResult]]] | None = None,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ):
        self.platform = platform
        self.primary = primary
        self.fallbacks = fallbacks or []
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.circuit_breaker = CircuitBreaker()  # из п.3

    async def search(self, *args, **kwargs) -> ParserResult:
        # 1. Проверка circuit breaker
        if self.circuit_breaker.state == "open":
            logger.warning(f"[{self.platform}] Circuit OPEN, skipping")
            return ParserResult(items=[], error=PlatformErrorType.UNKNOWN, 
                                error_msg="Circuit breaker open", platform=self.platform)

        # 2. Primary с ретраями
        for attempt in range(self.max_retries):
            try:
                result = await asyncio.wait_for(
                    self.primary(*args, **kwargs),
                    timeout=90.0
                )
                if result.error in (PlatformErrorType.RATE_LIMITED, PlatformErrorType.CAPTCHA):
                    # Пробуем фоллбэки
                    break
                if not result.error:
                    self.circuit_breaker.on_success()
                    return result
            except asyncio.TimeoutError:
                logger.warning(f"[{self.platform}] Timeout attempt {attempt+1}")
            except Exception as e:
                logger.error(f"[{self.platform}] Error attempt {attempt+1}: {e}")
            
            await asyncio.sleep(self.base_delay * (2 ** attempt))  # exponential backoff

        # 3. Fallbacks
        for i, fallback in enumerate(self.fallbacks):
            try:
                logger.info(f"[{self.platform}] Trying fallback #{i+1}")
                result = await asyncio.wait_for(fallback(*args, **kwargs), timeout=120.0)
                if not result.error:
                    result.fallback_used = True
                    self.circuit_breaker.on_success()
                    return result
            except Exception as e:
                logger.error(f"[{self.platform}] Fallback #{i+1} failed: {e}")

        # 4. Все упало
        self.circuit_breaker.on_failure()
        return ParserResult(
            items=[],
            error=PlatformErrorType.UNKNOWN,
            error_msg="All strategies exhausted",
            platform=self.platform
        )
```

### Интеграция в `multi_search.py`

```python
# В search_all_platforms() заменяем _search_one на:

async def _search_one(platform: str) -> ParserResult:
    parser = PARSER_REGISTRY[platform]  # ResilientParser instances
    return await parser.search(brand, item_type_ru, user_id, model, ...)

# Регистрация парсеров с фоллбэками:
PARSER_REGISTRY = {
    "fruitsfamily": ResilientParser(
        "fruitsfamily",
        primary=ff_search.search_by_brand_type,
        fallbacks=[
            lambda *a, **kw: ff_search.search_products_free_text(*a, **kw),  # альтернативный запрос
        ]
    ),
    "goofish": ResilientParser(
        "goofish",
        primary=goofish_search.search_by_brand_type,  # уже имеет Fast/Safe Path внутри
        fallbacks=[]
    ),
    "bunjang": ResilientParser(
        "bunjang",
        primary=bunjang_search.search_by_brand_type,
        fallbacks=[
            # Можно добавить поиск через веб-скрапинг если API упадет
        ]
    ),
    # ...
}
```

### Обработка ошибок для пользователя

```python
# В handlers.py execute_search():
platform_results = await search_all_platforms(...)

# Собираем ошибки по платформам
failed_platforms = [
    (p, r.error.value, r.error_msg) 
    for p, r in platform_results.items() 
    if r.error
]

if failed_platforms:
    warn_text = "⚠️ Некоторые площадки недоступны:\n" + "\n".join(
        f"  • {PLATFORM_INFO[p]['name']}: {err_type} ({msg[:50]})"
        for p, err_type, msg in failed_platforms
    )
    await msg.edit_text(warn_text + "\n\nПоказываю результаты с остальных...")
    # Логируем в Sentry/monitoring
```

### Рекомендации по парсерам

| Площадка | Что добавить |
|----------|--------------|
| **FruitsFamily** | Ротировка User-Agent, ретраи с backoff, fallback на web-scraping (Playwright) если GraphQL заблокирован |
| **Bunjang** | Прокси поддержка, обработка 403/капчи, кэширование категорий |
| **Carousell** | API v2 миграция, поддержка стран (SG/MY/PH/TW/HK), rate limit handling |
| **Mercari JP** | Официальное API (есть), парсинг веб (Playwright fallback), обработка `item_condition_id` изменений |
| **Goofish** | Уже есть Safe Path. Добавить: пул браузеров, автоматическая ротация аккаунтов/кук, метрики успеха/фоллбэков |

---

## Итоговый чек-лист исправлений (Priority Order)

### 🔴 Critical (Блокеры для продакшена 20+ пользователей)
- [ ] **Миграция на PostgreSQL + asyncpg** (SQLite не выдержит concurrent writes)
- [ ] **Rate limiting per-user** (Token Bucket / Sliding Window)
- [ ] **Playwright Pool** (минимум 3 браузера) или вынос Goofish в отдельный микросервис на Go/Node.js
- [ ] **Connection pooling** для всех HTTP клиентов (httpx.Limits, aiohttp.TCPConnector)
- [ ] **Secrets Management** (Vault/sops, ротация токенов)
- [ ] **Input Validation** (Pydantic модели для всех входящих данных от пользователя)

### 🟡 High (Надёжность и качество поиска)
- [ ] **Unified Smart Search Pipeline** (A→B→C цепочка с RapidFuzz + синонимами)
- [ ] **ResilientParser + Circuit Breaker** для каждой площадки
- [ ] **Redis кэш** результатов поиска (TTL 5-15 мин) + warmup популярных запросов
- [ ] **Encryption at Rest** для кук Goofish (cryptography.Fernet)
- [ ] **Structured Logging + Metrics** (Prometheus: latency, error_rate, fallback_rate per platform)

### 🟢 Medium (Архитектурные улучшения)
- [ ] **Worker Pool** (arq/Celery) — бот только принимает запросы, воркеры парсят
- [ ] **API Gateway** (FastAPI) — единый вход для парсеров, health checks, rate limiting
- [ ] **Semantic Search** (sentence-transformers) — опционально, для этапа C
- [ ] **Proxy Pool Manager** — ротация резидентных прокси для всех площадок
- [ ] **Integration Tests** — моки парсеров, проверка fallback цепочек

### 📋 Метрики для мониторинга (добавить в Prometheus/Grafana)
```
parser_requests_total{platform, status="success|error|fallback"}
parser_latency_seconds{platform, quantile="0.5|0.9|0.99"}
parser_fallback_rate{platform}
bot_active_users
bot_search_queue_length
cache_hit_rate
circuit_breaker_state{platform}
```

---

## Приложение: Структура нового модуля `services/`

```
goofish_parser/services/
├── __init__.py
├── multi_search.py          # Текущий — оставить для совместимости
├── smart_search.py          # НОВЫЙ: Pipeline A→B→C
├── resilience.py            # НОВЫЙ: ResilientParser, CircuitBreaker
├── rate_limit.py            # НОВЫЙ: TokenBucket, SlidingWindow
├── cache.py                 # НОВЫЙ: Redis cache с TTL/invalidation
├── circuit_breaker.py       # НОВЫЙ: из п.3
└── validators.py            # НОВЫЙ: Pydantic модели входа
```

---

**Готовность к продакшену (текущая):** ~40%  
**После внедрения Critical + High:** ~85%  
**Рекомендуемый таймлайн:** 2-3 недели на Critical, 1-2 месяца на полный High+Medium