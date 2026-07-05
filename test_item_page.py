"""Test if individual Goofish item pages are accessible without login."""
import json, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

# Known Goofish item IDs (can be found via search engines)
test_ids = ["748596325641", "735809767892", "751234567890", "763456789012", "755829718625"]

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
    )

    for item_id in test_ids:
        url = f"https://www.goofish.com/item?id={item_id}"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)
            title = page.title()
            body_text = page.evaluate("() => (document.body?.innerText || '').substring(0, 500)")
            has_item = "title" in body_text.lower() or "¥" in body_text or "￥" in body_text
            print(f"ID {item_id}: title='{title}', has_item_data={has_item}")
            print(f"  body: {body_text[:200]}")
        except Exception as e:
            print(f"ID {item_id}: ERROR - {e}")

    browser.close()
