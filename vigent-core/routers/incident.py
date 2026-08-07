"""routers/incident.py — 재해분석(사고 프레임 분석) (P1-7 분할). main 미import.

/safety/incident(페이지)·/frame(박스·협착 판정)·/analyze(VLM 서술).
"""
from app_state import DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body
from fastapi.responses import HTMLResponse
from isolated_detect import detect_isolated
from web_util import img_from_b64, incident_boxes

router = APIRouter()


@router.get("/safety/incident", response_class=HTMLResponse)
def safety_incident_page():
    """재해 원인분석(보조) — 사고 사진/영상 → 상황·빠진 조치·법령·유사재해·예방."""
    import incident
    return incident.render()

@router.post("/safety/incident/frame")
def safety_incident_frame(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """한 프레임의 위험도 채점(빠름, VLM 없음) — 영상 타임라인 분석용.
    반환: {score, person_count, hazards:[유형], detections:[클래스]}."""
    import proximity as _prox
    raw = payload.get("image_base64") or payload.get("image") or ""
    img = img_from_b64(raw)
    if img is None:
        return {"score": 0, "hazards": []}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    try:
        with _DETECT_LOCK:
            # forklift 제외(F-7) — 유령 지게차가 타임라인·협착 점수 오염. 측정은 payload.detectors 명시로 가능.
            # 2026-08: 서로 무관한 사진이 매 요청 들어올 수 있어(track_key 미지정 시 "default" 공유) 격리
            #   검출로 전환(detect_isolated) — 이전 요청의 박스가 이어붙는 버그 재발 방지.
            out = detect_isolated(guard, img, detectors=payload.get("detectors") or ["person", "ppe", "fire_smoke"])
    except Exception:  # noqa: BLE001
        return {"score": 0, "hazards": []}
    sig = out.get("signals", {}) or {}
    pc = out.get("person_count", 0)
    prox = _prox.detect(out.get("detections", []), aspect_hw=img.shape[0] / img.shape[1])  # 감사 E-1
    hz = []
    score = pc * 5
    if prox:
        score += 55
        hz.append("작업반경 침입(협착)")
    if sig.get("fire_smoke"):
        score += 45
        hz.append("화재·연기")
    if sig.get("ppe_missing"):
        score += 25
        hz.append("보호구 미착용")
    return {"score": score, "person_count": pc, "hazards": hz,
            "detections": [d.get("label") for d in out.get("detections", [])],
            "boxes": incident_boxes(out, prox)}

@router.post("/safety/incident/analyze")
def safety_incident_analyze(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """재해 영상/사진 원인분석 — 탐지 + VLM + 지식. 책임 비율 판정은 하지 않음."""
    import incident
    raw = payload.get("image_base64") or payload.get("image")
    if not raw:
        return {"ok": False, "error": "이미지 없음"}
    img = img_from_b64(raw)
    if img is None:
        return {"ok": False, "error": "이미지 디코딩 실패"}
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    present = []
    try:
        with _DETECT_LOCK:
            # 재해원인분석은 실시간이 아님 → 고해상도(1280)로 인식 정확도↑(느려도 됨).
            # ⚠ TTA(augment)는 약한 커스텀 모델(지게차·PPE)의 오탐을 증폭시켜 제거함(2026-07). 고해상도만 유지.
            # forklift 제외(F-7): 정탐 conf p50 0.002 ≈ 오탐 → 강재를 지게차로 오탐(협착 오염). 측정은
            #   payload.detectors 명시 지정 시 여전히 가능(payload 는 dict). T10b full 재학습 후 복원.
            # 2026-08: 격리 검출로 전환(detect_isolated) — 이유는 위 /frame 과 동일.
            out = detect_isolated(guard, img, detectors=payload.get("detectors") or ["person", "ppe", "fire_smoke"],
                                   imgsz=1280, augment=False)
        present = [d.get("label") for d in out.get("detections", [])]
    except Exception:  # noqa: BLE001
        out, present = {"detections": []}, []
    result = incident.analyze(img, present_classes=present, use_vlm=bool(payload.get("use_vlm")))
    import proximity as _prox
    result["boxes"] = incident_boxes(out, _prox.detect(
        out.get("detections", []), aspect_hw=img.shape[0] / img.shape[1]))   # 감사 E-1
    return result
