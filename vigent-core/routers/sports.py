"""routers/sports.py — 스포츠(요가 아사나) 라우트 (P1-7 분할). main 미import."""
import json

from fastapi import APIRouter, Body, HTTPException
from web_util import _ROOT

router = APIRouter()


@router.get("/sports/asanas")
def sports_asanas():
    """요가 동작 라이브러리(Yoga-82 수준). 정답각도(scored)·카테고리 포함."""
    p = _ROOT / "config" / "yoga_asanas.json"
    if not p.exists():
        return {"asanas": []}
    return json.loads(p.read_text(encoding="utf-8"))

@router.get("/sports/templates")
def sports_templates():
    """학습된 요가 동작 인식 템플릿(브라우저가 등록 없이 자동 인식). 없으면 빈값."""
    p = _ROOT / "config" / "yoga_templates.json"
    if not p.exists():
        return {"templates": {}}
    return json.loads(p.read_text(encoding="utf-8"))

@router.post("/sports/calibrate")
def sports_calibrate(payload: dict = Body(default={})):
    """정답 자세 보정 — 시연으로 측정한 각도(중앙값·허용오차)로 해당 동작 정답각도 갱신.
    payload={asana_id, angles:[{name, ideal, tol, n}]}. 데이터 기반 표시(user_calibrated)."""
    aid = payload.get("asana_id")
    measured = {m.get("name"): m for m in (payload.get("angles") or [])}
    if not aid or not measured:
        raise HTTPException(status_code=400, detail="asana_id·angles 필요")
    p = _ROOT / "config" / "yoga_asanas.json"
    lib = json.loads(p.read_text(encoding="utf-8"))
    updated = 0
    for a in lib["asanas"]:
        if a.get("id") != aid:
            continue
        for ang in a.get("angles", []):
            m = measured.get(ang["name"])
            if m and m.get("n", 0) >= 10:
                ang["ideal"] = round(float(m["ideal"]))
                ang["tol"] = max(8, round(float(m["tol"])))
                ang["data_based"] = True
                ang["user_calibrated"] = True
                ang["n"] = int(m["n"])
                updated += 1
        a["scored"] = len(a.get("angles", [])) > 0
    if updated:
        p.write_text(json.dumps(lib, ensure_ascii=False, indent=1), encoding="utf-8")
    # B: 정답 자세 키포인트(목표 자세 시연용)도 저장 — reference=[{x,y,z}, ...12점]
    ref = payload.get("reference")
    if isinstance(ref, list) and len(ref) >= 12:
        rp = _ROOT / "config" / "yoga_reference.json"
        refs = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
        refs[aid] = ref[:12]
        rp.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "updated": updated, "asana": aid, "reference_saved": bool(ref)}

@router.get("/sports/reference")
def sports_reference():
    """보정으로 저장된 정답 자세 키포인트(목표 자세 시연용). 없으면 빈값."""
    p = _ROOT / "config" / "yoga_reference.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

@router.post("/sports/session")
def sports_session(payload: dict = Body(default={})):
    """연습 1건(동작·점수·유지시간) 익명 기록. 토큰은 브라우저 로컬 랜덤값."""
    import sports_data
    return sports_data.log_session(
        token=payload.get("token", "anon"), asana=payload.get("asana", ""),
        score=payload.get("score", 0), hold_sec=payload.get("hold_sec", 0))

@router.get("/sports/progress")
def sports_progress(token: str = "anon", days: int = 30):
    """익명 토큰의 연습 진행도(추세·연속일·동작별 최고점)."""
    import sports_data
    return sports_data.progress(token, days)
