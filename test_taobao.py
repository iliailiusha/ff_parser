"""Test Taobao search - see if items are accessible without login."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

QUERY = "Nike 运动鞋 二手"

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
    
    # Try desktop search
    url = f"https://s.taobao.com/search?q={quote(QUERY)}"
    print(f"Navigating to: {url}")
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")

    # Check for items
    result = page.evaluate("""() => {
        // Various selectors Taobao uses
        const selectors = [
            '.items .item', '.item.J_MouserOnverReq', 
            '[class*=item]', '.grid-item', '.item-card',
            'div[data-index]', '.J_Item', '.item-wrapper',
        ];
        const found = {};
        for (const sel of selectors) {
            const count = document.querySelectorAll(sel).length;
            if (count > 0) found[sel] = count;
        }
        
        // Check for item links
        const links = Array.from(document.querySelectorAll('a'))
            .filter(a => a.href && (a.href.includes('/item/') || a.href.includes('detail')))
            .length;
        
        // Price elements
        const prices = Array.from(document.querySelectorAll('[class*=price]'))
            .filter(el => el.innerText.includes('¥') || el.innerText.includes('￥'))
            .length;
        
        return {
            found_selectors: found,
            item_links: links,
            price_elements: prices,
            body_sample: document.body?.innerText?.substring(0, 1500) || 'no body',
        };
    }""")
    
    print(f"\nResult:")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    # If items found, extract them
    if result.get("item_links", 0) > 0 or result.get("price_elements", 0) > 0:
        items = page.evaluate("""() => {
            const cards = document.querySelectorAll('[class*=item], [class*=Item]');
            const results = [];
            for (const card of cards) {
                const titleEl = card.querySelector('[class*=title], [class*=Title], [class*=Title]');
                const priceEl = card.querySelector('[class*=price]');
                const link = card.querySelector('a');
                if (titleEl || priceEl) {
                    results.push({
                        title: titleEl?.innerText?.trim()?.substring(0, 100),
                        price: priceEl?.innerText?.trim()?.substring(0, 30),
                        url: link?.href?.substring(0, 200),
                    });
                }
                if (results.length >= 5) break;
            }
            return results;
        }""")
        print(f"\nItems found: {len(items)}")
        for it in items[:5]:
            print(f"  {json.dumps(it, ensure_ascii=False)}")

    browser.close()
