"""routers/zone.py — 위험구역 폴리곤 조회/저장 + 침입 알림 (P1-7 분할).

main 미import(순환 방지). 공유상태=app_state, 공유헬퍼=web_util.
"""
import data_engine
from app_state import DEFAULT_THEME, STATE
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException  # noqa: F401  (일부 라우트에서 사용)
from web_util import decode_data_url, zone_get, zone_set

router = APIRouter()


@router.get("/zone/danger")
def zone_danger(theme: str = DEFAULT_THEME):
    """일반 위험구역 폴리곤(정규화 좌표) 반환."""
    return zone_get(theme, "danger_zones")

@router.post("/zone/danger")
def set_zone_danger(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """일반 위험구역 폴리곤 저장. payload={"points":[{"x":..,"y":..}, ...]}"""
    return zone_set(theme, "danger_zones", payload)

@router.get("/zone/machine")
def zone_machine(theme: str = DEFAULT_THEME):
    """프레스/전단기 방호구역 폴리곤(정규화 좌표) 반환(§8)."""
    return zone_get(theme, "machine_hazard_zones")

@router.post("/zone/machine")
def set_zone_machine(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """프레스/전단기 방호구역 폴리곤 저장(손 진입 시 guard_bypass=critical)."""
    return zone_set(theme, "machine_hazard_zones", payload)

@router.get("/zone/state")
@router.post("/zone/state")
def stub_zone_state(payload: dict = Body(default={})):
    return {"ok": True, "zones": [], "state": "idle"}

@router.post("/zone/intrusion")
def zone_intrusion_alert(payload: dict = Body(default={}), theme: str = DEFAULT_THEME):
    """위험구역 침입(몸통/머리/다리 등 '위험') → 휴대폰 알림(텔레그램/웹훅) + 증거 저장.
    프론트(AX 엔진)는 손/팔만이면 호출하지 않고, '위험' 부위 진입 시에만 호출한다."""
    bundle = STATE.get(theme) or _load_theme(theme)
    dispatcher = bundle["agents"].get("Dispatcher")
    reasons = payload.get("reasons") or ["위험구역 접근"]
    people = payload.get("people", 0)
    zone_name = payload.get("zone", "위험구역")
    msg = f"[{zone_name}] 위험구역 침입 — {', '.join(reasons)} · 구역 내 {people}명"

    # 증거 저장 + 인식로그 기록(데이터엔진) → 자동처리 콘솔에 노출. decoded 는 VLM 확정에 재사용.
    img = payload.get("image_base64")
    img_url = (img if (img or "").startswith("data:") else "data:image/jpeg;base64," + img) if img else None
    decoded = decode_data_url(img_url) if img_url else None
    rec = data_engine.log_event(rule="zone_intrusion", level="high",
                                site=zone_name, note=", ".join(reasons), image_data_url=img_url)
    saved = rec.get("evidence")

    # CNN→VLM 하이브리드 확정(opt-in: vlm_confirm). 고신뢰 오탐만 푸시 억제(증거·기록은 유지).
    vlm_conf, suppressed = None, False
    if payload.get("vlm_confirm"):
        import vlm_confirm as _vc
        vlm_conf = _vc.confirm(decoded, "zone_intrusion", reason=", ".join(reasons))
        if vlm_conf.get("available"):
            msg += f" · VLM 위험확률 {vlm_conf['risk']}% → {vlm_conf['verdict']}: {vlm_conf['reason']}"
        suppressed = bool(vlm_conf.get("suppress"))

    # ★[CODE_REVIEW M3-3, 2026-09-06] 예전엔 dispatcher.dispatch("high") 직접 호출 — 브라우저 8s 쿨다운 외에 서버 측
    #   억제가 없어 탭 수·재접속마다 통보가 곱해졌다. 이제 alert_notify.submit(출처 키 browser_zone:<cam>) 로
    #   통보 게이트(쿨다운·백오프·시간당 상한)를 탄다. 기록·증거·VLM 억제는 그대로.
    #   응답 phone_sent 는 "통보 큐 적재 여부"(실제 발송은 비동기) — fallback 은 미적재.
    queued, gate = False, "suppressed_by_vlm" if suppressed else "no_dispatcher"
    if not suppressed and dispatcher:
        import alert_notify
        n = alert_notify.submit(cam=f"browser_zone:{payload.get('cam') or zone_name}", rule="zone_intrusion",
                                level="high", message=msg, meta={"evidence": saved, "people": people})
        queued, gate = bool(n.get("queued")), str(n.get("reason"))
    return {"ok": True, "message": msg, "vlm_confirm": vlm_conf, "suppressed": suppressed,
            "phone_sent": queued,                              # 통보 큐 적재 여부(비동기 발송)
            "fallback": not queued,                            # 미적재(억제·미배선)
            "gate": gate,
            "evidence": saved}
