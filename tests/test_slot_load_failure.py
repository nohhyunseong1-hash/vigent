"""[F31] 슬롯 '로드 실패'도 DEGRADED 로 드러난다 — 눈이 멀었는데 초록불이면 안 된다.

배경(2026-08-24 발견): [F1] 은 슬롯 **추론 실패**(로드는 됐는데 매 프레임 예외)만 덮었다.
`_get_model()` 이 None 을 돌려주는 **로드 실패** 경로(가중치 손상·GPU OOM·라이브러리 오류)는
`if model is None: continue` 로 조용히 넘어가, 스트릭도 slot_degraded 도 서지 않았다.
실측(주입 시험): person 로드 실패 10프레임 → 검출 0건인데 `/health` 는 **healthy**.
person 이 죽으면 위험구역 침입 경보가 통째로 무력화되는데 아무 표시가 없는 상태였다.

★여기서 고정하는 계약 3가지:
  1) 모델이 None 이면 연속 임계 도달 시 DEGRADED — F1 배선(핵심 슬롯 → unhealthy)을 탄다.
  2) **꺼둔 슬롯은 영향 없다** — 호출하지 않은 슬롯이 degraded 로 뜨면 오탐이다.
  3) **정상 모델은 초록 유지** — 이 수정이 멀쩡한 슬롯을 빨갛게 만들면 안 된다(규칙6).
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import numpy as np  # noqa: E402
from agents import guard as guard_mod  # noqa: E402

_FAKE_IMG = np.zeros((64, 64, 3), dtype=np.uint8)


class _OkModel:
    """정상 모델 — 항상 빈 목록(검출 0건)을 정상 반환한다."""

    def detect(self, image_bgr, conf=0.0, imgsz=None, augment=False):
        return []


def _guard(models: dict | None = None, backend: dict | None = None) -> guard_mod.GuardAgent:
    """모델 로딩 없이 detect() 만 돌릴 수 있는 최소 가드.

    `_models` 에 없는 슬롯은 `_get_model()` 을 타는데, backend='yolo' + `_slot_path` 비어 있으면
    **예외 없이 None** 을 돌려준다(guard.py `if backend == "yolo" and not path`).
    로드 실패를 GPU 없이 재현하는 가장 조용한 경로라 이걸 쓴다.
    """
    g = guard_mod.GuardAgent.__new__(guard_mod.GuardAgent)
    g._models = dict(models or {})
    g._slot_path = {}
    g._backend = dict(backend or {})
    g._rfdetr_weights = {}
    g._load_errors = {}
    g._predict_fail_streak = {}
    g._slot_degraded = {}
    g._tracks_by_key = {}
    g._bytetrack_by_key = {}
    g._key_last_used = {}
    g._last_sweep_at = 0.0
    g._tid_seq = 0
    g.HYSTERESIS = dict(g.HYSTERESIS_FRAMES)
    g._sig_streak = {}
    g.PERSON_ENSEMBLE = False
    return g


class LoadFailureDegrades(unittest.TestCase):
    """계약 1 — 로드 실패가 표시된다."""

    def test_none_model_yields_no_detections(self):
        """전제 확인: 모델이 없으면 검출은 0건이다(=눈이 먼 상태)."""
        g = _guard()
        out = g.detect(_FAKE_IMG, detectors=["person"], track_key="t:none")
        self.assertEqual(out.get("detections"), [], "모델이 없는데 검출이 나왔다")

    def test_degraded_after_threshold(self):
        """★연속 임계 도달 시 DEGRADED — 수정 전에는 영원히 초록이었다."""
        g = _guard()
        thr = g.PREDICT_FAIL_DEGRADE_THRESHOLD
        for _ in range(thr - 1):
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:deg")
        self.assertFalse(g._slot_degraded.get("person"),
                         "임계 미만인데 벌써 DEGRADED (조급한 판정)")
        g.detect(_FAKE_IMG, detectors=["person"], track_key="t:deg")   # 임계 도달
        self.assertTrue(g._slot_degraded.get("person"),
                        "★로드 실패 연속 %d회인데 DEGRADED 가 안 섰다" % thr)

    def test_status_and_health_expose_it(self):
        """status() 노출 + F1 배선을 타 person 은 unhealthy 가 된다."""
        import health_status as hs
        g = _guard()
        for _ in range(g.PREDICT_FAIL_DEGRADE_THRESHOLD):
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:h")
        st = g.status()
        self.assertEqual(st["slot_degraded"], {"person": True}, "status() 에 노출 안 됨")
        verdict = hs.overall({"c": {"status": "ok"}}, True, 0, st["slot_degraded"])
        self.assertEqual(verdict, "unhealthy",
                         "★person 이 멀었는데 /health 가 unhealthy 가 아니다")

    def test_error_logged_with_reason(self):
        """원인이 로그로 드러난다 — 조용한 실패 금지."""
        g = _guard()
        with mock.patch.object(guard_mod, "_guard_logger") as lg:
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:log")
            self.assertTrue(lg.return_value.error.called, "ERROR 로그가 없다")

    def test_log_is_throttled_after_threshold(self):
        """★로그 폭주 방지 — 로드 실패는 재시도가 없어 매 프레임 영구 발생한다.

        그대로 두면 이 수정이 디스크를 채워 [F2](디스크 풀 → 기록·통보 사망)를 되살린다.
        """
        g = _guard()
        with mock.patch.object(guard_mod, "_guard_logger") as lg:
            for _ in range(60):
                g.detect(_FAKE_IMG, detectors=["person"], track_key="t:flood")
            calls = lg.return_value.error.call_count
        # 임계까지 매번(thr) + DEGRADED 승격 1회 = thr+1. 그 뒤 60프레임은 억제돼야 한다.
        self.assertLessEqual(calls, g.PREDICT_FAIL_DEGRADE_THRESHOLD + 1,
                             "★60프레임 동안 ERROR 로그가 %d줄 — 억제가 안 된다" % calls)


class NoFalsePositives(unittest.TestCase):
    """계약 2·3 — 이 수정이 멀쩡한 것을 빨갛게 만들면 안 된다(규칙6)."""

    def test_disabled_slot_is_untouched(self):
        """★꺼둔 슬롯(호출 안 한 슬롯)은 degraded 로 뜨지 않는다.

        forklift·fire_smoke 는 tuning 으로 끄면 worker 의 active_detectors() 에서 빠져
        애초에 detect() 에 넘어오지 않는다. 그런 슬롯이 빨간불이 되면 오탐이다.
        """
        g = _guard()
        for _ in range(10):
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:off")
        self.assertNotIn("forklift", g._slot_degraded, "호출도 안 한 슬롯이 degraded 로 떴다")
        self.assertNotIn("fire_smoke", g._slot_degraded)
        self.assertEqual(set(g.status()["slot_degraded"]), {"person"})

    def test_healthy_model_stays_green(self):
        """★정상 모델은 계속 초록 — 검출 0건이어도 '고장'이 아니다.

        사람이 없는 프레임은 정상적으로 0건이다. 이걸 실패로 세면 빈 현장이 전부 빨간불이 된다.
        """
        g = _guard(models={"person": _OkModel()})
        for _ in range(20):
            g.detect(_FAKE_IMG, detectors=["person"], track_key="t:ok")
        self.assertEqual(g._slot_degraded, {}, "★정상 모델인데 DEGRADED 로 떴다(오탐)")
        self.assertEqual(g._predict_fail_streak.get("person", 0), 0, "정상인데 실패 스트릭이 쌓였다")

    def test_mixed_one_dead_one_alive(self):
        """죽은 슬롯만 빨갛고 살아있는 슬롯은 그대로."""
        g = _guard(models={"ppe": _OkModel()})
        for _ in range(10):
            g.detect(_FAKE_IMG, detectors=["person", "ppe"], track_key="t:mix")
        self.assertTrue(g._slot_degraded.get("person"), "죽은 person 이 표시 안 됨")
        self.assertFalse(g._slot_degraded.get("ppe"), "★멀쩡한 ppe 까지 빨갛게 됐다")


class PathStripping(unittest.TestCase):
    """[F31] /health 는 무인증 허용이라 내부 절대경로를 응답에 싣지 않는다."""

    def test_paths_reduced_to_filename(self):
        from routers.system import _strip_paths
        win = "FileNotFoundError: D:" + chr(92) + "vigent" + chr(92) + "weights" + chr(92) + "a.pth 없음"
        self.assertNotIn("vigent", _strip_paths(win), "★윈도우 경로가 그대로 노출됐다")
        self.assertIn("a.pth", _strip_paths(win), "파일명까지 지워지면 진단이 불가능하다")
        posix = "RuntimeError: load /home/u/secret/weights/ppe.pth failed"
        self.assertNotIn("secret", _strip_paths(posix), "★posix 경로가 그대로 노출됐다")
        self.assertIn("ppe.pth", _strip_paths(posix))

    def test_plain_message_untouched(self):
        from routers.system import _strip_paths
        self.assertEqual(_strip_paths("RuntimeError: weights corrupted"),
                         "RuntimeError: weights corrupted")

    def test_length_capped(self):
        from routers.system import _strip_paths
        self.assertLessEqual(len(_strip_paths("x" * 5000)), 200)


if __name__ == "__main__":
    unittest.main()
