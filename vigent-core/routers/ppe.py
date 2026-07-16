"""routers/ppe.py — 보호구(PPE) 착용 점검 (P1-7 분할). main 미import.

/safety/ppe(페이지)·/live·/catalog·/rules(조회·저장)·/check(판정), /ppe/analyze-frame(스텁).
판정 로직은 ppe_check 모듈(함수 내부 로컬 import)에 있다.
"""
from app_state import DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse
from web_util import _img_from_b64

router = APIRouter()


@router.get("/safety/ppe", response_class=HTMLResponse)
def safety_ppe_page():
    """현장 보호구 설정 — 현장별 필수 보호구 선택."""
    import ppe_check
    return ppe_check.render()

@router.get("/safety/ppe/live", response_class=HTMLResponse)
def safety_ppe_live_page():
    """실시간 보호구 감지 — 카메라 + 주기 점검(VLM)."""
    import ppe_check
    return ppe_check.render_live()

@router.get("/safety/ppe/catalog")
def safety_ppe_catalog():
    """보호구 카탈로그(id·라벨·방식) — 메인 화면 메뉴에서 선택용."""
    import ppe_check
    return {"catalog": [{"id": p["id"], "label": p["label"], "method": p["method"]}
                        for p in ppe_check.PPE_CATALOG],
            "rules": ppe_check.get_rules()}

@router.get("/safety/ppe/rules")
def safety_ppe_rules_get():
    import ppe_check
    return ppe_check.get_rules()

@router.post("/safety/ppe/rules")
def safety_ppe_rules_set(payload: dict = Body(...)):
    import ppe_check
    return ppe_check.save_rules(payload.get("required") or [], payload.get("site", ""))

@router.post("/safety/ppe/check")
def safety_ppe_check(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """이미지 → 현장 필수 보호구 착용 점검(미착용 경고). use_vlm 권장."""
    import ppe_check
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = _img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 없음"}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    try:
        with _DETECT_LOCK:
            out = guard.detect(img, detectors=["person", "ppe"])
        dets = out.get("detections", [])
    except Exception:  # noqa: BLE001
        dets = []
    return ppe_check.check(dets, image_bgr=img, required=payload.get("required"),
                           use_vlm=bool(payload.get("use_vlm", True)))

@router.post("/ppe/analyze-frame")
def stub_ppe_analyze(payload: dict = Body(default={})):
    return {"ok": True, "ppe": [], "note": "stub"}
