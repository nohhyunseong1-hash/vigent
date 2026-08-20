#!/usr/bin/env python3
"""[B8] 가중치 자동 조달 — weights_manifest.json 을 읽어 없는 파일만 받고 SHA256 대조.

배경(audit/site_readiness_2026-08-16.md 🔴B8): 가중치는 `.gitignore` 라 clone 만으로는 없고,
자동 조달 스크립트가 저장소에 **0건**이었다. 지금까지 사람이 브라우저로 받아 손으로 넣었다 —
새 PC 설치가 재현 불가능했고, 잘못된 파일이 들어가도 알 수 없었다.

동작:
  1. weights_manifest.json 의 각 항목에 대해 로컬 파일 존재·크기·SHA256 확인
  2. 없거나 어긋나면 GitHub Release(`release_tag`)에서 내려받아 재검증
  3. 하나라도 **required 파일**이 실패하면 이유를 명시하고 **종료 코드 1**

기본은 required 만 받는다(`--all` 로 선택 파일까지). 다운로드 위치는
`VIGENT_WEIGHTS_BASE_URL` 로 덮어쓸 수 있다(사내 미러 등).

사용:
    python scripts/fetch_weights.py            # required 만
    python scripts/fetch_weights.py --all      # 폴백·롤백용까지 전부
    python scripts/fetch_weights.py --check    # 다운로드 없이 검증만
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
_MANIFEST = _ROOT / "weights_manifest.json"
_WEIGHTS = _ROOT / "vigent-core" / "weights"

OK, MISSING, CORRUPT, FAILED = "OK", "없음", "불일치", "실패"


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def load_manifest() -> dict[str, Any]:
    if not _MANIFEST.exists():
        print(f"[오류] 매니페스트가 없습니다: {_MANIFEST}")
        sys.exit(2)
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def resolve_url(entry: dict[str, Any], man: dict[str, Any]) -> str:
    """다운로드 URL 결정. 사내 미러(env) > release: 스킴 > 매니페스트 url 원문."""
    base = os.environ.get(str(man.get("base_url_env") or "VIGENT_WEIGHTS_BASE_URL"), "").rstrip("/")
    if base:
        return f"{base}/{entry['file']}"
    url = str(entry.get("url") or "")
    if url.startswith("release:"):
        tag = url.split(":", 1)[1] or str(man.get("release_tag") or "")
        repo = str(man.get("release_repo") or "")
        return f"https://github.com/{repo}/releases/download/{tag}/{entry['file']}"
    return url


def verify(entry: dict[str, Any]) -> tuple[str, str]:
    """로컬 파일 상태 → (상태, 설명)."""
    p = _WEIGHTS / entry["file"]
    if not p.exists():
        return MISSING, "파일 없음"
    size = p.stat().st_size
    want_size = int(entry.get("size_bytes") or 0)
    if want_size and size != want_size:
        return CORRUPT, f"크기 불일치(실제 {size:,} / 기대 {want_size:,})"
    want = str(entry.get("sha256") or "")
    if not want:
        return OK, "SHA 미기재 — 크기만 확인"
    got = sha256_of(p)
    if got != want:
        return CORRUPT, f"SHA 불일치(실제 {got[:16]}… / 기대 {want[:16]}…)"
    return OK, "검증됨"


def download(entry: dict[str, Any], man: dict[str, Any]) -> tuple[bool, str]:
    url = resolve_url(entry, man)
    if not url or "PLACEHOLDER" in url:
        return False, "다운로드 URL 미설정(매니페스트 url 또는 VIGENT_WEIGHTS_BASE_URL 필요)"
    dst = _WEIGHTS / entry["file"]
    tmp = dst.with_suffix(dst.suffix + ".part")
    _WEIGHTS.mkdir(parents=True, exist_ok=True)
    try:
        print(f"    ↓ {url}")
        with urllib.request.urlopen(url, timeout=60) as r, tmp.open("wb") as f:
            total = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                total += len(b)
                print(f"\r      {total/1048576:,.0f} MB", end="", flush=True)
        print()
    except urllib.error.HTTPError as e:
        tmp.unlink(missing_ok=True)
        hint = " (비공개 저장소면 접근 권한이 필요합니다)" if e.code in (401, 403, 404) else ""
        return False, f"HTTP {e.code}{hint}"
    except Exception as ex:  # noqa: BLE001
        tmp.unlink(missing_ok=True)
        return False, f"{type(ex).__name__}: {ex}"
    tmp.replace(dst)
    st, why = verify(entry)
    if st != OK:
        return False, f"다운로드는 됐으나 검증 실패 — {why}"
    return True, "다운로드·검증 완료"


def main() -> int:
    ap = argparse.ArgumentParser(description="가중치 조달·검증(B8)")
    ap.add_argument("--all", action="store_true", help="required 외 선택 파일까지 전부")
    ap.add_argument("--check", action="store_true", help="다운로드 없이 검증만")
    a = ap.parse_args()

    man = load_manifest()
    entries = [w for w in man.get("weights", []) if a.all or w.get("required")]
    if not entries:
        print("[오류] 대상 항목이 없습니다(매니페스트 required 플래그 확인)")
        return 2

    print(f"가중치 디렉터리: {_WEIGHTS}")
    print(f"대상 {len(entries)}개 ({'전체' if a.all else 'required 만'})\n")

    failures: list[tuple[str, str]] = []
    for e in entries:
        name = e["file"]
        req = "필수" if e.get("required") else "선택"
        st, why = verify(e)
        if st == OK:
            print(f"  [OK]   {name}  ({req}) — {why}")
            continue
        print(f"  [{st}] {name}  ({req}) — {why}")
        if a.check:
            failures.append((name, why))
            continue
        ok, msg = download(e, man)
        if ok:
            print(f"  [OK]   {name} — {msg}")
        else:
            print(f"  [{FAILED}] {name} — {msg}")
            failures.append((name, msg))

    print()
    required_fail = [(n, w) for n, w in failures
                     if any(e["file"] == n and e.get("required") for e in entries)]
    if required_fail:
        print("★ 필수 가중치 조달 실패 — 서버를 기동할 수 없습니다:")
        for n, w in required_fail:
            print(f"   - {n}: {w}")
        print("\n조치: 릴리스 접근 권한을 확인하거나, 사내 미러를 쓴다면")
        print(f"      set {man.get('base_url_env')}=https://<미러주소> 후 다시 실행하세요.")
        return 1
    if failures:
        print(f"선택 가중치 {len(failures)}건 실패(서버 기동에는 지장 없음): "
              + ", ".join(n for n, _ in failures))
    print("필수 가중치 전부 확인됨.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
