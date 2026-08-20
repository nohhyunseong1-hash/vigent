"""[W1·W2] 경보 통보 배선 + 폭주 방지 + 근접 디바운스 테스트.

★검증하는 계약 4가지:
  1) **발화**: 위험이 판정되면 통보가 제출된다(기록 다음에, 비동기로).
  2) **억제**: 같은 원인 반복은 쿨다운·시간당 상한으로 막는다 — 단 **기록은 억제되지 않는다**.
  3) **쿨다운 예외**: 등급이 오르면(high→critical) 쿨다운을 무시하고 통보한다.
  4) **전송 실패가 검출을 막지 않는다**: 전송기가 예외를 던져도 submit 은 정상 반환하고
     워커 루프가 계속 돈다.
"""
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_gate  # noqa: E402
import alert_notify  # noqa: E402
import zone_debounce  # noqa: E402


def cfg(**kw):
    """alerts.* 설정 주입(기본값은 배포값과 동일)."""
    vals = {"notify": True, "notify_cooldown_s": 300.0, "max_per_hour": 10, "queue_max": 200, **kw}
    return mock.patch.object(alert_gate.tuning, "val",
                             side_effect=lambda s, k, d, env=None: vals.get(k, d))


class TestGateFire(unittest.TestCase):
    """1) 발화 — 첫 위험은 반드시 통보된다."""

    def setUp(self):
        alert_gate.reset()

    def test_first_alert_notifies(self):
        with cfg():
            d = alert_gate.decide("cam1", "zone_intrusion", "high", now=1000.0)
        self.assertTrue(d["notify"])
        self.assertEqual(d["suppressed"], 0)

    def test_different_rules_are_independent(self):
        """규칙이 다르면 서로의 쿨다운에 걸리지 않는다 — 화재가 침입 때문에 막히면 안 된다."""
        with cfg():
            self.assertTrue(alert_gate.decide("cam1", "zone_intrusion", "high", now=1000.0)["notify"])
            self.assertTrue(alert_gate.decide("cam1", "fire_smoke", "critical", now=1001.0)["notify"])

    def test_different_cameras_are_independent(self):
        with cfg():
            self.assertTrue(alert_gate.decide("cam1", "ppe_missing", "high", now=1000.0)["notify"])
            self.assertTrue(alert_gate.decide("cam2", "ppe_missing", "high", now=1001.0)["notify"])


