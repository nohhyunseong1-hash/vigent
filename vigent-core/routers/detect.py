"""routers/detect.py — 프레임 단위 추론 엔드포인트 (P1-7 분할). main 미import.

/detect/frame·/rfdetr/frame·/rfdetr/vlm·/segment/frame — 저수준 프레임 검출/세그/VLM.
PPE·incident 전용 프레임 분석은 각 도메인 라우터에 있다.
"""
from app_state import DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException
from web_util import decode_data_url, is_safety_label

router = APIRouter()


@router.post("/detect/frame")
def detect_frame(payload: dict = Body(...), theme: str = DEFAULT_THEME):
    """Guard 딥러닝 정밀 탐지(브라우저 백엔드 보강).
    payload={image_base64(접두사 유무 무관) | image(data URL), ppe?:bool, conf?:float, detectors?:[...]}.
    반환(프론트 계약): {success, detections:[{class,score,bbox:[x,y,w,h]px}], hazards:[...], person_count, signals}.
    모델 없으면 해당 검출기만 비활성(무중단)."""
    bundle = STATE.get(theme) or _load_theme(theme)
    guard = bundle["agents"].get("Guard")
    # image_base64(접두사 없는 base64) 우선 + 기존 image(data URL) 호환. 접두사 없으면 보정.
    raw = payload.get("image_base64") or payload.get("image") or ""
    if raw and not raw.startswith("data:"):
        raw = "data:image/jpeg;base64," + raw
    img = decode_data_url(raw)
    if img is None:
        raise HTTPException(status_code=400, detail="이미지 디코딩 실패(image_base64/image 확인)")
    # 검출기 선택: 안전 모드(ppe=true)면 person+ppe+fire(보호구·화재), 아니면 person만.
    # ★device 정정(F-14, 2026-07-19): guard.detect 는 실제 **MPS**로 돈다(vision.yaml 전 슬롯
    #   backend:rfdetr → RfdetrDetector prefer_mps=True). 과거 "guard=CPU" 주석은 YOLO 시절 잔재로 오류.
    #   MPS 다모델 동시추론 크래시(F-14)는 CPU 강등이 아니라 아래 _DETECT_LOCK 로 guard·rfdetr·VLM
    #   3개 MPS 엔진을 직렬화해 차단한다(app_state.DETECT_LOCK, RLock). device 상세는 device.py 상단.
    # ★ forklift 잠정 비활성(F-7, 2026-07-11 실측): 과소학습으로 정탐/오탐 conf가 완전 겹쳐(정탐 p50 0.002,
    #   max 0.005 = 오탐과 동일) 임계로 분리 불가. 사람 몸통을 conf 0.002로 오인(웹캠 벤치 pos_bare 100%).
    #   → 라이브·safety-local 소비 경로에서 제외해 사람 오인 박스 차단. 임계 0.30 은폐형 off는 기각(명시적 비활성).
    #   측정/게이트 경로는 payload.detectors=["forklift",...] 명시 지정 시 추론 가능(T10b full 재학습 후 복원).
    detectors = payload.get("detectors")
    if detectors is None:
        detectors = ["person", "ppe", "fire_smoke"] if payload.get("ppe") else ["person"]
    # 라이브 반응성: 프론트가 이미 640px로 줄여 보내므로(realtime_core.js) 감지도 640으로 맞춘다.
    # 960으로 upscale하면 없는 디테일 만들려 2배 느려질 뿐(정확도 이득 없음) → 640이 거의 순수 이득.
    # (오프라인 재해분석은 별도로 imgsz=1280 유지). payload.imgsz 로 현장서 조정 가능.
    live_imgsz = int(payload.get("imgsz") or 640)
    # reset_tracks(단발·stateless): 그 요청만 서버측 추적 상태를 비우고 검출(F-8 측정용).
    #   추적(_track)은 라이브 연속프레임 안정화 계층 → 독립 이미지(벤치/단발 분석)에 누적되면
    #   IoU 우연매칭·잔상으로 검출을 오염(측정≠배포 착시). 라이브 프론트는 이 옵션 미전송 → 추적 유지·저하0.
    with _DETECT_LOCK:                       # 동시 추론 직렬화(로딩/추론 race 방지)
        if payload.get("reset_tracks"):
            guard._tracks = []               # 락 내부라 라이브 요청과 경쟁 없이 원자적
        out = guard.detect(img, detectors=detectors, conf=payload.get("conf"), imgsz=live_imgsz)
    # 정규화 bbox(0~1) → 전송 이미지 픽셀 [x,y,w,h] + 프론트 키(class/score)로 변환
    H, W = img.shape[:2]
    dets = []
    for d in out.get("detections", []):
        x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])
        dets.append({"class": d.get("label"), "score": d.get("conf"),
                     "id": d.get("tid", -1),   # 안정 트랙 id(클라 id 매칭용 · 1.8b). 미부여=-1
                     "bbox": [round(x1 * W, 1), round(y1 * H, 1),
                              round((x2 - x1) * W, 1), round((y2 - y1) * H, 1)]})
    # 안전 전용: 잡동사니(노트북·TV·의자 등) 서버단에서 제거 → 사람·위험물·차량·화재·보호구만
    if payload.get("safety_only"):
        dets = [d for d in dets if is_safety_label(d.get("class"))]
    hazards = [{"type": d.get("label", "").lower(), "label": d.get("label"),
                "confidence": d.get("conf", 0),
                "severity": "high" if d.get("conf", 0) >= 0.5 else "mid"}
               for d in out.get("detections", []) if d.get("label", "").lower() in ("fire", "smoke")]
    # 동적 작업반경(협착) — 지게차·차량 근처 사람 진입(거리 자동추정)
    import proximity as _prox
    import tuning as _tun
    radius_m = float(payload.get("radius_m") or _tun.val("proximity", "radius_m", 3.0, env="VIGENT_RADIUS_M"))
    prox = _prox.detect(out.get("detections", []), radius_m, aspect_hw=H / W)   # 감사 E-1: 종횡비 보정
    return {"success": True, "detections": dets, "hazards": hazards,
            "person_count": out.get("person_count", 0), "signals": out.get("signals", {}),
            "proximity": prox}

@router.post("/rfdetr/frame")
def rfdetr_frame(payload: dict = Body(...)):
    """웹캠 프레임 → rf-detr 사람탐지 + 추적 + 위험구역 침입 판정(빠름)."""
    import rfdetr_service
    img = decode_data_url(payload.get("image", ""))
    if img is None:
        raise HTTPException(status_code=400, detail="image(data URL) 디코딩 실패")
    return rfdetr_service.rfdetr.detect(img)

@router.post("/rfdetr/vlm")
def rfdetr_vlm(payload: dict = Body(...)):
    """이벤트 프레임 → mlx-vlm 위험요약 JSON(느림, 프론트가 침입 시 드물게 호출)."""
    import rfdetr_service
    img = decode_data_url(payload.get("image", ""))
    if img is None:
        raise HTTPException(status_code=400, detail="image(data URL) 디코딩 실패")
    return rfdetr_service.vlm.summarize_bgr(img)

@router.post("/segment/frame")
def stub_segment(payload: dict = Body(default={})):
    return {"ok": True, "segments": [], "note": "stub"}
