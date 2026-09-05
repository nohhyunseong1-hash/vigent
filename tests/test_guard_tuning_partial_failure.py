"""[CODE_REVIEW M1-6] tuning.yaml 값 하나가 잘못돼도 **조용히 부분 적용**되면 안 된다.

배경: guard.__init__ 의 튜닝 블록이 통째로 `try … except Exception: pass` 였다. 예컨대
`detect.ema: "abc"` 처럼 형변환이 실패하면 **그 줄 이후의 모든 설정이 로그 한 줄 없이 기본값**으로
남았다(track.algo 등). ppe.required 오타를 크게 드러내도록 고친 취지와 정반대의 조용한 폴백.

고정하는 계약:
  ① 잘못된 키는 기본값 유지 + ERROR 로그 + status()["tuning_warn"] 노출(조용히 넘기지 않음)
  ② ★그 뒤의 다른 키는 **그대로 적용**된다(부분 적용 금지 — 키 단위 격리)
  ③ 정상 설정이면 tuning_warn 은 빈 목록(회귀 0)
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import tuning  # noqa: E402
import vision_loader  # noqa: E402
from agents import guard as guard_mod  # noqa: E402


def _guard_with_bad(sec: str, key: str, bad):
    real = tuning.val

    def fake_val(s, k, default, env=None):
        if s == sec and k == key:
            return bad
        return real(s, k, default, env)

    with mock.patch.object(tuning, "val", side_effect=fake_val):
        return guard_mod.GuardAgent(vision_loader.load_vision("safety"))


class TuningPartialFailure(unittest.TestCase):
    def test_bad_value_is_logged_and_defaulted_but_later_keys_still_apply(self):
        expected_algo = str(tuning.val("track", "algo", "iou")).strip().lower()   # 실제 tuning.yaml 값
        with self.assertLogs("vigent.guard", level="ERROR") as cm:
            g = _guard_with_bad("detect", "ema", "abc")           # float("abc") → ValueError
        self.assertEqual(g.EMA, guard_mod.GuardAgent.EMA, "잘못된 값이면 클래스 기본값이어야 한다")
        self.assertTrue(any("ema" in line for line in cm.output), f"어느 키가 실패했는지 로그에 없다: {cm.output}")
        warn = g.status().get("tuning_warn")
        self.assertTrue(warn and any("ema" in w for w in warn), f"status()에 노출 안 됨: {warn}")
        # ★핵심: ema 뒤에 읽히는 track.algo 는 여전히 tuning.yaml 값이어야 한다(부분 적용 금지)
        self.assertEqual(g.TRACK_ALGO, expected_algo,
                         "앞 키 하나가 실패했다고 뒤 키(track.algo)가 기본값으로 떨어졌다 — 부분 적용")

    def test_valid_config_has_no_warning(self):
        g = guard_mod.GuardAgent(vision_loader.load_vision("safety"))
        self.assertEqual(g.status().get("tuning_warn"), [])


if __name__ == "__main__":
    unittest.main()
