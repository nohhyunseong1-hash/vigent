"""VIGENT Sports — 연습 기록·진행도(익명).

피트니스 제품의 핵심: 매 세션을 기록해 '지난주보다 나아졌나'를 보여준다.
개인정보: 이름·얼굴 없음. 브라우저 로컬 랜덤 토큰으로만 본인 기록 그룹화.
저장: data/sports/sessions_<YYYYMMDD>.jsonl (1줄 = 1 세션).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DIR = _ROOT / "data" / "sports"


def log_session(token: str, asana: str, score: float, hold_sec: float,
                best: bool = False) -> dict[str, Any]:
    """한 동작 연습 1건(점수·유지시간) 익명 기록."""
    _DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    rec = {"ts": ts.isoformat(timespec="seconds"), "date": ts.strftime("%Y-%m-%d"),
           "token": (token or "anon")[:40], "asana": str(asana or "")[:40],
           "score": round(float(score or 0), 1), "hold_sec": round(float(hold_sec or 0), 1)}
    fp = _DIR / f"sessions_{ts.strftime('%Y%m%d')}.jsonl"
    with open(fp, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True}


def _read(days: int) -> list[dict[str, Any]]:
    if not _DIR.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    out = []
    for fp in sorted(_DIR.glob("sessions_*.jsonl")):
        if fp.stem.replace("sessions_", "") < cutoff:
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def progress(token: str, days: int = 30) -> dict[str, Any]:
    """익명 토큰의 연습 진행도 — 일자별 평균점수·연습수, 동작별 최고점, 연속일."""
    recs = [r for r in _read(days) if r.get("token") == (token or "anon")[:40]]
    by_date: dict[str, dict[str, float]] = defaultdict(lambda: {"ssum": 0.0, "n": 0, "hold": 0.0})
    best_by_asana: dict[str, float] = {}
    dates = set()
    for r in recs:
        d = by_date[r["date"]]
        d["ssum"] += r.get("score", 0); d["n"] += 1; d["hold"] += r.get("hold_sec", 0)
        dates.add(r["date"])
        a = r.get("asana", "")
        if a:
            best_by_asana[a] = max(best_by_asana.get(a, 0), r.get("score", 0))
    series = []
    for date in sorted(by_date):
        d = by_date[date]
        series.append({"date": date, "avg_score": round(d["ssum"] / d["n"], 1) if d["n"] else 0,
                       "sessions": d["n"], "hold_min": round(d["hold"] / 60, 1)})
    # 연속 연습일(streak)
    streak = 0
    day = datetime.now()
    while day.strftime("%Y-%m-%d") in dates:
        streak += 1
        day -= timedelta(days=1)
    today = datetime.now().strftime("%Y-%m-%d")
    return {"ok": True, "days": days, "series": series,
            "today": next((s for s in series if s["date"] == today), None),
            "streak": streak, "total_sessions": len(recs),
            "mastered": [{"asana": a, "best": s} for a, s in
                         sorted(best_by_asana.items(), key=lambda x: -x[1])[:8]]}
