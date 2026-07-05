"""Try different API approaches to search without login."""
import json, sys, io, hashlib, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from urllib.parse import quote

# Get fresh cookies and token
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
    
    page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    
    cookies = {c["name"]: c["value"] for c in context.cookies()}
    h5_tk = cookies.get("_m_h5_tk", "")
    token = h5_tk.split("_")[0] if "_" in h5_tk else ""
    
    print(f"Token: {token[:15] if token else 'NONE'}...")
    print(f"Cookies: {list(cookies.keys())}")
    
    # Approach 1: Try the search API with proper search data parameter
    print("\n=== APPROACH 1: Search API with search params ===")
    def md5(s):
        return hashlib.md5(s.encode()).hexdigest()
    
    t = str(int(time.time() * 1000))
    data = json.dumps({
        "q": "Nike 运动鞋",
        "bizFrom": "pcSearch",
        "searchReqFromPage": "xyPcSearch",
        "pageNo": 1,
        "pageSize": 20,
    })
    sign = md5(f"{token}&{t}&34839810&{data}")
    url = (f"https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"
           f"?jsv=2.7.2&appKey=34839810&t={t}&sign={sign}&v=1.0&type=originaljson"
           f"&accountSite=xianyu&dataType=json&timeout=20000"
           f"&api=mtop.taobao.idlemtopsearch.pc.search")
    
    result = page.evaluate("""async (args) => {
        const [url, dataStr] = args;
        try {
            const resp = await fetch(url, {
                method: 'POST',
                headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                body: 'data=' + encodeURIComponent(dataStr),
            });
            return await resp.text();
        } catch(e) {
            return 'FETCH_ERROR: ' + e.message;
        }
    }""", [url, data])
    
    try:
        parsed = json.loads(result)
        ret = parsed.get("ret", [])
        print(f"  ret: {ret}")
        if "data" in parsed:
            data_keys = list(parsed["data"].keys())
            print(f"  data keys: {data_keys}")
            if "cardList" in parsed["data"]:
                print(f"  cardList count: {len(parsed['data']['cardList'])}")
                if parsed["data"]["cardList"]:
                    print(f"  first card: {json.dumps(parsed['data']['cardList'][0], ensure_ascii=False)[:500]}")
    except:
        print(f"  raw: {result[:500]}")
    
    # Approach 2: Try the index API that worked (homepage data)
    print("\n=== APPROACH 2: Homepage data API ===")
    t2 = str(int(time.time() * 1000))
    data2 = json.dumps({"bizFrom": "pcIndex"})
    sign2 = md5(f"{token}&{t2}&34839810&{data2}")
    url2 = (f"https://h5api.m.goofish.com/h5/mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get/1.0/"
            f"?jsv=2.7.2&appKey=34839810&t={t2}&sign={sign2}&v=1.0&type=originaljson"
            f"&accountSite=xianyu&dataType=json")
    
    result2 = page.evaluate("""async (url) => {
        try {
            const resp = await fetch(url, {method: 'POST'});
            return await resp.text();
        } catch(e) {
            return 'FETCH_ERROR: ' + e.message;
        }
    }""", url2)
    
    try:
        parsed2 = json.loads(result2)
        ret2 = parsed2.get("ret", [])
        print(f"  ret: {ret2}")
        if "data" in parsed2:
            print(f"  data keys: {list(parsed2['data'].keys())[:15]}")
            for k, v in parsed2["data"].items():
                if isinstance(v, list) and len(v) > 0:
                    print(f"  {k}: list[{len(v)}]")
                    if isinstance(v[0], dict):
                        print(f"    first item keys: {list(v[0].keys())[:10]}")
    except:
        print(f"  raw: {result2[:500]}")
    
    # Approach 3: Try API without any session option
    print("\n=== APPROACH 3: Search API without sessionOption ===")
    t3 = str(int(time.time() * 1000))
    data3 = json.dumps({"q": "Nike 运动鞋", "pageNo": 1, "pageSize": 20})
    sign3 = md5(f"{token}&{t3}&34839810&{data3}")
    url3 = (f"https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"
            f"?jsv=2.7.2&appKey=34839810&t={t3}&sign={sign3}&v=1.0&type=originaljson"
            f"&accountSite=xianyu&dataType=json&api=mtop.taobao.idlemtopsearch.pc.search")
    
    result3 = page.evaluate("""async (args) => {
        const [url, dataStr] = args;
        const resp = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/x-www-form-urlencoded'},
            body: 'data=' + encodeURIComponent(dataStr),
        });
        return await resp.text();
    }""", [url3, data3])
    
    try:
        parsed3 = json.loads(result3)
        print(f"  ret: {parsed3.get('ret', [])}")
        print(f"  data keys: {list(parsed3.get('data', {}).keys())[:10]}")
    except:
        print(f"  raw: {result3[:500]}")
    
    browser.close()
