#!/usr/bin/env python3
"""VIGENT 가중치 검증·다운로드 (C-S1).

weights_manifest.json 을 기준으로 vigent-core/weights/ 의 모델 파일 무결성(SHA256)을 검증하고,
없거나 변조된 파일은 매니페스트 url 에서 내려받아 재검증한다.

사용:
  python fetch_weights.py verify              # 로컬 파일 SHA 검증(다운로드 안 함)
  python fetch_weights.py download            # 없는/변조된 파일만 내려받아 검증
  python fetch_weights.py download --force     # 전부 재다운로드
  python fetch_weights.py download --only ppe_css_v1.pt

URL: 매니페스트 url 은 자리표시자(PLACEHOLDER). 실제 호스팅은 base_url_env(VIGENT_WEIGHTS_BASE_URL)로 주입:
  VIGENT_WEIGHTS_BASE_URL=https://host/path python fetch_weights.py download
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
# 경로는 env 로 override 가능(커스텀 배포 위치·검증 테스트).
_MANIFEST = Path(os.environ.get("VIGENT_WEIGHTS_MANIFEST", str(_ROOT / "weights_manifest.json")))
_WEIGHTS = Path(os.environ.get("VIGENT_WEIGHTS_DIR", str(_ROOT / "vigent-core" / "weights")))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def _resolve_url(entry: dict, base: str) -> str:
    url = entry.get("url", "")
    if base:
        return base.rstrip("/") + "/" + entry["file"]
    return url


def verify() -> int:
    """로컬 파일 검증. 반환 = 문제 건수(0=전부 정상)."""
    man = _load_manifest()
    problems = 0
    print(f"=== 가중치 검증 (manifest schema v{man.get('schema_version')}, product {man.get('product_version')}) ===")
    for e in man["weights"]:
        p = _WEIGHTS / e["file"]
        req = "필수" if e.get("required") else "선택"
        if not p.exists():
            print(f"  [MISSING] {e['file']} ({req}) — 없음")
            if e.get("required"):
                problems += 1
            continue
        actual = _sha256(p)
        if actual == e["sha256"]:
            print(f"  [OK]      {e['file']} ({req}) — SHA 일치")
        else:
            print(f"  [TAMPERED] {e['file']} ({req}) — SHA 불일치!")
            print(f"             기대 {e['sha256'][:16]}… / 실제 {actual[:16]}…")
            problems += 1
    print(f"  → 문제 {problems}건" + ("" if problems else " (전부 정상)"))
    return problems


def download(force: bool, only: str | None) -> int:
    import urllib.request
    man = _load_manifest()
    base = os.environ.get(man.get("base_url_env", ""), "")
    problems = 0
    for e in man["weights"]:
        if only and e["file"] != only:
            continue
        p = _WEIGHTS / e["file"]
        if p.exists() and not force and _sha256(p) == e["sha256"]:
            print(f"  [SKIP] {e['file']} — 이미 검증됨")
            continue
        url = _resolve_url(e, base)
        if "PLACEHOLDER" in url:
            print(f"  [WAIT] {e['file']} — url 미정(자리표시자). VIGENT_WEIGHTS_BASE_URL 설정 필요")
            if e.get("required") and not p.exists():
                problems += 1
            continue
        print(f"  [GET]  {e['file']} ← {url}")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(url, p)
            actual = _sha256(p)
            if actual != e["sha256"]:
                print(f"  [FAIL] {e['file']} — 다운로드 후 SHA 불일치(변조·손상). 삭제.")
                p.unlink(missing_ok=True)
                problems += 1
            else:
                print(f"  [OK]   {e['file']} — 검증 완료")
        except Exception as ex:  # noqa: BLE001
            print(f"  [ERR]  {e['file']} — {type(ex).__name__}: {ex}")
            problems += 1
    return problems


def main() -> None:
    ap = argparse.ArgumentParser(description="VIGENT 가중치 검증·다운로드")
    ap.add_argument("cmd", choices=["verify", "download"], default="verify", nargs="?")
    ap.add_argument("--force", action="store_true", help="전부 재다운로드")
    ap.add_argument("--only", help="특정 파일만")
    a = ap.parse_args()
    n = verify() if a.cmd == "verify" else download(a.force, a.only)
    sys.exit(1 if n else 0)


if __name__ == "__main__":
    main()
