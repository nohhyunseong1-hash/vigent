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


_OVERRIDE_KEYS = {("motion", "immobile_s")}   # [R15] 카메라별 override 허용 키 — 지금은 무동작 임계 1개(일반화는 다음 단계)


def normalize_overrides(raw: Any) -> dict[str, Any]:
    """[CODE_REVIEW M7-7(b)·R15] 카메라별 override 정규화 — 허용 키만 남기고 값 검증(양수 float). 그 외 키는 버린다.
    빈 dict = 해제. 잘못된 값은 ValueError(라우트가 400 으로 바꾼다)."""
    out: dict[str, Any] = {}
    if not isinstance(raw, dict):
        return out
    for sec, key in _OVERRIDE_KEYS:
        body = raw.get(sec)
        if not isinstance(body, dict) or key not in body:
            continue
        try:
            v = float(body[key])
        except (TypeError, ValueError):
            raise ValueError(f"overrides.{sec}.{key} 는 숫자여야 한다: {body[key]!r}") from None
        if v <= 0:
            raise ValueError(f"overrides.{sec}.{key} 는 0 보다 커야 한다: {v}")
        out.setdefault(sec, {})[key] = v
    return out


_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]+:")   # 2자 이상 스킴(C: 같은 드라이브 문자는 제외)


def validate_source(src: str) -> str:
    """[1단계 M-4·M-5] 카메라 source 허용 규칙. 반환 "" = 허용, 그 외 = 거부 사유.

    실사용 조사(2026-10-10): 운영 = rtsp:// · 데모 = 웹캠 번호("0") · 벤치/부하시험 = 로컬 영상 파일.
    허용: rtsp/rtsps · 순수 숫자 · **허용 폴더(저장소 루트·VIGENT_DATA_DIR) 안의 실재 파일**.
    차단: http(s) 등 그 외 모든 스킴 — 등록된 source 는 서버(FFmpeg)가 대신 접속하고(내부망 정찰 SSRF),
    go2rtc 에도 그대로 넘어간다(go2rtc 의 exec: 스킴 = 프로세스 실행, M-5). 허용 폴더 밖 파일 경로는
    /cameras/{cid}/test 미리보기로 임의 파일이 읽히는 통로라 차단. 기존 등록분은 재검증하지 않는다."""
    s = (src or "").strip()
    if not s:
        return "source 비어 있음"
    if s.isdigit():
        return ""                                    # 웹캠 번호
    low = s.lower()
    if low.startswith(("rtsp://", "rtsps://")):
        return ""                                    # 운영 카메라
    if _SCHEME_RE.match(s):                           # http·https·exec·ffmpeg·file 등 그 외 스킴 전부
        return (f"허용되지 않는 source 스킴입니다: {s.split(':', 1)[0]} — "
                "rtsp(s):// 주소·웹캠 번호·허용 폴더 안의 영상 파일만 등록할 수 있습니다")
    try:
        p = Path(s).resolve()
    except OSError:
        return f"경로를 해석할 수 없습니다: {s}"
    if not p.exists():
        return f"파일이 없습니다: {s} — 존재하는 영상·이미지 파일만 등록할 수 있습니다"
    import data_paths
    roots = [_ROOT]
    try:
        roots.append(data_paths.data_dir())
    except Exception:  # noqa: BLE001  데이터 루트 계산 실패 시 저장소 루트만 허용
        pass
    if not any(p.is_relative_to(r) for r in roots):
        return (f"허용 폴더 밖 파일입니다: {s} — 저장소 폴더 또는 VIGENT_DATA_DIR "
                f"({'·'.join(str(r) for r in roots)}) 아래만 등록할 수 있습니다")
    return ""


def upsert(cid: str, name: str | None = None, source: str | None = None,
           enabled: bool | None = None, fps: float | None = None,
           zone: Any = None, overrides: Any = None) -> dict[str, Any]:
    """등록/수정. source 지정 시 원본은 secrets, 공개엔 마스킹 저장.
    source 는 validate_source 통과 필수(위반 시 ValueError → 라우트가 400 으로 변환).
    overrides: [R15] 카메라별 설정 override({"motion": {"immobile_s": 90}}), None=유지, {}=해제."""
    if source is not None:
        err = validate_source(source)
        if err:
            raise ValueError(err)
    norm_over = normalize_overrides(overrides) if overrides is not None else None
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
        if norm_over is not None:
            c["overrides"] = norm_over
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
