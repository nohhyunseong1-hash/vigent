#!/usr/bin/env python3
"""local_sink.py — 벤치 전용 로컬 통보 싱크(127.0.0.1). [H-3]

★왜 있는가
  4채널 벤치는 진짜 경보를 만든다. 그 경보가 **실제 통보 채널(텔레그램·이메일)로 나가면 안 된다**.
  그렇다고 채널을 아예 비우면 경보가 큐에 들어가지 않아(`channels_configured()` False)
  **"경보 큐→전송 p95" 를 잴 수 없다** — 합격 기준 하나가 통째로 미측정이 된다.
  그래서 **로컬에서만 받는 웹훅**을 채널로 준다. 전송 경로는 그대로 타면서 밖으로는 한 바이트도 안 나간다.

사용:
    python scripts/bench/local_sink.py --port 9911 --out audit/bench_sink_<tag>.jsonl
받은 건수는 종료 시 stderr 에 찍고, 본문은 out 에 1줄 1건(JSONL)으로 남긴다.
★본문에 현장 이미지 경로 등이 들어갈 수 있어 out 은 audit/ 아래에 둔다(저장소 커밋 금지 대상).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# [2026-10-08 새 환경 점검] cp949 콘솔(PYTHONUTF8 미설정 Windows)에서 한글·기호 print 가 UnicodeEncodeError 로 죽던 것 —
#   실측: setup_env.py 가 새 clone 의 첫 print 에서 종료돼 pip 설치가 시작도 안 됐다. stdout/stderr 를 UTF-8 로 재설정한다.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


_COUNT = {"n": 0}
_OUT = {"f": None}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        _COUNT["n"] += 1
        if _OUT["f"]:
            try:
                rec = {"ts": time.time(), "path": self.path, "body": body.decode("utf-8", "replace")[:4000]}
                _OUT["f"].write(json.dumps(rec, ensure_ascii=False) + "\n")
                _OUT["f"].flush()
            except Exception:  # noqa: BLE001  싱크가 벤치를 망가뜨리면 안 된다
                pass
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"received": _COUNT["n"]}).encode())

    def log_message(self, *a: object) -> None:   # 요청 로그 억제(콘솔 오염 방지)
        return


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9911)
    ap.add_argument("--out", default="")
    a = ap.parse_args()
    if a.out:
        _OUT["f"] = open(a.out, "a", encoding="utf-8")
    # ★127.0.0.1 에만 바인드한다. 0.0.0.0 이면 같은 망의 다른 기기가 접근할 수 있다.
    srv = HTTPServer(("127.0.0.1", a.port), Handler)
    print(f"local sink on http://127.0.0.1:{a.port}/sink", file=sys.stderr, flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print(f"received={_COUNT['n']}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
