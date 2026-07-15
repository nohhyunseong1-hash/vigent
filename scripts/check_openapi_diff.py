#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-7 move-only 증명 — 현재 app 의 라우트(경로·메서드)·OpenAPI paths 를 baseline 과 비교.

사용: /opt/anaconda3/bin/python3 scripts/check_openapi_diff.py
  - audit/baseline_routes.json (경로,메서드 집합) 와 비교 → 추가/삭제 0 이어야 통과.
  - baseline_openapi.json 의 paths 키 집합도 비교(스키마 경로 무변경).
반환코드: 0=무변경(통과), 1=차이 있음(중단·보고).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402

app = main.app
cur_routes = sorted({(r.path, tuple(sorted(r.methods)))
                     for r in app.routes if getattr(r, "methods", None)})
base_routes = sorted({(p, tuple(m))
                      for p, m in json.load(open(ROOT / "audit" / "baseline_routes.json", encoding="utf-8"))})

cur_set, base_set = set(cur_routes), set(base_routes)
added = sorted(cur_set - base_set)
removed = sorted(base_set - cur_set)

base_paths = set(json.load(open(ROOT / "baseline_openapi.json", encoding="utf-8")).get("paths", {}))
cur_paths = set(app.openapi().get("paths", {}))
paths_added = sorted(cur_paths - base_paths)
paths_removed = sorted(base_paths - cur_paths)

print(f"라우트(경로,메서드): 현재 {len(cur_routes)} / 기준 {len(base_routes)}")
print(f"OpenAPI paths: 현재 {len(cur_paths)} / 기준 {len(base_paths)}")
ok = not (added or removed or paths_added or paths_removed)
if ok:
    print("✅ 무변경(move-only 유지) — 통과")
    sys.exit(0)
print("❌ 차이 발견 — 중단·보고 필요")
for label, items in [("추가된 라우트", added), ("삭제된 라우트", removed),
                     ("추가 paths", paths_added), ("삭제 paths", paths_removed)]:
    if items:
        print(f"  [{label}] {len(items)}")
        for it in items[:20]:
            print(f"     {it}")
sys.exit(1)