class TestGateSuppress(unittest.TestCase):
    """2) 억제 — [M3] 의 '정지 오검출이 경보를 계속 낳는' 상황을 막는다."""

    def setUp(self):
        alert_gate.reset()

    def test_repeat_within_cooldown_suppressed(self):
        with cfg():
            alert_gate.decide("cam1", "immobility", "high", now=1000.0)
            d = alert_gate.decide("cam1", "immobility", "high", now=1000.0 + 299.0)
        self.assertFalse(d["notify"])
        self.assertEqual(d["reason"], "cooldown")

    def test_after_cooldown_notifies_again(self):
        """★첫 통보 뒤 쿨다운은 백오프로 600초가 된다 — 301초에는 아직 억제, 601초에 통보."""
        with cfg():
            alert_gate.decide("cam1", "immobility", "high", now=1000.0)
            self.assertFalse(alert_gate.decide("cam1", "immobility", "high",
                                               now=1000.0 + 301.0)["notify"])
            d = alert_gate.decide("cam1", "immobility", "high", now=1000.0 + 601.0)
        self.assertTrue(d["notify"])

    def test_suppressed_count_is_carried_into_next_message(self):
        """★억제된 사실이 사라지면 안 된다 — 다음 통보에 건수가 실린다."""
        with cfg():
            alert_gate.decide("cam1", "immobility", "high", now=1000.0)
            for i in range(1, 6):
                alert_gate.decide("cam1", "immobility", "high", now=1000.0 + i)
            d = alert_gate.decide("cam1", "immobility", "high", now=1000.0 + 700.0)
        self.assertTrue(d["notify"])
        self.assertEqual(d["suppressed"], 5)
        self.assertIn("5건 억제", alert_gate.annotate("경보", d["suppressed"]))

    def test_hourly_cap_is_final_defense(self):
        """시간당 상한 — 등급 상승 예외로도 못 넘는 최종 방어선."""
        with cfg(notify_cooldown_s=0.0, max_per_hour=3):
            got = [alert_gate.decide("cam1", "fire_smoke", "critical", now=1000.0 + i)["notify"]
                   for i in range(6)]
        self.assertEqual(got, [True, True, True, False, False, False])

    def test_hourly_window_rolls_off(self):
        with cfg(notify_cooldown_s=0.0, max_per_hour=2):
            alert_gate.decide("cam1", "ppe_missing", "high", now=1000.0)
            alert_gate.decide("cam1", "ppe_missing", "high", now=1001.0)
            self.assertFalse(alert_gate.decide("cam1", "ppe_missing", "high", now=1002.0)["notify"])
            # 1시간 뒤 — 창이 지나 다시 열린다
            self.assertTrue(alert_gate.decide("cam1", "ppe_missing", "high", now=1000.0 + 3601)["notify"])

    def test_m3_scenario_221_events_become_bounded(self):
        """★[M3] 재현 — 이 테스트가 설계 결함을 잡아냈다.

        실측: 무동작 오경보 221건/24시간 = **평균 391초 간격**. 고정 쿨다운 300초로는
        391초 간격이 그대로 통과하고 시간당 9.2건이라 상한(당시 10)에도 안 걸려
        **221건이 전부 나갔다.** 백오프를 넣어야 수렴한다.
        """
        with cfg():
            notified = sum(1 for i in range(221)
                           if alert_gate.decide("cam1", "immobility", "high",
                                                now=1000.0 + i * 391.0)["notify"])
        self.assertLess(notified, 40, f"억제가 약하다 — {notified}건 통보(경보 폭탄)")
        self.assertGreater(notified, 0, "전부 억제됐다 — 이상 자체를 못 알게 된다")

    def test_real_site_alerts_are_not_suppressed(self):
        """★★가장 중요한 계약: 드물게 오는 **진짜 경보는 하나도 억제되지 않는다.**

        억제가 세면 오경보는 줄지만 진짜 위험을 놓친다 — 그러면 안전 제품이 아니다.
        수 시간 간격으로 오는 실제 경보(하루 4건)는 전부 통보돼야 한다.
        """
        with cfg():
            got = [alert_gate.decide("cam1", "zone_intrusion", "high", now=t)["notify"]
                   for t in (0.0, 7200.0, 30000.0, 60000.0)]
        self.assertEqual(got, [True] * 4, "실제 경보가 억제됐다 — 안전 실패")

    def test_backoff_grows_then_caps(self):
        """백오프는 2배씩 늘고 상한에서 멈춘다."""
        with cfg(notify_cooldown_s=300.0, backoff_max_s=1200.0, max_per_hour=99):
            d1 = alert_gate.decide("cam1", "immobility", "high", now=0.0)
            d2 = alert_gate.decide("cam1", "immobility", "high", now=700.0)
            d3 = alert_gate.decide("cam1", "immobility", "high", now=2000.0)
            d4 = alert_gate.decide("cam1", "immobility", "high", now=3300.0)
        self.assertEqual([d1["next_cooldown_s"], d2["next_cooldown_s"]], [600.0, 1200.0])
        self.assertEqual(d3["next_cooldown_s"], 1200.0, "상한을 넘어 계속 커졌다")
        self.assertEqual(d4["next_cooldown_s"], 1200.0)

    def test_backoff_resets_after_quiet(self):
        """★조용해지면 기본값 복귀 — 옛 소동 때문에 새 위험이 늦게 알려지면 안 된다."""
        with cfg(quiet_reset_s=1800.0):
            alert_gate.decide("cam1", "immobility", "high", now=0.0)
            alert_gate.decide("cam1", "immobility", "high", now=400.0)     # 억제(쿨다운 300→)
            d = alert_gate.decide("cam1", "immobility", "high", now=100000.0)
        self.assertTrue(d["notify"])
        self.assertEqual(d["next_cooldown_s"], 600.0, "백오프가 리셋되지 않았다")


