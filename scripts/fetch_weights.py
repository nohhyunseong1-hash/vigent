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


def github_token() -> str:
    """GitHub 토큰을 찾는다. 없으면 빈 문자열(공개 저장소면 없어도 된다).

    [2026-08-21] 저장소를 **비공개로 전환**하면서 필요해졌다 — 비공개 릴리스 자산은
    인증 없이 받으면 **403 이 아니라 404** 로 응답한다(존재 자체를 숨긴다). 그래서
    "파일이 없다" 와 "권한이 없다" 가 겉으로 구분되지 않아, 아래 download() 가 이를
    명시적으로 갈라 안내한다.

    찾는 순서:
      1. 환경변수 GITHUB_TOKEN / GH_TOKEN / VIGENT_GITHUB_TOKEN
      2. git 자격증명 도우미(`git credential fill`) — Windows 는 GCM 이 이미 갖고 있는 경우가 많다
    ★토큰 값은 절대 출력하지 않는다(로그·콘솔 유출 방지).
    """
    import subprocess
    for k in ("GITHUB_TOKEN", "GH_TOKEN", "VIGENT_GITHUB_TOKEN"):
        v = os.environ.get(k, "").strip()
        if v:
            return v
    try:
        r = subprocess.run(["git", "credential", "fill"],
                           input="protocol=https\nhost=github.com\n\n",
                           capture_output=True, text=True, timeout=20)
        for line in (r.stdout or "").splitlines():
            if line.startswith("password="):
                return line.split("=", 1)[1].strip()
    except Exception:  # noqa: BLE001  자격증명 도우미가 없거나 실패 → 토큰 없음으로 처리
        pass
    return ""


def release_asset_url(repo: str, tag: str, filename: str, token: str) -> str:
    """비공개 릴리스에서 파일 하나의 **API 자산 URL** 을 찾는다(없으면 빈 문자열).

    비공개 저장소는 `releases/download/...` 브라우저 URL 로는 토큰을 붙여도 받기 어렵다.
    자산 API(`/repos/{repo}/releases/assets/{id}`)에 `Accept: application/octet-stream` 을
    주는 것이 정식 경로다.
    """
    if not token:
        return ""
    api = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    req = urllib.request.Request(api, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "vigent-fetch-weights",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rel = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001  릴리스 조회 실패 → 호출자가 기존 경로로 폴백
        return ""
    for a in rel.get("assets") or []:
        if a.get("name") == filename:
            return str(a.get("url") or "")
    return ""


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


def target_path(entry: dict[str, Any]) -> Path:
    """항목의 로컬 경로 — `dest`(weights/ 아래 하위 디렉터리)가 있으면 그 밑. [CODE_REVIEW M7-2b] rtmlib 포즈 캐시는
    `rtm_cache/hub/checkpoints/`(= TORCH_HOME/hub/checkpoints, install_service.ps1·run.ps1 이 TORCH_HOME 을 그리로 고정).
    [5단계 마무리, 2026-09-06] `root_dest`(저장소 루트 기준 디렉터리)가 있으면 weights/ 밖 — go2rtc.exe 같은 바이너리는 `bin/`."""
    root_dest = str(entry.get("root_dest") or "").strip().strip("/\\")
    if root_dest:
        return _ROOT / root_dest / entry["file"]
    dest = str(entry.get("dest") or "").strip().strip("/\\")
    return (_WEIGHTS / dest / entry["file"]) if dest else (_WEIGHTS / entry["file"])


def verify(entry: dict[str, Any]) -> tuple[str, str]:
    """로컬 파일 상태 → (상태, 설명)."""
    p = target_path(entry)
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
    raw = str(entry.get("url") or "")
    if raw.startswith("local:") and not os.environ.get(str(man.get("base_url_env") or "VIGENT_WEIGHTS_BASE_URL")):
        # [2026-10-08 새 환경 점검] Release 에 올리지 않은 산출물(예: fk510_smoke) — 예전엔 urlopen 이 'unknown url type: local' 로
        #   죽어 무엇을 해야 하는지 알 수 없었다. 어디서 복사하고 어떻게 확인하는지를 돌려준다.
        return False, (f"Release 미업로드(local) — 개발기 또는 USB 스테이지의 portable\\app\\vigent-core\\weights\\{entry['file']} 를 "
                       f"{target_path(entry)} 로 복사한 뒤 `--check --all` 로 SHA 확인(기대 {str(entry.get('sha256', ''))[:16]}…). 원본: {raw[6:]}")
    url = resolve_url(entry, man)
    if not url or "PLACEHOLDER" in url:
        return False, "다운로드 URL 미설정(매니페스트 url 또는 VIGENT_WEIGHTS_BASE_URL 필요)"
    headers: dict[str, str] = {"User-Agent": "vigent-fetch-weights"}
    # [2026-08-21] 비공개 저장소 대응 — release: 스킴이면 토큰이 있을 때 자산 API 로 바꾼다.
    #   토큰이 없으면 기존 브라우저 URL 그대로 시도한다(공개 저장소면 그대로 받아진다).
    if str(entry.get("url") or "").startswith("release:"):
        tok = github_token()
        if tok:
            repo = str(man.get("release_repo") or "")
            tag = str(entry["url"]).split(":", 1)[1] or str(man.get("release_tag") or "")
            api_url = release_asset_url(repo, tag, entry["file"], tok)
            if api_url:
                url = api_url
                headers["Accept"] = "application/octet-stream"
            headers["Authorization"] = f"Bearer {tok}"
    dst = target_path(entry)
    tmp = dst.with_suffix(dst.suffix + ".part")
    dst.parent.mkdir(parents=True, exist_ok=True)
    member = str(entry.get("archive_member") or "")      # [M7-2b] zip 안의 파일 1개만 꺼낸다(rtmlib 은 end2end.onnx)
    try:
        print(f"    ↓ {url}")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as r, tmp.open("wb") as f:
            total = 0
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                total += len(b)
                print(f"\r      {total/1048576:,.0f} MB", end="", flush=True)
        print()
        if member:
            import zipfile
            with zipfile.ZipFile(tmp) as z:
                names = [n for n in z.namelist() if n.endswith(member)]
                if len(names) != 1:
                    raise RuntimeError(f"압축 안에 '{member}' 가 {len(names)}개(1개여야 함): {names[:3]}")
                extracted = dst.with_suffix(dst.suffix + ".extract")
                with z.open(names[0]) as src, extracted.open("wb") as out:
                    while True:
                        b = src.read(1 << 20)
                        if not b:
                            break
                        out.write(b)
            tmp.unlink(missing_ok=True)
            tmp = extracted
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
