"""routers/detect.py — 프레임 단위 추론 엔드포인트 (P1-7 분할). main 미import.

/detect/frame·/rfdetr/frame·/rfdetr/vlm·/segment/frame — 저수준 프레임 검출/세그/VLM.
PPE·incident 전용 프레임 분석은 각 도메인 라우터에 있다.
"""
import logging

from app_state import DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException
from web_util import decode_data_url, is_safety_label

router = APIRouter()
_log = logging.getLogger("vigent.detect")
_LAST_WH: dict[str, tuple[int, int]] = {}   # 3.6: track_key 별 직전 프레임 크기(다중출처 공유 감지)
_WH_FLIP: dict[str, int] = {}               # 3.6: 해상도 교대 횟수(경고 임계용)

# 다인 포즈(2.4): yolov8n-pose(bottom-up) 1회 로드 캐시. CPU 고정(ultralytics MPS 다모델 크래시 이력).
_POSE_MODEL = None
_POSE_LOAD_ERR: str | None = None
_POSE_TICK: dict[str, int] = {}   # 2.5 ①: track_key 별 요청 카운터(인터리브)
_PRESS_STREAK: dict[str, dict[int, int]] = {}   # 2.6: track_key → {person id: 연속 위반 프레임}
_PRESS_LAST: dict[str, list] = {}               # 2.6: 스킵 프레임에 직전 press 상태 유지


def _multi_pose(img, imgsz: int) -> list[dict]:
    """다인 포즈 추정 → [{keypoints:[[x,y]×17], keypoint_confidence:[×17]}]. 좌표는 입력(전송) 이미지 픽셀
    (프론트 realtime_core.js 의 poses 소비 형식과 일치). 보조 기능이라 실패해도 [] 반환(검출 무중단)."""
    global _POSE_MODEL, _POSE_LOAD_ERR
    if _POSE_MODEL is None:
        if _POSE_LOAD_ERR:
            return []
        try:
            from pathlib import Path

            from ultralytics import YOLO
            _POSE_MODEL = YOLO(str(Path(__file__).resolve().parent.parent / "weights" / "yolov8n-pose.pt"))
        except Exception as ex:  # noqa: BLE001
            _POSE_LOAD_ERR = f"{type(ex).__name__}: {ex}"
            return []
    try:
        res = _POSE_MODEL.predict(img, verbose=False, device="cpu", imgsz=imgsz)[0]
        kp = getattr(res, "keypoints", None)
        if kp is None or kp.xy is None:
            return []
        xy = kp.xy.cpu().numpy()
        cf = kp.conf.cpu().numpy() if kp.conf is not None else None
        poses: list[dict] = []
        for i in range(len(xy)):
            poses.append({
                "keypoints": [[round(float(x), 1), round(float(y), 1)] for x, y in xy[i]],
                "keypoint_confidence": [round(float(c), 3) for c in (cf[i] if cf is not None else [])],
            })
        return poses
    except Exception:  # noqa: BLE001  보조 기능 — 실패해도 검출 유지
        return []


