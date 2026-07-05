"""Test mobile site + raw API call approaches."""
import json, sys, io, hashlib, time, random
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# 1. Try mobile site
print("=== MOBILE SITE ===")
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 430, "height": 932},
        locale="zh-CN",
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/16.0 Mobile/15E148 Safari/604.1"
        ),
    )
    from urllib.parse import quote
    page.goto(f"https://m.goofish.com/search?q={quote('Nike 运动鞋')}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    
    body_text = page.evaluate("() => document.body?.innerText?.substring(0, 2000) || ''")
    has_items = page.evaluate("() => document.querySelectorAll('[class*=item]').length > 5")
    
    print(f"Mobile URL: {page.url}")
    print(f"Has items: {has_items}")
    print(f"Body sample: {body_text[:1000]}")

    # Check for item links
    links = page.evaluate("""() => {
        const items = [];
        document.querySelectorAll('a').forEach(a => {
            if (a.href && (a.href.includes('/item/') || a.href.includes('id='))) {
                items.push({href: a.href.substring(0,100), text: a.innerText.trim().substring(0,50)});
            }
        });
        return items.slice(0,5);
    }""")
    print(f"\nItem links ({len(links)}):")
    for l in links[:5]:
        print(f"  {json.dumps(l, ensure_ascii=False)}")

    browser.close()

# 2. Try raw MTOP API call
print("\n=== RAW MTOP API ===")
APP_KEY = "34839810"
TOKEN = ""

# First get a cookie/token from homepage visit
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    h5_tk = cookies.get("_m_h5_tk", "")
    if "_" in h5_tk:
        TOKEN = h5_tk.split("_")[0]
    print(f"Got token: {TOKEN[:10] if TOKEN else 'NONE'}...")
    print(f"Cookies: {list(cookies.keys())}")
    browser.close()

# Try calling search API via fetch inside page context
if TOKEN:
    print("\n=== SEARCH API VIA PAGE ===")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        
        result = page.evaluate("""async ({token, appKey}) => {
            const t = Date.now();
            const data = JSON.stringify({
                q: "Nike 运动鞋",
                type: 0,
                bizFrom: "pcSearch",
                searchReqFromPage: "xyPcSearch",
                pageNo: 1,
                pageSize: 20,
            });
            const sign = MD5(token + "&" + t + "&" + appKey + "&" + data);
            const url = `https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/?jsv=2.7.2&appKey=${appKey}&t=${t}&sign=${sign}&v=1.0&type=originaljson&accountSite=xianyu&dataType=json&timeout=20000&api=mtop.taobao.idlemtopsearch.pc.search&sessionOption=AutoLoginOnly`;
            
            try {
                const resp = await fetch(url, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body: 'data=' + encodeURIComponent(data),
                });
                return await resp.text();
            } catch(e) {
                return 'ERROR: ' + e.message;
            }
        }""", {"token": TOKEN, "appKey": APP_KEY})
        
        truncated = result[:2000] if len(result) > 2000 else result
        print(f"Search API result: {truncated}")
        
        browser.close()
else:
    print("No token available, skipping API test")
