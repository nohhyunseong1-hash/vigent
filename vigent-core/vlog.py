"""VIGENT 로깅 인프라 (C-S1).

- 일반 로그: 콘솔 + 파일(로테이션 10MB×5). 레벨은 VIGENT_LOG_LEVEL(기본 INFO).
- 이벤트 로그: 경보·사고를 json lines 로 별도 파일에 기록 → 사고 감사 추적(D3).
사용:  from vlog import get; log = get(__name__);  log.info("...")
       from vlog import log_event; log_event({"type":"incident", ...})
로그 위치: VIGENT_LOG_DIR(기본 <repo>/logs). print 대체용(서빙 런타임).
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_LOG_DIR = Path(os.environ.get("VIGENT_LOG_DIR", str(_ROOT / "logs")))
_LEVEL = os.environ.get("VIGENT_LOG_LEVEL", "INFO").upper()

_configured = False
_event_logger: logging.Logger | None = None


def setup() -> None:
    """루트 로거 1회 구성(콘솔 + 파일 로테이션). 중복 호출 무해."""
    global _configured
    if _configured:
        return
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001  로그 디렉토리 실패해도 콘솔은 살림
        pass
    root = logging.getLogger()
    root.setLevel(_LEVEL)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)
    try:
        fh = logging.handlers.RotatingFileHandler(
            _LOG_DIR / "vigent.log", maxBytes=10_000_000, backupCount=5, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception:  # noqa: BLE001
        pass
    _configured = True


def get(name: str = "vigent") -> logging.Logger:
    """구성된 네임드 로거 반환(print 대체용)."""
    setup()
    return logging.getLogger(name)


def _events() -> logging.Logger | None:
    """구조화 이벤트 전용 로거(json lines, 콘솔 전파 안 함)."""
    global _event_logger
    if _event_logger is None:
        try:
            _LOG_DIR.mkdir(parents=True, exist_ok=True)
            lg = logging.getLogger("vigent.events")
            lg.setLevel(logging.INFO)
            lg.propagate = False
            eh = logging.handlers.RotatingFileHandler(
                _LOG_DIR / "events.jsonl", maxBytes=10_000_000, backupCount=10, encoding="utf-8")
            eh.setFormatter(logging.Formatter("%(message)s"))
            lg.addHandler(eh)
            _event_logger = lg
        except Exception:  # noqa: BLE001  이벤트 로그 실패는 기능을 죽이지 않음
            return None
    return _event_logger


def log_event(event: dict) -> None:
    """경보·사고 이벤트를 json line 한 줄로 기록(사고 감사 추적). 실패해도 무해."""
    lg = _events()
    if lg is None:
        return
    try:
        lg.info(json.dumps(event, ensure_ascii=False, default=str))
    except Exception:  # noqa: BLE001
        pass
