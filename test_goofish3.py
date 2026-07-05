"""Intercept the MTOP search API response."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

QUERY = "Nike 运动鞋"
API_RESPONSES = []

def handle_response(response):
    url = response.url
    if "gaia.idle.data.gw.v2.index.get" in url or "search" in url.lower():
        body = response.text() if response.status == 200 else None
        API_RESPONSES.append({
            "url": url[:300],
            "status": response.status,
        })
        if response.status == 200 and body:
            try:
                data = json.loads(body)
                API_RESPONSES[-1]["has_data"] = "data" in data
                API_RESPONSES[-1]["keys"] = list(data.keys())[:10]
                if "data" in data and isinstance(data["data"], dict):
                    API_RESPONSES[-1]["data_keys"] = list(data["data"].keys())[:10]
            except:
                API_RESPONSES[-1]["parse_error"] = body[:200]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page.on("response", handle_response)

    from urllib.parse import quote
    url = f"https://www.goofish.com/search?q={quote(QUERY)}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(10000)

    print(f"\nAPI responses captured: {len(API_RESPONSES)}")
    for r in API_RESPONSES:
        print(json.dumps(r, ensure_ascii=False, indent=2))

    browser.close()
