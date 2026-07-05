"""Explore Goofish QR login flow non-interactively."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from curl_cffi import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

# Step 1: Get login page to obtain cookies & csrf
print("=== Step 1: Login page ===")
s = requests.Session(impersonate="chrome124")
resp = s.get("https://passport.goofish.com/mini_login.htm?lang=zh_cn&appName=xianyu", headers=HEADERS, timeout=15)
print(f"Status: {resp.status_code}")
print(f"Content length: {len(resp.text)}")

# Extract CSRF token
import re
csrf_match = re.search(r'name="_csrf_token"\s+value="([^"]+)"', resp.text)
csrf_token = csrf_match.group(1) if csrf_match else "NOT_FOUND"
print(f"CSRF token: {csrf_token}")

# Look for QR related data
qr_match = re.search(r'qrcode[^/]*/([^"\']+)', resp.text, re.IGNORECASE)
if qr_match:
    print(f"QR path: {qr_match.group(1)[:100]}")

# Step 2: Try to get QR code
print("\n=== Step 2: QR code generate ===")
resp2 = s.get(
    "https://passport.goofish.com/newlogin/qrcode/generate.do",
    params={
        "appName": "xianyu",
        "fromSite": "77",
        "appEntrance": "baxia",
        "_csrf_token": csrf_token,
    },
    headers=HEADERS,
    timeout=15,
)
print(f"Status: {resp2.status_code}")
try:
    data = resp2.json()
    print(f"Response keys: {list(data.keys())}")
    print(f"Response: {json.dumps(data, ensure_ascii=False)[:1000]}")
except:
    print(f"Raw: {resp2.text[:500]}")

# Step 3: Check cookies
print("\n=== Cookies ===")
for name, value in s.cookies.items():
    print(f"  {name}: {value[:30]}...")
