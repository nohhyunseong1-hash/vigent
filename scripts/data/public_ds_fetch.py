#!/usr/bin/env python3
"""scripts/data/public_ds_fetch.py — 공개 데이터셋 표본 수신(전체 export 1개 파일). 크기·zip 구조를 같은 실행에서 검증한다(규칙 11). [2026-09-27]

  roboflow <workspace/project/version> <out.zip> [--fmt coco]
  gdrive <file_id> <out.zip>
키는 .env 의 ROBOFLOW_API_KEY, 출력하지 않는다. 진행 상황은 30초마다 한 줄.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from roboflow_probe import load_key  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 vigent-fetch"}


def stream(url: str, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time(); last = t0; got = 0
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, open(out, "wb") as f:
        total = int(r.headers.get("Content-Length") or -1)
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk); got += len(chunk)
            if time.time() - last >= 30:
                last = time.time(); print(f"  {got/1048576:.0f} MB / {total/1048576:.0f} MB · {got/1048576/(last-t0):.1f} MB/s", flush=True)
    print(f"  받음 {got:,} B / 헤더 {total:,} B · {time.time()-t0:.0f}s")
    if total > 0 and got != total:
        raise SystemExit(f"★크기 불일치: {got} != {total}")
    return got


def verify_zip(p: Path) -> dict:
    if not zipfile.is_zipfile(p):
        raise SystemExit(f"★zip 아님: {p}")
    z = zipfile.ZipFile(p); bad = z.testzip(); n = len(z.namelist())
    if bad:
        raise SystemExit(f"★CRC 불일치 멤버: {bad}")
    return {"members": n, "bytes": p.stat().st_size}


def roboflow_url(slug: str, fmt: str) -> str:
    key = load_key()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.roboflow.com/{slug}/{fmt}?api_key={urllib.parse.quote(key)}", headers=UA), timeout=120) as r:
        return json.loads(r.read().decode("utf-8"))["export"]["link"]


def gdrive_url(fid: str) -> str:
    url = f"https://drive.usercontent.google.com/download?id={fid}&export=download"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        if "text/html" not in r.headers.get("Content-Type", ""):
            return url
        html = r.read(200000).decode("utf-8", "replace")
    params = dict(re.findall(r'name="(\w+)" value="([^"]*)"', html))
    if "id" not in params:
        raise SystemExit("★confirm 폼을 찾지 못함(공유 설정/할당량 확인)")
    return "https://drive.usercontent.google.com/download?" + urllib.parse.urlencode(params)


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("kind", choices=["roboflow", "gdrive"]); ap.add_argument("target"); ap.add_argument("out"); ap.add_argument("--fmt", default="coco")
    a = ap.parse_args(); out = Path(a.out)
    if out.exists() and zipfile.is_zipfile(out):
        print(f"이미 있음(zip 구조 OK): {out} {out.stat().st_size:,} B"); print(json.dumps(verify_zip(out))); return 0
    url = roboflow_url(a.target, a.fmt) if a.kind == "roboflow" else gdrive_url(a.target)
    print(f"== {a.kind} {a.target} → {out}")
    stream(url, out); info = verify_zip(out); print("검증:", json.dumps(info)); return 0


if __name__ == "__main__":
    sys.exit(main())
