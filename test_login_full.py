"""Full QR login flow test with polling."""
import json, sys, io, time, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from curl_cffi import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# Create session
s = requests.Session(impersonate="chrome124")

# Step 1: Get login page cookies
print("=== Step 1: Getting login page ===")
resp = s.get("https://passport.goofish.com/mini_login.htm?lang=zh_cn&appName=xianyu", headers=HEADERS, timeout=15)
csrf_match = re.search(r'name="_csrf_token"\s+value="([^"]+)"', resp.text)
csrf_token = csrf_match.group(1) if csrf_match else ""
print(f"CSRF: {csrf_token[:20] if csrf_token else 'NONE'}...")

# Step 2: Get QR code
print("\n=== Step 2: Getting QR code ===")
qr_resp = s.get(
    "https://passport.goofish.com/newlogin/qrcode/generate.do",
    params={"appName": "xianyu", "fromSite": "77", "appEntrance": "baxia", "_csrf_token": csrf_token},
    headers=HEADERS,
    timeout=15,
)
qr_data = qr_resp.json()
code_content = qr_data["content"]["data"]["codeContent"]
print(f"QR code URL: {code_content}")

# Generate QR image
try:
    import qrcode
    from PIL import Image
    qr = qrcode.make(code_content)
    qr.save("goofish_qr.png")
    print("QR image saved to goofish_qr.png")
except ImportError:
    print("qrcode library not installed, install with: pip install qrcode[pil]")

# Step 3: Poll for login completion
print("\n=== Step 3: Polling for login ===")
print("Scan the QR code with 闲鱼 app and confirm login...")

# Extract lgToken from code content
lg_token_match = re.search(r'lgToken=([^&]+)', code_content)
lg_token = lg_token_match.group(1) if lg_token_match else ""
print(f"lgToken: {lg_token[:30]}...")

# Try various polling strategies
for i in range(40):  # poll for 120 seconds (3s intervals)
    time.sleep(3)
    
    # Strategy 1: Check if _m_h5_tk cookie appeared
    if "_m_h5_tk" in s.cookies:
        print(f"✓ _m_h5_tk cookie found! Login successful!")
        break
    
    # Strategy 2: Try to call login check API
    try:
        check = s.get("https://passport.goofish.com/newlogin/qrcodeQuery.do",
            params={"lgToken": lg_token, "_csrf_token": csrf_token},
            headers=HEADERS, timeout=10)
        data = check.json()
        code = data.get("content", {}).get("data", {}).get("resultCode", -1)
        status = data.get("content", {}).get("data", {}).get("status", -1)
        print(f"  [{i*3}s] QR status: resultCode={code}, status={status}")
        if code == 1:  # scanned but not confirmed
            print("  ℹ️ Scanned! Waiting for confirmation on phone...")
        elif code == 2 or code == 100:  # confirmed
            print("  ✓ Login confirmed!")
            break
    except Exception as e:
        print(f"  [{i*3}s] Poll error: {e}")
    
    # Strategy 3: Check cookies changed
    print(f"  Cookies: {list(s.cookies.keys())}")
else:
    print("✗ Timeout waiting for login")

# Step 4: Check authenticated access
print("\n=== Step 4: Check authenticated state ===")
print(f"Final cookies: {dict(s.cookies)}")
if "_m_h5_tk" in s.cookies:
    print(f"Token available! Search should work now")

# Try search API with auth
if "_m_h5_tk" in s.cookies:
    import hashlib
    h5_tk = s.cookies["_m_h5_tk"]
    token = h5_tk.split("_")[0] if "_" in h5_tk else ""
    
    t = str(int(time.time() * 1000))
    data_str = json.dumps({"q": "Nike 运动鞋", "bizFrom": "pcSearch", "searchReqFromPage": "xyPcSearch", "pageNo": 1, "pageSize": 20})
    sign = hashlib.md5(f"{token}&{t}&34839810&{data_str}".encode()).hexdigest()
    
    search_url = (f"https://h5api.m.goofish.com/h5/mtop.taobao.idlemtopsearch.pc.search/1.0/"
                  f"?jsv=2.7.2&appKey=34839810&t={t}&sign={sign}&v=1.0&type=originaljson"
                  f"&accountSite=xianyu&dataType=json&api=mtop.taobao.idlemtopsearch.pc.search")
    
    search_resp = s.post(search_url, data={"data": data_str}, headers=HEADERS, timeout=15)
    search_result = search_resp.json()
    print(f"Search ret: {search_result.get('ret', [])}")
    if "data" in search_result:
        data_keys = list(search_result["data"].keys())[:10]
        print(f"Search data keys: {data_keys}")
        if "cardList" in search_result["data"]:
            print(f"Items found: {len(search_result['data']['cardList'])}")
            if search_result["data"]["cardList"]:
                print(f"Sample: {json.dumps(search_result['data']['cardList'][0], ensure_ascii=False)[:500]}")
