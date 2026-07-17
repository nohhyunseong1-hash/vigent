"""web_util.py — 라우터 공통 웹 헬퍼 (P1-7 분할, move-only).

이미지 디코드·검출 박스·위험구역 조회/저장·안전라벨 필터 등 여러 도메인이 공유하는 헬퍼.
★ main 을 import 하지 않는다(순환 방지). 공유 상태(STATE/load_theme)는 app_state 에서 가져온다.
※ 공개 헬퍼 함수는 언더스코어 없는 이름(B3). 내부 전용(_zone_cfg_path·_load_allowed_webhook_hosts)과
  모듈 상수(_HERE·_ROOT·_SAFETY_KEEP·_TBM_CSS)는 _ 유지.
"""
from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

import runtime_config
from app_state import STATE
from app_state import load_theme as _load_theme
from fastapi import HTTPException

if TYPE_CHECKING:                     # numpy 는 타입검사 전용(런타임 import 는 함수 내부 유지 — 동작·기동비용 불변)
    import numpy as np

_HERE = Path(__file__).resolve().parent            # vigent-core/ (main._HERE 와 동일)
_ROOT = _HERE.parent                               # 프로젝트 루트(main._ROOT 와 동일 값, 독립 계산)

_SAFETY_KEEP = {"person", "knife", "scissors", "car", "truck", "bus", "motorcycle",
                "bicycle", "forklift", "train", "boat", "fire", "smoke", "cigarette"}


def decode_data_url(image: str) -> "np.ndarray | None":
    """data:image/...;base64,... → cv2 BGR numpy. 실패하면 None."""
    import base64
    import re

    import cv2
    import numpy as np
    m = re.match(r"^data:image/\w+;base64,(.+)$", image or "", re.S)
    if not m:
        return None
    try:
        buf = np.frombuffer(base64.b64decode(m.group(1)), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:  # noqa: BLE001
        return None

def img_from_b64(raw: "str | None") -> "np.ndarray | None":
    """base64 또는 data:URL 문자열 → BGR numpy(없거나 실패 시 None). data: 접두어 자동 보정.
    여러 엔드포인트의 동일 디코드 블록을 한 곳으로 통합."""
    if not raw:
        return None
    rawd = raw if str(raw).startswith("data:") else "data:image/jpeg;base64," + raw
    return decode_data_url(rawd)

def incident_boxes(out: dict, prox: list) -> list:
    """탐지 결과 → 박스 목록(정규화 bbox + 위험여부). 협착쌍·화재·보호구미착용을 위험으로 표시."""
    def overlap(a: "list[float]", b: "list[float]") -> bool:
        ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy > 0
    prox_persons = [p.get("person_bbox") for p in (prox or [])]
    has_prox = bool(prox)
    boxes = []
    for d in out.get("detections", []):
        cls = (d.get("label") or "")
        cl = cls.lower()
        bb = d.get("bbox", [0, 0, 0, 0])
        hazard = (cl in ("fire", "smoke") or cl.startswith("no-")
                  or (cl == "forklift" and has_prox)
                  or any(pb and overlap(bb, pb) for pb in prox_persons))
        boxes.append({"class": cls, "bbox": [round(v, 4) for v in bb], "hazard": bool(hazard)})
    return boxes

def zone_points(z: dict) -> list[tuple[float, float]]:
    """위험구역 json dict → 정규화 (x,y) 튜플 목록. worker·rfdetr_service 공용(P2-11 중복 제거).
    ※ 파일 읽기·에러처리·경로결정은 각 호출자가 유지(계약이 달라 함수 자체는 통합 안 함).순수 변환만 공유."""
    return [(p["x"], p["y"]) for p in z.get("points", [])]

def _zone_cfg_path(theme: str, key: str) -> str | None:
    bundle = STATE.get(theme) or _load_theme(theme)
    return (bundle["config"].raw.get("judgment", {}) or {}).get("zones", {}).get(key)

def zone_get(theme: str, key: str) -> dict:
    zone_path = _zone_cfg_path(theme, key)
    if not zone_path:
        return {"points": []}
    p = runtime_config.read_path(zone_path)   # B2: 런타임(data/) 우선 → 없으면 config/ 시드
    if not p.exists():
        return {"points": []}
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def zone_set(theme: str, key: str, payload: dict) -> dict:
    zone_path = _zone_cfg_path(theme, key)
    if not zone_path:
        raise HTTPException(status_code=400, detail=f"vision.yaml 에 {key} 경로가 없음")
    points = []
    for pt in payload.get("points", []) or []:
        try:
            x, y = float(pt["x"]), float(pt["y"])
        except (KeyError, TypeError, ValueError):
            raise HTTPException(status_code=400, detail="points 형식 오류({x,y} 필요)")
        points.append({"x": max(0.0, min(1.0, x)), "y": max(0.0, min(1.0, y))})
    p = runtime_config.runtime_path(zone_path)   # B2: 런타임 write 는 항상 data/ 하위(config/ 는 시드로 불변)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"points": points}, f, ensure_ascii=False)
    return {"ok": True, "count": len(points), "saved_to": str(p.relative_to(_ROOT))}

def is_safety_label(label: "str | None") -> bool:   # 본문이 (label or "")로 None 안전 → 시그니처도 그에 맞춤(P2-12)
    l = (label or "").lower()
    if l in _SAFETY_KEEP:
        return True
    return any(k in l for k in ("hardhat", "helmet", "vest", "mask", "glove", "goggle", "boots"))


def _load_allowed_webhook_hosts() -> set[str]:
    """config/security.json 의 allowed_webhook_hosts(아웃바운드 웹훅 목적지 화이트리스트)."""
    try:
        f = _ROOT / "config" / "security.json"
        return set(json.loads(f.read_text(encoding="utf-8")).get("allowed_webhook_hosts") or [])
    except Exception:  # noqa: BLE001  설정 없으면 빈 집합(전부 미허용 = fail-closed)
        return set()

def webhook_allowed(url: str) -> bool:
    """url 의 호스트가 화이트리스트에 있으면 True(서브도메인 endswith 매칭)."""
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return False
    return any(host == h or host.endswith("." + h) for h in _load_allowed_webhook_hosts())


@functools.lru_cache(maxsize=None)
def tpl(name: str) -> str:
    """templates/<name> 를 1회 읽어 캐시. 기동 후 첫 요청에 로드·이후 재사용."""
    return (_HERE / "templates" / name).read_text(encoding="utf-8")

# TBM·auto 페이지 공유 CSS(P1-7) — tbm·safety_core 두 도메인이 함께 쓰므로 web_util 상주.
_TBM_CSS = tpl("tbm.css")   # templates/tbm.css 로드 — 내용 분리 전과 바이트 동일

def env_or_dotenv(key: str) -> str:
    """환경변수 우선, 없으면 .env 에서 key 값을 읽는다(비밀은 코드/응답에 노출 안 함)."""
    v = os.environ.get(key, "").strip()
    if v:
        return v
    envf = _ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith(key):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""

def evidence_url(path: str | None) -> str | None:
    """data/evidence/... 저장경로 → /evidence/... 서빙 URL."""
    if path and path.startswith("data/evidence/"):
        return "/evidence/" + path[len("data/evidence/"):]
    return None

def product_version() -> str:
    """제품 버전 단일 소스(VERSION 파일). /health·app.version 이 함께 사용."""
    try:
        return (_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        return "unknown"
