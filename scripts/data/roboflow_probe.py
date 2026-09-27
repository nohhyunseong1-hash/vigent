#!/usr/bin/env python3
"""scripts/data/roboflow_probe.py — Roboflow Universe 프로젝트의 **메타데이터만**(라이선스·클래스·장수·버전) API 로 조회한다. 다운로드 없음. [2026-09-27]

키는 .env 의 ROBOFLOW_API_KEY 를 읽고 절대 출력하지 않는다. 결과는 JSON 으로 저장.
사용: python scripts/data/roboflow_probe.py <workspace/project> [...] --out <json>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_key() -> str:
    k = os.environ.get("ROBOFLOW_API_KEY", "")
    if not k:
        for ln in (Path(__file__).resolve().parents[2] / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
            if ln.startswith("ROBOFLOW_API_KEY="):
                k = ln.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        raise SystemExit("ROBOFLOW_API_KEY 없음(.env)")
    return k


def get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "vigent-probe"}), timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def probe(slug: str, key: str) -> dict:
    ws, proj = slug.split("/", 1)
    try:
        j = get(f"https://api.roboflow.com/{ws}/{proj}?api_key={urllib.parse.quote(key)}")
    except Exception as ex:                       # 404/403 등 — 키는 URL 에 있으므로 메시지에서 뺀다
        return {"slug": slug, "error": type(ex).__name__ + ": " + str(ex).split("?")[0][:120]}
    p = j.get("project", {}); vers = j.get("versions", [])
    latest = max(vers, key=lambda v: int(str(v.get("id", "0/0")).rsplit("/", 1)[-1] or 0)) if vers else {}
    return {"slug": slug, "name": p.get("name"), "license": p.get("license"), "type": p.get("type"), "images": p.get("images"),
            "classes": p.get("classes"), "public": p.get("public"), "created": p.get("created"), "updated": p.get("updated"),
            "versions": len(vers), "latest_version": latest.get("id"), "latest_images": latest.get("images"),
            "latest_preprocessing": latest.get("preprocessing"), "latest_augmentation": latest.get("augmentation"),
            "latest_exports": latest.get("exports"), "latest_splits": latest.get("splits")}


def main() -> int:
    ap = argparse.ArgumentParser(); ap.add_argument("slugs", nargs="+"); ap.add_argument("--out", required=True)
    a = ap.parse_args(); key = load_key(); out = [probe(s, key) for s in a.slugs]
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for o in out:
        if "error" in o:
            print(f"✗ {o['slug']}: {o['error']}"); continue
        cls = o["classes"] or {}
        print(f"{o['slug']}: license={o['license']} images={o['images']} versions={o['versions']} latest={o['latest_version']}({o['latest_images']}) classes={dict(list(cls.items())[:12])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
