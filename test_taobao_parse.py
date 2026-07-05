"""Parse Taobao search results from HTML."""
import json, sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from curl_cffi import requests
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

QUERY = "Nike 运动鞋 二手"

resp = requests.get(
    f"https://s.taobao.com/search?q={quote(QUERY)}",
    headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.taobao.com/",
    },
    impersonate="chrome124",
    timeout=20,
)

soup = BeautifulSoup(resp.text, "html.parser")

# Look for item data in script tags or HTML
# Taobao embeds item data in <script> tags with JSON
scripts = soup.find_all("script")
print(f"Total script tags: {len(scripts)}")

items_found = []

for script in scripts:
    text = script.string or ""
    if "item" in text.lower() and ("price" in text.lower() or "nid" in text.lower()):
        # Try to extract JSON objects
        matches = re.finditer(r'\{"item.*?\}', text, re.DOTALL)
        for m in matches:
            try:
                data = json.loads(m.group())
                if "nid" in data and "title" in data:
                    items_found.append(data)
                    if len(items_found) >= 5:
                        break
            except:
                pass
        if items_found:
            break

if items_found:
    print(f"\nItems found in scripts: {len(items_found)}")
    for it in items_found[:5]:
        print(f"  {json.dumps(it, ensure_ascii=False)[:300]}")
else:
    # Try to find items in HTML directly
    print("\nNo items in scripts, scanning HTML...")
    # Look for price patterns
    price_patterns = re.findall(r'(?:¥|￥|价格[：:])?\s*(\d+\.?\d*)', resp.text)
    title_patterns = re.findall(r'<a[^>]*title="([^"]+)"', resp.text)
    print(f"Prices found: {price_patterns[:10]}")
    print(f"Titles found: {title_patterns[:5]}")

# Search for item data in g_page_config or page JSON
print("\n=== Searching for data config ===")
for script in scripts:
    text = script.string or ""
    if "g_page_config" in text or "pageData" in text or "itemlist" in text:
        print(f"Found data config script, length: {len(text)}")
        print(f"Sample: {text[:500]}")
        break

# Also check for auction-card/items
cards = soup.select('[class*=item], [class*=Item], [class*=card], [class*=Card], [data-nid]')
print(f"\nHTML card elements: {len(cards)}")
if cards:
    card = cards[0]
    print(f"Card HTML: {str(card)[:500]}")

# Look for raw item data in the entire response
if "nid" in resp.text:
    # Extract item IDs
    nids = re.findall(r'"nid"\s*:\s*"(\d+)"', resp.text)
    print(f"\nItem IDs (nid): {nids[:10]}")
    titles = re.findall(r'"title"\s*:\s*"([^"]+)"', resp.text)
    print(f"Titles: {titles[:5]}")
    prices = re.findall(r'"price"\s*:\s*"([^"]+)"', resp.text)
    print(f"Prices: {prices[:10]}")
