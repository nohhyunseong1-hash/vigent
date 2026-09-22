"""[F-35] 알림 채널 자가시험 — 조용한 실패를 드러내는지 확인한다.

★무엇을 고정하는가 (실제 사고 2026-08-21~09-10)
  텔레그램 토큰이 401 이 된 뒤 **20일간 경보 213건이 사람에게 닿지 않았는데 아무도 몰랐다.**
  /health 도 화면도 조용했다. 그래서 아래를 고정한다:
    1. HTTP 4xx 확정 → state="config_error" · **CRITICAL 로그 1회**(반복은 카운트만)
    2. 망 오류·타임아웃 → state="unknown" — **설정 오류로 단정하지 않는다**
       (현장 노트북 Wi-Fi 가 불안정해 기동 직후 실패가 잦다 — 오탐 배너 방지)
    3. unknown 이 30분을 넘으면 unknown_too_long=True (노란 배너 조건)
    4. 정상이면 state="ok" 이고 CRITICAL 이 남지 않는다
"""
from __future__ import annotations

import logging
import sys
import time
import unittest
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))


class _Resp:
    """requests 응답 흉내 — 실제 망을 타지 않는다."""

    def __init__(self, code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = code
        self.ok = 200 <= code < 300
        self._p = payload or {}
        self.headers: dict[str, str] = {}

    def json(self) -> dict[str, Any]:
        return self._p


class NotifySelftestTest(unittest.TestCase):
    def setUp(self) -> None:
        from agents import dispatcher as D
        self.D = D
        D.reset_delivery_stats_for_test()
        self._orig_cfg = D.notify_cfg
        self._orig_req = D.requests
        # 토큰이 설정된 상태로 고정(값은 가짜 — 실제 토큰을 쓰지 않는다)
        D.notify_cfg = lambda: {**{k: None for k in
                                   ("webhook_url", "smtp_host", "smtp_user", "smtp_pass", "email_to")},
                                "telegram_token": "123456:FAKE-TOKEN-FOR-TEST", "telegram_chat": "999",
                                "smtp_port": 587}

    def tearDown(self) -> None:
        self.D.notify_cfg = self._orig_cfg
        self.D.requests = self._orig_req
        self.D.reset_delivery_stats_for_test()

    def _fake_requests(self, resp: Any) -> None:
        class _R:
            @staticmethod
            def get(*_a: Any, **_k: Any) -> Any:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        self.D.requests = _R

    # ── 1. 4xx 확정 ────────────────────────────────────────────────────────
    def test_http_401_marks_config_error_and_logs_critical_once(self) -> None:
        D = self.D
        self._fake_requests(_Resp(401, {"ok": False, "description": "Unauthorized"}))
        with self.assertLogs("vigent.dispatcher", level="CRITICAL") as cm:
            st = D.selftest_channels(force=True)
        self.assertEqual(st["state"], "config_error")
        self.assertIn("401", st["reason"])
        self.assertEqual(len(cm.output), 1, "첫 발생만 CRITICAL 이어야 한다")
        self.assertNotIn("FAKE-TOKEN", cm.output[0], "★로그에 토큰이 새면 안 된다")

        # 반복 — CRITICAL 이 더 남지 않고 카운트만 오른다
        before = D._DELIVERY["config_error_count"]
        logging.getLogger("vigent.dispatcher").setLevel(logging.CRITICAL)
        D.note_config_error("telegram", 401)
        self.assertEqual(D._DELIVERY["config_error_count"], before + 1)

    def test_config_error_surfaces_in_status(self) -> None:
        """dispatcher.status() 에 실려야 /health 가 볼 수 있다."""
        D = self.D
        self._fake_requests(_Resp(401, {"ok": False}))
        D.selftest_channels(force=True)
        import vision_loader
        agent = D.DispatcherAgent(vision_loader.load_vision("safety"))
        s = agent.status()
        self.assertEqual(s["last_config_error"], "telegram HTTP 401")
        self.assertEqual(s["selftest"]["state"], "config_error")
        self.assertNotIn("FAKE-TOKEN", str(s), "★상태에 토큰이 새면 안 된다")

    # ── 2. 망 오류는 설정 오류가 아니다 ─────────────────────────────────────
    def test_network_error_is_unknown_not_config_error(self) -> None:
        """★현장 Wi-Fi 가 불안정해도 '불능' 으로 단정하지 않는다."""
        D = self.D
        self._fake_requests(TimeoutError("연결 시간 초과"))
        st = D.selftest_channels(force=True)
        self.assertEqual(st["state"], "unknown")
        self.assertIsNone(D._DELIVERY["last_config_error"], "망 오류로 설정오류를 기록하면 안 된다")
        self.assertFalse(D.selftest_status()["unknown_too_long"], "방금 실패한 것은 아직 경고 대상이 아니다")

    def test_5xx_is_unknown_not_config_error(self) -> None:
        """텔레그램 서버 장애(5xx)도 우리 설정 문제가 아니다."""
        D = self.D
        self._fake_requests(_Resp(502))
        st = D.selftest_channels(force=True)
        self.assertEqual(st["state"], "unknown")
        self.assertIsNone(D._DELIVERY["last_config_error"])

    # ── 3. 30분 초과 미확인 → 노란 배너 조건 ────────────────────────────────
    def test_unknown_over_30min_flags_warning(self) -> None:
        D = self.D
        self._fake_requests(TimeoutError("망 오류"))
        D.selftest_channels(force=True)
        self.assertFalse(D.selftest_status()["unknown_too_long"])
        # 31분 전부터 미확인이었던 것으로 되돌린다
        D._SELFTEST["unknown_since"] = time.time() - (D.SELFTEST_UNKNOWN_WARN_SEC + 60)
        self.assertTrue(D.selftest_status()["unknown_too_long"], "30분 초과면 노란 배너 조건")

    def test_retry_interval_respected(self) -> None:
        """미확인 상태에서 매 요청마다 망을 타지 않는다(10분 간격)."""
        D = self.D
        self._fake_requests(TimeoutError("망 오류"))
        D.selftest_channels(force=True)
        n1 = D._SELFTEST["attempts"]
        D.selftest_channels()                      # force 없이 — 간격 이내라 건너뛴다
        self.assertEqual(D._SELFTEST["attempts"], n1, "재시도 간격 이내에는 다시 묻지 않는다")

    # ── 4. 정상 ────────────────────────────────────────────────────────────
    def test_ok_state_has_no_critical(self) -> None:
        D = self.D
        self._fake_requests(_Resp(200, {"ok": True, "result": {"username": "testbot"}}))
        st = D.selftest_channels(force=True)
        self.assertEqual(st["state"], "ok")
        self.assertEqual(st["bot"], "testbot")
        self.assertIsNone(D._DELIVERY["last_config_error"])
        self.assertFalse(D.selftest_status()["unknown_too_long"])

    def test_startup_loop_is_background_and_does_not_block(self) -> None:
        """★기동 경로가 getMe 타임아웃만큼 늦어지면 안 된다 — 배경 스레드로 돈다."""
        import threading
        D = self.D
        self._fake_requests(_Resp(200, {"ok": True, "result": {"username": "bg"}}))
        before = threading.active_count()
        t0 = time.time()
        D.start_selftest_loop()
        self.assertLess(time.time() - t0, 0.5, "기동 호출이 즉시 돌아와야 한다")
        for _ in range(50):                        # 배경 스레드가 끝나길 잠깐 기다린다
            if D._SELFTEST["state"] == "ok":
                break
            time.sleep(0.02)
        self.assertEqual(D._SELFTEST["state"], "ok")
        self.assertGreaterEqual(before, 1)

    def test_not_configured(self) -> None:
        D = self.D
        D.notify_cfg = lambda: {"telegram_token": None, "telegram_chat": None, "webhook_url": None,
                                "smtp_host": None, "smtp_user": None, "smtp_pass": None,
                                "email_to": None, "smtp_port": 587}
        st = D.selftest_channels(force=True)
        self.assertEqual(st["state"], "not_configured")

    # ── 5. 전송 실패 경로도 같은 기록을 탄다 ────────────────────────────────
    def test_classify_http_401_records_config_error(self) -> None:
        """실제 전송이 401 을 받아도 배너·CRITICAL 경로를 탄다(자가시험만이 아니라)."""
        D = self.D
        with self.assertLogs("vigent.dispatcher", level="CRITICAL"):
            out = D._classify_http("telegram", _Resp(401))
        self.assertTrue(out["config_error"])
        self.assertEqual(D._DELIVERY["last_config_error"], "telegram HTTP 401")
        self.assertEqual(D.selftest_status()["state"], "config_error")

    # ── 6. 마지막 성공 시각 ────────────────────────────────────────────────
    def test_counts_has_last_success_ts(self) -> None:
        """'언제부터 안 가고 있나' 를 /health 가 말할 수 있어야 한다."""
        import alert_queue
        c = alert_queue.counts()
        self.assertIn("last_success_ts", c)


if __name__ == "__main__":
    unittest.main()
