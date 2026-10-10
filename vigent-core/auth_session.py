"""auth_session.py — 브라우저 세션 인증(로그인 폼 + 쿠키 세션 + 실패 횟수 제한).

[S3 엣지박스 리허설]에서 발견: VIGENT_REQUIRE_TOKEN=1 모드는 전 라우트에 Bearer 헤더를
요구하는데, 브라우저의 평범한 페이지 이동(주소창 입력·링크 클릭)은 헤더를 실을 방법이
없어 대시보드 자체가 401로 막혔다. API/스크립트 클라이언트는 기존 Authorization: Bearer
그대로 쓰고, 브라우저는 이 모듈이 제공하는 /login 폼으로 세션 쿠키를 발급받아 쓴다.

단일 운영자 전제([[B12]] RBAC는 백로그) — 세션은 프로세스 메모리에만 보관한다. 서버
재기동 시 전부 무효화되어 재로그인이 필요하지만, 엣지박스 1대·운영자 1인 환경에서는
허용 가능한 트레이드오프로 판단(다중 사용자 시점엔 B12 RBAC 재검토 조건에 포함).
main.py 의 _auth_guard·ws_auth.ws_token_ok 양쪽에서 재사용하므로 이 모듈은 main·
app_state·라우터 어느 쪽도 import 하지 않는다(P1-7 순환 금지 규칙과 동일한 이유).
"""
from __future__ import annotations

import hmac
import secrets
import time

import tuning

SESSION_COOKIE = "vigent_session"

SESSION_TTL_S = tuning.val("auth", "session_ttl_hours", 12) * 3600
_LOCKOUT_THRESHOLD = tuning.val("auth", "lockout_threshold", 5)
_LOCKOUT_WINDOW_S = tuning.val("auth", "lockout_window_min", 15) * 60
_LOCKOUT_DURATION_S = tuning.val("auth", "lockout_duration_min", 15) * 60

_sessions: dict[str, float] = {}          # session_id -> 만료 시각(epoch)
_failures: dict[str, list[float]] = {}    # ip -> 최근 실패 시각 목록(창 내)
_locked_until: dict[str, float] = {}      # ip -> 잠금 해제 시각(epoch)


def create_session() -> str:
    # [1단계 L-3] 만료 세션은 로그인 시점에 청소 — 예전엔 validate 로 읽힌 것만 지워서,
    #   반복 로그인 환경에서 _sessions 가 무한히 자랄 수 있었다(메모리 누수).
    now = time.time()
    for k in [k for k, exp in _sessions.items() if now > exp]:
        _sessions.pop(k, None)
    sid = secrets.token_urlsafe(32)
    _sessions[sid] = now + SESSION_TTL_S
    return sid


def validate_session(sid: str | None) -> bool:
    if not sid:
        return False
    exp = _sessions.get(sid)
    if exp is None:
        return False
    if time.time() > exp:
        _sessions.pop(sid, None)
        return False
    return True


def revoke_session(sid: str | None) -> None:
    if sid:
        _sessions.pop(sid, None)


def is_locked(ip: str) -> bool:
    until = _locked_until.get(ip)
    if until is None:
        return False
    if time.time() > until:
        _locked_until.pop(ip, None)
        _failures.pop(ip, None)
        return False
    return True


def record_failure(ip: str) -> None:
    now = time.time()
    hist = [t for t in _failures.get(ip, []) if now - t < _LOCKOUT_WINDOW_S]
    hist.append(now)
    _failures[ip] = hist
    if len(hist) >= _LOCKOUT_THRESHOLD:
        _locked_until[ip] = now + _LOCKOUT_DURATION_S


def clear_failures(ip: str) -> None:
    _failures.pop(ip, None)
    _locked_until.pop(ip, None)


def check_token(token: str, expected: str) -> bool:
    # [1단계 L-3] 비ASCII 입력(한글 오타 등)이 오면 compare_digest 가 TypeError 를 던져
    #   500 이 났다 — 인증 실패(False)로 조용히 처리한다(fail-closed, 우회 아님).
    try:
        return hmac.compare_digest(token, expected)
    except TypeError:
        return False
