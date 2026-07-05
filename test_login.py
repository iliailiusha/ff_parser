"""Explore Goofish QR code login flow."""
import json, sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="zh-CN",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36",
    )
    page = context.new_page()
    
    # Navigate to Goofish 
    page.goto("https://www.goofish.com/", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(5000)
    
    # Check current URL - might have redirected
    print(f"Current URL: {page.url}")
    print(f"Title: {page.title()}")
    
    # Look for login link/button and click it
    login_btn = page.query_selector('[class*=login], a[href*="login"], [class*=sign]')
    if login_btn:
        print(f"Found login button: {login_btn.inner_text()[:50]}")
    
    # Check for QR code image
    qr = page.query_selector('img[class*=qrcode], img[class*=qr], img[src*="qrcode"]')
    if qr:
        print(f"QR code found: {qr.get_attribute('src')[:100]}")
    
    # Print page content summary
    body_text = page.evaluate("() => document.body?.innerText?.substring(0, 1000) || ''")
    print(f"\nPage body:\n{body_text}")
    
    # Save screenshot for debugging
    page.screenshot(path="goofish_login.png")
    print("\nScreenshot saved to goofish_login.png")
    
    input("\nPress Enter after scanning QR code...")
    
    # Check cookies after login
    cookies = {c["name"]: c["value"] for c in context.cookies()}
    print(f"\nCookies after login: {list(cookies.keys())}")
    print(f"_m_h5_tk present: {'_m_h5_tk' in cookies}")
    
    browser.close()
