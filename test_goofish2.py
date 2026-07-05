"""Deeper inspection of Goofish search page - look for hidden items."""
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
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(8000)

    # Check ALL links on the page
    all_links = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('a')).map(a => ({
            href: a.href,
            text: a.innerText.substring(0, 50),
        }));
    }""")
    
    item_links = [l for l in all_links if "/item/" in l["href"]]
    print(f"\nTotal links: {len(all_links)}")
    print(f"Item links: {len(item_links)}")
    for l in item_links[:5]:
        print(f"  {json.dumps(l, ensure_ascii=False)}")

    # Check for any hidden elements with item data
    hidden_items = page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        const results = [];
        for (const el of all) {
            if (el.innerText && el.innerText.includes('¥') && el.children.length === 0) {
                results.push(el.innerText.trim().substring(0, 100));
                if (results.length > 10) break;
            }
        }
        return results;
    }""")
    print(f"\nElements with ¥: {len(hidden_items)}")
    for h in hidden_items[:5]:
        print(f"  {h}")

    # Check for script tags that might contain item data
    scripts = page.evaluate("""() => {
        return Array.from(document.querySelectorAll('script')).map(s => ({
            src: s.src.substring(0, 100),
            len: (s.textContent || '').length,
        })).filter(s => s.len > 1000);
    }""")
    print(f"\nLarge scripts: {len(scripts)}")
    for s in scripts[:3]:
        print(f"  src={s['src']}, len={s['len']}")

    # Check if there's an API XHR response with items
    print(f"\nBody length: {len(page.content())}")
    
    # Check response that might have item data
    responses = []
    def handle_response(response):
        if 'search' in response.url.lower() or 'list' in response.url.lower():
            responses.append({"url": response.url[:200], "status": response.status})
    
    page.on("response", handle_response)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(5000)
    
    print(f"\nSearch-related responses: {len(responses)}")
    for r in responses[:10]:
        print(f"  {r}")

    browser.close()
