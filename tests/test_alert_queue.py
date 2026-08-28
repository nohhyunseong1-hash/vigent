"""[B5] 경보 전송 내구 큐 테스트.

배경(감사 🔴B5): 경보 전송이 1회성이라 **순단 중 발생한 위험 경보가 영구 소실**됐다
(dispatcher._send_webhook/_send_email — 실패하면 sent:False 반환하고 끝, 재시도·큐 0건).

지시 시나리오: 채널을 강제로 끊고 경보 5건 발생 → 채널 복구 → **5건 모두 순서대로 도착**.
추가로 프로세스 재시작 후 큐 이월(내구성)과 쿨다운과의 비충돌을 검증한다.
"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_queue as q  # noqa: E402


class _Channel:
    """전송 채널 흉내 — up=False 면 실패(순단 재현), 도착 순서를 기록."""

    def __init__(self, up=True):
        self.up = up
        self.received: list[str] = []

    def send(self, level, message, meta):
        if not self.up:
            return {"delivered": False, "results": [{"channel": "webhook", "sent": False}]}
        self.received.append(message)
        return {"delivered": True, "results": [{"channel": "webhook", "sent": True}]}


class _QueueTest(unittest.TestCase):
    def setUp(self):
        # ★[2026-08-28] 배경 재시도 스레드를 **먼저 재운다.**
        #   main.py 가 기동 시 alert_queue.start() 를 부르므로, main 을 import 하는 테스트가
        #   하나라도 있으면 재시도 스레드가 스위트 내내 살아 5초마다 drain() 한다.
        #   그러면 **그 시점의 전역 sender**(= 이 테스트의 채널)로 경보가 새어 들어가
        #   타이밍에 따라 실패한다(셔플 10회 중 4회 실측: test_dead_is_not_retried 등).
        q.stop()
        try:
            __import__("alert_notify").stop()
        except Exception:  # noqa: BLE001
            pass
        self.tmp = tempfile.TemporaryDirectory()
        q._reset_for_test(Path(self.tmp.name) / "aq.db")
        self.ch = _Channel()
        q.set_sender(self.ch.send)

    def tearDown(self):
        q.stop()
        q._reset_for_test()
        self.tmp.cleanup()


class TestOutageAndRecovery(_QueueTest):
    def test_five_alerts_survive_outage_and_arrive_in_order(self):
        """★지시 시나리오: 채널 끊김 중 5건 → 복구 → 5건 모두 순서대로 도착."""
        self.ch.up = False
        for i in range(1, 6):
            rid = q.enqueue("high", f"경보{i}")
            q.try_send({"id": rid, "level": "high", "message": f"경보{i}", "meta": {}, "attempts": 0})
        self.assertEqual(self.ch.received, [])           # 하나도 못 갔다
        self.assertEqual(q.pending_count(), 5)           # 그러나 사라지지 않았다

        self.ch.up = True                                 # 채널 복구
        # 백오프 대기를 건너뛰고 즉시 재시도(테스트에서 수십 초를 기다릴 수 없다).
        #   ※ due() 로 조회하면 백오프가 걸린 행은 애초에 안 나오므로 직접 갱신해야 한다.
        q._db().execute("UPDATE alerts SET next_attempt_at=0 WHERE status='pending'")
        q._db().commit()
        q.drain(limit=50)

        self.assertEqual(self.ch.received, ["경보1", "경보2", "경보3", "경보4", "경보5"])
        self.assertEqual(q.pending_count(), 0)

    def test_success_path_marks_sent(self):
        rid = q.enqueue("high", "정상경보")
        q.try_send({"id": rid, "level": "high", "message": "정상경보", "meta": {}, "attempts": 0})
        self.assertEqual(self.ch.received, ["정상경보"])
        self.assertEqual(q.counts()["sent"], 1)
        self.assertEqual(q.pending_count(), 0)


class TestBackoffAndDeadLetter(_QueueTest):
    def test_backoff_grows_and_is_capped(self):
        self.ch.up = False
        rid = q.enqueue("high", "실패경보")
        prev = 0.0
        for _ in range(4):
            q.mark_failed(rid, "boom")
            row2 = q._db().execute("SELECT next_attempt_at FROM alerts WHERE id=?", (rid,)).fetchone()
            delay = row2[0] - time.time()
            self.assertGreaterEqual(delay, prev - 1)      # 단조 증가(측정 오차 여유)
            self.assertLessEqual(delay, q.backoff_cap_s() + 1)
            prev = delay

    def test_dead_letter_after_max_attempts(self):
        """재시도 한도를 넘으면 dead — 조용히 사라지지 않고 표시로 남는다."""
        rid = q.enqueue("high", "영영실패")
        for _ in range(q.max_attempts()):
            q.mark_failed(rid, "boom")
        self.assertEqual(q.counts()["dead"], 1)
        self.assertEqual(q.pending_count(), 0)

    def test_dead_is_not_retried(self):
        rid = q.enqueue("high", "죽은경보")
        for _ in range(q.max_attempts()):
            q.mark_failed(rid, "boom")
        self.ch.up = True
        q.drain(limit=50)
        self.assertEqual(self.ch.received, [])            # dead 는 재전송 대상이 아니다


class TestDurability(_QueueTest):
    def test_queue_survives_process_restart(self):
        """★프로세스 재시작 후에도 큐가 살아남아 이어서 전송된다."""
        self.ch.up = False
        for i in range(3):
            rid = q.enqueue("high", f"이월{i}")
            q.mark_failed(rid, "채널 끊김")
        db_path = q._DB_PATH
        self.assertEqual(q.pending_count(), 3)

        q._reset_for_test(db_path)                        # 연결을 닫았다 다시 여는 것 = 재시작 흉내
        self.assertEqual(q.pending_count(), 3)            # 이월됐다

        ch2 = _Channel(up=True)
        q.set_sender(ch2.send)
        q._db().execute("UPDATE alerts SET next_attempt_at=0")
        q._db().commit()
        q.drain(limit=50)
        self.assertEqual(ch2.received, ["이월0", "이월1", "이월2"])

    def test_write_ahead_survives_crash_before_send(self):
        """전송 시도 전에 죽어도 경보는 남는다(선기록 후전송)."""
        q.enqueue("critical", "기록만됨")
        self.assertEqual(q.pending_count(), 1)            # 전송 시도조차 안 했는데 남아 있다


class TestHealthIntegration(_QueueTest):
    def test_pending_makes_health_degraded(self):
        """미전송이 1건이라도 있으면 /health 는 degraded 여야 한다."""
        import health_status
        cams = {"c1": health_status.camera_status(
            {"running": True, "uptime_s": 900, "last_frame_secs_ago": 0.4,
             "last_detect_secs_ago": 0.3})}
        self.assertEqual(health_status.overall(cams, True, alert_backlog=0), health_status.HEALTHY)
        self.assertEqual(health_status.overall(cams, True, alert_backlog=1), health_status.DEGRADED)


class TestCooldownIndependence(_QueueTest):
    def test_queue_does_not_duplicate_suppressed_alerts(self):
        """쿨다운은 상류 필터, 큐는 하류 전달 보장 — 쿨다운이 거른 건 큐에 들어오지 않는다.

        (worker 가 쿨다운 통과분만 log_event/dispatch 하므로, 큐가 스스로 중복을 만들지 않는지만
        확인한다: enqueue 1회 = 행 1개.)"""
        q.enqueue("high", "중복확인")
        q.enqueue("high", "중복확인")
        self.assertEqual(q.pending_count(), 2)            # 같은 문구라도 별개 사건이면 별개 행
        rows = q.due(limit=10)
        self.assertEqual([r["id"] for r in rows], sorted(r["id"] for r in rows))   # 순서 보존


class TestLogOnlyLevelNotRetriedForever(_QueueTest):
    """[2026-08-21] 원격 채널이 없는 등급이 영원히 재시도되다 데드레터가 되던 결함.

    실측 경위: worker 가 rapid_motion·crowd_density 를 level="mid" 로 발화하는데
    dispatch 기본 배선 `on_severity` 에는 "mid" 가 없어(있는 것은 "medium") log 전용으로
    폴백한다. 그런데 큐에는 들어가므로 delivered=False 가 계속되고 10회 재시도 후
    **dead**. 그 사이 pending 때문에 `/health` 가 **degraded** 로 떨어졌다.
    """

    def test_result_without_remote_channel_is_terminal(self):
        """★로그 채널만 있는 결과는 '전달 완료'로 종결한다 — 재시도하지 않는다."""
        def log_only(level, message, meta):
            return {"delivered": False, "level": level,
                    "results": [{"channel": "log", "sent": True, "text": message}]}
        q.set_sender(log_only)
        rid = q.enqueue("mid", "급격한 이동 감지", None)
        self.assertTrue(q.try_send(dict(q.due()[0])), "종결 처리되지 않았다")
        c = q.counts()
        self.assertEqual(c["pending"], 0, "pending 이 남아 degraded 를 유발한다")
        self.assertEqual(c["dead"], 0)
        self.assertEqual(c["sent"], 1)
        self.assertIsInstance(rid, int)

    def test_relay_only_result_is_also_terminal(self):
        """safety_relay_signal 만 있는 결과도 원격 전송이 아니므로 종결 대상이다."""
        def relay_only(level, message, meta):
            return {"delivered": False,
                    "results": [{"channel": "safety_relay_signal", "sent": True},
                                {"channel": "log", "sent": True}]}
        q.set_sender(relay_only)
        q.enqueue("critical", "프레스 우회", None)
        q.try_send(dict(q.due()[0]))
        self.assertEqual(q.counts()["pending"], 0)

    def test_real_remote_failure_still_retries(self):
        """★반대로 원격 채널을 실제로 시도했다가 실패한 건은 **계속 재시도**해야 한다.

        (순단 복구 보장이 이 큐의 존재 이유다 — 종결 처리가 이걸 먹으면 안 된다.)
        """
        self.ch.up = False
        q.enqueue("high", "위험구역 침입", None)
        q.try_send(dict(q.due()[0]))
        self.assertEqual(q.counts()["pending"], 1, "원격 실패 건이 종결돼 유실됐다")


class TestQueueEligibilityFollowsWiring(unittest.TestCase):
    """상류 차단: 원격 동작이 배선된 등급만 큐에 넣는다(하드코딩 금지)."""

    def _agent(self, on_severity):
        import sys
        from pathlib import Path as _P
        sys.path.insert(0, str(_P(__file__).resolve().parent.parent / "vigent-core"))
        from agents.dispatcher import DispatcherAgent

        class _Cfg:
            raw = {"dispatch": {"on_severity": on_severity}}
        return DispatcherAgent(_Cfg())

    def test_log_only_level_is_not_queued(self):
        a = self._agent({"critical": ["alarm"], "high": ["alarm", "manager_call"],
                         "medium": ["log"]})
        self.assertFalse(a._queue_enabled("mid"), "배선에 없는 등급이 큐에 들어간다")
        self.assertFalse(a._queue_enabled("medium"))

    def test_remote_levels_are_queued(self):
        a = self._agent({"critical": ["alarm"], "high": ["alarm", "manager_call"],
                         "medium": ["log"]})
        self.assertTrue(a._queue_enabled("critical"))
        self.assertTrue(a._queue_enabled("high"))

    def test_follows_custom_wiring(self):
        """현장에서 mid 에 원격을 배선하면 그때는 큐에 들어가야 한다."""
        a = self._agent({"mid": ["manager_call"]})
        self.assertTrue(a._queue_enabled("mid"))


if __name__ == "__main__":
    unittest.main()
