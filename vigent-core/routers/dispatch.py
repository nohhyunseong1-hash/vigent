"""routers/dispatch.py — 보조 방호신호 릴레이 (P1-7 분할). main 미import.

/dispatch/relay — 보조 방호신호 **수동 시험용** 경로.
★[CODE_REVIEW M8-9, 2026-09-06 정정] 예전 문서의 "guard_bypass(critical) 시 프론트가 호출" 은 사실이 아니었다 — 프론트·허브·서버
  어디에도 호출부가 없다(실측 0). 실제 §8 보조 방호신호는 워커가 guard_bypass 를 발화하면 `alert_notify.submit(critical)` →
  `dispatcher.dispatch` → `on_severity.critical` 기본 액션 `safety_relay_signal` → `relay.turn_on`(relay.enabled 일 때) 경로로
  **자동** 실행된다(notify.yaml 에 on_severity 가 없으면 기본값). 이 라우트는 현장 시험(릴레이 배선 확인)에서 사람이 부른다.
⚠ 비전은 보조·감시 계층이며 인증 하드웨어의 1차 비상정지를 대체하지 않는다.
"""
import vlog
from app_state import DEFAULT_THEME, STATE
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException
from web_util import env_or_dotenv, webhook_allowed

router = APIRouter()


@router.post("/dispatch/relay")
def dispatch_relay(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """§8 보조 방호신호 — 수동 시험용(호출부 0, [M8-9]). 자동 경로는 워커 guard_bypass → dispatch(critical) 의 safety_relay_signal.
    ⚠ 비전은 보조·감시 계층이며 1차 비상정지를 대체하지 않는다."""
    # 웹훅 목적지 화이트리스트(C-S0): WEBHOOK_URL 이 설정돼 있고 미등재 호스트면 거부.
    #   (미설정=텔레그램만/무전송 → 통과. 안전경보 경로를 정상설정에서 막지 않음.)
    _wh = env_or_dotenv("WEBHOOK_URL")
    if _wh and not webhook_allowed(_wh):
        raise HTTPException(status_code=403,
                            detail="dispatch 웹훅 목적지 미허용 — config/security.json allowed_webhook_hosts 에 호스트 등록 필요")
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    _event = payload.get("event", "guard_bypass")
    # ★[CODE_REVIEW M3-3, 2026-09-06] 예전엔 dispatcher.relay() → dispatch("critical") 직접 호출(게이트 우회).
    #   이제 alert_notify.submit(출처 키 manual) 로 통보 게이트를 탄다 — critical 등급 상승 예외는 게이트가 유지.
    #   응답 형태는 relay() 와 호환(relay·event·is_primary_safety·boundary), delivered 는 "큐 적재" 의미.
    import alert_notify
    import tuning
    text = str(tuning.val("alerts", "guard_bypass_text", "위험기계 방호구역 신체 진입 감지")).strip()
    n = alert_notify.submit(cam="manual", rule=str(_event), level="critical",
                            message=f"{_event}: {text}", meta=payload.get("meta") or {})
    result = {"relay": "auxiliary_signal", "event": _event, "is_primary_safety": False,
              "boundary": "§8.1 — 비전은 보조·감시 계층. 1차 정지는 인증 하드웨어 책임.",
              "delivered": bool(n.get("queued")), "queued": bool(n.get("queued")), "gate": n.get("reason"),
              "dispatcher": dispatcher is not None}
    import datetime as _dt  # 구조화 이벤트 로그(C-S1, D3 감사추적)
    vlog.log_event({"ts": _dt.datetime.now().isoformat(timespec="seconds"),
                    "type": "dispatch_relay", "event": _event, "theme": theme, "result": result})
    return result
