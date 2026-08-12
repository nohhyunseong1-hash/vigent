"""routers/recognition.py — 안전 이벤트 증거 로거(P1-7 분할). main 미import.

★[곁다리 정리, 2026-08-12] 이름과 달리 얼굴인식이 아니다 — ppe_missing·zone_intrusion 등
안전 판정 이벤트를 기록·조회하는 로그다(data_engine 기록소 배선, guard 판정 결과 저장).
"recognition"은 "(위험) 인식" 의미로 붙은 이름이며 사람 신원 식별과 무관하다.

/recognition/log(기록·조회)·/recognition/log/download(CSV)·/recognition/note(스텁).
"""
import json

import data_engine
from fastapi import APIRouter, Body, Response

router = APIRouter()


@router.post("/recognition/log")
def recognition_log(payload: dict = Body(...)):
    """데이터엔진 — 위험 이벤트 1건 기록(+증거 프레임 저장).
    payload={rule, level, score, site, note, image(data URL, 선택)}"""
    return data_engine.log_event(
        rule=payload.get("rule", ""), level=payload.get("level", ""),
        score=payload.get("score", 0), site=payload.get("site", ""),
        note=payload.get("note", ""), image_data_url=payload.get("image"))

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
