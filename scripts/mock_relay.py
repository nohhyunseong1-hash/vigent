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
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

try:   # Windows 콘솔(cp949 등)이 이모지·한글기호를 못 찍어 죽는 문제 방지 — 출력 인코딩만 강제(로직 무관)
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

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

        # ★[F29, 2026-08-21] 단일 스레드 HTTPServer → ThreadingHTTPServer.
        #   relay.py 는 OFF 를 8회까지 재시도하는데(사이렌이 안 꺼지는 게 최악이라 의도한 설계),
        #   단일 스레드 서버는 그 연속 요청을 직렬 처리하느라 전체 스위트 부하에서 밀린다.
        #   그 결과 test_relay 가 **단독 5/5 통과인데 전체 스위트에서는 절반 확률로 실패**했다
        #   — 진짜 회귀와 flake 를 구분할 수 없게 되는 것이 게이트에서 가장 나쁘다.
        self._srv = ThreadingHTTPServer(("127.0.0.1", port), _H)
        self._srv.daemon_threads = True          # 핸들러 스레드가 종료를 붙잡지 않게
        self.port = self._srv.server_address[1]
        self._th = threading.Thread(target=self._srv.serve_forever, daemon=True)

    def start(self, wait_s: float = 3.0) -> "MockRelay":
        """서버를 띄우고 **실제로 응답할 때까지 기다린다.**

        ★기동을 안 기다리면 첫 요청이 연결 거부로 실패해 테스트가 흔들린다 —
        `serve_forever` 는 스레드 시작 직후 곧바로 수락 가능한 상태가 아니다.
        """
        self._th.start()
        import urllib.request
        deadline = time.time() + wait_s
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/log", timeout=0.5):
                    return self                  # 응답 확인 = 수락 준비 완료
            except Exception:  # noqa: BLE001
                time.sleep(0.02)
        raise RuntimeError(f"mock 릴레이 기동 실패(포트 {self.port}) — {wait_s}s 내 응답 없음")

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
