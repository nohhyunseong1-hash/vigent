"""tbm_store.py — 작업 전 TBM(안전점검 회의) 회의록 저장·조회

한전 「스마트 TBM」의 '작업 전 안전점검 회의록'을 VIGENT Safety에 맞춰 구현한 저장 계층.
위험성평가서(Scribe → data/risk_assessments/)와 같은 방식으로, 회의록 1건을
JSON 1파일로 data/tbm/ 에 저장한다. 코어 추론 로직과 무관(가산식·폴백 원칙에 영향 없음).

저장 위치/파일명
  · data/tbm/tbm_<YYYYMMDD_HHMMSS>.json   (1파일 = 회의록 1건)

회의록 스키마(키는 코드 안정성을 위해 영어, 화면은 한국어)
  id, created_at, site(현장), process(작업공종), work_desc(작업내용),
  supervisor(감독관), hazards[](중점 위험요인), checklist[]{item, ok},
  workers[]{name, signed}, notes(전달사항)
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

KST = timezone(timedelta(hours=9))
_ROOT = Path(__file__).resolve().parent.parent
_TBM = _ROOT / "data" / "tbm"

# 작성 화면이 기본 제시하는 작업 전 점검 항목(작업자가 가감 가능)
DEFAULT_CHECKLIST = [
    "작업자 건강상태 이상 없음(음주·피로·복약 등)",
    "개인 보호구(안전모·안전화·안전대 등) 착용 확인",
    "작업 도구·장비 점검 및 이상 없음",
    "작업 구역 주변 위험요인(추락·협착·감전 등) 확인",
    "비상 연락·대피 경로 공유",
]


def _norm_workers(raw: Any) -> list[dict]:
    """workers 입력을 [{name, signed}] 로 정규화. 이름 없는 항목은 버린다."""
    out: list[dict] = []
    for w in raw or []:
        if isinstance(w, dict):
            name = str(w.get("name", "")).strip()
            signed = bool(w.get("signed", False))
        else:  # 문자열만 온 경우
            name, signed = str(w).strip(), False
        if name:
            out.append({"name": name, "signed": signed})
    return out


def _norm_checklist(raw: Any) -> list[dict]:
    """checklist 입력을 [{item, ok}] 로 정규화. 없으면 기본 항목(미체크)."""
    out: list[dict] = []
    for c in raw or []:
        if isinstance(c, dict):
            item = str(c.get("item", "")).strip()
            ok = bool(c.get("ok", False))
        else:
            item, ok = str(c).strip(), False
        if item:
            out.append({"item": item, "ok": ok})
    if not out:
        out = [{"item": x, "ok": False} for x in DEFAULT_CHECKLIST]
    return out


# ── 공종별 위험요인 추천 (JSA 대상작업 기반) ────────────────────────────
_JSA_PATH = _ROOT / "config" / "corpus" / "jsa_hazards.json"
_jsa_cache: dict | None = None


def _load_jsa() -> list[dict]:
    """jsa_hazards.json 의 공종 목록 로드(1회 캐시). 없으면 빈 목록(무중단)."""
    global _jsa_cache
    if _jsa_cache is None:
        try:
            _jsa_cache = json.loads(_JSA_PATH.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            _jsa_cache = {"공종": []}
    return _jsa_cache.get("공종", []) or []


def jsa_catalog() -> list[dict]:
    """작성 화면 드롭다운용 공종 이름 목록."""
    return [{"id": j.get("id", ""), "name": j.get("name", "")} for j in _load_jsa()]


def _match_process(process: str) -> dict | None:
    """작업공종 자유텍스트 → 가장 잘 맞는 공종 1개. 매칭 없으면 None."""
    text = (process or "").strip().lower()
    if not text:
        return None
    best, best_score = None, 0
    for j in _load_jsa():
        score = 0
        name = str(j.get("name", "")).lower()
        if name and (name in text or text in name):
            score += 3
        for a in j.get("aliases", []) or []:
            if a and str(a).lower() in text:
                score += 1
        if score > best_score:
            best, best_score = j, score
    return best


def suggest(process: str) -> dict[str, Any]:
    """공종 추천. 반환: {matched, hazards[], checklist[], rules[]}. 매칭 없으면 일반작업 폴백."""
    j = _match_process(process)
    fallback = j is None
    if fallback:  # 매칭 실패 → 일반작업으로 폴백(빈손 방지)
        j = next((x for x in _load_jsa() if x.get("id") == "general"), None) or {}
    return {
        "matched": None if fallback else j.get("name", ""),
        "fallback": fallback,
        "hazards": list(j.get("hazards", []) or []),
        "checklist": list(j.get("checklist", []) or []),
        "rules": list(j.get("rules", []) or []),
    }


def create(payload: dict) -> dict[str, Any]:
    """회의록 1건 저장. 항상 결과를 반환(예외로 죽지 않음). 반환: 저장된 record(+saved_path)."""
    ts = datetime.now(KST)
    tid = f"tbm_{ts.strftime('%Y%m%d_%H%M%S')}"
    record = {
        "id": tid,
        "created_at": ts.isoformat(timespec="seconds"),
        "site": str(payload.get("site", "")).strip(),
        "process": str(payload.get("process", "")).strip(),
        "work_desc": str(payload.get("work_desc", "")).strip(),
        "supervisor": str(payload.get("supervisor", "")).strip(),
        "hazards": [str(h).strip() for h in (payload.get("hazards") or []) if str(h).strip()],
        "checklist": _norm_checklist(payload.get("checklist")),
        "workers": _norm_workers(payload.get("workers")),
        "notes": str(payload.get("notes", "")).strip(),
    }
    _TBM.mkdir(parents=True, exist_ok=True)
    path = _TBM / f"{tid}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["saved_path"] = str(path.relative_to(_ROOT))
    return record


def list_recent(limit: int = 100) -> list[dict]:
    """저장된 회의록 요약 목록(최신순). 파일이 깨졌으면 건너뛴다."""
    if not _TBM.exists():
        return []
    items: list[dict] = []
    for p in sorted(_TBM.glob("tbm_*.json"), reverse=True)[:limit]:
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        workers = r.get("workers", []) or []
        items.append({
            "id": r.get("id", p.stem),
            "created_at": r.get("created_at", ""),
            "site": r.get("site", ""),
            "process": r.get("process", ""),
            "supervisor": r.get("supervisor", ""),
            "worker_count": len(workers),
            "signed_count": sum(1 for w in workers if w.get("signed")),
            "hazard_count": len(r.get("hazards", []) or []),
        })
    return items


def get(tid: str) -> dict | None:
    """저장된 회의록 1건 원본 반환. 없거나 깨졌으면 None."""
    safe = re.sub(r"[^a-zA-Z0-9_]", "", tid or "")
    if not safe:
        return None
    p = _TBM / f"{safe}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
