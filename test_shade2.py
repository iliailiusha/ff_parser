"""Capture ALL API responses from goofish search page to find item data."""
import json, sys, io, hashlib, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from urllib.parse import quote, parse_qs, urlparse

captured = {}

def handle_response(response):
    url = response.url
    if "h5api.m.goofish.com" not in url:
        return
    if response.status != 200:
        return
    
    api_name = ""
    if "index.get" in url:
        api_name = "homepage"
    elif "item.search.activate" in url:
        api_name = "activate"
    elif "pc.search" in url and "activate" not in url:
        api_name = "search"
    elif "search.shade" in url:
        api_name = "shade"
    elif "user.page.nav" in url:
        api_name = "nav"
    elif "loginuser" in url:
        api_name = "loginuser"
    elif "search" in url.lower():
        api_name = "other_search"
    else:
        return
    
    if api_name in captured:
        return
    
    try:
        body = response.body().decode("utf-8", errors="replace")
        data = json.loads(body)
        captured[api_name] = {
            "ret": data.get("ret", []),
            "data_keys": list(data.get("data", {}).keys()),
        }
        # Check for items in nested structures
        if "data" in data:
            d = data["data"]
            for k, v in d.items():
                if isinstance(v, list) and len(v) > 0:
                    captured[api_name][f"list_{k}_count"] = len(v)
                    if isinstance(v[0], dict):
                        captured[api_name][f"list_{k}_keys"] = list(v[0].keys())[:10]
                        # Check if this looks like an item
                        first = v[0]
                        if any(x in str(first) for x in ["price", "title", "item", "url", "name"]):
                            captured[api_name][f"list_{k}_sample"] = json.dumps(first, ensure_ascii=False)[:500]
    except:
        pass

QUERY = "Nike 运动鞋"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    )
    page = context.new_page()
    page.on("response", handle_response)
    
    url = f"https://www.goofish.com/search?q={quote(QUERY)}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(10000)
    
    print("=== CAPTURED APIS ===")
    print(json.dumps(captured, ensure_ascii=False, indent=2))
    
    browser.close()
