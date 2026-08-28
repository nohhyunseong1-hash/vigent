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
    """계약 3 — ★오타가 안전 기능을 죽이면 안 되고, **조용히 넘어가서도 안 된다**.

    ★[2026-08-28] 예전에는 오타·빈 목록이 **로그 한 줄 없이** 기본 3종으로 복귀했다.
      그러면 운영자는 "마스크를 껐다"고 믿는데 오탐은 그대로 나고 원인은 보이지 않는다.
      조용한 폴백이 오탐 자체보다 나쁘다 — 반드시 드러나야 한다.
    """

    def test_unknown_label_falls_back_to_default(self):
        g = _guard(["NO-Helmet", "오타"])      # 전부 미지의 라벨
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"},
                         "★오타만 있는 설정에서 보호구 경보가 통째로 꺼졌다")

    def test_unknown_label_is_not_silent(self):
        """★핵심 — 무시했다는 사실이 상태로 드러나야 한다."""
        g = _guard(["helemt"])
        warn = g.status()["ppe_config_warn"]
        self.assertTrue(warn, "★오타가 조용히 무시됐다 — 운영자가 알 방법이 없다")
        self.assertIn("helemt", warn, "무엇이 잘못됐는지 문구에 없다")
        self.assertIn("NO-Hardhat", warn, "가능한 값 안내가 없다")

    def test_unknown_label_logs_error(self):
        """로그로도 남는다 — /health 를 안 보는 운영자를 위해."""
        with mock.patch.object(guard_mod, "_guard_logger") as lg:
            _guard(["helemt"])
        self.assertTrue(lg.return_value.error.called or lg.return_value.warning.called,
                        "★설정 무효인데 로그가 없다")

    def test_empty_list_is_not_silent(self):
        """빈 리스트도 마찬가지 — 보호구 경보가 꺼지지도, 조용하지도 않는다."""
        g = _guard([])
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"},
                         "★빈 리스트로 보호구 경보가 통째로 꺼졌다")
        self.assertTrue(g.status()["ppe_config_warn"], "★빈 리스트가 조용히 무시됐다")

    def test_partial_typo_invalidates_whole_config(self):
        """★[2026-08-28 재수정] 일부만 유효해도 **설정 전체를 무효**로 본다.

        예전에는 "유효한 것만 골라 쓰기"를 했는데, 그게 **가장 위험한 경우에 신호가 가장
        약한** 구조였다 — 오타 단독·빈 목록은 기본 3종으로 폴백해 커버리지가 **넓어지지만**,
        부분 무효만 커버리지가 **좁아졌다.** 예: 안전모+조끼를 의도한
        `['helemt','NO-Safety-Vest']` 가 조끼만 감시하고 **안전모 미착용 경보가 조용히 사라진다.**
        앞의 둘은 과탐 쪽으로 틀리지만 이건 **미탐 쪽으로** 틀린다.
        """
        g = _guard(["helemt", "NO-Safety-Vest"])
        self.assertEqual(g.PPE_REQUIRED, {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"},
                         "★부분 무효인데 좁은 설정이 적용됐다 — 안전모 경보가 조용히 사라진다")
        warn = g.status()["ppe_config_warn"]
        self.assertTrue(warn, "부분 무효를 알리지 않았다")
        self.assertIn("helemt", warn, "무엇이 잘못됐는지 문구에 없다")

    def test_all_invalid_cases_behave_identically(self):
        """★세 경우(오타단독·빈목록·부분무효)의 처리가 **같아야** 한다 — 심각도 통일."""
        results = [(_guard(r).PPE_REQUIRED, bool(_guard(r).status()["ppe_config_warn"]))
                   for r in (["helemt"], [], ["helemt", "NO-Safety-Vest"])]
        base = {"NO-Hardhat", "NO-Safety-Vest", "NO-Mask"}
        for req, warned in results:
            self.assertEqual(req, base, "무효 설정인데 기본값으로 안 돌아갔다")
            self.assertTrue(warned, "무효 설정인데 조용하다")

    def test_partial_invalid_logs_error_not_just_warning(self):
        """★부분 무효도 ERROR 다 — 예전엔 WARN 뿐이라 신호가 약했다."""
        with mock.patch.object(guard_mod, "_guard_logger") as lg:
            _guard(["helemt", "NO-Safety-Vest"])
        self.assertTrue(lg.return_value.error.called,
                        "★부분 무효가 ERROR 로 남지 않는다 — 미탐 방향인데 신호가 약하다")

    def test_valid_config_has_no_warning(self):
        """정상 설정에서는 경고가 없어야 한다 — 늑대소년이 되면 아무도 안 본다."""
        self.assertEqual(_guard(["NO-Hardhat", "NO-Safety-Vest"]).status()["ppe_config_warn"], "")
        self.assertEqual(_guard().status()["ppe_config_warn"], "")


class WiredIntoSignal(unittest.TestCase):
    def test_signal_uses_instance_set(self):
        """모듈 상수가 아니라 인스턴스 설정을 봐야 현장 조정이 먹는다."""
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "agents"
               / "guard.py").read_text(encoding="utf-8")
        self.assertIn('d["label"] in self.PPE_REQUIRED', src,
                      "★ppe_missing 판정이 아직 모듈 상수를 본다 — 설정이 안 먹는다")


if __name__ == "__main__":
    unittest.main()
