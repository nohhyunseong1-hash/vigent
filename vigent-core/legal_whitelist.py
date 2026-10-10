"""법령 화이트리스트 게이트 — A-SPRINT Phase 3 (§7 환각 차단).

두 가지 경로:
  1) 감사(audit) — 결정경로(safety_citations.json) 인용에 적용.
     화이트리스트 밖 조문을 '로그만' 남긴다. 문서 내용은 건드리지 않는다(§6 저하 없음).
     → "자주 인용 시도되는 보류 조문" 빈도 데이터 수집용.
  2) 게이트(gate) — VLM 자유생성 '관련법령'에 적용(실제 환각 구멍).
     화이트리스트 밖/파싱불가 조문을 '안전관리자 확인 필요'로 치환 + 로그.

폴백 정책 ★[2단계 A-5, 2026-10-10 변경 — 사용자 승인]:
  예전에는 statutes.yaml·yaml 미비 시 게이트를 '비활성(전부 통과)'로 뒀다(fail-open).
  그러나 이 게이트가 막는 것은 **VLM 이 지어낸 법조문의 문서 인용**이라, 조용한 비활성은
  곧 환각 조문이 위험성평가서에 실리는 사고다 → 게이트 경로(gate_vlm_text)는 미로드 시
  생성 조문을 통과시키지 않고 '안전관리자 확인 필요(사유)'로 치환한다(fail-closed).
  결정경로 감사(audit_citations)는 원래 비파괴(로그만)라 미로드 시 기존대로 아무것도 안 한다.
  화이트리스트는 지연 적재 + 파일 변경 감지로 **재시작 없이** 재적재된다(A-5 ②).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("vigent.legal")

_ROOT = Path(__file__).resolve().parent.parent          # vigent-core/ -> VIGENT/
_STATUTES = _ROOT / "data" / "legal" / "statutes.yaml"
_BLOCKED_LOG = _ROOT / "data" / "legal" / "blocked_citations.log"

_ART_RE = re.compile(r"제\s*(\d+)\s*조")


def _canon_law(source: str) -> str | None:
    """법령명 문자열 → 정규 키. 법령이 아니면(KOSHA 가이드·IEC 등) None."""
    s = (source or "").strip()
    if not s:
        return None
    # '산업안전보건기준에 관한 규칙' 이 '산업안전보건' 을 포함하므로 규칙을 먼저 판정
    if "안전보건규칙" in s or "기준에 관한 규칙" in s or "기준에관한규칙" in s:
        return "rule"
    if "산업안전보건법 시행령" in s or "산업안전보건법시행령" in s:
        return "osha_enf"          # 시행령(현재 화이트리스트 밖)
    if "산업안전보건법" in s:
        return "osha"
    if "중대재해" in s:
        return "cap"               # 중처법/시행령(현재 화이트리스트 밖)
    if "위험성평가에 관한 지침" in s or "고시" in s:
        return "notice"            # 고시(현재 화이트리스트 밖)
    # KOSHA Guide / IEC / ISO 등은 법령이 아님 → 감사 대상에서 제외
    if "KOSHA" in s or "IEC" in s or "ISO" in s or "가이드" in s.lower() or "guide" in s.lower():
        return None
    return None


def _art_num(clause: str) -> int | None:
    m = _ART_RE.search(clause or "")
    return int(m.group(1)) if m else None


def load_whitelist() -> dict[str, Any]:
    """statutes.yaml 로드. 실패 시 enabled=False (게이트 비활성 폴백)."""
    try:
        import yaml  # noqa: PLC0415
    except ImportError as e:   # [2단계 A-9] 사유를 담아 반환(예전 무주석 except Exception + 침묵 — 원인 추적 불가)
        return {"enabled": False, "reason": f"yaml 라이브러리 없음({e})", "index": {}, "meta": {}}
    if not _STATUTES.exists():
        return {"enabled": False, "reason": "statutes.yaml 없음", "index": {}, "meta": {}}
    try:
        with open(_STATUTES, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:  # noqa: BLE001
        return {"enabled": False, "reason": f"파싱 실패: {e}", "index": {}, "meta": {}}

    index: dict[str, list[tuple[int, int, str]]] = {}
    for s in data.get("statutes", []):
        if str(s.get("status", "")).strip() != "active":
            continue
        lk = str(s.get("law_key", "")).strip()
        if not lk:
            continue
        lo = int(s.get("article_from", 0) or 0)
        hi = int(s.get("article_to", lo) or lo)
        has_text = bool(str(s.get("text") or "").strip()) and "정본" in str(s.get("text_status", ""))  # noqa: F841  향후 내용대조 승격용(의도적 미사용)
        index.setdefault(lk, []).append((lo, hi, s.get("article", ""), ))
        # has_text 는 향후 내용 대조 승격용(현재 정본 0건이라 미사용)
    return {"enabled": True, "index": index, "meta": data.get("_meta", {})}


# [2단계 A-5 ②] import 시 1회 로드 → 지연 적재 + 변경 감지 재적재.
#   예전 `_WL = load_whitelist()` 는 파일을 나중에 넣어도 프로세스 재시작까지 비활성이었다.
#   성공 상태는 파일 서명(존재+mtime)이 같으면 캐시를 쓰고, 실패 상태는 매 호출 재시도한다
#   (게이트 호출은 문서 생성 때만이라 비용 무시 가능). 미로드 ERROR 는 같은 사유당 1회만.
_WL_CACHE: dict[str, Any] = {}


def _file_sig() -> tuple[bool, float]:
    try:
        return (True, _STATUTES.stat().st_mtime) if _STATUTES.exists() else (False, 0.0)
    except OSError:
        return (False, 0.0)


def _wl() -> dict[str, Any]:
    sig = _file_sig()
    cached = _WL_CACHE.get("wl")
    if cached is not None and cached.get("enabled") and _WL_CACHE.get("sig") == sig:
        return cached
    wl = load_whitelist()
    _WL_CACHE["wl"] = wl
    _WL_CACHE["sig"] = sig
    if not wl.get("enabled") and _WL_CACHE.get("warned_reason") != wl.get("reason"):
        _WL_CACHE["warned_reason"] = wl.get("reason")
        _LOG.error("법령 화이트리스트 미로드(%s) — VLM 법령 게이트 fail-closed: 생성 조문은 "
                   "'안전관리자 확인 필요'로 치환된다. data/legal/statutes.yaml 을 확인하라.", wl.get("reason"))
    elif wl.get("enabled"):
        _WL_CACHE.pop("warned_reason", None)
    return wl


def is_whitelisted(law_key: str | None, art_num: int | None) -> bool:
    wl = _wl()
    if not wl.get("enabled"):
        return True                       # 감사(비파괴) 경로 폴백 — 게이트 경로는 gate_vlm_text 가 먼저 차단한다
    if law_key is None or art_num is None:
        return False
    for lo, hi, _art in wl["index"].get(law_key, []):
        if lo <= art_num <= hi:
            return True
    return False


def _log_blocked(rec: dict[str, Any]) -> None:
    try:
        _BLOCKED_LOG.parent.mkdir(parents=True, exist_ok=True)
        # [Z-2] D그룹(운영 로그) 회전 — 법적 보관 요구가 없는 로그라 크기상한만 넘으면 회전
        import tuning
        from retention import rotate_if_large
        rotate_if_large(_BLOCKED_LOG, tuning.val("retention", "ops_log_max_mb", 50))
        rec = {"ts": datetime.now().isoformat(timespec="seconds"), **rec}
        with open(_BLOCKED_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        pass                              # 로깅 실패가 문서 생성을 막지 않는다(§6)


def audit_citations(citations: list[dict[str, Any]], doc_type: str, rule_id: str = "") -> list[dict]:
    """결정경로 인용 감사: 보류 조문을 '로그만'. 문서는 안 건드림(비파괴).
    반환: 보류로 기록된 항목 목록(테스트/리포트용)."""
    if not _wl().get("enabled"):
        return []                         # 비파괴 감사 — 미로드 시 기존대로 아무것도 안 함(문서 불변)
    blocked = []
    for c in citations or []:
        lk = _canon_law(c.get("source", ""))
        if lk is None:
            continue                      # 법령 아님(가이드/IEC) → 감사 제외
        an = _art_num(c.get("clause", ""))
        if is_whitelisted(lk, an):
            continue
        rec = {"law": c.get("source", ""), "article": c.get("clause", ""),
               "law_key": lk, "art_num": an, "doc_type": doc_type,
               "rule_id": rule_id, "reason": "보류(화이트리스트 밖)"}
        _log_blocked(rec)
        blocked.append(rec)
    return blocked


def gate_vlm_text(text: str, doc_type: str = "VLM") -> str:
    """VLM 자유생성 '관련법령' 게이트: 화이트리스트 밖/파싱불가 조문을
    '안전관리자 확인 필요'로 치환 + 로그. 화이트리스트 내 조문만 통과.

    [2단계 A-5 ①] 화이트리스트 미로드 시 fail-closed — 예전엔 원문 그대로 통과(fail-open)라
    statutes.yaml 이 없거나 깨진 상태에서 VLM 환각 조문이 평가서에 그대로 인용됐다.
    검증할 수 없는 생성 조문은 전부 '안전관리자 확인 필요(사유)'로 치환한다."""
    raw = str(text or "").strip()
    if not raw:
        return raw
    wl = _wl()
    if not wl.get("enabled"):
        _log_blocked({"law": raw[:60], "article": "?", "law_key": None, "art_num": None,
                      "doc_type": doc_type, "reason": f"게이트 미로드 차단({wl.get('reason')})"})
        return f"안전관리자 확인 필요(법령 게이트 미로드: {wl.get('reason')})"
    out = []
    changed = False
    for seg in re.split(r"[;\n]", raw):
        seg = seg.strip()
        if not seg:
            continue
        lk = _canon_law(seg)
        an = _art_num(seg)
        if lk is not None and an is not None and is_whitelisted(lk, an):
            out.append(seg)               # 화이트리스트 통과
        else:
            out.append("안전관리자 확인 필요")
            changed = True
            _log_blocked({"law": seg[:60], "article": f"제{an}조" if an else "?",
                          "law_key": lk, "art_num": an, "doc_type": doc_type,
                          "reason": "VLM 자유생성 차단(화이트리스트 밖/파싱불가)"})
    result = "; ".join(dict.fromkeys(out))  # 중복 '확인 필요' 축약
    return result if changed or result else raw


def frequency_report(top: int = 20) -> dict[str, Any]:
    """blocked_citations.log 집계 → 보류 조문 인용 빈도 순위."""
    counts: dict[str, dict[str, Any]] = {}
    total = 0
    if _BLOCKED_LOG.exists():
        for line in _BLOCKED_LOG.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            key = f"{r.get('law','?')} {r.get('article','?')}"
            e = counts.setdefault(key, {"law": r.get("law", ""), "article": r.get("article", ""),
                                        "count": 0, "doc_types": {}, "rules": set()})
            e["count"] += 1
            e["doc_types"][r.get("doc_type", "?")] = e["doc_types"].get(r.get("doc_type", "?"), 0) + 1
            if r.get("rule_id"):
                e["rules"].add(r["rule_id"])
            total += 1
    ranked = sorted(counts.values(), key=lambda x: x["count"], reverse=True)[:top]
    for e in ranked:
        e["rules"] = sorted(e["rules"])
    wl = _wl()
    return {"total_blocked": total, "distinct": len(counts), "ranking": ranked,
            "whitelist_enabled": wl.get("enabled"), "whitelist_reason": wl.get("reason", "active")}


if __name__ == "__main__":
    wl = load_whitelist()
    print("enabled:", wl.get("enabled"), wl.get("reason", ""))
    print("law_keys:", {k: len(v) for k, v in wl.get("index", {}).items()})
    print(json.dumps(frequency_report(), ensure_ascii=False, indent=2))