class TestGateEscalation(unittest.TestCase):
    """3) 등급 상승은 쿨다운을 무시한다 — 악화를 늦게 알면 안 된다."""

    def setUp(self):
        alert_gate.reset()

    def test_escalation_bypasses_cooldown(self):
        with cfg():
            alert_gate.decide("cam1", "fire_smoke", "high", now=1000.0)
            d = alert_gate.decide("cam1", "fire_smoke", "critical", now=1001.0)
        self.assertTrue(d["notify"])
        self.assertEqual(d["reason"], "escalated")

    def test_de_escalation_does_not_bypass(self):
        """등급이 내려가는 것은 예외가 아니다(억제 유지)."""
        with cfg():
            alert_gate.decide("cam1", "fire_smoke", "critical", now=1000.0)
            self.assertFalse(alert_gate.decide("cam1", "fire_smoke", "high", now=1001.0)["notify"])

    def test_korean_level_labels_rank(self):
        """저장소에 '높음'·'중간' 한글 등급이 섞여 있다 — 순위 비교가 깨지면 안 된다."""
        self.assertGreater(alert_gate.rank("critical"), alert_gate.rank("높음"))
        self.assertEqual(alert_gate.rank("높음"), alert_gate.rank("high"))
        self.assertEqual(alert_gate.rank("중간"), alert_gate.rank("mid"))


class TestNotifyRollback(unittest.TestCase):
    """롤백 경로: alerts.notify=false 면 구 동작(통보 안 함, 기록은 그대로)."""

    def setUp(self):
        alert_notify.reset_for_test()

    def test_disabled_returns_not_queued(self):
        with cfg(notify=False):
            r = alert_notify.submit("cam1", "zone_intrusion", "high", "테스트")
        self.assertFalse(r["queued"])
        self.assertEqual(r["reason"], "disabled")


class TestSendFailureDoesNotBlockDetection(unittest.TestCase):
    """4) ★전송 실패·지연이 검출을 막지 않는다."""

    def setUp(self):
        alert_notify.reset_for_test()

    def tearDown(self):
        alert_notify.stop()
        alert_notify.reset_for_test()

    def test_submit_never_raises_when_sender_explodes(self):
        boom = mock.Mock(side_effect=RuntimeError("채널 폭발"))
        with cfg():
            alert_notify.set_sender(boom)
            alert_notify.start()
            r = alert_notify.submit("cam1", "fire_smoke", "critical", "불")
        self.assertTrue(r["queued"], "제출 자체는 성공해야 한다(전송은 스레드가 담당)")
        for _ in range(50):                       # 스레드가 처리할 시간
            if alert_notify.stats()["failed"]:
                break
            time.sleep(0.05)
        self.assertGreaterEqual(alert_notify.stats()["failed"], 1)
        with cfg():                               # ★스레드가 죽지 않았는지 — 다음 경보도 받는다
            r2 = alert_notify.submit("cam1", "zone_intrusion", "high", "침입")
        self.assertTrue(r2["queued"])
        self.assertTrue(alert_notify.stats()["thread_alive"], "전송 스레드가 죽었다")

    def test_submit_is_fast_even_with_slow_sender(self):
        """★느린 채널(2초)이 검출 루프를 멈추면 안 된다 — submit 은 즉시 반환한다."""
        def slow(lvl, msg, meta):
            time.sleep(2.0)
            return {"delivered": True}
        with cfg():
            alert_notify.set_sender(slow)
            alert_notify.start()
            t = time.perf_counter()
            alert_notify.submit("cam1", "proximity_hazard", "high", "근접")
            elapsed = time.perf_counter() - t
        self.assertLess(elapsed, 0.25, f"submit 이 {elapsed:.2f}초 블로킹했다(검출 정지 위험)")

    def test_submit_survives_gate_exception(self):
        with mock.patch.object(alert_gate, "decide", side_effect=RuntimeError("게이트 고장")), cfg():
            r = alert_notify.submit("cam1", "ppe_missing", "high", "보호구")
        self.assertFalse(r["queued"])
        self.assertEqual(r["reason"], "exception")


