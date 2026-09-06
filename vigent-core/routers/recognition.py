"""routers/recognition.py — 안전 이벤트 증거 로거(P1-7 분할). main 미import.

★[곁다리 정리, 2026-08-12] 이름과 달리 얼굴인식이 아니다 — ppe_missing·zone_intrusion 등
안전 판정 이벤트를 기록·조회하는 로그다(data_engine 기록소 배선, guard 판정 결과 저장).
"recognition"은 "(위험) 인식" 의미로 붙은 이름이며 사람 신원 식별과 무관하다.

/recognition/log(기록·조회)·/recognition/log/download(CSV)·/recognition/note(스텁).
"""
import json

import data_engine
from fastapi import APIRouter, Body, HTTPException, Response

router = APIRouter()


_EXTRA_RULES = {"press_zone", "safety_measure_missing"}   # 규칙 지식베이스 밖이지만 서버가 실제로 쓰는 규칙명


def allowed_rules() -> set[str]:
    """[CODE_REVIEW M8-7] /recognition/log 가 받는 규칙명 화이트리스트 = 위험성평가 규칙 지식베이스(RULE_KB) + 서버 규칙.
    실사고: 프론트 디버그 텔레메트리(coord_*)·정체불명 rule='t' 194행이 안전 이벤트 로그에 섞여 있었다."""
    try:
        from agents.scribe import RULE_KB
        base = set(RULE_KB.keys())
    except Exception:  # noqa: BLE001  지식베이스 로드 실패 시 최소 집합
        base = {"zone_intrusion", "ppe_missing", "fire_smoke", "proximity_hazard", "immobility", "rapid_motion",
                "crowd_density", "ergonomic_risk", "guard_bypass", "lone_worker"}
    return base | _EXTRA_RULES


@router.post("/recognition/log")
def recognition_log(payload: dict = Body(...)):
    """데이터엔진 — 위험 이벤트 1건 기록(+증거 프레임 저장).
    payload={rule, level, score, site, note, image(data URL, 선택), source?(browser 등)}
    [M8-7] rule 은 화이트리스트(allowed_rules) 밖이면 400 — 디버그·오타 행이 안전 이벤트 로그에 섞이지 않게."""
    rule = str(payload.get("rule") or "").strip()
    if rule not in allowed_rules():
        raise HTTPException(status_code=400, detail=f"rule 미허용: {rule!r} (허용: 위험성평가 규칙명)")
    return data_engine.log_event(
        rule=rule, level=payload.get("level", ""),
        score=payload.get("score", 0), site=payload.get("site", ""),
        note=payload.get("note", ""), image_data_url=payload.get("image"),
        source=str(payload.get("source") or "browser"))

@router.get("/recognition/log")
def recognition_log_list(limit: int = 100, hours: float | None = None):
    """저장된 인식 로그 목록(최신순)."""
    return {"events": data_engine.list_events(limit=limit, hours=hours)}

@router.get("/recognition/log/download")
def recognition_log_download():
    """전체 인식 로그를 JSONL 로 다운로드."""
    lines = [json.dumps(r, ensure_ascii=False) for r in data_engine.list_events(limit=100000)]
    return Response("\n".join(lines), media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=vigent_events.jsonl"})

@router.post("/recognition/note")
def stub_recognition_note(payload: dict = Body(default={})):
    return {"ok": True}


_PIN_ALLOWED_PREFIXES = ("data/evidence/", "data/recognition/")


def _pin_target(payload: dict) -> str:
    """[CODE_REVIEW M6-3] pin 대상 상대경로 검증 — 증거·인식 로그 아래만 허용(경로 탈출·임의 파일 pin 차단)."""
    rel = data_engine.norm_rel(str(payload.get("path") or ""))
    if not rel or ".." in rel.split("/") or rel.startswith("/") or ":" in rel.split("/")[0]:
        raise HTTPException(status_code=400, detail="path 는 data/evidence/… 또는 data/recognition/… 상대경로여야 한다")
    if not rel.startswith(_PIN_ALLOWED_PREFIXES):
        raise HTTPException(status_code=400, detail="pin 은 증거(data/evidence)·인식 로그(data/recognition)만 가능")
    return rel


@router.post("/recognition/pin")
def recognition_pin(payload: dict = Body(...)):
    """[M6-3] 증거·인식 로그 파일을 보존 스윕에서 제외(pin). payload={path, reason?}. 사람이 unpin 하기 전까지 유지."""
    rel = _pin_target(payload)
    data_engine.pin_evidence(rel, reason=str(payload.get("reason") or "manual"))
    return {"ok": True, "path": rel, "pinned": data_engine.pinned_map()}


@router.post("/recognition/unpin")
def recognition_unpin(payload: dict = Body(...)):
    """[M6-3] pin 해제 — 다음 스윕부터 보존 일수 규칙을 다시 적용한다."""
    rel = _pin_target(payload)
    data_engine.unpin_evidence(rel)
    return {"ok": True, "path": rel, "pinned": data_engine.pinned_map()}
