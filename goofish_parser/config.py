import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID", "")

CNY_TO_RUB_FALLBACK = float(os.getenv("CNY_TO_RUB", "12"))
USD_TO_RUB = float(os.getenv("USD_TO_RUB", "85"))

API_BASE_URL = os.getenv("API_BASE_URL", "")
PROXY_URL = os.getenv("PROXY_URL") or None

PROXY_HOST = os.getenv("PROXY_HOST", "")
PROXY_USER = os.getenv("PROXY_USER", "")
PROXY_PASS = os.getenv("PROXY_PASS", "")

DB_PATH = DATA_DIR / "storage.db"
COOKIES_PATH = DATA_DIR / "cookies.json"

APP_KEY = "34839810"
MTOP_HOST = "https://h5api.m.goofish.com"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

SEARCH_JS = r"""
(limit) => (async () => {
  const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const waitFor = async (predicate, timeoutMs = 10000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (predicate()) return true;
      await wait(200);
    }
    return false;
  };
  const clean = (v) => (v || '').replace(/\s+/g, ' ').trim();
  const sel = {
    card: 'a[href*="/item?id="]',
    title: '[class*="row1-wrap-title"], [class*="main-title"]',
    attrs: '[class*="row2-wrap-cpv"] span',
    priceWrap: '[class*="price-wrap"]',
    priceNum: '[class*="number"]',
    priceDec: '[class*="decimal"]',
    priceDesc: '[class*="price-desc"]',
    sellerWrap: '[class*="row4-wrap-seller"]',
    sellerText: '[class*="seller-text"]',
    badge: '[title*="芝麻"], [class*="credit"]',
  };
  await waitFor(() => {
    const bodyText = document.body?.innerText || '';
    return Boolean(
      document.querySelector(sel.card)
      || /暂无相关宝贝|未找到/.test(bodyText)
      || /请先登录|验证码/.test(bodyText)
    );
  });
  const bodyText = document.body?.innerText || '';
  const requiresAuth = /请先登录|登录后/.test(bodyText);
  const blocked = /验证码|安全验证|异常访问/.test(bodyText);
  const empty = /暂无相关宝贝|未找到/.test(bodyText);
  const items = Array.from(document.querySelectorAll(sel.card))
    .slice(0, limit)
    .map((card) => {
      const href = card.href || card.getAttribute('href') || '';
      const title = clean(card.querySelector(sel.title)?.textContent || '');
      const attrs = Array.from(card.querySelectorAll(sel.attrs))
        .map((n) => clean(n.textContent || ''))
        .filter(Boolean);
      const priceWrap = card.querySelector(sel.priceWrap);
      const priceNumber = clean(priceWrap?.querySelector(sel.priceNum)?.textContent || '');
      const priceDecimal = clean(priceWrap?.querySelector(sel.priceDec)?.textContent || '');
      const priceStr = (priceNumber + priceDecimal).replace(/^¥\s*/, '');
      const location = clean(card.querySelector(sel.sellerWrap)?.querySelector(sel.sellerText)?.textContent || '');
      const badge = clean(card.querySelector(sel.badge)?.textContent || '');
      return { title, url: href, price: priceStr, attrs, location, badge };
    })
    .filter((it) => it.title && it.url);
  return { requiresAuth, blocked, empty, items };
})()
"""
