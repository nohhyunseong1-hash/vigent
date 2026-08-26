"""[규칙9] 운영 구성이 바뀌면 기준선도 다시 잰다 — 낡은 수치가 조용히 인용되는 것을 막는다.

★배경(2026-08-25 실제 사고): 2026-08-13 에 추적기를 IoU → ByteTrack 으로 바꿨는데
기준선을 다시 재지 않았다. 그 결과 **12일간 기획서·기준선 리포트가 person 재현율 68~77%**
를 인용했으나, 현 운영 구성 실측은 **38~59%** 였다. 심사·고객에게 그 숫자를 말했다면
사후에 신뢰가 무너진다.

이 테스트는 "수치가 맞는가"를 검사하지 않는다(그건 벤치마크의 일이다).
**낡았을 수 있는 수치에 경고 표기가 붙어 있는가**만 검사한다 — 사람이 지우면 실패한다.
"""
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


class StaleMetricsAreFlagged(unittest.TestCase):
    """IoU 시절 person 수치를 인용한 문서에 정정 표기가 살아 있는가."""

    def test_proposal_has_correction_block(self):
        t = (_ROOT / "docs" / "proposal_base_2026-08.md").read_text(encoding="utf-8")
        self.assertIn("68.2%", t, "기획서에서 해당 표가 사라졌다면 이 테스트를 갱신하라")
        self.assertIn("정정 (2026-08-25)", t,
                      "★기획서의 person 재현율 정정 블록이 지워졌다 — 낡은 77% 가 그대로 나간다")
        self.assertIn("38.2%", t, "정정 블록에 현 운영 실측값이 없다")

    def test_baseline_report_is_flagged(self):
        t = (_ROOT / "benchmarks" / "v1_field_baseline_report.md").read_text(encoding="utf-8")
        self.assertIn("[2026-08-25 정정]", t,
                      "★기준선 리포트의 'IoU 시절' 표기가 지워졌다")

    def test_rule_is_documented(self):
        t = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("운영 구성이 바뀌면 기준선도 다시 잰다", t,
                      "★규칙9 가 사라졌다 — 같은 사고가 반복된다")


class TrackerConfigIsPinned(unittest.TestCase):
    """★추적기를 바꾸면 이 테스트가 실패한다 — 바꾼 사람이 기준선 재측정을 하게 만든다."""

    def test_tracker_change_forces_rebaseline(self):
        import yaml
        cfg = yaml.safe_load((_ROOT / "config" / "tuning.yaml").read_text(encoding="utf-8"))
        algo = (cfg.get("track") or {}).get("algo")
        self.assertEqual(
            algo, "bytetrack",
            "★추적기가 바뀌었다. 성능 기준선이 무효가 된다(2026-08-13 사고 참조).\n"
            "  `python benchmarks/x5_recall_knobs.py --exp tracker` 로 재측정하고,\n"
            "  기획서·기준선 리포트의 person 수치를 갱신한 뒤 이 테스트의 기대값을 바꿔라.")
