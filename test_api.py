"""Try search API with curl_cffi directly."""
import json, sys, io, hashlib, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from curl_cffi import requests
from playwright.sync_api import sync_playwright

print("Getting fresh cookies from homepage...")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(3000)
    
    cookies_raw = page.context.cookies()
    cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies_raw)
    h5_tk = next((c["value"] for c in cookies_raw if c["name"] == "_m_h5_tk"), "")
    token = h5_tk.split("_")[0] if "_" in h5_tk else ""
    
    print(f"Cookie count: {len(cookies_raw)}")
    print(f"Token: {token[:15] if token else 'NONE'}...")
    browser.close()

def md5(s):
    return hashlib.md5(s.encode()).hexdigest()

# Try search API with curl_cffi impersonation
print("\n=== search API via curl_cffi ===")
t = str(int(time.time() * 1000))
data = json.dumps({"q": "Nike 运动鞋", "bizFrom": "pcSearch", "searchReqFromPage": "xyPcSearch", "pageNo": 1, "pageSize": 20})
sign = md5(f"{token}&{t}&34839810&{data}")

url = (f"https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"
       f"?jsv=2.7.2&appKey=34839810&t={t}&sign={sign}&v=1.0&type=originaljson"
       f"&accountSite=xianyu&dataType=json&api=mtop.taobao.idlemtopsearch.pc.search")

try:
    resp = requests.post(
        url,
        data={"data": data},
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
            "Referer": "https://www.goofish.com/",
            "Cookie": cookie_str,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        impersonate="chrome124",
        timeout=20,
    )
    print(f"Status: {resp.status_code}")
    body = resp.text[:2000]
    try:
        parsed = json.loads(resp.text)
        print(f"ret: {parsed.get('ret', [])}")
        print(f"data keys: {list(parsed.get('data', {}).keys())[:15]}")
    except:
        print(f"body: {body}")
except Exception as e:
    print(f"Error: {e}")

# Try homepage API as backup
print("\n=== homepage API ===")
t2 = str(int(time.time() * 1000))
data2 = json.dumps({"bizFrom": "pcIndex"})
sign2 = md5(f"{token}&{t2}&34839810&{data2}")
url2 = (f"https://h5api.m.goofish.com/h5/mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get/1.0/"
        f"?jsv=2.7.2&appKey=34839810&t={t2}&sign={sign2}&v=1.0&type=originaljson"
        f"&accountSite=xianyu&dataType=json&api=mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get")

try:
    resp2 = requests.post(url2, data={"data": data2}, impersonate="chrome124", timeout=20,
        headers={"Referer": "https://www.goofish.com/", "Cookie": cookie_str})
    print(f"Status: {resp2.status_code}")
    parsed2 = json.loads(resp2.text)
    print(f"ret: {parsed2.get('ret', [])}")
    if "data" in parsed2:
        print(f"data keys: {list(parsed2['data'].keys())[:15]}")
        for k, v in parsed2["data"].items():
            if isinstance(v, list):
                print(f"  {k}: list[{len(v)}]")
                if v and isinstance(v[0], dict):
                    print(f"    sample keys: {list(v[0].keys())[:10]}")
except Exception as e:
    print(f"Error: {e}")
