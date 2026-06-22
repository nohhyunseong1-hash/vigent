"""audit_store.py — 감사추적(승인 이력) 저장

책임 회피 설계의 핵심: "AI는 권고, 최종 승인은 사람"을 기록으로 증명한다.
안전관리자가 위험 이벤트에 대해 위험성평가를 승인하거나 조치를 확인하면,
누가·언제·무엇을 승인했는지 1줄로 남긴다(법적 분쟁 시 사람이 최종판단했음을 입증).

저장: data/audit/audit_<YYYYMMDD>.jsonl  (1줄 = 승인 1건)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
_ROOT = Path(__file__).resolve().parent.parent
_AUDIT = _ROOT / "data" / "audit"


def record(event_ts: str, rule: str, action: str,
           approver: str = "안전관리자", site: str = "",
           ra_aid: str = "", note: str = "") -> dict[str, Any]:
    """승인 1건 기록. action ∈ {risk_assessment, acknowledge}. 항상 결과 반환."""
    ts = datetime.now(KST)
    rec = {
        "at": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"), "time": ts.strftime("%H:%M:%S"),
        "event_ts": str(event_ts or ""),
        "rule": str(rule or ""),
        "action": str(action or "acknowledge"),
        "approver": str(approver or "안전관리자").strip(),
        "site": str(site or ""),
        "ra_aid": str(ra_aid or ""),
        "note": str(note or ""),
    }
    _AUDIT.mkdir(parents=True, exist_ok=True)
    with open(_AUDIT / f"audit_{ts.strftime('%Y%m%d')}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _read_all(limit: int = 2000) -> list[dict[str, Any]]:
    if not _AUDIT.exists():
        return []
    out: list[dict[str, Any]] = []
    for fp in sorted(_AUDIT.glob("audit_*.jsonl")):
        for line in fp.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    out.sort(key=lambda r: r.get("at", ""), reverse=True)
    return out[:limit]


def list_recent(limit: int = 200) -> list[dict[str, Any]]:
    """감사추적 목록(최신순)."""
    return _read_all(limit)


def event_key(event_ts: str, rule: str) -> str:
    """승인 매칭 키 — 같은 초의 다른 규칙을 구분하기 위해 (ts+rule) 복합키."""
    return f"{event_ts or ''}|{rule or ''}"


def by_event() -> dict[str, dict[str, Any]]:
    """event_key → 최신 승인 레코드(피드에서 '승인됨' 표시용)."""
    idx: dict[str, dict[str, Any]] = {}
    for r in _read_all():                       # 최신순 → 먼저 본 게 최신
        k = event_key(r.get("event_ts", ""), r.get("rule", ""))
        if k not in idx:
            idx[k] = r
    return idx
