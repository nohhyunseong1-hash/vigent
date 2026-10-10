"""tests/test_a4_fault_flag.py — 결함주입 스위치 판정 회귀 (2단계 A-4, 2026-10-10).

배경(점검 실측): `fault_stop_detect = bool(os.environ.get("VIGENT_FAULT_STOP_DETECT"))` —
bool("0") 은 True 라서 **끄려고** `=0` 을 설정하면 오히려 켜졌다. 이 스위치는 켜지면
_process_frame 이 즉시 return → 프레임 수신·/health 200 은 유지되는데 **추론이 0** 이
되는 무증상 상태(stale_detect 재현용 테스트 전용 장치가 운영을 죽이는 꼴).
→ 문자열 '1' 정확 일치만 켜는 _fault_stop_detect_enabled() 로 교정(worker.py 의 다른
환경 스위치와 동일 규칙). scripts/test_health_fault_injection.py 의 문서화된 사용법
(`VIGENT_FAULT_STOP_DETECT=1`)은 그대로 동작한다.
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

ENV = "VIGENT_FAULT_STOP_DETECT"


class TestFaultFlag(unittest.TestCase):
    def setUp(self):
        self._prev = os.environ.get(ENV)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = self._prev

    def _enabled(self) -> bool:
        import worker
        return worker._fault_stop_detect_enabled()

    def test_zero_means_off(self):
        """핵심 사고 조건: '0'(끄기 의도)이 켜짐으로 해석되면 안 된다."""
        os.environ[ENV] = "0"
        self.assertFalse(self._enabled())

    def test_false_and_empty_mean_off(self):
        for v in ("false", "no", "", "  "):
            os.environ[ENV] = v
            self.assertFalse(self._enabled(), f"{v!r} 는 꺼짐이어야 한다")
        os.environ.pop(ENV, None)
        self.assertFalse(self._enabled(), "미설정 = 꺼짐(기본 동작 불변)")

    def test_one_means_on(self):
        """문서화된 사용법(scripts/test_health_fault_injection.py: =1)은 그대로 켜진다."""
        os.environ[ENV] = "1"
        self.assertTrue(self._enabled())
        os.environ[ENV] = " 1 "
        self.assertTrue(self._enabled(), "공백 섞인 '1' 도 허용(strip)")

    def test_class_attribute_uses_same_rule(self):
        """Worker 클래스 속성이 이 판정 함수로 계산되는지 — import 시점 env 기준.
        (현재 프로세스는 env 미설정으로 import 됐으므로 False 여야 한다.)"""
        import worker
        self.assertFalse(worker.Worker.fault_stop_detect)


if __name__ == "__main__":
    unittest.main()
