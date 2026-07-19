import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol, List, Optional

from rapidfuzz import fuzz, process

from goofish_parser.scraper.models import GoofishItem, PLATFORM_INFO
from goofish_parser.storage.db import get_enabled_platforms
from goofish_parser.bot.translation import CLOTHING_RU_TO_KO

logger = logging.getLogger(__name__)


SIMILAR_WORDS_EXPANDED = {
    "кроссовки": ["кеды", "ботинки", "сникерсы", "кедсы", "спортивная обувь", "раннинг"],
    "кеды": ["кроссовки", "сланцы", "кедсы", "спортивная обувь"],
    "ботинки": ["кроссовки", "сапоги", "ботильоны", "ботинки мужские", "ботинки женские"],
    "сапоги": ["ботинки", "чулки", "угги", "дюти"],
    "футболка": ["майка", "лонгслив", "поло", "ти-шёрт", "t-shirt", "top"],
    "майка": ["футболка", "топ", "слитный", "без рукавов"],
    "лонгслив": ["футболка", "свитер", "рубашка", "длинный рукав"],
    "рубашка": ["блузка", "шелк", "оксфорд", "фланель", "хавайская"],
    "свитер": ["свитшот", "толстовка", "худи", "джемпер", "пуловер", "кардиган"],
    "свитшот": ["свитер", "толстовка", "худи", "мужская одежда", "женская одежда"],
    "толстовка": ["свитер", "свитшот", "худи", "спортивная"],
    "худи": ["свитер", "свитшот", "толстовка", "болоний", "спортивная"],
    "куртка": ["пуховик", "ветровка", "бомбер", "косуха", "джинсовка", "пальто", "парка"],
    "пуховик": ["куртка", "пальто", "ветровка", "зимняя одежда"],
    "пальто": ["куртка", "пуховик", "тренч", "плащ"],
    "ветровка": ["куртка", "бомбер", "проветриватель"],
    "бомбер": ["куртка", "ветровка", "переходка"],
    "косуха": ["куртка", "кожаная куртка", "байкерка", "ледер"],
    "джинсовка": ["куртка", "джинсовая куртка", "трукер"],
    "джинсы": ["штаны", "брюки", "карго", "джоггеры", "трясины", "деним"],
    "штаны": ["джинсы", "брюки", "карго", "джоггеры", "трясины", "котон"],
    "брюки": ["штаны", "джинсы", "слаксы", "классика", "офисные"],
    "шорты": ["бермуды", "спортивные шорты", "плавки", "короткие штаны"],
    "платье": ["юбка", "сарафан", "макси", "мини", "миди", "блузка"],
    "юбка": ["платье", "мини", "миди", "макси", "плиссированная"],
    "костюм": ["пиджак", "блейзер", "комплект", "деловой"],
    "пиджак": ["блейзер", "костюм", "джакет", "спорт-пиджак"],
    "жилетка": ["жилет", "пуховик без рукавов", "даун-жилет"],
    "карго": ["штаны", "джинсы", "брюки", "рабочие штаны", "тактические"],
    "джоггеры": ["штаны", "треники", "спортивные штаны", "трясины"],
    "треники": ["джоггеры", "штаны", "спортивные брюки", "свитшот"],
    "лепгинсы": ["колготки", "тяги", "спортлеггинсы", "йога"],
    "шапка": ["кепка", "бейсболка", "панама", "бини", "ушанка"],
    "кепка": ["шапка", "бейсболка", "панама", "кепка бейсболка"],
    "панама": ["шапка", "кепка", "бакет", "летняя шапка"],
    "рюкзак": ["сумка", "бакпак", "рюкзак городской", "рюкзак турystyczный"],
    "сумка": ["рюкзак", "кроссбоди", "шоппер", "клатч", "баг"],
    "ремень": ["пояс", "ремень кожаный", "ремень тканевый"],
    "носки": ["носочки", "готы", "спортивные носки"],
    "шарф": ["снуд", "платок", "палантин"],
    "перчатки": ["варежки", "митенки", "перчатки кожаные"],
    "часы": ["умные часы", "наручные часы", "смарт-часы"],
    "очки": ["солнцезащитные очки", "оправы", "-Ray-Ban", "авиаторы"],
    "браслет": ["ремня", "бисер", "кожа", "металл"],
    "кольцо": ["перстень", "обручальное", "пятиграмое"],
    "серьги": ["стuds", "кольца", "виссящие", "заколки"],
    "балетки": ["мокасины", "лофферы", "топсайдеры", "спортивная обувь"],
    "мокасины": ["балетки", "лофферы", "водительские"],
    "лофферы": ["мокасины", "балетки", "спортивная обувь"],
    "челси": ["ботинки", "сапоги", "анкл-бутсы"],
    "анкл-бутсы": ["челси", "ботинки", "сапоги", "бутсы"],
    "сланцы": ["кеды", "шлепки", "слайды", "кроссовки"],
    "слайды": ["сланцы", "шлепки", "кеды"],
    "кепка бейсболка": ["кепка", "бейсболка", "шапка"],
    "флиска": ["свитер", "худи", "полар", "флисовая куртка"],
}


@dataclass
class SearchStepResult:
    items: List[GoofishItem]
    strategy: str
    corrected_query: Optional[str] = None
    synonyms_used: Optional[List[str]] = None
    platform_counts: Optional[dict] = None


