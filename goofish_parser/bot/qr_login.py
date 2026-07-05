import logging
import re
import json
import time
import hashlib
from io import BytesIO
from typing import Optional

from curl_cffi import requests
import qrcode

from goofish_parser.config import COOKIES_PATH, APP_KEY

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-CN,zh;q=0.9",
}

QR_POLL_INTERVAL = 3
QR_POLL_TIMEOUT = 120


def _make_session() -> requests.Session:
    s = requests.Session(impersonate="chrome124")
    for k, v in HEADERS.items():
        s.headers[k] = v
    return s


def get_qr_code() -> Optional[tuple[bytes, str, requests.Session]]:
    session = _make_session()

    resp = session.get(
        "https://passport.goofish.com/mini_login.htm?lang=zh_cn&appName=xianyu",
        timeout=15,
    )
    m = re.search(r'name="_csrf_token"\s+value="([^"]+)"', resp.text)
    csrf_token = m.group(1) if m else ""

    qr_resp = session.get(
        "https://passport.goofish.com/newlogin/qrcode/generate.do",
        params={
            "appName": "xianyu",
            "fromSite": "77",
            "appEntrance": "baxia",
            "_csrf_token": csrf_token,
        },
        timeout=15,
    )
    qr_data = qr_resp.json()
    if qr_data.get("hasError"):
        logger.error(f"QR generate error: {qr_data}")
        return None

    code_content = qr_data["content"]["data"]["codeContent"]
    img = qrcode.make(code_content, border=2, box_size=8)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    qr_bytes = buf.getvalue()

    session._qr_csrf = csrf_token
    session._qr_code_content = code_content
    return qr_bytes, code_content, session


def poll_login(session: requests.Session, on_status=None) -> bool:
    lg_token = ""
    m = re.search(r'lgToken=([^&]+)', session._qr_code_content)
    if m:
        lg_token = m.group(1)

    for _ in range(QR_POLL_TIMEOUT // QR_POLL_INTERVAL):
        time.sleep(QR_POLL_INTERVAL)

        if "_m_h5_tk" in session.cookies:
            _save_cookies(session)
            logger.info("Login detected via _m_h5_tk cookie")
            return True

        try:
            check = session.get(
                "https://passport.goofish.com/newlogin/qrcodeQuery.do",
                params={"lgToken": lg_token, "_csrf_token": getattr(session, "_qr_csrf", "")},
                timeout=10,
            )
            data = check.json()
            result = data.get("content", {}).get("data", {})
            code = result.get("resultCode", -1)

            if code == 100:
                _save_cookies(session)
                logger.info("Login confirmed (resultCode=100)")
                return True
            elif code == 1:
                if on_status:
                    on_status("scanned")
            elif code == 2:
                _save_cookies(session)
                logger.info("Login confirmed (resultCode=2)")
                return True
        except Exception as e:
            logger.debug(f"QR poll error: {e}")

        if "_m_h5_tk" in session.cookies:
            _save_cookies(session)
            return True

    logger.warning("QR login timeout")
    return False


def _save_cookies(session: requests.Session) -> None:
    cookie_dict = dict(session.cookies)
    COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
    COOKIES_PATH.write_text(
        json.dumps(cookie_dict, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"Cookies saved to {COOKIES_PATH}")
