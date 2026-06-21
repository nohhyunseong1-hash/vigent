"""VIGENT Office — 자세 복지 데이터 영속·추세(익명).

개인정보 보호(office 원칙):
  - 이름·얼굴 없음. 브라우저가 만든 '익명 랜덤 토큰'으로만 본인 기록을 그룹화.
  - 저장은 파일(jsonl) — DB 없이 가볍게. data/ 는 .gitignore(외부 유출 없음).

저장: data/office/posture_<YYYYMMDD>.jsonl  (1줄 = 1 주기 샘플)
추세: 토큰별로 날짜 집계 → 일자별 평균점수·바른자세 비율
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DIR = _ROOT / "data" / "office"


def log_posture(token: str, good_sec: float, bad_sec: float,
                avg_score: float, joints: dict[str, Any] | None = None) -> dict[str, Any]:
    """한 주기(예: 60초)의 익명 자세 통계를 누적 기록."""
    _DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now()
    rec = {
        "ts": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"),
        "token": (token or "anon")[:40],
        "good_sec": round(float(good_sec or 0), 1),
        "bad_sec": round(float(bad_sec or 0), 1),
        "avg_score": round(float(avg_score or 0), 1),
        "joints": joints or {},
    }
    fp = _DIR / f"posture_{ts.strftime('%Y%m%d')}.jsonl"
    with open(fp, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True, "saved": rec["ts"]}


def _read(days: int) -> list[dict[str, Any]]:
    if not _DIR.exists():
        return []
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
    out = []
    for fp in sorted(_DIR.glob("posture_*.jsonl")):
        if fp.stem.replace("posture_", "") < cutoff:
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def trend(token: str, days: int = 7) -> dict[str, Any]:
    """토큰(익명)의 최근 N일 자세 추세 — 일자별 평균점수·바른자세 비율."""
    recs = [r for r in _read(days) if r.get("token") == (token or "anon")[:40]]
    by_date: dict[str, dict[str, float]] = defaultdict(lambda: {"good": 0.0, "bad": 0.0, "ssum": 0.0, "n": 0})
    for r in recs:
        d = by_date[r["date"]]
        d["good"] += r.get("good_sec", 0)
        d["bad"] += r.get("bad_sec", 0)
        d["ssum"] += r.get("avg_score", 0)
        d["n"] += 1
    series = []
    for date in sorted(by_date):
        d = by_date[date]
        total = d["good"] + d["bad"]
        series.append({
            "date": date,
            "avg_score": round(d["ssum"] / d["n"], 1) if d["n"] else 0,
            "good_ratio": round(d["good"] / total * 100, 1) if total else 0,
            "good_min": round(d["good"] / 60, 1),
            "bad_min": round(d["bad"] / 60, 1),
        })
    # 요약(오늘 vs 기간 평균)
    today = datetime.now().strftime("%Y-%m-%d")
    today_row = next((s for s in series if s["date"] == today), None)
    avg_all = round(sum(s["avg_score"] for s in series) / len(series), 1) if series else 0
    return {"ok": True, "token_days": days, "series": series,
            "today": today_row, "period_avg_score": avg_all, "samples": len(recs)}


def team_report(days: int = 7) -> dict[str, Any]:
    """관리자용 팀 단위 익명 집계 — 개인 식별 없이 전체 통계만(복지 프로그램 관리용)."""
    recs = _read(days)
    by_date: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"good": 0.0, "bad": 0.0, "ssum": 0.0, "n": 0, "tokens": set()})
    all_tokens: set[str] = set()
    g_total = b_total = ssum = 0.0
    n = 0
    for r in recs:
        d = by_date[r["date"]]
        d["good"] += r.get("good_sec", 0); d["bad"] += r.get("bad_sec", 0)
        d["ssum"] += r.get("avg_score", 0); d["n"] += 1; d["tokens"].add(r.get("token"))
        all_tokens.add(r.get("token"))
        g_total += r.get("good_sec", 0); b_total += r.get("bad_sec", 0)
        ssum += r.get("avg_score", 0); n += 1
    series = []
    for date in sorted(by_date):
        d = by_date[date]; total = d["good"] + d["bad"]
        series.append({
            "date": date, "participants": len(d["tokens"]),
            "avg_score": round(d["ssum"] / d["n"], 1) if d["n"] else 0,
            "good_ratio": round(d["good"] / total * 100, 1) if total else 0,
        })
    tot = g_total + b_total
    return {
        "ok": True, "days": days,
        "participants": len(all_tokens),       # 익명 참여 인원(고유 토큰 수)
        "team_avg_score": round(ssum / n, 1) if n else 0,
        "team_good_ratio": round(g_total / tot * 100, 1) if tot else 0,
        "good_hours": round(g_total / 3600, 1), "bad_hours": round(b_total / 3600, 1),
        "series": series, "samples": n,
    }