class SearchStrategy(Protocol):
    async def search(self, query: str, platforms: List[str], **kwargs) -> SearchStepResult: ...


def extract_clothing_keywords(query: str) -> List[str]:
    text_lower = query.lower()
    found = []
    for ru_word in CLOTHING_RU_TO_KO:
        if ru_word in text_lower:
            found.append(ru_word)
    return found


class ExactSearch:
    async def search(self, query: str, platforms: List[str], **kwargs) -> SearchStepResult:
        from goofish_parser.services.multi_search import search_all_platforms_free_text, merge_platform_results
        
        results = await search_all_platforms_free_text(query, platforms=platforms, **kwargs)
        items = merge_platform_results(results)
        counts = {p: len(i) for p, i in results.items() if i}
        return SearchStepResult(items=items, strategy="exact", platform_counts=counts)


class FuzzySearch:
    def __init__(self, known_terms: List[str], threshold: int = 80):
        self.known_terms = known_terms
        self.threshold = threshold

    async def search(self, query: str, platforms: List[str], **kwargs) -> SearchStepResult:
        matches = process.extract(query, self.known_terms, scorer=fuzz.WRatio, limit=5)
        corrected = [m[0] for m in matches if m[1] >= self.threshold]

        if not corrected:
            return SearchStepResult(items=[], strategy="fuzzy")

        from goofish_parser.services.multi_search import search_all_platforms_free_text, merge_platform_results
        
        all_items = []
        all_counts = {}
        for cq in corrected[:3]:
            results = await search_all_platforms_free_text(cq, platforms=platforms, **kwargs)
            items = merge_platform_results(results)
            all_items.extend(items)
            for p, cnt in ((p, len(i)) for p, i in results.items() if i):
                all_counts[p] = all_counts.get(p, 0) + cnt

        seen = set()
        uniq = [i for i in all_items if not (i.item_id in seen or seen.add(i.item_id))]
        return SearchStepResult(
            items=uniq,
            strategy="fuzzy",
            corrected_query=corrected[0],
            platform_counts=all_counts,
        )


class SynonymSearch:
    def __init__(self, synonym_map: dict[str, List[str]]):
        self.synonym_map = synonym_map

    async def search(self, query: str, platforms: List[str], **kwargs) -> SearchStepResult:
        clothing_types = extract_clothing_keywords(query)
        if not clothing_types:
            return SearchStepResult(items=[], strategy="synonym")

        from goofish_parser.services.multi_search import search_all_platforms_free_text, merge_platform_results
        
        all_synonyms = []
        for ct in clothing_types:
            all_synonyms.extend(self.synonym_map.get(ct, []))

        if not all_synonyms:
            return SearchStepResult(items=[], strategy="synonym")

        all_items = []
        all_counts = {}
        synonyms_used = []

        for syn in all_synonyms:
            for ct in clothing_types:
                new_query = query.replace(ct, syn, 1)
                if new_query != query:
                    results = await search_all_platforms_free_text(new_query, platforms=platforms, **kwargs)
                    items = merge_platform_results(results)
                    if items:
                        synonyms_used.append(syn)
                        all_items.extend(items)
                        for p, cnt in ((p, len(i)) for p, i in results.items() if i):
                            all_counts[p] = all_counts.get(p, 0) + cnt
                    break

        seen = set()
        uniq = [i for i in all_items if not (i.item_id in seen or seen.add(i.item_id))]
        return SearchStepResult(
            items=uniq,
            strategy="synonym",
            synonyms_used=synonyms_used,
            platform_counts=all_counts,
        )


class SmartSearchPipeline:
    def __init__(self, strategies: List[SearchStrategy]):
        self.strategies = strategies

    async def execute(self, query: str, platforms: List[str], **kwargs) -> List[SearchStepResult]:
        results = []
        for strategy in self.strategies:
            res = await strategy.search(query, platforms, **kwargs)
            results.append(res)
            if res.items:
                logger.info(f"SmartSearch: found {len(res.items)} items via {res.strategy}")
                break
            else:
                logger.info(f"SmartSearch: {res.strategy} returned 0, trying next")
        return results

    async def execute_first_success(self, query: str, platforms: List[str], **kwargs) -> SearchStepResult:
        for strategy in self.strategies:
            res = await strategy.search(query, platforms, **kwargs)
            if res.items:
                return res
        return SearchStepResult(items=[], strategy="none")


def build_default_pipeline(known_terms: Optional[List[str]] = None) -> SmartSearchPipeline:
    if known_terms is None:
        known_terms = list(CLOTHING_RU_TO_KO.keys()) + list(SIMILAR_WORDS_EXPANDED.keys())
        known_terms.extend([v for vals in SIMILAR_WORDS_EXPANDED.values() for v in vals])

    return SmartSearchPipeline([
        ExactSearch(),
        FuzzySearch(known_terms=known_terms, threshold=80),
        SynonymSearch(synonym_map=SIMILAR_WORDS_EXPANDED),
    ])


_smart_search: Optional[SmartSearchPipeline] = None


def get_smart_search() -> SmartSearchPipeline:
    global _smart_search
    if _smart_search is None:
        _smart_search = build_default_pipeline()
    return _smart_search