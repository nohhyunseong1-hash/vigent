"""go2rtc_client.py — go2rtc 주소 **한 곳**. [OPEN_ISSUES_20261008 #16]

예전엔 `http://127.0.0.1:1984` 가 routers/cameras 2곳·routers/tapo 5곳·starvation_guard 1곳에 리터럴로 흩어져 있었고
포트 상수(_G2_PORT)는 cameras 에만 있었다. 주소를 바꾸면 세 파일을 같이 고쳐야 했다.
환경변수 VIGENT_GO2RTC_URL(예: http://127.0.0.1:1984)로 덮어쓸 수 있다 — config/go2rtc.yaml api.listen 과 같아야 한다.
"""
from __future__ import annotations

import os
import urllib.parse

BASE: str = os.environ.get("VIGENT_GO2RTC_URL", "http://127.0.0.1:1984").rstrip("/")
_u = urllib.parse.urlparse(BASE)
HOST: str = _u.hostname or "127.0.0.1"
PORT: int = int(_u.port or 1984)


def url(path: str, **query: str) -> str:
    """HTTP URL. query 는 urlencode. 예: url("/api/streams", src="cam1")"""
    q = ("?" + urllib.parse.urlencode(query)) if query else ""
    return BASE + ("/" + path.lstrip("/")) + q


def ws_url(path: str, **query: str) -> str:
    """WebSocket URL(ws://). 예: ws_url("/api/ws", src="cam1")"""
    return url(path, **query).replace("http://", "ws://", 1).replace("https://", "wss://", 1)
