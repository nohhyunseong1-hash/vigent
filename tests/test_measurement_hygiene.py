"""[2026-08-21] 측정 스크립트가 **죽은 항목·뭉뚱그린 사유**에 속지 않는지.

이틀 연속 같은 실수가 났다:
  - 08-20 offline_probe: `status==healthy` 를 요구 → 오프라인에서 텔레그램이 못 나가
    degraded 가 되는 **정상 동작**을 실패로 판정
  - 08-21 capacity_probe: /health 에 남은 **정지 카메라**의 stale age(40,544초)가
    `base_cycle_s` 로 잡혀 지연 판정이 무력화 + 경보 적체 degraded 2샘플로 N=2 가 탈락
    → **"한계 1대"라는 거짓 결과**(audit/capacity_probe_invalid_2026-08-21.md)

두 실수의 뿌리는 하나다: **집계에 무관한 항목을 섞고, 실패 사유를 뭉뚱그린 것.**
전수 점검에서 offline_probe·soak_report 에도 같은 패턴이 남아 있어 함께 고쳤고,
여기서 회귀를 잠근다.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


cap = _load("capacity_probe")

# /health 모사 — 가동 카메라 1대 + **삭제 후 남은 정지 카메라 1대**(stale age)
GHOST = {"status": "stopped", "last_detect_latency_ms": 171.7,
         "last_detect_age_s": 40544.0, "dropped_frames": 0}
LIVE = {"status": "ok", "last_detect_latency_ms": 160.0,
        "last_detect_age_s": 0.5, "dropped_frames": 0}


class TestStoppedCameraDoesNotPoisonMetrics(unittest.TestCase):
    """정지 카메라가 섞여도 집계·기준이 망가지지 않는다."""

    def _sample(self, cams, status="healthy", pending=0):
        h = {"status": status, "cameras": cams, "alerts": {"pending": pending}}
        orig = cap.api
        cap.api = lambda path: (200, h)
        try:
            return cap.sample(1)
        finally:
            cap.api = orig

    def test_aggregate_excludes_stopped(self):
        s = self._sample({"test": LIVE, "ghost": GHOST})
        self.assertEqual(s["age"], [0.5], "정지 카메라의 stale age 가 집계에 섞였다")
        self.assertEqual(s["lat"], [160.0])

    def test_base_cycle_uses_real_camera_only(self):
        samples = [self._sample({"test": LIVE, "ghost": GHOST}) for _ in range(5)]
        m = cap.summarize(samples, None)
        self.assertEqual(m["real_age_p95"], 0.5)
        self.assertLess(m["real_age_p95"], cap.BASE_CYCLE_SANE_MAX_S,
                        "기준 주기가 정상 범위를 벗어나면 측정이 무효가 된다")

    def test_stopped_camera_is_not_a_failure(self):
        samples = [self._sample({"test": LIVE, "ghost": GHOST}) for _ in range(5)]
        m = cap.summarize(samples, None)
        self.assertEqual(m["degraded_camera_samples"], 0)
        ok, bad = cap.judge(m, base_cycle_s=0.5)
        self.assertTrue(ok, f"정지 카메라만으로 불합격이 났다: {bad}")


class TestDegradedCauseIsSeparated(unittest.TestCase):
    """경보 적체 degraded 는 용량과 무관하므로 불합격이 아니다."""

    def _samples(self, cams, status, pending):
        out = []
        h = {"status": status, "cameras": cams, "alerts": {"pending": pending}}
        orig = cap.api
        cap.api = lambda path: (200, h)
        try:
            for _ in range(5):
                out.append(cap.sample(1))
        finally:
            cap.api = orig
        return out

    def test_alert_backlog_degraded_passes(self):
        """카메라는 멀쩡한데 미전송 경보 때문에 degraded — 합격이어야 한다."""
        m = cap.summarize(self._samples({"test": LIVE}, "degraded", 3), None)
        self.assertEqual(m["degraded_samples"], 5)
        self.assertEqual(m["degraded_camera_samples"], 0)
        self.assertEqual(m["degraded_alert_samples"], 5)
        self.assertEqual(m["alert_backlog_max"], 3)
        ok, bad = cap.judge(m, base_cycle_s=0.5)
        self.assertTrue(ok, f"경보 적체만으로 불합격이 났다: {bad}")

    def test_camera_degraded_fails(self):
        """카메라가 실제로 저하되면 불합격이어야 한다."""
        stale = dict(LIVE, status="stale_detect")
        m = cap.summarize(self._samples({"test": stale}, "degraded", 0), None)
        self.assertEqual(m["degraded_camera_samples"], 5)
        ok, bad = cap.judge(m, base_cycle_s=0.5)
        self.assertFalse(ok)
        self.assertTrue(any("카메라 저하" in b for b in bad), bad)


class TestOfflineProbeIgnoresStopped(unittest.TestCase):
    """offline_probe 도 같은 실수를 갖고 있었다(전수 점검에서 발견)."""

    def test_cams_ok_ignores_stopped(self):
        src = (ROOT / "scripts" / "offline_probe.py").read_text(encoding="utf-8")
        self.assertIn('v.get("status") != "stopped"', src,
                      "정지 카메라를 걸러내는 코드가 사라졌다")
        self.assertNotIn('return bool(c) and all(v.get("status") == "ok" for v in c.values())', src,
                         "정지 카메라까지 ok 를 요구하는 옛 코드가 남아 있다")


if __name__ == "__main__":
    unittest.main()
