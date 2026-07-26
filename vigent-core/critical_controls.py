"""생명직결(즉시사망) 필수확정 통제 레지스트리 로더.

config/critical_controls.yaml 을 읽어, 점검항목(check_point)이 생명직결 통제에
해당하는지 매칭한다. 비전 미감지라도 위험수준+법령으로 '확인필요(필수)' 표면화하기 위함(§7).

폴백(§6 절대저하 없음): yaml 미설치·파일 없음·파싱 실패 시 **빈 레지스트리**로 폴백한다.
그러면 match_control 은 항상 None 을 반환하고, 호출부는 기존 '수동확인' 동작을 그대로 유지한다.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

_PATH = Path(__file__).resolve().parent.parent / "config" / "critical_controls.yaml"
_CACHE: Optional[list[dict[str, Any]]] = None


def _load() -> list[dict[str, Any]]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    controls: list[dict[str, Any]] = []
    try:
        import yaml  # 지연 import — 미설치 시 폴백
        data = yaml.safe_load(_PATH.read_text(encoding="utf-8")) or {}
        raw = data.get("controls") or []
        controls = [c for c in raw if isinstance(c, dict) and c.get("match")]
    except Exception:  # noqa: BLE001 — 어떤 실패든 빈 레지스트리로 폴백
        controls = []
    _CACHE = controls
    return controls


def match_control(check_point: str, process: str = "") -> Optional[dict[str, Any]]:
    """check_point 가 생명직결 통제 키워드에 부분일치하면 해당 control dict, 아니면 None.

    control 에 process_any 가 있으면, process(공정명)가 그 목록 중 하나를 포함할 때만 매칭한다
    (예: 소화설비는 화기작업 맥락에서만 발동 — 동일 점검항목의 타 공정 오탐 방지).
    """
    if not check_point:
        return None
    for c in _load():
        pa = c.get("process_any")
        for kw in c.get("match", []):
            if kw and kw in check_point:
                if pa and not any(p in (process or "") for p in pa):
                    break                       # 공정 맥락 불일치 → 이 control 건너뛰고 다음으로
                return c
    return None