class TestProximityDebounce(unittest.TestCase):
    """[W2] 근접 디바운스 — 침입(1.0s)보다 짧은 0.4s."""

    def test_single_frame_hit_does_not_confirm(self):
        """★단일 프레임 오검출은 경보가 되지 않는다(도입 목적)."""
        db = zone_debounce.ZoneDebouncer(enter=0.4, exit_=1.0)
        self.assertFalse(db.update("c", True, now=100.0))
        self.assertFalse(db.update("c", False, now=100.5))

    def test_two_consecutive_detections_confirm(self):
        """검출주기 0.5초에서 연속 2회면 확정 — 0.4초 임계의 의도."""
        db = zone_debounce.ZoneDebouncer(enter=0.4, exit_=1.0)
        db.update("c", False, now=99.5)
        self.assertFalse(db.update("c", True, now=100.0))
        self.assertTrue(db.update("c", True, now=100.5))

    def test_exit_is_slower_than_enter(self):
        """해제는 진입보다 느리다 — 경계에서 깜빡여도 경보가 성급히 풀리지 않는다."""
        db = zone_debounce.ZoneDebouncer(enter=0.4, exit_=1.0)
        db.update("c", False, now=99.5)
        db.update("c", True, now=100.0)
        self.assertTrue(db.update("c", True, now=100.5))
        self.assertTrue(db.update("c", False, now=101.0), "즉시 해제됐다(너무 빠름)")
        self.assertTrue(db.update("c", False, now=101.9), "1.0초 전에 해제됐다")
        self.assertFalse(db.update("c", False, now=102.1), "1.0초 지나도 해제되지 않았다")

    def test_zone_path_unchanged_when_no_args(self):
        """★인자 없이 만들면 기존 config(zone.*)를 읽는다 — 침입 동작 무변경."""
        vals = {"enter_s": 1.0, "exit_s": 1.0}
        with mock.patch.object(zone_debounce.tuning, "val",
                               side_effect=lambda s, k, d, env=None: vals.get(k, d)):
            db = zone_debounce.ZoneDebouncer()
            db.update("c", False, now=99.5)
            db.update("c", True, now=100.0)
            self.assertFalse(db.update("c", True, now=100.5), "1.0초 전에 확정됐다")
            self.assertTrue(db.update("c", True, now=101.0))


class TestDeriveWiring(unittest.TestCase):
    """_derive 가 근접 디바운서를 실제로 태우는지(전이에서만 발화)."""

    def _dets(self):
        return [{"label": "forklift", "bbox": [0.40, 0.30, 0.80, 0.90], "class": "forklift"},
                {"label": "person", "bbox": [0.82, 0.45, 0.90, 0.88], "class": "person"}]

    def test_proximity_fires_only_on_transition(self):
        """_derive 는 now 를 넘기지 않으므로 실시계를 쓴다 — 검출주기 0.5초를 흉내 낸다."""
        import worker as W
        db = zone_debounce.ZoneDebouncer(enter=0.4, exit_=1.0)
        out = {"detections": self._dets(), "signals": {}, "person_count": 1}
        clock = [1000.0]
        fired_all = []
        with mock.patch.object(W.proximity, "detect",
                               return_value=[{"vehicle": "forklift", "distance_m": 1.2}]), \
             mock.patch.object(zone_debounce.time, "time", side_effect=lambda: clock[0]):
            for _ in range(3):
                fired_all.append(W._derive(out, [], 0.5625, cid="c", prox_debouncer=db))
                clock[0] += 0.5                       # 검출주기 0.5초
        rules = [[r for r, _, _ in f] for f in fired_all]
        self.assertNotIn("proximity_hazard", rules[0])
        self.assertIn("proximity_hazard", rules[1], "확정 전이에서 발화하지 않았다")
        self.assertNotIn("proximity_hazard", rules[2], "체류 중 재발화했다(폭주 위험)")

    def test_rollback_path_fires_every_frame(self):
        """prox_debouncer=None → 구 동작(매 프레임 발화)."""
        import worker as W
        out = {"detections": self._dets(), "signals": {}, "person_count": 1}
        with mock.patch.object(W.proximity, "detect",
                               return_value=[{"vehicle": "forklift", "distance_m": 1.2}]):
            f1 = W._derive(out, [], 0.5625, cid="c", prox_debouncer=None)
            f2 = W._derive(out, [], 0.5625, cid="c", prox_debouncer=None)
        for f in (f1, f2):
            self.assertIn("proximity_hazard", [r for r, _, _ in f])


