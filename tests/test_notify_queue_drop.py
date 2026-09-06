"""[CODE_REVIEW M4-6] 통보 대기열이 가득 차 최고령 경보를 폐기할 때 — 조용히 stats 만 올리지 말고 WARNING + /health 노출.

계약: ① 폐기 시 WARNING 로그 1줄(폐기 누적 수 포함) ② alert_notify.stats()["dropped"] 증가 ③ /health alerts.dropped 로 노출
(health_status.alert_health 가 dropped 를 경고 "notify_queue_dropped" 로 싣는다 — status 는 바꾸지 않음: 최신 경보는 살아 있다).
"""
import queue
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_gate  # noqa: E402
import alert_notify  # noqa: E402
import health_status  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


class QueueDropIsVisible(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        alert_gate.reset()
        alert_notify.reset_for_test()
        alert_notify._q = queue.Queue(maxsize=2)      # 전송 스레드 없음 → 큐가 소비되지 않는다

    def test_drop_logs_warning_and_counts(self):
        with self.assertLogs("vigent.alert_notify", level="WARNING") as cm:
            for i in range(3):                        # 규칙을 달리해 게이트에 안 걸리게
                alert_notify.submit(cam="c", rule=f"r{i}", level="high", message=f"m{i}")
        st = alert_notify.stats()
        self.assertEqual(st["dropped"], 1)
        self.assertEqual(st["queue_depth"], 2)
        self.assertTrue(any("폐기" in line for line in cm.output), f"폐기 WARNING 없음: {cm.output}")

    def test_health_exposes_dropped_as_warning(self):
        problems, warnings = health_status.alert_health(
            {"pending": 0, "dead": 0, "dead_1h": 0},
            {"channels_configured": True, "undeliverable_count": 0, "dropped": 3})
        self.assertEqual(problems, 0, "폐기는 경고(최신 경보는 살아 있다) — degraded 아님")
        self.assertIn("notify_queue_dropped", warnings)


if __name__ == "__main__":
    unittest.main()