def _pose_bbox(keypoints: list, conf: list) -> list | None:
    """유효(conf≥0.3) 키포인트들의 bounding box [x,y,w,h] (전송 이미지 픽셀)."""
    xs, ys = [], []
    for i, kp in enumerate(keypoints):
        if i < len(conf) and conf[i] < 0.3:
            continue
        xs.append(kp[0]); ys.append(kp[1])
    if not xs:
        return None
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def _assign_pose_ids(poses: list[dict], person_dets: list[dict]) -> None:
    """각 pose 에 person 트랙 id 부여(2.4b ①) — 키포인트 bbox ↔ person 박스 IoU 매칭(미매칭 -1).
    박스·스켈레톤·색상이 같은 id 로 묶여 클라 매칭이 자명해진다. person_dets 는 [x,y,w,h] 픽셀."""
    persons = [(d.get("id", -1), d["bbox"]) for d in person_dets
               if str(d.get("class") or "").lower() == "person"]
    for p in poses:
        pb = _pose_bbox(p.get("keypoints", []), p.get("keypoint_confidence") or [])
        bid, best = -1, 0.1
        if pb:
            for pid, box in persons:
                ix = max(0.0, min(pb[0] + pb[2], box[0] + box[2]) - max(pb[0], box[0]))
                iy = max(0.0, min(pb[1] + pb[3], box[1] + box[3]) - max(pb[1], box[1]))
                inter = ix * iy
                ua = pb[2] * pb[3] + box[2] * box[3] - inter
                v = inter / ua if ua > 0 else 0.0
                if v > best:
                    best, bid = v, pid
        p["id"] = bid


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
    track_key = str(payload.get("track_key") or "browser")   # 5단계: 요청별 추적 격리(기본 browser)
    # 재발 방지(3.6): 같은 track_key 로 크게 다른 해상도 프레임이 번갈아 들어오면 서로 다른 출처가
    #   한 추적 풀을 공유하는 신호(유령박스 원인) → 경고. 신규 호출부는 반드시 고유 track_key 지정.
    _h, _w = img.shape[:2]
    _prev = _LAST_WH.get(track_key)
    if _prev and (abs(_prev[0] - _w) > 8 or abs(_prev[1] - _h) > 8):
        _WH_FLIP[track_key] = _WH_FLIP.get(track_key, 0) + 1
        if _WH_FLIP[track_key] in (3, 30):
            _log.warning("track_key '%s' 에 다른 해상도 프레임 교대(%dx%d↔%dx%d) — 다중 출처 공유 의심."
                         " 신규 /detect/frame 호출부는 고유 track_key 지정 필요.",
                         track_key, _prev[1], _prev[0], _w, _h)
    _LAST_WH[track_key] = (_w, _h)
    with _DETECT_LOCK:                       # 동시 추론 직렬화(로딩/추론 race 방지)
        if payload.get("reset_tracks"):
            guard._tracks_by_key[track_key] = []   # 그 키만 비움(락 내부라 원자적)
        out = guard.detect(img, detectors=detectors, conf=payload.get("conf"),
                           imgsz=live_imgsz, track_key=track_key)
        # 다인 포즈(2.4): pose=true 요청 시에만. 락 내부 실행(guard 와 직렬화). CPU 라 MPS 무영향.
        # 2.5 ① 인터리브: N요청당 1회만 추론(기본 3). 스킵 요청은 [] → 프론트가 직전 poses 유지 +
        #   One-Euro·외삽(2.4b)으로 사이를 메워 ~3Hz ingest 로도 부드러움 유지. N=1 이면 매 프레임(현행).
        poses = []
        if payload.get("pose"):
            import tuning as _tun
            _n = max(1, int(_tun.val("detect", "pose_interleave", 3)))
            _c = _POSE_TICK.get(track_key, 0)
            _POSE_TICK[track_key] = _c + 1
            if _c % _n == 0:
                poses = _multi_pose(img, live_imgsz)
    # 정규화 bbox(0~1) → 전송 이미지 픽셀 [x,y,w,h] + 프론트 키(class/score)로 변환
    H, W = img.shape[:2]
    dets = []
    for d in out.get("detections", []):
        x1, y1, x2, y2 = d.get("bbox", [0, 0, 0, 0])
        dets.append({"class": d.get("label"), "score": d.get("conf"),
                     "id": d.get("tid", -1),   # 안정 트랙 id(클라 id 매칭용 · 1.8b). 미부여=-1
                     "bbox": [round(x1 * W, 1), round(y1 * H, 1),
                              round((x2 - x1) * W, 1), round((y2 - y1) * H, 1)]})
    # 포즈에 person 트랙 id 부여(2.4b ①) — safety_only 필터 전(사람 박스 온전할 때) 매칭.
    if poses:
        _assign_pose_ids(poses, dets)
    # 프레스 방호구역 부위별 침입(2.6) — press=true 요청 시. 보조·예방 신호만(1차 방호는 인증 HW 책임).
    #   히스테리시스: 사람 id 별 연속 confirm_frames(기본 2) 위반 시 확정. 포즈 없는(인터리브 스킵) 프레임은 직전 상태 유지.
    press: list = []
    if payload.get("press"):
        import press_zone
        import tuning as _tun
        from web_util import zone_get
        if poses:
            polys = [press_zone.zone_points_to_poly((zone_get(theme, "machine_hazard_zones") or {}).get("points", []))]
            cframes = max(1, int(_tun.val("press", "confirm_frames", 2)))
            kpc = float(_tun.val("press", "kp_conf", 0.5))
            viol = {v["id"]: v["parts"] for v in press_zone.evaluate(poses, polys, W, H, kpc)}
            streak = _PRESS_STREAK.setdefault(track_key, {})
            confirmed, seen = [], set()
            for _p in poses:
                pid = _p.get("id", -1)
                seen.add(pid)
                if pid in viol:
                    streak[pid] = streak.get(pid, 0) + 1
                    if streak[pid] >= cframes:
                        confirmed.append({"id": pid, "parts": viol[pid]})
                else:
                    streak[pid] = 0
            for _k in [k for k in streak if k not in seen]:
                del streak[_k]
            _PRESS_LAST[track_key] = confirmed
            press = confirmed
        else:
            press = _PRESS_LAST.get(track_key, [])
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
            "proximity": prox, "poses": poses, "press": press}

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
