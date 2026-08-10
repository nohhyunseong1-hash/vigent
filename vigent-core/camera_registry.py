"""camera_registry — 카메라 영구 등록·관리(3.0 Phase 1).

자격증명 보안: rtsp_url 의 user:pass 는 **원본은 data/camera_secrets.json(.gitignore 대상 data/)** 에만
두고, 공개 레지스트리(data/cameras.json)·API 응답·로그·이벤트에는 항상 **마스킹된 source** 만 노출한다.
워커는 source_of(id) 로 원본(연결용)을 받고, 화면/로그/이벤트는 mask_source 로 가린다.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_PUB = _DATA / "cameras.json"          # 공개(마스킹) 레지스트리 — data/ 라 gitignore
_SEC = _DATA / "camera_secrets.json"   # 원본 source(자격증명 포함) — data/ 라 gitignore
_LOCK = threading.RLock()

_CRED_RE = re.compile(r"^(\w+://)([^/@]+)@(.+)$")   # scheme://user:pass@rest 전체매칭(source 필드용)
_CRED_ANYWHERE_RE = re.compile(r"(\w+://)([^\s/@]+)@")   # 긴 문자열 어디든 등장하는 자격증명(예외 메시지용)


def mask_source(src: str) -> str:
    """rtsp://user:pass@host/... → rtsp://***:***@host/... (자격증명 없으면 원본 그대로)."""
    m = _CRED_RE.match(src or "")
    return f"{m.group(1)}***:***@{m.group(3)}" if m else (src or "")


def scrub_credentials(text: str) -> str:
    """[S2-수정] 임의 텍스트(예외 메시지·트레이스백) 안에 섞인 scheme://user:pass@ 패턴을
    전부 마스킹한다. mask_source 는 문자열 전체가 source 하나일 때만 매칭하므로,
    "OpenCV: rtsp://admin:secret@1.2.3.4/... 열기 실패" 처럼 긴 메시지 중간에 자격증명이
    끼어 있는 경우는 못 잡는다 — 이 함수는 문자열 어디든 등장하는 패턴을 찾아 마스킹한다."""
    return _CRED_ANYWHERE_RE.sub(r"\1***:***@", text or "")


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  파일 없음/깨짐 → 빈 상태
        return {}


def _save(path: Path, data: dict) -> None:
    _DATA.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _find(cams: list[dict], cid: str) -> dict | None:
    return next((c for c in cams if c.get("id") == cid), None)


def list_cameras() -> list[dict[str, Any]]:
    """공개 목록(마스킹된 source). API 응답용."""
    with _LOCK:
        return list(_load(_PUB).get("cameras", []))


def get(cid: str) -> dict | None:
    with _LOCK:
        return _find(_load(_PUB).get("cameras", []), cid)


def upsert(cid: str, name: str | None = None, source: str | None = None,
           enabled: bool | None = None, fps: float | None = None,
           zone: Any = None) -> dict[str, Any]:
    """등록/수정. source 지정 시 원본은 secrets, 공개엔 마스킹 저장."""
    with _LOCK:
        pub = _load(_PUB)
        cams = pub.setdefault("cameras", [])
        sec = _load(_SEC)
        c = _find(cams, cid)
        if c is None:
            c = {"id": cid, "name": cid, "enabled": False, "fps": 2.0, "zone": None,
                 "source": "", "has_creds": False}
            cams.append(c)
        if name is not None:
            c["name"] = name
        if fps is not None:
            c["fps"] = float(fps)
        if zone is not None:
            c["zone"] = zone
        if enabled is not None:
            c["enabled"] = bool(enabled)
        if source is not None:
            sec[cid] = source                          # 원본 → secrets(gitignore)
            c["source"] = mask_source(source)          # 공개 = 마스킹
            c["has_creds"] = c["source"] != source
        _save(_PUB, pub)
        _save(_SEC, sec)
        return dict(c)


def set_enabled(cid: str, enabled: bool) -> dict | None:
    with _LOCK:
        if get(cid) is None:
            return None
        return upsert(cid, enabled=enabled)


def delete(cid: str) -> bool:
    with _LOCK:
        pub = _load(_PUB)
        cams = pub.get("cameras", [])
        before = len(cams)
        cams[:] = [c for c in cams if c.get("id") != cid]
        sec = _load(_SEC)
        sec.pop(cid, None)
        _save(_PUB, pub)
        _save(_SEC, sec)
        return len(cams) < before


def source_of(cid: str) -> str | None:
    """워커용 **원본** source(자격증명 포함). secrets 우선, 없으면 공개 source(파일/웹캠 등)."""
    with _LOCK:
        sec = _load(_SEC)
        if cid in sec:
            return sec[cid]
        c = get(cid)
        return c.get("source") if c else None
