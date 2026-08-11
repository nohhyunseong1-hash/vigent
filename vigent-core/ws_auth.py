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
"""
from __future__ import annotations

import hmac
import os

import auth_session
from fastapi import WebSocket


def ws_token_ok(ws: WebSocket) -> bool:
    """main._auth_guard 와 동일한 규칙으로 WS 핸드셰이크를 인증한다.

    VIGENT_API_TOKEN 미설정 시 True(로컬 개발 무인증 유지 — HTTP 쪽과 동일 정책, 기존 동작 불변).
    설정 시 아래 중 하나가 유효해야 True: 쿼리 `?token=<토큰>` · `Authorization: Bearer <토큰>`
    헤더(상수시간 비교) · 로그인으로 발급된 세션 쿠키.
    """
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
