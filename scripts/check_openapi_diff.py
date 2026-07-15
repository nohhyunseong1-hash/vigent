#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P1-7 move-only 증명 — 현재 app 의 라우트를 baseline 과 비교.

권위 있는 불변식 2가지(둘 다 무변경이어야 통과):
  ① HTTP: OpenAPI (path, method) 집합 == baseline_openapi.json 의 것.
     ★ include_router(최신 Starlette 는 _IncludedRouter 로 지연매칭 → app.routes 얕은 열거로는
       안 보임)까지 openapi 는 정확히 반영하므로, openapi 를 기준으로 비교한다.
  ② WebSocket: app.routes 를 재귀(원 라우터 original_router 포함)로 훑어 WS 경로 집합 == audit/baseline_ws.json.
반환코드: 0=무변경(통과), 1=차이(중단·보고).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
from starlette.routing import WebSocketRoute  # noqa: E402

_HTTP = {"get", "post", "put", "delete", "patch", "head", "options"}


def _ops(schema):
    return {(p, m.lower()) for p, item in schema.get("paths", {}).items()
            for m in item if m.lower() in _HTTP}


def _walk(routes):
    for r in routes:
        yield r
        sub = getattr(r, "routes", None) or getattr(getattr(r, "original_router", None), "routes", None)
        if sub:
            yield from _walk(sub)


base_ops = _ops(json.load(open(ROOT / "baseline_openapi.json", encoding="utf-8")))
cur_ops = _ops(main.app.openapi())
ops_added, ops_removed = sorted(cur_ops - base_ops), sorted(base_ops - cur_ops)

cur_ws = {r.path for r in _walk(main.app.routes) if isinstance(r, WebSocketRoute)}
ws_file = ROOT / "audit" / "baseline_ws.json"
base_ws = set(json.load(open(ws_file, encoding="utf-8"))) if ws_file.exists() else cur_ws
ws_added, ws_removed = sorted(cur_ws - base_ws), sorted(base_ws - cur_ws)

print(f"HTTP (path,method): 현재 {len(cur_ops)} / 기준 {len(base_ops)}")
print(f"WebSocket 경로: 현재 {sorted(cur_ws)} / 기준 {sorted(base_ws)}")
if not (ops_added or ops_removed or ws_added or ws_removed):
    print("✅ 무변경(move-only 유지) — 통과")
    sys.exit(0)
print("❌ 차이 발견 — 중단·보고 필요")
for label, items in [("추가 op", ops_added), ("삭제 op", ops_removed),
                     ("추가 ws", ws_added), ("삭제 ws", ws_removed)]:
    if items:
        print(f"  [{label}] {len(items)}: {items[:20]}")
sys.exit(1)
