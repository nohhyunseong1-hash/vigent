"""routers/dispatch.py — 보조 방호신호 릴레이 (P1-7 분할). main 미import.

/dispatch/relay — guard_bypass(critical) 시 프론트가 호출하는 보조 방호신호.
⚠ 비전은 보조·감시 계층이며 인증 하드웨어의 1차 비상정지를 대체하지 않는다.
"""
import vlog
from app_state import DEFAULT_THEME, STATE
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException
from web_util import _env_or_dotenv, _webhook_allowed

router = APIRouter()


@router.post("/dispatch/relay")
def dispatch_relay(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """§8 보조 방호신호. guard_bypass(critical) 발생 시 프론트가 호출.
    ⚠ 비전은 보조·감시 계층이며 1차 비상정지를 대체하지 않는다."""
    # 웹훅 목적지 화이트리스트(C-S0): WEBHOOK_URL 이 설정돼 있고 미등재 호스트면 거부.
    #   (미설정=텔레그램만/무전송 → 통과. 안전경보 경로를 정상설정에서 막지 않음.)
    _wh = _env_or_dotenv("WEBHOOK_URL")
    if _wh and not _webhook_allowed(_wh):
        raise HTTPException(status_code=403,
                            detail="dispatch 웹훅 목적지 미허용 — config/security.json allowed_webhook_hosts 에 호스트 등록 필요")
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    _event = payload.get("event", "guard_bypass")
    result = dispatcher.relay(_event, payload.get("meta"))
    import datetime as _dt  # 구조화 이벤트 로그(C-S1, D3 감사추적)
    vlog.log_event({"ts": _dt.datetime.now().isoformat(timespec="seconds"),
                    "type": "dispatch_relay", "event": _event, "theme": theme, "result": result})
    return result
