import hashlib
import json
import time
from typing import Any, Optional
from urllib.parse import quote

from curl_cffi.requests import AsyncSession

from goofish_parser.config import APP_KEY, MTOP_HOST, USER_AGENT
from goofish_parser.scraper.session import get_cookies, get_token, get_proxy_url


def calc_sign(token: str, timestamp: str, data: str) -> str:
    raw = f"{token}&{timestamp}&{APP_KEY}&{data}"
    return hashlib.md5(raw.encode()).hexdigest()


async def mtop_request(
    api: str,
    data: dict[str, Any] | str,
    *,
    version: str = "1.0",
    spm_cnt: str = "a21ybx.home.0.0",
    extra_params: Optional[dict[str, str]] = None,
) -> dict[str, Any]:
    token = get_token()
    if not token:
        return {"ret": ["FAIL_SYS_TOKEN_EMPTY"]}

    cookies = get_cookies()
    timestamp = str(int(time.time() * 1000))
    data_str = data if isinstance(data, str) else json.dumps(data, separators=(",", ":"))
    sign = calc_sign(token, timestamp, data_str)

    url = f"{MTOP_HOST}/h5/{api}/{version}/"

    params = {
        "jsv": "2.7.2",
        "appKey": APP_KEY,
        "t": timestamp,
        "sign": sign,
        "v": version,
        "type": "originaljson",
        "accountSite": "xianyu",
        "dataType": "json",
        "timeout": "20000",
        "api": api,
        "sessionOption": "AutoLoginOnly",
        "spm_cnt": spm_cnt,
    }
    if extra_params:
        params.update(extra_params)

    headers = {
        "accept": "application/json",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://www.goofish.com",
        "referer": "https://www.goofish.com/",
        "user-agent": USER_AGENT,
        "cookie": "; ".join(f"{k}={v}" for k, v in cookies.items() if k != "_m_h5_tk_token"),
    }

    body = f"data={quote(data_str)}"
    proxy_url = get_proxy_url()

    async with AsyncSession() as session:
        resp = await session.post(
            url,
            params=params,
            headers=headers,
            data=body,
            proxy=proxy_url,
            timeout=30,
            impersonate="chrome124",
        )
        return resp.json()
