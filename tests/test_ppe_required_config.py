"""[현장 2026-08-27] 보호구 경보 대상을 현장별로 고를 수 있어야 한다.

★배경(실측): 학원 야외 실습장에서 보호구 경보 **490건 중 87건(17.8%, CI 14.6~21.4)** 이
"마스크 미착용"만으로 발화했다. 완전 착용 장면(07)에서는 **81건 중 72건(88.9%)** 이 그랬다 —
안전모 0.83~0.91 · 조끼 0.87~0.93 으로 **정상 착용한 상태**였는데도 경보가 났다(육안 확인).
마스크는 그 현장의 필수 보호구가 아니어서 **운영상 무의미한 경보**였다.

여기서 고정하는 계약:
  1) ★**기본값은 기존 3종 그대로** — 설정하지 않으면 동작이 바뀌지 않는다(규칙6).
  2) `ppe.required` 로 좁힐 수 있다.
  3) ★**오타·미지의 라벨로 경보가 통째로 꺼지지 않는다** — 알려진 라벨과 교집합이
     비면 기본값을 유지한다. 안전 기능이 오타 하나로 죽는 것이 가장 나쁘다.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import tuning  # noqa: E402
import vision_loader  # noqa: E402
from agents import guard as guard_mod  # noqa: E402


def _guard(required=None):
    """guard 는 `tuning` 을 **메서드 안에서 지역 import** 하므로 모듈 자체를 패치한다."""
    real = tuning.section

    def fake_section(name):
        if name == "ppe" and required is not None:
            return {"required": required}
        return real(name)

    with mock.patch.object(tuning, "section", side_effect=fake_section):
        return guard_mod.GuardAgent(vision_loader.load_vision("safety"))


class DefaultUnchanged(unittest.TestCase):
    def test_default_keeps_all_three(self):
        """★설정 없으면 기존 3종 — 승인 없이 안전 기능이 좁아지면 안 된다."""
        g = _guard()
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"})

    def test_module_constant_untouched(self):
        """모듈 상수는 그대로 — 다른 소비자가 참조한다."""
        self.assertEqual(guard_mod.PPE_MISSING_LABELS,
                         {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"})


class NarrowingWorks(unittest.TestCase):
    def test_can_drop_mask(self):
        """★현장 조치 — 마스크를 빼면 그 경보가 사라진다."""
        g = _guard(["NO-Hardhat", "NO-Safety-Vest"])
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest"})
        self.assertNotIn("NO-Mask", g.PPE_REQUIRED)

    def test_single_item(self):
        g = _guard(["NO-Hardhat"])
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat"})


class MisconfigurationIsSafe(unittest.TestCase):
    """계약 3 — ★오타가 안전 기능을 죽이면 안 된다."""

    def test_unknown_label_falls_back_to_default(self):
        g = _guard(["NO-Helmet", "오타"])      # 전부 미지의 라벨
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"},
                         "★오타만 있는 설정에서 보호구 경보가 통째로 꺼졌다")

    def test_empty_list_falls_back(self):
        g = _guard([])
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"})

    def test_partial_typo_keeps_valid_ones(self):
        """일부만 유효하면 유효한 것만 쓴다(전부 무시하지 않는다)."""
        g = _guard(["NO-Hardhat", "오타"])
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat"})


class WiredIntoSignal(unittest.TestCase):
    def test_signal_uses_instance_set(self):
        """모듈 상수가 아니라 인스턴스 설정을 봐야 현장 조정이 먹는다."""
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "agents"
               / "guard.py").read_text(encoding="utf-8")
        self.assertIn('d["label"] in self.PPE_REQUIRED', src,
                      "★ppe_missing 판정이 아직 모듈 상수를 본다 — 설정이 안 먹는다")


if __name__ == "__main__":
    unittest.main()
