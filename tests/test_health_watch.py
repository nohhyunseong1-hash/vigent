"""OPEN_ISSUES_20261008 #5 — 감시 중단 원격 통보(health_watch). 설계 5줄을 그대로 고정한다.

  ① 전이 때만 발화: healthy→unhealthy 1건, 유지 중 0건, →healthy 복구 1건
  ② confirm: 같은 판정이 2회 연속이어야 발화(1회 깜빡임은 무시)
  ③ cooldown: 같은 키·같은 상태는 cooldown 안에 재통보 없음(suppressed 카운트)
  ④ 카메라 stale·슬롯 degraded 도 키별로 같은 규칙 · level 은 high(critical 금지 — 사이렌)
  ⑤ 스레드: 예열 전·유예 중엔 판정 안 함 · stop 으로 끝남 · submit 은 cam="system", edge=True
"""
from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "tests"))

import health_watch as hw  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


def _snap(state="healthy", cams=None, slots=None):
    return {"state": state, "cams": cams or {}, "slots": slots or {}}


class WatcherLogic(unittest.TestCase):
    def test_transition_confirm_cooldown_recovery(self):
        w = hw.Watcher(confirm=2, cooldown_s=100)
        self.assertEqual(w.observe(_snap("healthy"), 0), []); self.assertEqual(w.observe(_snap("healthy"), 30), [])   # 정상 확정은 통보 없음
        self.assertEqual(w.observe(_snap("unhealthy"), 60), [], "1회 관측은 깜빡임")
        ev = w.observe(_snap("unhealthy"), 90)
        self.assertEqual([(e["key"], e["state"], e["bad"]) for e in ev], [("overall", "unhealthy", True)])
        self.assertEqual(w.observe(_snap("unhealthy"), 120), [], "유지 중 재통보 없음")
        # 짧은 복구 뒤 재악화(cooldown 안) → 복구 1건, 재악화는 억제
        w.observe(_snap("healthy"), 150); rec = w.observe(_snap("healthy"), 180)
        self.assertEqual([(e["key"], e["recovered"]) for e in rec], [("overall", True)])
        w.observe(_snap("unhealthy"), 185); again = w.observe(_snap("unhealthy"), 186)
        self.assertEqual(again, []); self.assertEqual(w.suppressed, 1)
        # cooldown 뒤에는 다시 발화
        w.observe(_snap("healthy"), 300); w.observe(_snap("healthy"), 301)
        w.observe(_snap("unhealthy"), 400); late = w.observe(_snap("unhealthy"), 401)
        self.assertEqual(len(late), 1)

    def test_camera_and_slot_keys(self):
        w = hw.Watcher(confirm=1, cooldown_s=10)
        self.assertEqual(w.observe(_snap(cams={"c1": "ok"}, slots={"person": False}), 0), [])
        ev = w.observe(_snap("degraded", cams={"c1": "stale_frame"}, slots={"person": True}), 1)
        keys = sorted((e["key"], e["state"]) for e in ev)
        self.assertEqual(keys, [("camera:c1", "stale_frame"), ("overall", "degraded"), ("slot:person", "degraded")])
        for e in ev:
            rule, level, msg = hw.rule_and_message(e)
            self.assertEqual(level, "high", "critical 은 dispatch.on_severity 가 사이렌을 울린다")
            self.assertTrue(msg)
        self.assertEqual({hw.rule_and_message(e)[0] for e in ev}, {"camera_stale", "health_degraded", "slot_degraded"})
        rec = w.observe(_snap("healthy", cams={"c1": "ok"}, slots={"person": False}), 20)
        self.assertEqual({hw.rule_and_message(e)[0] for e in rec}, {"camera_recovered", "health_recovered", "slot_recovered"})
        # starting→ok 같은 정상 변형은 통보 없음
        w2 = hw.Watcher(confirm=1, cooldown_s=10)
        w2.observe(_snap(cams={"c2": "starting"}), 0)
        self.assertEqual(w2.observe(_snap(cams={"c2": "ok"}), 1), [])


class CheckOnceAndThread(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts()); hw.reset_for_test(); self.addCleanup(hw.reset_for_test)

    def test_check_once_submits_system_edge(self):
        sent = []
        sub = lambda **k: sent.append(k) or {"queued": True}   # noqa: E731
        with mock.patch.object(hw, "_cfg", side_effect=lambda k, d: {"watch_confirm": 1, "watch_cooldown_s": 600}.get(k, d)):
            self.assertEqual(hw.check_once(now=0, snap_fn=lambda: _snap("healthy"), submit=sub), [])
            ev = hw.check_once(now=1, snap_fn=lambda: _snap("unhealthy"), submit=sub)
        self.assertEqual(len(ev), 1); self.assertEqual(sent[0]["cam"], "system"); self.assertTrue(sent[0]["edge"])
        self.assertEqual(sent[0]["rule"], "health_unhealthy"); self.assertEqual(sent[0]["level"], "high")
        self.assertEqual(hw.status()["notified"], 1); self.assertEqual(hw.status()["last_state"], "unhealthy")

    def test_snapshot_exception_does_not_kill(self):
        def boom():
            raise RuntimeError("worker 없음")
        self.assertEqual(hw.check_once(now=0, snap_fn=boom, submit=lambda **k: {"queued": True}), [])
        self.assertIn("RuntimeError", hw.status()["last_error"])

    def test_thread_waits_for_ready_and_stops(self):
        calls = []
        with mock.patch.object(hw, "_cfg", side_effect=lambda k, d: {"watch_interval_s": 0.05, "startup_grace_s": 0.0}.get(k, d)), \
             mock.patch.object(hw, "_ready", return_value=False), mock.patch.object(hw, "check_once", side_effect=lambda: calls.append(1)):
            hw.start(); time.sleep(0.3)
            self.assertEqual(calls, [], "예열 전엔 판정하지 않는다")
            with mock.patch.object(hw, "_ready", return_value=True):
                time.sleep(0.3)
            self.assertGreaterEqual(len(calls), 2)
            hw.stop()
        self.assertFalse(any(t.name == "vigent-health-watch" and t.is_alive() for t in threading.enumerate()))

    def test_snapshot_uses_health_build(self):
        import health_status
        with mock.patch("worker.manager.status", return_value={"cameras": {"c1": {"running": True, "last_frame_ts": time.time(), "last_detect_ts": time.time()}}}), \
             mock.patch.dict("app_state.STATE", {"safety": {"agents": {"Guard": mock.Mock(status=lambda: {"slot_degraded": {"ppe": True}, "rfdetr_slots": [{"slot": "ppe"}]}), "Dispatcher": None}}}, clear=False), \
             mock.patch("alert_queue.counts", return_value={"pending": 0, "dead_1h": 0}):
            s = hw.snapshot()
        self.assertEqual(s["state"], health_status.DEGRADED); self.assertIn(s["cams"]["c1"], ("ok", "starting")); self.assertEqual(s["slots"], {"ppe": True})   # 가짜 state 는 기동 유예(starting)일 수 있다


if __name__ == "__main__":
    unittest.main()
