"""[2026-08-20] /health 의 검출기 표시가 **실제 런타임 설정과 일치**하는지 검증.

배경(학원 현장 노트북 설치 중 실측): routers/system.py 가 disabled_detectors 를 하드코딩해
`detect.include_forklift: 1` 로 지게차를 켠 학원 프로파일에서도 /health 는 계속
"forklift 제외됨" 으로 보고했다. 동작은 맞고 표시만 틀린 상태 —
이 프로젝트가 F-8·Q-3 에서 반복해 금지해 온 '조용한 거짓말' 유형이라 회귀를 막는다.

검증 대상:
  1. 전역 기본 프로파일   → forklift 제외 / fire_smoke 포함
  2. 학원 프로파일        → forklift 포함 / fire_smoke 제외
  3. 둘 다 끔 / 둘 다 켬  → 경계값
  4. active 와 disabled 는 항상 서로 배타적이고 합치면 알려진 슬롯 전체다
  5. 제외된 슬롯에는 반드시 사유 문자열이 붙는다(빈 사유 금지)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker  # noqa: E402


def _tuning_stub(include_fire_smoke: int, include_forklift: int):
    """tuning.val 을 프로파일 값으로 대체한다(파일 I/O 없이 설정만 바꿔 끼운다)."""
    values = {"include_fire_smoke": include_fire_smoke, "include_forklift": include_forklift}

    def fake_val(sec, key, default, env=None):
        if sec == "detect" and key in values:
            return values[key]
        return default

    return fake_val


class TestDetectorVisibility(unittest.TestCase):

    def _run(self, *, fire_smoke, forklift):
        with mock.patch.object(worker.tuning, "val", _tuning_stub(fire_smoke, forklift)):
            return worker.active_detectors(), worker.disabled_detectors()

    def test_global_default_profile(self):
        """전역 기본: fire_smoke 켬(1) · forklift 끔(0)."""
        active, disabled = self._run(fire_smoke=1, forklift=0)
        self.assertIn("fire_smoke", active)
        self.assertNotIn("forklift", active)
        self.assertIn("forklift", disabled)
        self.assertNotIn("fire_smoke", disabled)

    def test_academy_profile(self):
        """학원 프로파일: forklift 켬(1) · fire_smoke 끔(0).

        ★이것이 회귀 대상이다 — 하드코딩 시절엔 forklift 가 disabled 에 남아 있었다."""
        active, disabled = self._run(fire_smoke=0, forklift=1)
        self.assertIn("forklift", active)
        self.assertNotIn("forklift", disabled,
                         "학원 프로파일에서 forklift 를 켰는데 /health 가 제외됐다고 보고한다")
        self.assertNotIn("fire_smoke", active)
        self.assertIn("fire_smoke", disabled)

    def test_both_off(self):
        active, disabled = self._run(fire_smoke=0, forklift=0)
        self.assertEqual(set(active), {"person", "ppe"})
        self.assertEqual(set(disabled), {"fire_smoke", "forklift"})

    def test_both_on(self):
        active, disabled = self._run(fire_smoke=1, forklift=1)
        self.assertEqual(set(active), {"person", "ppe", "fire_smoke", "forklift"})
        self.assertEqual(disabled, {})

    def test_active_and_disabled_are_complementary(self):
        """어떤 프로파일이든 active ∪ disabled = 알려진 슬롯 전체, 교집합은 공집합."""
        for fs in (0, 1):
            for fl in (0, 1):
                with self.subTest(fire_smoke=fs, forklift=fl):
                    active, disabled = self._run(fire_smoke=fs, forklift=fl)
                    self.assertEqual(set(active) & set(disabled), set())
                    self.assertEqual(set(active) | set(disabled), set(worker._KNOWN_SLOTS))

    def test_every_disabled_slot_has_a_reason(self):
        """사유 없는 제외 금지 — 현장에서 '왜 꺼졌는지' 를 /health 만 보고 알아야 한다."""
        for fs in (0, 1):
            for fl in (0, 1):
                with self.subTest(fire_smoke=fs, forklift=fl):
                    _, disabled = self._run(fire_smoke=fs, forklift=fl)
                    for slot, reason in disabled.items():
                        self.assertTrue(reason and reason.strip(), f"{slot} 사유 비어 있음")
                        self.assertGreater(len(reason), 20, f"{slot} 사유가 너무 짧다")


class TestHealthBodyMatchesProfile(unittest.TestCase):
    """종단 확인: /health 응답 본문이 프로파일을 그대로 반영하는가.

    worker 단일 출처만 맞고 라우터가 여전히 하드코딩이면 위 테스트는 통과해도
    현장에서 보는 /health 는 틀린다 — 그 간극을 여기서 막는다.
    """

    def _health_body(self, *, fire_smoke, forklift):
        import json as _json

        from routers import system as _sys
        with mock.patch.object(worker.tuning, "val", _tuning_stub(fire_smoke, forklift)):
            resp = _sys.health()
        return _json.loads(resp.body.decode("utf-8"))

    def test_academy_profile_visible_in_health(self):
        b = self._health_body(fire_smoke=0, forklift=1)
        self.assertIn("forklift", b["active_detectors"])
        self.assertNotIn("forklift", b["disabled_detectors"],
                         "/health 가 켜진 forklift 를 제외됐다고 보고한다(하드코딩 회귀)")
        self.assertIn("fire_smoke", b["disabled_detectors"])

    def test_global_default_visible_in_health(self):
        b = self._health_body(fire_smoke=1, forklift=0)
        self.assertIn("fire_smoke", b["active_detectors"])
        self.assertIn("forklift", b["disabled_detectors"])
        self.assertNotIn("fire_smoke", b["disabled_detectors"])

    def test_health_matches_worker_single_source(self):
        """라우터 표시 == worker 계산. 둘이 갈라지면 실패한다."""
        for fs in (0, 1):
            for fl in (0, 1):
                with self.subTest(fire_smoke=fs, forklift=fl):
                    b = self._health_body(fire_smoke=fs, forklift=fl)
                    with mock.patch.object(worker.tuning, "val", _tuning_stub(fs, fl)):
                        self.assertEqual(b["active_detectors"], worker.active_detectors())
                        self.assertEqual(b["disabled_detectors"], worker.disabled_detectors())


class TestWarmupMatchesProfile(unittest.TestCase):
    """예열 슬롯이 **실제로 돌릴 슬롯**과 같은가.

    하드코딩 시절엔 학원 프로파일에서 끈 fire_smoke 를 예열하고(4.9s + VRAM 낭비),
    켠 forklift 는 예열하지 않아 현장 첫 프레임이 느려졌다 — 표시가 아니라 동작이 틀린 경우다.
    """

    class _FakeGuard:
        def __init__(self):
            self.warmed = []

        def detect(self, img, detectors=None, track_key=None):
            self.warmed.extend(detectors or [])
            return []

    def _warm(self, *, fire_smoke, forklift):
        import readiness
        g = self._FakeGuard()
        with mock.patch.object(worker.tuning, "val", _tuning_stub(fire_smoke, forklift)),              mock.patch.object(readiness, "required_weights_missing", lambda: []):
            readiness.warmup(g)
        return g.warmed

    def test_academy_profile_warms_forklift_not_fire_smoke(self):
        warmed = self._warm(fire_smoke=0, forklift=1)
        self.assertIn("forklift", warmed, "학원 프로파일인데 forklift 를 예열하지 않는다")
        self.assertNotIn("fire_smoke", warmed, "껐는데 fire_smoke 를 예열한다(시간·VRAM 낭비)")

    def test_global_default_warms_fire_smoke_not_forklift(self):
        warmed = self._warm(fire_smoke=1, forklift=0)
        self.assertIn("fire_smoke", warmed)
        self.assertNotIn("forklift", warmed)

    def test_warmup_equals_active_detectors(self):
        for fs in (0, 1):
            for fl in (0, 1):
                with self.subTest(fire_smoke=fs, forklift=fl):
                    warmed = self._warm(fire_smoke=fs, forklift=fl)
                    with mock.patch.object(worker.tuning, "val", _tuning_stub(fs, fl)):
                        self.assertEqual(warmed, worker.active_detectors())


if __name__ == "__main__":
    unittest.main()