class TestWorkerCallsNotify(unittest.TestCase):
    """★통합: 워커의 프레임 처리가 실제로 '기록 → 통보' 를 부르는지.

    단위 테스트만으로는 "게이트는 맞지만 아무도 안 부른다"([M1] 에서 실제로 발견된 상태)를
    못 잡는다 — 그래서 _process_frame 을 직접 돌려 호출 자체를 확인한다.
    """

    def _run_one_frame(self, signals):
        import numpy as np
        import worker as W

        cam = W.Worker()
        ctx = W._FrameCtx(["person", "ppe"], [], W.MotionTracker(), W.ErgonomicsTracker(),
                          False, 30.0, Path("."), "cam-t", "file.mp4")
        guard = mock.Mock()
        guard.detect.return_value = {"detections": [], "signals": signals, "person_count": 0}
        frame = np.zeros((90, 160, 3), dtype=np.uint8)
        cam._process_frame(frame, time.time(), guard, threading.RLock(), ctx)
        return cam

    def test_fired_risk_is_recorded_then_notified(self):
        import worker as W
        with mock.patch.object(W.data_engine, "log_event",
                               return_value={"evidence": "data/evidence/x.jpg"}) as rec, \
             mock.patch.object(W.alert_notify, "submit",
                               return_value={"queued": True, "suppressed": 0}) as sub:
            cam = self._run_one_frame({"fire_smoke": True})
        self.assertTrue(rec.called, "이벤트 기록이 호출되지 않았다")
        self.assertTrue(sub.called, "★통보가 호출되지 않았다 — 배선이 끊겼다")
        kw = sub.call_args.kwargs
        self.assertEqual(kw["rule"], "fire_smoke")
        self.assertEqual(kw["cam"], "cam-t")
        self.assertEqual(kw["meta"]["evidence"], "data/evidence/x.jpg",
                         "증거 경로가 통보에 실리지 않았다")
        self.assertEqual(cam.state.get("alerts_notified"), 1)

    def test_record_happens_before_notify(self):
        """★순서 계약: 기록이 먼저다 — 전송이 실패해도 증거·이벤트는 남아야 한다."""
        import worker as W
        order = []
        with mock.patch.object(W.data_engine, "log_event",
                               side_effect=lambda **k: order.append("record") or {}), \
             mock.patch.object(W.alert_notify, "submit",
                               side_effect=lambda **k: order.append("notify") or {"queued": True}):
            self._run_one_frame({"fire_smoke": True})
        self.assertEqual(order, ["record", "notify"])

    def test_notify_failure_does_not_break_frame_processing(self):
        """★통보가 폭발해도 프레임 처리는 계속된다(검출 무중단)."""
        import worker as W
        with mock.patch.object(W.data_engine, "log_event", return_value={}), \
             mock.patch.object(W.alert_notify, "submit", side_effect=RuntimeError("통보 폭발")):
            cam = self._run_one_frame({"fire_smoke": True})
        # _process_frame 이 프레임 단위 예외를 격리하므로 루프는 살아 있다
        self.assertIsNotNone(cam.state, "워커 상태가 사라졌다")

    def test_suppressed_alert_is_counted(self):
        import worker as W
        with mock.patch.object(W.data_engine, "log_event", return_value={}), \
             mock.patch.object(W.alert_notify, "submit",
                               return_value={"queued": False, "reason": "cooldown"}):
            cam = self._run_one_frame({"fire_smoke": True})
        self.assertEqual(cam.state.get("alerts_suppressed"), 1)
        self.assertEqual(cam.state.get("last_suppress_reason"), "cooldown")


if __name__ == "__main__":
    unittest.main()
