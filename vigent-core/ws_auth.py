"""ws_auth.py — WebSocket 핸드셰이크 토큰 검증 (P0 수정, [S3-후속1] 세션 쿠키 추가).

main.py 의 `@app.middleware("http")` 는 Starlette 에서 HTTP scope 에만 적용되고 websocket scope 에는
적용되지 않는다 — 그 결과 `/tapo/ws` 등 WebSocket 라우트는 `main._auth_guard` 의 VIGENT_API_TOKEN 검사를
그대로 우회했다(VIGENT_API_TOKEN 을 설정해 외부 노출한 배포에서도 토큰 없이 연결·카메라 영상 열람 가능).
이 모듈은 각 WS 핸들러가 진입부에서 호출할 공용 헬퍼다. main·app_state 의존 없음(라우터가 자유롭게 재사용
가능) — HTTP 쪽(`_auth_guard`)과 동일한 시크릿(VIGENT_API_TOKEN)·동일 상수시간 비교 규칙을 재사용한다.

[S3-후속1] 브라우저 JS의 `new WebSocket(...)`는 커스텀 헤더를 못 실으므로, 로그인 페이지에서
발급한 세션 쿠키(auth_session.SESSION_COOKIE)도 인증 수단으로 인정한다 — 같은 오리진 WS
핸드셰이크는 일반 HTTP 요청처럼 Cookie 헤더를 자동으로 실어 보내므로 프론트 JS 수정 없이
동작한다.

[1단계 H-5, 2026-10-10] Origin·Host 검사 추가 — 웹소켓은 브라우저의 동일 출처 정책(CORS)을
받지 않아서, 관리자가 악성 웹페이지를 하나 열면 그 페이지가 `new WebSocket("ws://127.0.0.1:8010/
tapo/ws")` 로 몰래 접속해 카메라 영상을 외부로 중계할 수 있었다(Cross-Site WebSocket Hijacking).
main._auth_guard 의 Host 허용목록(DNS rebinding 방어)도 HTTP scope 전용이라 WS 에는 없었다.
→ HTTP 쪽과 같은 허용목록 기준으로 ① Host 헤더 ② (있을 때만) Origin 헤더를 검사한다.
  · 브라우저가 아닌 클라이언트(curl 등)는 Origin 을 안 보냄 → Host 만 검사(기존 도구 호환).
  · 세션 쿠키는 SameSite=Lax 라 WS 핸드셰이크를 막지 못하므로, 토큰 모드에서도 Origin 검사가
    교차 사이트의 쿠키 편승을 막는 유일한 방어다.
  · 예외가 필요하면(파일럿 특수 구성 등) VIGENT_WS_ALLOW_ORIGINS=호스트1,호스트2 로 추가 허용.
"""
from __future__ import annotations

import hmac
import os
from urllib.parse import urlparse

import auth_session
from fastapi import WebSocket


def _host_only(raw: str) -> str:
    """Host 헤더에서 포트 제거(IPv6 '[::1]:8010' 포함) — main._host_only 와 동일 규칙."""
    h = (raw or "").strip().lower()
    if h.startswith("["):                     # IPv6: [::1]:port → [::1]
        return h[:h.index("]") + 1] if "]" in h else h
    return h.split(":")[0]


def _host_allowlist() -> set[str] | None:
    """main._host_allowlist 와 동일 규칙(모듈 무의존 설계라 여기서 다시 계산).
    명시 지정(VIGENT_ALLOWED_HOSTS) > 로컬 바인딩 기본 목록 > 외부 바인딩은 None(토큰이 방어)."""
    explicit = [h.strip().lower() for h in os.environ.get("VIGENT_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if explicit:
        return set(explicit)
    bind = os.environ.get("VIGENT_HOST", "127.0.0.1").strip()
    if bind in ("127.0.0.1", "localhost", "::1", ""):
        return {"127.0.0.1", "localhost", "::1", "[::1]", "testserver"}
    return None


def _extra_ws_origins() -> set[str]:
    return {h.strip().lower() for h in os.environ.get("VIGENT_WS_ALLOW_ORIGINS", "").split(",") if h.strip()}


def _handshake_source_ok(ws: WebSocket) -> bool:
    """① Host 가 허용목록에 있고 ② Origin(있으면)의 호스트도 허용돼야 True."""
    allowed = _host_allowlist()
    host = _host_only(ws.headers.get("host", ""))
    if allowed is not None and host and host not in allowed:
        return False                           # DNS rebinding — HTTP 쪽과 동일 차단
    origin = (ws.headers.get("origin", "") or "").strip().lower()
    if not origin:
        return True                            # 브라우저가 아님(curl 등) — Host 검사로 충분
    ohost = (urlparse(origin).hostname or "").lower()
    bracketed = f"[{ohost}]" if ohost and ":" in ohost else ohost   # IPv6 표기 통일
    if ohost in _extra_ws_origins() or origin in _extra_ws_origins():
        return True
    if allowed is not None:
        return bool(ohost) and (ohost in allowed or bracketed in allowed)
    # 외부 바인딩 + 허용목록 미지정: 같은 호스트에서 온 페이지(동일 출처)만 허용
    return bool(ohost) and (ohost == host or bracketed == host)


def ws_token_ok(ws: WebSocket) -> bool:
    """main._auth_guard 와 동일한 규칙으로 WS 핸드셰이크를 인증한다.

    [H-5] 토큰 이전에 출처부터 — Host·Origin 이 허용목록 밖이면 토큰이 맞아도 거부한다
    (교차 사이트 페이지가 관리자의 세션 쿠키에 편승하는 것을 차단).
    VIGENT_API_TOKEN 미설정 시 출처 검사만 적용(로컬 개발 무인증 유지 — HTTP 쪽과 동일 정책).
    설정 시 아래 중 하나가 유효해야 True: 쿼리 `?token=<토큰>` · `Authorization: Bearer <토큰>`
    헤더(상수시간 비교) · 로그인으로 발급된 세션 쿠키.
    """
    if not _handshake_source_ok(ws):
        return False
    token = os.environ.get("VIGENT_API_TOKEN", "").strip()
    if not token:
        return True
    q = ws.query_params.get("token", "")
    if q and hmac.compare_digest(q, token):
        return True
    auth = ws.headers.get("authorization", "")
    if hmac.compare_digest(auth, f"Bearer {token}"):
        return True
    return auth_session.validate_session(ws.cookies.get(auth_session.SESSION_COOKIE))
