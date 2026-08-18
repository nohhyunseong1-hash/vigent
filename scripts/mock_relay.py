#!/usr/bin/env python3
"""[P3b] mock 릴레이 서버 — 실물 릴레이 없이 ON/OFF 시퀀스를 검증한다.

실물 네트워크 릴레이가 없으므로, 같은 HTTP 계약을 흉내 내는 서버로 relay.py 를 시험한다.
장애 주입이 가능하다: 지연·타임아웃·5xx·완전 다운.

사용(수동 확인):
    python scripts/mock_relay.py --port 8099
    curl "http://127.0.0.1:8099/relay?state=on"
    curl "http://127.0.0.1:8099/log"      # ON/OFF 시퀀스 확인

테스트에서는 `MockRelay` 를 직접 import 해 쓴다(tests/test_relay.py).
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse


class MockRelay:
    """ON/OFF 요청을 기록하는 최소 서버. 장애 주입 옵션 포함."""

    def __init__(self, port: int = 0):
        self.log: list[tuple[float, str]] = []      # (시각, 'on'|'off')
        self.fail_status: int | None = None          # 설정 시 이 상태코드로 응답(예: 500)
        self.delay_s: float = 0.0                    # 응답 지연(타임아웃 유발용)
        self.down: bool = False                      # True 면 연결 자체를 거부하듯 예외
        self._lock = threading.Lock()
        outer = self

        class _H(BaseHTTPRequestHandler):
            def do_GET(self):                        # noqa: N802
                u = urlparse(self.path)
                if u.path == "/log":
                    body = json.dumps([{"t": t, "action": a} for t, a in outer.log]).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if outer.down:
                    self.close_connection = True     # 응답 없이 끊는다
                    return
                if outer.delay_s:
                    time.sleep(outer.delay_s)
                state = (parse_qs(u.query).get("state") or ["?"])[0]
                if outer.fail_status:
                    self.send_response(outer.fail_status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                with outer._lock:
                    outer.log.append((time.time(), state))
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

            do_POST = do_GET                         # noqa: N815

            def log_message(self, *a):               # 콘솔 소음 억제
                pass

        self._srv = HTTPServer(("127.0.0.1", port), _H)
        self.port = self._srv.server_address[1]
        self._th = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self) -> "MockRelay":
        self._th.start()
        return self

    def stop(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/relay"

    def actions(self) -> list[str]:
        with self._lock:
            return [a for _, a in self.log]

    def clear(self) -> None:
        with self._lock:
            self.log.clear()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    m = MockRelay(a.port).start()
    print(f"mock 릴레이: {m.url}  (로그: http://127.0.0.1:{m.port}/log)")
    print("Ctrl+C 로 종료")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        m.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
