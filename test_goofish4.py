"""Intercept the item.search.activate API to see raw item data."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

QUERY = "Nike 运动鞋"
CAPTURED = {}

def handle_response(response):
    url = response.url
    if "item.search.activate" in url and response.status == 200:
        try:
            body = response.body()
            CAPTURED["activate"] = {
                "url": url[:300],
                "body_len": len(body),
            }
            # Try to parse as JSON
            try:
                data = json.loads(body.decode("utf-8", errors="replace"))
                CAPTURED["activate"]["parsed"] = True
                CAPTURED["activate"]["keys"] = list(data.keys())
                if "data" in data:
                    data_keys = list(data["data"].keys())
                    CAPTURED["activate"]["data_keys"] = data_keys
                    if "cardList" in data["data"]:
                        cardList = data["data"]["cardList"]
                        CAPTURED["activate"]["card_count"] = len(cardList)
                        if cardList:
                            first = cardList[0]
                            CAPTURED["activate"]["first_card_keys"] = list(first.keys())
                            CAPTURED["activate"]["first_card"] = json.dumps(first, ensure_ascii=False)[:2000]
            except:
                CAPTURED["activate"]["body_sample"] = body.decode("utf-8", errors="replace")[:2000]
        except Exception as e:
            CAPTURED["activate_error"] = str(e)

def handle_request(request):
    url = request.url
    if "item.search.activate" in url:
        CAPTURED["activate_req"] = {
            "url": url[:400],
            "method": request.method,
            "headers": dict(request.headers),
            "post_data": request.post_data,
        }

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.on("response", handle_response)
    page.on("request", handle_request)

    from urllib.parse import quote, urlencode, parse_qs
    search_url = f"https://www.goofish.com/search?q={quote(QUERY)}"
    print(f"Navigating to: {search_url}")
    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(8000)

    print("\n=== CAPTURED DATA ===")
    print(json.dumps(CAPTURED, ensure_ascii=False, indent=2))
    browser.close()
