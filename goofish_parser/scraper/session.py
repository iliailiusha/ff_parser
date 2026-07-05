import asyncio
import json
import hashlib
import random
import time
from pathlib import Path
from typing import Optional

from curl_cffi import requests as curl_requests
from playwright.async_api import async_playwright

from goofish_parser.config import COOKIES_PATH, USER_AGENT, APP_KEY, PROXY_HOST, PROXY_USER, PROXY_PASS, SEARCH_JS

_cookies: dict[str, str] = {}
_token: str = ""
_session_id: str = ""


def generate_session_id() -> str:
    return str(random.randint(100000, 999999))


def get_proxy_url() -> Optional[str]:
    if PROXY_HOST and PROXY_USER and PROXY_PASS:
        return f"http://{PROXY_USER}:{PROXY_PASS}@{PROXY_HOST}"
    return None


def get_proxy_config() -> Optional[dict]:
    if PROXY_HOST and PROXY_USER and PROXY_PASS:
        return {
            "server": f"http://{PROXY_HOST}",
            "username": PROXY_USER,
            "password": PROXY_PASS,
        }
    return None


def _extract_token(cookies: dict[str, str]) -> str:
    h5_tk = cookies.get("_m_h5_tk", "")
    if "_" in h5_tk:
        return h5_tk.split("_")[0]
    return cookies.get("_m_h5_tk_token", "")


def _save_cookies() -> None:
    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = dict(_cookies)
    if _token:
        data["_m_h5_tk_token"] = _token
    COOKIES_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cookies() -> dict[str, str]:
    global _cookies, _token
    if COOKIES_PATH.exists():
        _cookies = json.loads(COOKIES_PATH.read_text(encoding="utf-8"))
        _token = _extract_token(_cookies)
    return _cookies


def get_cookies() -> dict[str, str]:
    if not _cookies:
        load_cookies()
    return _cookies


def get_token() -> str:
    if not _token:
        load_cookies()
    return _token


async def init_session() -> None:
    global _cookies, _token, _session_id

    _session_id = generate_session_id()
    proxy = get_proxy_config()

    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        proxy=proxy,
    )
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )

    page = await context.new_page()
    await page.goto(
        "https://www.goofish.com/",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    await page.wait_for_timeout(5000)

    cookies_list = await context.cookies()
    _cookies = {c["name"]: c["value"] for c in cookies_list}
    _token = _extract_token(_cookies)

    _save_cookies()

    await browser.close()
    await playwright.stop()


async def ensure_session() -> None:
    if not get_token():
        await init_session()


def _mtop_sign(token: str, timestamp: str, app_key: str, data: str) -> str:
    raw = f"{token}&{timestamp}&{app_key}&{data}"
    return hashlib.md5(raw.encode()).hexdigest()


async def search_page(query: str, limit: int = 30) -> dict:
    await ensure_session()

    token = get_token()
    cookies = get_cookies()

    if token:
        try:
            return await asyncio.to_thread(_search_via_mtop_sync, query, token, cookies, limit)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"MTOP search failed, falling back to Playwright: {e}")

    return await _search_via_playwright(query, cookies, limit)


def _search_via_mtop_sync(query: str, token: str, cookies: dict, limit: int) -> dict:
    t = str(int(time.time() * 1000))
    data_payload = json.dumps({
        "q": query,
        "bizFrom": "pcSearch",
        "searchReqFromPage": "xyPcSearch",
        "pageNo": 1,
        "pageSize": limit,
    })
    sign = _mtop_sign(token, t, APP_KEY, data_payload)

    url = (
        f"https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"
        f"?jsv=2.7.2&appKey={APP_KEY}&t={t}&sign={sign}&v=1.0&type=originaljson"
        f"&accountSite=xianyu&dataType=json"
        f"&api=mtop.taobao.idlemtopsearch.pc.search"
    )

    session = curl_requests.Session(impersonate="chrome124")
    for k, v in cookies.items():
        if k != "_m_h5_tk_token":
            session.cookies.set(k, v)

    resp = session.post(
        url,
        data={"data": data_payload},
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.goofish.com/",
            "Accept": "application/json",
        },
        timeout=20,
    )
    result = resp.json()
    ret = result.get("ret", [])
    ret_str = "; ".join(ret) if isinstance(ret, list) else str(ret)

    if any("FAIL" in r for r in (ret if isinstance(ret, list) else [ret])):
        return {"requiresAuth": True, "blocked": False, "empty": False, "items": [], "error": ret_str}

    items = _extract_mtop_items(result)
    return {"requiresAuth": False, "blocked": False, "empty": len(items) == 0, "items": items}


def _extract_mtop_items(result: dict) -> list[dict]:
    items = []
    data = result.get("data", {})
    if not data:
        return items

    card_list = data.get("cardList") or []
    for card in card_list:
        card_data = card.get("cardData", {})
        card_type = card.get("cardType", 0)

        if card_type == 1:
            item = {
                "title": card_data.get("title", ""),
                "url": f"https://www.goofish.com/item?id={card_data.get('itemId', '')}",
                "price": str(card_data.get("price", "0")),
                "attrs": [card_data.get("category", ""), card_data.get("condition", "")],
                "location": card_data.get("province", "") + card_data.get("city", ""),
                "badge": card_data.get("badge", ""),
            }
            if item["title"]:
                items.append(item)
                if len(items) >= 30:
                    break

    return items


async def _search_via_playwright(query: str, cookies: dict, limit: int) -> dict:
    proxy = get_proxy_config()
    playwright = await async_playwright().start()
    browser = await playwright.chromium.launch(
        headless=True,
        proxy=proxy,
    )
    context = await browser.new_context(
        user_agent=USER_AGENT,
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )

    await context.add_cookies([
        {"name": k, "value": v, "domain": ".goofish.com", "path": "/"}
        for k, v in cookies.items()
        if k != "_m_h5_tk_token"
    ])

    page = await context.new_page()
    from urllib.parse import quote
    url = f"https://www.goofish.com/search?q={quote(query)}"

    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)

    for _ in range(3):
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)
    await page.evaluate("window.scrollTo(0, 0)")

    result = await page.evaluate(SEARCH_JS, limit)

    await browser.close()
    await playwright.stop()

    return result
