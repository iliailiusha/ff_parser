"""Test Taobao search API via curl_cffi with impersonation."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from curl_cffi import requests
from urllib.parse import quote

QUERY = "Nike 运动鞋 二手"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://www.taobao.com/",
}

# Approach 1: Taobao search results page
print("=== Taobao s.taobao.com search ===")
resp = requests.get(
    f"https://s.taobao.com/search?q={quote(QUERY)}",
    headers=HEADERS,
    impersonate="chrome124",
    timeout=20,
)
print(f"Status: {resp.status_code}")
print(f"Content length: {len(resp.text)}")

# Check response
if 'item' in resp.text.lower() and ('¥' in resp.text or '￥' in resp.text):
    print("Items found in response!")
    # Try to extract items
    import re
    prices = re.findall(r'[¥￥]\s*[\d,]+\.?\d*', resp.text)
    print(f"Price examples: {prices[:5]}")
else:
    # Look for login/block signals
    signals = {
        "login": "登录" in resp.text or "请登录" in resp.text,
        "captcha": "验证" in resp.text or "滑块" in resp.text,
        "blocked": "拥挤" in resp.text or "访问" in resp.text,
        "empty": "没有找到" in resp.text,
    }
    print(f"Signals: {json.dumps(signals, ensure_ascii=False)}")
    if resp.text:
        print(f"Body sample: {resp.text[:1000]}")

# Approach 2: Taobao list API (JSON endpoint)
print("\n=== Taobao list API ===")
resp2 = requests.get(
    f"https://www.taobao.com/list?q={quote(QUERY)}",
    headers=HEADERS,
    impersonate="chrome124",
    timeout=20,
)
print(f"Status: {resp2.status_code}")
print(f"Body: {resp2.text[:1000]}")

# Approach 3: m.taobao.com (mobile)
print("\n=== m.taobao.com ===")
resp3 = requests.get(
    f"https://m.taobao.com/search?q={quote(QUERY)}",
    headers={
        **HEADERS,
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148",
    },
    impersonate="safari17_0_ios",
    timeout=20,
)
print(f"Status: {resp3.status_code}")
print(f"Body: {resp3.text[:1000]}")
