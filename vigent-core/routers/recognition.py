"""routers/recognition.py — 얼굴/출입 인식 로그 (P1-7 분할). main 미import.

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
