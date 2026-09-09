"""portable_wait.py — 포터블 런처 보조: /health 가 200 이 될 때까지 기다렸다가 브라우저를 연다.

VIGENT_시작.bat 이 `start /b` 로 백그라운드 실행한다(같은 콘솔 창 — 창을 닫으면 함께 종료).
기동 직후 ~15초는 모델 예열 중이라 503 이 정상이다. 최대 대기(기본 90초)를 넘기면 안내만 남기고 끝난다.

사용: python portable_wait.py <port> [max_wait_s]
환경: VIGENT_PORTABLE_NOBROWSER=1 이면 브라우저를 열지 않는다(검증 자동화용).
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    max_wait = float(sys.argv[2]) if len(sys.argv) > 2 else 90.0
    url_health = f"http://127.0.0.1:{port}/health"
    # [4차, 2026-09-10] 브라우저는 현장 관제 화면(/safety-hub)을 연다 — /home 은 메뉴(허브)라 제3 PC 시험에서 사용자가 관제 화면을 못 찾았다.
    #   docs/academy_visit_day.md §A-1 "관제 대시보드 = /safety-hub". 메뉴로 가려면 /home.
    url_home = f"http://127.0.0.1:{port}/safety-hub"
    # 회사 PC 의 HTTP(S)_PROXY 환경변수가 127.0.0.1 요청까지 프록시로 보내 실패하게 하므로, 로컬 헬스체크는 프록시를 쓰지 않는다.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    t0 = time.time()
    last = ""
    while time.time() - t0 < max_wait:
        try:
            with opener.open(url_health, timeout=3) as r:
                if r.status == 200:
                    print(f"[포터블] 서버 준비 완료({time.time() - t0:.0f}초) → {url_home}")
                    if os.environ.get("VIGENT_PORTABLE_NOBROWSER") != "1":
                        try:
                            os.startfile(url_home)  # type: ignore[attr-defined]
                        except Exception as e:  # noqa: BLE001
                            print(f"[포터블] 브라우저 자동 열기 실패({e}) — 직접 여세요: {url_home}")
                    return 0
        except urllib.error.HTTPError as e:      # 503 = 예열 중(정상)
            last = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001   연결 거부 = 아직 안 뜸
            last = type(e).__name__
        time.sleep(2)
    print(f"[포터블] {max_wait:.0f}초 안에 서버가 준비되지 않았습니다(마지막 상태: {last}). "
          f"창의 오류 메시지를 확인하고, 그래도 안 되면 사용법.md 의 '문제가 생겼을 때' 를 보세요.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
