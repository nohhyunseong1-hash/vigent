"""[F5·F1·F2] 설치 전 안전 리뷰 수정 3건의 회귀 방지.

각 항목은 "조용히 실패하던" 고장 모드다 — 고쳤다는 사실보다 **다시 조용해지지 않는 것**이
중요해서, 계약을 여기에 못박는다.

  F5 위험구역 전역 폴백: 카메라별 구역이 없으면 **침입 판정을 하지 않는다**.
     이전에는 개발용 전역 좌표(config/danger_zone.json)가 조용히 적용돼, 운영자가
     "구역 미설정 = 감지 없음" 으로 믿는 동안 엉뚱한 자리를 감시했다.
  F1 슬롯 저하 노출: person 슬롯이 죽으면 /health 가 unhealthy 여야 한다.
     이전에는 다른 슬롯이 last_detect_ts 를 갱신해 stale 에도 안 걸려 영원히 healthy 였다.
  F2 기록 실패 격리: 디스크가 차서 증거·이벤트를 못 남겨도 **알림은 나가야 한다**.
     이전에는 log_event 의 OSError 가 호출부로 올라가 alert_notify.submit 까지 건너뛰었다.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import data_engine  # noqa: E402
import health_status as hs  # noqa: E402
import worker as W  # noqa: E402

ZONE = [(0.1, 0.1), (0.9, 0.1), (0.9, 0.9), (0.1, 0.9)]
GLOBAL_ZONE = [(0.0, 0.0), (0.5, 0.0), (0.5, 0.5)]


def _img(tmp: Path) -> str:
    """이미지 소스 — _setup_run 이 캡처를 열지 않아 부수효과 없이 검증 가능."""
    import cv2
    import numpy as np
    p = tmp / "f.jpg"
    cv2.imwrite(str(p), np.zeros((90, 160, 3), dtype=np.uint8))
    return str(p)


def _tuning(**vals):
    return mock.patch.object(W.tuning, "val",
                             side_effect=lambda s, k, d, env=None: vals.get(k, d))


# ───────────────────────────────────────────────── F5
class TestZoneFallbackBlocked(unittest.TestCase):
    """F5 — '설정 안 함' 과 '개발용 좌표 적용' 은 완전히 다르다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src = _img(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _setup(self, zone, **vals):
        w = W.Worker()
        with _tuning(**vals), \
             mock.patch.object(W, "_load_zone", return_value=list(GLOBAL_ZONE)):
            out = w._setup_run(self.src, "cam", 2.0, ["person"], zone)
        return w, out[1]          # (worker, ctx)

    def test_no_camera_zone_means_no_zone(self):
        """★구역 미설정이면 전역 좌표를 쓰지 않는다(기본 동작)."""
        w, ctx = self._setup(None)
        self.assertEqual(ctx.zone, [], "미설정인데 전역 구역이 적용됐다")
        self.assertEqual(w.state["zone_source"], "none")
        self.assertEqual(w.state["zone_points"], 0)

    def test_no_zone_never_fires_intrusion(self):
        """구역이 없으면 침입 판정 자체가 성립하지 않는다."""
        out = {"detections": [{"label": "person", "class": "person",
                               "bbox": [0.2, 0.2, 0.4, 0.8]}],
               "signals": {}, "person_count": 1}
        fired = W._derive(out, [], 0.5625, cid="cam",
                          debouncer=W.zone_debounce.ZoneDebouncer())
        self.assertNotIn("zone_intrusion", [r for r, _, _ in fired])

    def test_camera_zone_is_used(self):
        """카메라별 구역이 있으면 그대로 쓴다(기존 동작 불변)."""
        w, ctx = self._setup([list(p) for p in ZONE])
        self.assertEqual(len(ctx.zone), 4)
        self.assertEqual(w.state["zone_source"], "camera")

    def test_global_fallback_is_opt_in(self):
        """★롤백 경로: zone.global_fallback=true 면 구 동작(전역 폴백) 복원."""
        w, ctx = self._setup(None, global_fallback=True)
        self.assertEqual(len(ctx.zone), 3, "opt-in 인데 전역 구역이 적용되지 않았다")
        self.assertEqual(w.state["zone_source"], "global")

    def test_fallback_on_but_no_global_file(self):
        """폴백을 켰는데 전역 파일도 비어 있으면 none 으로 정직하게 남는다."""
        w = W.Worker()
        with _tuning(global_fallback=True), mock.patch.object(W, "_load_zone", return_value=[]):
            out = w._setup_run(self.src, "cam", 2.0, ["person"], None)
        self.assertEqual(out[1].zone, [])
        self.assertEqual(w.state["zone_source"], "none")

    def test_zone_source_reaches_health(self):
        """운영자가 /health 로 '구역 미설정' 을 볼 수 있어야 한다."""
        c = hs.camera_status({"running": True, "last_frame_secs_ago": 0.3,
                              "last_detect_secs_ago": 0.2, "uptime_s": 600,
                              "zone_source": "none", "zone_points": 0})
        self.assertEqual(c["zone_source"], "none")
        self.assertEqual(c["zone_points"], 0)


# ───────────────────────────────────────────────── F1
class TestSlotDegradedSurfaces(unittest.TestCase):
    """F1 — 사람을 못 보는 상태가 healthy 로 보이면 안 된다."""

    OKCAM = {"c1": {"status": hs.OK}}

    def test_person_slot_degraded_is_unhealthy(self):
        """★person 은 모든 규칙의 입력 — 죽으면 감시 목적 상실이라 unhealthy(503)."""
        r = hs.overall(self.OKCAM, model_loaded=True, slot_degraded={"person": True})
        self.assertEqual(r, hs.UNHEALTHY)

    def test_noncritical_slot_degraded_is_degraded(self):
        """ppe·fire_smoke 저하는 기능 축소지 감시 실패는 아니다 → degraded."""
        for slot in ("ppe", "fire_smoke", "forklift"):
            r = hs.overall(self.OKCAM, model_loaded=True, slot_degraded={slot: True})
            self.assertEqual(r, hs.DEGRADED, f"{slot} 저하가 반영되지 않았다")

    def test_false_values_are_ignored(self):
        """복구된 슬롯(False)은 정상으로 본다."""
        r = hs.overall(self.OKCAM, model_loaded=True,
                       slot_degraded={"person": False, "ppe": False})
        self.assertEqual(r, hs.HEALTHY)

    def test_no_slot_info_keeps_old_behavior(self):
        """인자를 안 주면 기존 판정 그대로(하위호환)."""
        self.assertEqual(hs.overall(self.OKCAM, model_loaded=True), hs.HEALTHY)

    def test_build_passes_slot_degraded_through(self):
        ws = {"cameras": {"c1": {"running": True, "last_frame_secs_ago": 0.3,
                                 "last_detect_secs_ago": 0.2, "uptime_s": 600}}}
        st, _ = hs.build(ws, model_loaded=True, slot_degraded={"person": True})
        self.assertEqual(st, hs.UNHEALTHY)

    def test_health_router_wires_slot_degraded(self):
        """호출부 계약 — 라우터가 guard 에서 꺼내 build 로 넘기고 본문에도 싣는다."""
        src = (Path(__file__).resolve().parent.parent
               / "vigent-core" / "routers" / "system.py").read_text(encoding="utf-8")
        self.assertIn('slot_degraded = _gs.get("slot_degraded"', src)
        self.assertIn("slot_degraded=slot_degraded", src)
        self.assertIn('"slot_degraded": slot_degraded,', src)


# ───────────────────────────────────────────────── F2
class TestRecordFailureDoesNotBlockAlert(unittest.TestCase):
    """F2 — 디스크가 차도 알림은 나가야 한다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self._orig = (data_engine._ROOT, data_engine._EVIDENCE, data_engine._RECOG)
        data_engine._ROOT, data_engine._EVIDENCE, data_engine._RECOG = (
            d, d / "evidence", d / "recognition")

    def tearDown(self):
        (data_engine._ROOT, data_engine._EVIDENCE, data_engine._RECOG) = self._orig
        self.tmp.cleanup()

    def test_log_event_survives_disk_failure(self):
        """★기록이 실패해도 예외를 올리지 않고 record 를 돌려준다(호출부의 통보가 이어진다)."""
        with mock.patch.object(Path, "mkdir", side_effect=OSError("No space left on device")):
            rec = data_engine.log_event(rule="zone_intrusion", level="high", site="c1",
                                        note="침입")
        self.assertIsInstance(rec, dict)
        self.assertEqual(rec["rule"], "zone_intrusion")
        self.assertIs(rec.get("logged"), False, "기록 실패가 표시되지 않았다")

    def test_log_event_survives_write_failure(self):
        real_open = open

        def boom(f, *a, **k):
            if str(f).endswith(".jsonl"):
                raise OSError("No space left on device")
            return real_open(f, *a, **k)

        with mock.patch("builtins.open", side_effect=boom):
            rec = data_engine.log_event(rule="fire_smoke", level="critical", site="c1")
        self.assertEqual(rec["rule"], "fire_smoke")
        self.assertIs(rec.get("logged"), False)

    def test_evidence_failure_returns_none_not_raise(self):
        """증거 저장 실패는 evidence=None 으로 흡수 — 이벤트 자체는 살아남는다."""
        tiny = ("data:image/jpeg;base64,"
                "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a")
        with mock.patch.object(Path, "mkdir", side_effect=OSError("disk full")):
            rec = data_engine.log_event(rule="ppe_missing", level="high",
                                        image_data_url=tiny)
        self.assertIsNone(rec["evidence"])
        self.assertEqual(rec["rule"], "ppe_missing")

    def test_normal_path_still_records(self):
        """정상 경로는 그대로 — 격리가 기록 자체를 죽이면 안 된다."""
        rec = data_engine.log_event(rule="zone_intrusion", level="high", site="c1")
        self.assertNotIn("logged", rec, "정상인데 실패 표시가 붙었다")
        files = list((data_engine._RECOG).glob("events_*.jsonl"))
        self.assertEqual(len(files), 1)
        saved = json.loads(files[0].read_text(encoding="utf-8").strip())
        self.assertEqual(saved["rule"], "zone_intrusion")

    def test_worker_calls_notify_after_record(self):
        """★통합 계약: 기록이 실패해도 워커는 통보를 호출한다."""
        import numpy as np
        cam = W.Worker()
        ctx = W._FrameCtx(["person"], [], W.MotionTracker(), W.ErgonomicsTracker(),
                          False, 30.0, Path(self.tmp.name), "cam-f2", "f.mp4")
        guard = mock.Mock()
        guard.detect.return_value = {"detections": [], "signals": {"fire_smoke": True},
                                     "person_count": 0}
        import threading
        import time as _t
        with mock.patch.object(W.data_engine, "log_event",
                               side_effect=lambda **k: {"evidence": None, "logged": False}), \
             mock.patch.object(W.alert_notify, "submit",
                               return_value={"queued": True, "suppressed": 0}) as sub:
            cam._process_frame(np.zeros((90, 160, 3), dtype=np.uint8), _t.time(),
                               guard, threading.RLock(), ctx)
        self.assertTrue(sub.called, "기록 실패 상황에서 통보가 호출되지 않았다")


if __name__ == "__main__":
    unittest.main()
