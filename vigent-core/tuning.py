"""tuning.py — 현장 튜닝값 로더(config/tuning.yaml)

현장·카메라마다 달라야 하는 임계값(협착 반경·장비 크기·군집 인원·conf 등)을
코드가 아니라 config/tuning.yaml 에서 읽는다. 파일이 없거나 키가 없으면 호출부의 기본값을
쓰므로 절대 저하 없음. 환경변수가 있으면 환경변수가 우선.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CACHE: dict[str, Any] | None = None


def cfg() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        p = _ROOT / "config" / "tuning.yaml"
        _CACHE = {}
        if p.exists():
            try:
                import yaml
                _CACHE = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            except Exception:  # noqa: BLE001
                _CACHE = {}
    return _CACHE


def section(name: str) -> dict[str, Any]:
    v = cfg().get(name)
    return v if isinstance(v, dict) else {}


def val(sec: str, key: str, default: Any, env: str | None = None) -> Any:
    """tuning.yaml[sec][key] 값. 없으면 default. env 지정 시 환경변수가 최우선."""
    if env and os.environ.get(env):
        try:
            return type(default)(os.environ[env])
        except Exception:  # noqa: BLE001
            return os.environ[env]
    v = section(sec).get(key)
    return v if v is not None else default
