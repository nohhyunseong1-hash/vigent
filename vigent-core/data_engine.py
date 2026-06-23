"""data_engine.py — 위험 이벤트 증거·로그 자동 저장 (§15-6, 데이터엔진)

위험 이벤트(zone_intrusion·fall_suspected·ppe_missing·guard_bypass)가 감지되면
  1) 증거 프레임 이미지(JPEG) 저장
  2) 인식 로그(JSONL) 1줄 추가
한다. 저장된 이벤트는 위험성평가서(Scribe) 생성 시 빈도 집계로 재사용된다.

저장 위치/파일명 규칙
  · 증거 프레임 : data/evidence/<YYYYMMDD>/ev_<YYYYMMDD_HHMMSS>_<rule>_<level>.jpg
  · 인식 로그   : data/recognition/events_<YYYYMMDD>.jsonl   (1줄 = 1이벤트)

개인정보(§8.3): 증거 프레임은 로컬에만 저장한다. (얼굴 비식별화·암호화는 상용 단계 과제)
"""
from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
_ROOT = Path(__file__).resolve().parent.parent
_EVIDENCE = _ROOT / "data" / "evidence"
_RECOG = _ROOT / "data" / "recognition"

# 데이터엔진이 다루는 위험 이벤트(규칙) 화이트리스트
HAZARD_RULES = {"zone_intrusion", "fall_suspected", "ppe_missing", "guard_bypass",
                "ergonomic_risk", "fire_smoke", "trip_hazard"}

_DATAURL = re.compile(r"^data:image/\w+;base64,(.+)$", re.S)


def _save_frame(image_data_url: str, ts: datetime, rule: str, level: str) -> str | None:
    """base64 data URL → JPEG 파일 저장. 반환: 프로젝트 루트 기준 상대경로(없으면 None)."""
    m = _DATAURL.match(image_data_url or "")
    if not m:
        return None
    day = ts.strftime("%Y%m%d")
    folder = _EVIDENCE / day
    folder.mkdir(parents=True, exist_ok=True)
    safe_rule = re.sub(r"[^a-zA-Z0-9_]", "", rule) or "event"
    fname = f"ev_{ts.strftime('%Y%m%d_%H%M%S')}_{safe_rule}_{level}.jpg"
    try:
        (folder / fname).write_bytes(base64.b64decode(m.group(1)))
    except (ValueError, OSError):
        return None
    return str((folder / fname).relative_to(_ROOT))


def log_event(rule: str, level: str = "", score: float = 0.0,
              site: str = "", note: str = "",
              image_data_url: str | None = None) -> dict[str, Any]:
    """위험 이벤트 1건 기록(+증거 프레임). 항상 결과를 반환(예외로 죽지 않음)."""
    ts = datetime.now(KST)
    evidence = _save_frame(image_data_url, ts, rule, level) if image_data_url else None
    record = {
        "ts": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"), "time": ts.strftime("%H:%M:%S"),
        "rule": rule, "level": level, "score": round(float(score or 0), 1),
        "site": site, "note": note, "evidence": evidence,
    }
    _RECOG.mkdir(parents=True, exist_ok=True)
    logfile = _RECOG / f"events_{ts.strftime('%Y%m%d')}.jsonl"
    with open(logfile, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def _read_all(within_hours: float | None = None) -> list[dict[str, Any]]:
    """저장된 이벤트를 최신순으로 읽는다(옵션: 최근 N시간만)."""
    if not _RECOG.exists():
        return []
    cutoff = datetime.now(KST) - timedelta(hours=within_hours) if within_hours else None
    out: list[dict[str, Any]] = []
    for fp in sorted(_RECOG.glob("events_*.jsonl")):
        for line in fp.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff:
                try:
                    if datetime.fromisoformat(rec["ts"]) < cutoff:
                        continue
                except (KeyError, ValueError):
                    pass
            out.append(rec)
    out.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return out


def list_events(limit: int = 100, hours: float | None = None) -> list[dict[str, Any]]:
    return _read_all(hours)[:limit]


def aggregate(hours: float = 24) -> list[dict[str, Any]]:
    """최근 N시간 이벤트를 규칙별로 집계 → [{rule, count}] (위험성평가 빈도 산정용)."""
    counts: dict[str, int] = {}
    for rec in _read_all(hours):
        r = rec.get("rule")
        if r in HAZARD_RULES:
            counts[r] = counts.get(r, 0) + 1
    return [{"rule": r, "count": c} for r, c in
            sorted(counts.items(), key=lambda kv: kv[1], reverse=True)]
