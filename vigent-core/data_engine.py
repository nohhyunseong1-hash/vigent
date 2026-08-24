"""data_engine.py — 위험 이벤트 증거·로그 자동 저장 (§15-6, 데이터엔진)

위험 이벤트(zone_intrusion·ppe_missing·guard_bypass)가 감지되면
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
_PINNED = _EVIDENCE / "pinned.json"   # [Z-2] pin된 증거 목록 — retention.py 스위퍼가 참조,
                                        # 어떤 보존기간 삭제 경로로도 지워지지 않음(테스트로 보장)

# 데이터엔진이 다루는 위험 이벤트(규칙) 화이트리스트
HAZARD_RULES = {"zone_intrusion", "ppe_missing", "guard_bypass",
                "ergonomic_risk", "fire_smoke", "trip_hazard", "safety_measure_missing",
                "proximity_hazard", "crowd_density", "lone_worker",
                "immobility", "rapid_motion",
                # 신규(사망재해 주요 유형) — 비전 훅 + 센서 연동
                "falling_object", "height_fall_risk", "machine_entanglement",
                "asphyxiation", "gas_alarm", "heat_stress", "electrical_hazard"}

_DATAURL = re.compile(r"^data:image/\w+;base64,(.+)$", re.S)


def _elog():
    """지연 import 로거 — data_engine 은 vlog 를 최상위에서 끌어오지 않는다(순환 회피)."""
    import vlog
    return vlog.get("vigent.data_engine")


def _save_frame(image_data_url: str, ts: datetime, rule: str, level: str) -> str | None:
    """base64 data URL → JPEG 파일 저장. 반환: 프로젝트 루트 기준 상대경로(없으면 None)."""
    m = _DATAURL.match(image_data_url or "")
    if not m:
        return None
    day = ts.strftime("%Y%m%d")
    folder = _EVIDENCE / day
    safe_rule = re.sub(r"[^a-zA-Z0-9_]", "", rule) or "event"
    fname = f"ev_{ts.strftime('%Y%m%d_%H%M%S')}_{safe_rule}_{level}.jpg"
    try:
        # ★[F2, 2026-08-21] mkdir 도 try 안으로 — 디스크 풀·권한 오류의 OSError 가 호출부까지
        #   올라가면 worker._process_frame 의 프레임 단위 except 로 빠져 **뒤에 있는 알림 전송
        #   (alert_notify.submit)까지 건너뛴다.** 증거를 못 남기는 것과 경보를 못 보내는 것은
        #   전혀 다른 사고다 — 여기서 삼키고 None 을 돌려준다.
        folder.mkdir(parents=True, exist_ok=True)
        (folder / fname).write_bytes(base64.b64decode(m.group(1)))
    except (ValueError, OSError) as ex:
        _elog().error("증거 프레임 저장 실패(%s) — 이벤트 기록·알림은 계속한다: %s",
                      type(ex).__name__, ex)
        return None
    return str((folder / fname).relative_to(_ROOT))


def pinned_paths() -> set[str]:
    """pin된 증거 상대경로 집합(프로젝트 루트 기준). 읽기 실패는 빈 집합(삭제를 막는 방향이
    아니게 안전하게 실패 — 단 이 함수를 부르는 retention.sweep()은 dry_run 기본이라 실수로
    지워지지 않는다)."""
    try:
        return set(json.loads(_PINNED.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return set()


def pin_evidence(rel_path: str) -> None:
    """증거 파일(data/evidence/... 상대경로)을 보존 정책 삭제 대상에서 제외한다."""
    paths = pinned_paths()
    paths.add(rel_path)
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    _PINNED.write_text(json.dumps(sorted(paths), ensure_ascii=False, indent=2), encoding="utf-8")


def unpin_evidence(rel_path: str) -> None:
    paths = pinned_paths()
    paths.discard(rel_path)
    _EVIDENCE.mkdir(parents=True, exist_ok=True)
    _PINNED.write_text(json.dumps(sorted(paths), ensure_ascii=False, indent=2), encoding="utf-8")


def log_event(rule: str, level: str = "", score: float = 0.0,
              site: str = "", note: str = "",
              image_data_url: str | None = None,
              privacy_failed: bool = False) -> dict[str, Any]:
    """위험 이벤트 1건 기록(+증거 프레임). 항상 결과를 반환(예외로 죽지 않음).

    ★[D4-②, 2026-08-24] `privacy_failed=True` 면 그 증거 이미지는 **얼굴 모자이크가
      실패한 원본**이다. 설계 결정상 저장은 계속하되(증거 보전 우선), 기록에 표시해
      **나중에 그 건만 골라 삭제**할 수 있게 한다. 표시가 없으면 원본이 어느 건인지
      알 수 없어 전량 폐기밖에 수가 없다.
    """
    ts = datetime.now(KST)
    evidence = _save_frame(image_data_url, ts, rule, level) if image_data_url else None
    record = {
        "ts": ts.isoformat(timespec="seconds"),
        "date": ts.strftime("%Y-%m-%d"), "time": ts.strftime("%H:%M:%S"),
        "rule": rule, "level": level, "score": round(float(score or 0), 1),
        "site": site, "note": note, "evidence": evidence,
    }
    if privacy_failed:                 # [D4-②] 원본이 저장된 건만 표시(선별 삭제용 꼬리표)
        record["privacy_failed"] = True
    # ★[F2] docstring 의 "예외로 죽지 않음" 을 실제로 보장한다 — 이전에는 mkdir·open 이
    #   try 밖이라 디스크 풀에서 예외가 올라갔고, **기록 실패가 알림 실패로 전이**됐다.
    #   기록이 실패해도 record 는 정상 반환해 호출부의 통보 경로가 이어지게 한다.
    try:
        _RECOG.mkdir(parents=True, exist_ok=True)
        logfile = _RECOG / f"events_{ts.strftime('%Y%m%d')}.jsonl"
        with open(logfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as ex:
        record["logged"] = False
        _elog().error("★이벤트 로그 기록 실패(%s) — 알림은 계속 보낸다(디스크·권한 확인 필요): %s",
                      type(ex).__name__, ex)
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
    """최근 N시간 이벤트를 규칙별로 집계 → [{rule, count, levels, evidence_paths, notes}].
    위험성평가에서 빈도(count)·중대성(levels: 실제 등급 분포)·증거(evidence_paths)를 쓴다."""
    counts: dict[str, int] = {}
    levels: dict[str, dict[str, int]] = {}
    evidence: dict[str, list[str]] = {}
    notes: dict[str, list[str]] = {}
    for rec in _read_all(hours):
        r = rec.get("rule")
        if r not in HAZARD_RULES:
            continue
        counts[r] = counts.get(r, 0) + 1
        lv = (rec.get("level") or "low").lower()
        levels.setdefault(r, {})[lv] = levels.get(r, {}).get(lv, 0) + 1
        ev = rec.get("evidence")
        if ev:
            evidence.setdefault(r, []).append(ev)
        nt = rec.get("note")
        if nt:
            notes.setdefault(r, []).append(nt)
    return [{"rule": r, "count": c, "levels": levels.get(r, {}),
             "evidence_paths": evidence.get(r, [])[-4:],     # 최근 증거 최대 4장
             "notes": notes.get(r, [])[-4:]}
            for r, c in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)]
