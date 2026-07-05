"""Try finding Goofish items via web search (Bing/Google) or alternative sites."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from urllib.parse import quote

# Approach 1: Search via DuckDuckGo with site:goofish.com
# Approach 2: Try Poizon (得物) which shows market prices
# Approach 3: Try 1688.com

# Let's check what sites show Goofish-like data without login
query = "Nike 运动鞋"

# Approach 1: Try 1688.com (Alibaba wholesale)
print("=== 1688.com ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    url = f"https://www.1688.com/chanpin/{quote(query)}.html"
    print(f"URL: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    
    items = page.evaluate("""() => {
        const cards = document.querySelectorAll('[class*=item], [class*=offer], .offer-list-row .grid-item');
        const results = [];
        for (const card of cards) {
            const titleEl = card.querySelector('[class*=title], a[title]');
            const priceEl = card.querySelector('[class*=price]');
            if (titleEl || priceEl) {
                results.push({
                    title: (titleEl?.title || titleEl?.innerText || '').trim().substring(0, 100),
                    price: (priceEl?.innerText || '').trim().substring(0, 30),
                });
            }
            if (results.length >= 5) break;
        }
        return {
            count: results.length,
            items: results,
        };
    }""")
    print(f"Items: {json.dumps(items, ensure_ascii=False)[:1000]}")
    browser.close()

# Approach 2: Try DuckDuckGo search for goofish items
print("\n=== DuckDuckGo site:goofish.com ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    ddg_url = f"https://html.duckduckgo.com/html/?q=site:goofish.com+Nike+{quote('运动鞋')}"
    page.goto(ddg_url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    
    links = page.evaluate("""() => {
        const results = [];
        document.querySelectorAll('.result__a, a[href*="goofish"]').forEach(a => {
            if (a.href && a.href.includes('goofish')) {
                results.push({
                    text: a.innerText?.trim()?.substring(0, 100),
                    href: a.href?.substring(0, 200),
                });
            }
        });
        return results.slice(0, 10);
    }""")
    print(f"Goofish links found: {len(links)}")
    for l in links:
        print(f"  {json.dumps(l, ensure_ascii=False)}")
    browser.close()

# Approach 3: Try dewu.com (得物) - popular sneaker marketplace
print("\n=== Dewu.com (得物) ===")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    url = f"https://www.dewu.com/s?q={quote(query)}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    
    result = page.evaluate("""() => {
        return {
            title: document.title,
            body: (document.body?.innerText || '').substring(0, 500),
            items: document.querySelectorAll('[class*=item], [class*=card]').length,
        };
    }""")
    print(f"Result: {json.dumps(result, ensure_ascii=False)}")
    browser.close()
