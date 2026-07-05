"""Check if any Goofish API returns items without login."""
import json, sys, io, hashlib, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

responses = {}

def handle_response(response):
    url = response.url
    if "gaia.idle.data.gw.v2.index.get" in url and response.status == 200:
        try:
            data = json.loads(response.body().decode("utf-8", errors="replace"))
            if "data" in data:
                print(f"\n=== homepage API ===")
                print(f"ret: {data.get('ret', [])}")
                for k, v in data["data"].items():
                    if isinstance(v, list):
                        print(f"  {k}: list[{len(v)}]")
                        if v and isinstance(v[0], dict):
                            print(f"    first keys: {list(v[0].keys())[:15]}")
        except:
            pass

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )
    page = context.new_page()
    page.on("response", handle_response)
    
    page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(8000)
    
    # Get the response data from the first API call that returned items
    result = page.evaluate("""async () => {
        // Try hitting the index API that returns homepage items
        const t = Date.now();
        const token = (document.cookie.match(/_m_h5_tk=([^;]+)/) || [])[1] || '';
        const appKey = '34839810';
        const md5 = s => {
            const hash = new Bun ? Bun.CryptoHasher.hash('md5', s).hex() : 
                Array.from(new Uint8Array(await crypto.subtle.digest('MD5', new TextEncoder().encode(s))))
                    .map(b => b.toString(16).padStart(2, '0')).join('');
            return s;
        };
        // Use simple approach
        const data = JSON.stringify({"bizFrom":"pcIndex"});
        const sign = md5(token + '&' + t + '&' + appKey + '&' + data);
        const url = 'https://h5api.m.goofish.com/h5/mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get/1.0/?jsv=2.7.2&appKey=' + appKey + '&t=' + t + '&sign=' + sign + '&v=1.0&type=originaljson&accountSite=xianyu&dataType=json';
        
        const resp = await fetch(url, {method: 'POST', body: 'data=' + encodeURIComponent(data)});
        return await resp.text();
    }""")
    
    try:
        data = json.loads(result)
        print(f"\n=== Manual API call ===")
        print(f"ret: {data.get('ret', [])}")
        if "data" in data:
            for k, v in data["data"].items():
                if isinstance(v, list):
                    print(f"  {k}: list[{len(v)}]")
                    if v and isinstance(v[0], dict):
                        fk = list(v[0].keys())[:15]
                        print(f"    keys: {fk}")
                        print(f"    sample: {json.dumps(v[0], ensure_ascii=False)[:500]}")
    except:
        print(f"\nRaw: {result[:500]}")
    
    browser.close()
