"""tuning.py — 현장 튜닝값 로더(config/tuning.yaml)

현장·카메라마다 달라야 하는 임계값(협착 반경·장비 크기·군집 인원·conf 등)을
코드가 아니라 config/tuning.yaml 에서 읽는다. 파일이 없거나 키가 없으면 호출부의 기본값을
쓰므로 절대 저하 없음. 환경변수가 있으면 환경변수가 우선.

★[CODE_REVIEW M7-1, 2026-09-06] **엄격 로더** — 같은 매핑에 같은 키가 두 번 나오면 예외.
  실사고: `alerts:` 최상위 블록이 4행·224행에 두 번 있어 PyYAML 이 뒤 블록으로 덮어썼고, 앞 블록의
  8개 키(notify·notify_cooldown_s·backoff_factor·backoff_max_s·quiet_reset_s·max_per_hour·queue_max·
  guard_bypass_text)는 파일에 적혀 있어도 **어떤 코드도 읽지 못했다**(17일 잠복, 코드 기본값과 같아 증상 없음).
  중복·파싱 오류는 조용히 {} 로 넘기지 않고 TuningConfigError 를 던진다 → 기동 실패로 드러난다(대표 지시).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_CACHE: dict[str, Any] | None = None


class TuningConfigError(RuntimeError):
    """tuning.yaml 이 잘못됐다(중복 키·파싱 오류). 기본값으로 조용히 대체하지 않는다."""


def _strict_loader():
    """중복 키를 거부하는 SafeLoader — 같은 매핑 안의 두 번째 키에서 즉시 예외(줄 번호 포함)."""
    import yaml

    class _Strict(yaml.SafeLoader):
        pass

    def _mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
        seen: dict[Any, int] = {}
        for k_node, _v in node.value:
            key = loader.construct_object(k_node, deep=deep)
            line = k_node.start_mark.line + 1
            if key in seen:
                raise TuningConfigError(
                    f"중복 키 '{key}' (줄 {seen[key]} 와 줄 {line}) — YAML 은 뒤 블록으로 앞 블록을 조용히 덮는다. "
                    f"두 블록을 하나로 합쳐라")
            seen[key] = line
        return yaml.SafeLoader.construct_mapping(loader, node, deep)   # type: ignore[no-any-return]

    _Strict.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)
    return _Strict


def load_strict(text: str, source: str = "<tuning>") -> dict[str, Any]:
    """YAML 문자열 → dict. 중복 키·파싱 오류는 TuningConfigError(source 포함)."""
    import yaml
    try:
        data = yaml.load(text, Loader=_strict_loader())   # noqa: S506  SafeLoader 파생
    except TuningConfigError as ex:
        raise TuningConfigError(f"{source}: {ex}") from None
    except yaml.YAMLError as ex:
        raise TuningConfigError(f"{source}: YAML 파싱 오류 — {ex}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise TuningConfigError(f"{source}: 최상위가 매핑이 아니다({type(data).__name__})")
    return data


def load_file(path: Path) -> dict[str, Any]:
    """파일 → dict(엄격). 없으면 {}."""
    if not path.exists():
        return {}
    return load_strict(path.read_text(encoding="utf-8"), source=str(path))


def cfg() -> dict[str, Any]:
    global _CACHE
    if _CACHE is None:
        _CACHE = load_file(_ROOT / "config" / "tuning.yaml")
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
