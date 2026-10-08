#!/usr/bin/env python3
"""scripts/data/public_ds_size.py — 공개 데이터셋 표본 수신 전 **크기만** 조회한다(본문 다운로드 없음). [2026-09-27]

  roboflow <workspace/project/version> [--fmt coco]  : export 링크 발급 → HEAD 로 Content-Length
  gdrive <file_id>                                  : Google Drive 대용량 confirm 페이지를 거쳐 HEAD 로 크기
키(ROBOFLOW_API_KEY)는 .env 에서 읽고 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

# [2026-10-08 새 환경 점검] cp949 콘솔(PYTHONUTF8 미설정 Windows)에서 한글·기호 print 가 UnicodeEncodeError 로 죽던 것 —
#   실측: setup_env.py 가 새 clone 의 첫 print 에서 종료돼 pip 설치가 시작도 안 됐다. stdout/stderr 를 UTF-8 로 재설정한다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from roboflow_probe import load_key  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 vigent-probe"}


def head_len(url: str) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return int(r.headers.get("Content-Length") or -1), r.headers.get("Content-Type", "")
    except Exception as ex:
        return -1, type(ex).__name__ + ": " + str(ex)[:80]


def roboflow_export(slug: str, fmt: str) -> dict:
    key = load_key()
    url = f"https://api.roboflow.com/{slug}/{fmt}?api_key={urllib.parse.quote(key)}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
        j = json.loads(r.read().decode("utf-8"))
    link = (j.get("export") or {}).get("link", "")
    n, ct = head_len(link) if link else (-1, "no link")
    return {"slug": slug, "fmt": fmt, "bytes": n, "mb": round(n / 1048576, 1) if n > 0 else None, "content_type": ct, "link_host": urllib.parse.urlparse(link).netloc}


def gdrive_size(fid: str) -> dict:
    url = f"https://drive.usercontent.google.com/download?id={fid}&export=download"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        ct = r.headers.get("Content-Type", ""); body = r.read(200000) if "text/html" in ct else b""
        if "text/html" not in ct:
            return {"id": fid, "bytes": int(r.headers.get("Content-Length") or -1), "direct": True}
    html = body.decode("utf-8", "replace")
    params = dict(re.findall(r'name="(\w+)" value="([^"]*)"', html))
    size = re.search(r"\(([\d.]+[KMG])\)", html)
    final = "https://drive.usercontent.google.com/download?" + urllib.parse.urlencode(params)
    return {"id": fid, "confirm_params": sorted(params), "size_on_page": size.group(1) if size else None, "final_url_host": urllib.parse.urlparse(final).netloc,
            "filename": (re.search(r'class="uc-name-size"><a[^>]*>([^<]+)</a>', html) or [None, None])[1]}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("kind", choices=["roboflow", "gdrive"]); ap.add_argument("target"); ap.add_argument("--fmt", default="coco")
    a = ap.parse_args()
    out = roboflow_export(a.target, a.fmt) if a.kind == "roboflow" else gdrive_size(a.target)
    print(json.dumps(out, ensure_ascii=False)); return 0


if __name__ == "__main__":
    sys.exit(main())
