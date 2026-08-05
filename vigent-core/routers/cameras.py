"""routers/cameras.py — 카메라 등록·관리 CRUD + 워커 연동(3.0 Phase 1).

자격증명은 camera_registry 가 secrets 로 분리·마스킹 → 응답엔 마스킹된 source 만 노출.
enable=워커 start(cam_id=track_key 격리), disable=stop. startup 자동복원은 autostart_enabled().
"""
import camera_registry as _reg
from app_state import DEFAULT_THEME, STATE
from app_state import DETECT_LOCK as _DETECT_LOCK
from app_state import load_theme as _load_theme
from fastapi import APIRouter, Body, HTTPException, Response

router = APIRouter()


def _worker(cid: str):
    import worker as _w
    return _w.manager._workers.get(cid)


def _guard():
    bundle = STATE.get(DEFAULT_THEME) or _load_theme(DEFAULT_THEME)
    return bundle["agents"].get("Guard")


def _start(cid: str):
    """레지스트리 원본 source 로 워커 시작(자격증명은 워커 내부만, 로그는 마스킹)."""
    import worker as _w
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    src = _reg.source_of(cid)
    if not src:
        raise HTTPException(status_code=400, detail="source 미등록")
    return _w.manager.start(_guard(), _DETECT_LOCK, cid, src,
                            name=c.get("name") or cid, fps=float(c.get("fps", 2.0)),
                            zone=c.get("zone"))


@router.get("/cameras")
def cameras_list():
    """등록 카메라 목록(마스킹) + 워커 라이브 상태 병합."""
    import worker as _w
    st = _w.manager.status().get("cameras", {})
    out = []
    for c in _reg.list_cameras():
        w = st.get(c["id"], {})
        out.append({**c, "online": bool(w.get("running")), "fps_live": w.get("fps"),
                    "reconnects": w.get("reconnects"), "last_frame_secs_ago": w.get("last_frame_secs_ago")})
    return {"cameras": out, "count": len(out)}


@router.post("/cameras")
def cameras_add(payload: dict = Body(...)):
    """등록/수정. payload={id, name?, source(rtsp/파일/웹캠번호), fps?, zone?, enabled?}. source 는 마스킹 저장."""
    cid = str(payload.get("id") or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="id 필요")
    c = _reg.upsert(cid, name=payload.get("name"), source=payload.get("source"),
                    fps=payload.get("fps"), zone=payload.get("zone"), enabled=payload.get("enabled"))
    worker = _start(cid) if c.get("enabled") else None
    return {"ok": True, "camera": c, "worker": worker}


@router.post("/cameras/{cid}/enable")
def cameras_enable(cid: str):
    if _reg.set_enabled(cid, True) is None:
        raise HTTPException(status_code=404, detail="없는 카메라")
    return {"ok": True, "worker": _start(cid)}


@router.post("/cameras/{cid}/disable")
def cameras_disable(cid: str):
    import worker as _w
    if _reg.set_enabled(cid, False) is None:
        raise HTTPException(status_code=404, detail="없는 카메라")
    return {"ok": True, "worker": _w.manager.stop(cid)}


@router.delete("/cameras/{cid}")
def cameras_delete(cid: str):
    import worker as _w
    _w.manager.stop(cid)
    return {"ok": _reg.delete(cid)}


@router.get("/cameras/{cid}/detections")
def cameras_detections(cid: str):
    """경량 오버레이용 — 워커 최신 검출(정규화 bbox)·인원·신호. 프론트가 화면크기로 복원."""
    wk = _worker(cid)
    if wk is None:
        return {"online": False, "detections": [], "person_count": 0, "signals": {}, "fired": []}
    return {"online": bool(wk.state.get("running")), "detections": wk._last_dets,
            "person_count": wk._last_pc, "signals": wk._last_sig, "fired": wk._last_fired}


@router.get("/cameras/{cid}/snapshot")
def cameras_snapshot(cid: str):
    """워커 최신 프레임 JPEG(파일소스 카드/미리보기 — WebRTC 미가용 시 폴링용)."""
    import cv2
    wk = _worker(cid)
    fr = getattr(wk, "_last_frame", None) if wk else None
    if fr is None:
        raise HTTPException(status_code=404, detail="프레임 없음(오프라인/워밍업)")
    ok, buf = cv2.imencode(".jpg", cv2.resize(fr, (640, 360)), [cv2.IMWRITE_JPEG_QUALITY, 70])
    return Response(content=buf.tobytes(), media_type="image/jpeg")


@router.post("/cameras/{cid}/test")
def cameras_test(cid: str):
    """연결 테스트 — source 에서 1프레임 잡기 성공 여부(+스냅샷 미리보기). 자격증명은 응답에 노출 안 함."""
    import base64

    import cv2
    src = _reg.source_of(cid)
    if not src:
        raise HTTPException(status_code=404, detail="source 미등록")
    cap = cv2.VideoCapture(int(src) if str(src).isdigit() else src)
    ok, fr = cap.read()
    cap.release()
    if not ok or fr is None:
        return {"ok": False, "error": "프레임을 못 잡음(연결 실패/경로 오류)"}
    _, buf = cv2.imencode(".jpg", cv2.resize(fr, (480, 270)), [cv2.IMWRITE_JPEG_QUALITY, 65])
    return {"ok": True, "snapshot": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()}


@router.get("/cameras/{cid}/zone")
def cameras_zone_get(cid: str):
    """카메라별 위험구역 폴리곤(정규화 좌표). 비어 있으면 워커는 전역 구역으로 폴백."""
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    pts = c.get("zone") or []
    return {"points": [{"x": float(p[0]), "y": float(p[1])} for p in pts], "count": len(pts)}


@router.post("/cameras/{cid}/zone")
def cameras_zone_set(cid: str, payload: dict = Body(...)):
    """카메라별 위험구역 저장. payload={"points":[{"x":..,"y":..}, ...]}(정규화 0~1).
    비우면 전역 구역 폴백. 실행 중 카메라는 워커를 재시작해 즉시 반영한다."""
    import worker as _w
    c = _reg.get(cid)
    if not c:
        raise HTTPException(status_code=404, detail="없는 카메라")
    pts = payload.get("points") or []
    zone = [[float(p["x"]), float(p["y"])] for p in pts]
    _reg.upsert(cid, zone=zone)
    restarted = False
    if _worker(cid) is not None and (_reg.get(cid) or {}).get("enabled"):
        _w.manager.stop(cid)
        _start(cid)
        restarted = True
    return {"ok": True, "count": len(zone), "restarted": restarted}


def autostart_enabled() -> dict:
    """서버 startup 자동복원 — enabled 카메라 워커 자동 start. 실패해도 서버는 뜬다."""
    res: dict = {}
    for c in _reg.list_cameras():
        if not c.get("enabled"):
            continue
        try:
            _start(c["id"])
            res[c["id"]] = "started"
        except Exception as ex:  # noqa: BLE001
            res[c["id"]] = f"fail: {type(ex).__name__}"
    return res
