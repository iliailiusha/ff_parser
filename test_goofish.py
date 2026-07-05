"""Test Goofish search page to debug the scraper."""
import json, sys, io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

QUERY = "Nike 运动鞋"

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

    from urllib.parse import quote
    url = f"https://www.goofish.com/search?q={quote(QUERY)}"
    print(f"Navigating to: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)

    print(f"\nCurrent URL: {page.url}")
    print(f"Page title length: {len(page.title())}")

    html = page.content()
    checks = {
        "captcha": "验证码" in html or "安全验证" in html,
        "login_prompt": "请先登录" in html,
        "no_results": "暂无相关宝贝" in html or "未找到" in html,
        "has_item_link": "/item?id=" in html,
    }
    print("\nChecks:")
    for k, v in checks.items():
        print(f"  {k}: {v}")

    # Try the actual selectors from SEARCH_JS
    result = page.evaluate("""() => {
        const sel = {
            card: 'a[href*="/item?id="]',
            title: '[class*="row1-wrap-title"], [class*="main-title"]',
            priceWrap: '[class*="price-wrap"]',
            priceNum: '[class*="number"]',
        };
        const cards = document.querySelectorAll(sel.card);
        return {
            card_count: cards.length,
            sample_html: cards.length > 0 ? cards[0].outerHTML.substring(0, 1000) : 'none',
            body_sample: document.body ? document.body.innerText.substring(0, 3000) : 'no body',
        };
    }""")
    print(f"\nResult:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    browser.close()
