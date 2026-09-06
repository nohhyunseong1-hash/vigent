"""[CODE_REVIEW M7-1] tuning.yaml 엄격 로더 + "파일에 적힌 키 ⊆ 코드가 읽는 키" 드리프트 게이트.

실사고(2026-09-06 발견): config/tuning.yaml 에 최상위 `alerts:` 가 두 번(4행·224행) 있어 PyYAML 이 뒤 블록으로 덮어썼다.
앞 블록의 8개 키는 파일에 적혀 있어도 어떤 코드도 읽지 못했다(17일 잠복). 이 테스트가 고정하는 계약:
  1) 같은 매핑의 중복 키 → TuningConfigError(줄 번호 포함). 파싱 오류도 {} 로 삼키지 않는다.
  2) 실제 config/tuning.yaml·academy 프로파일은 엄격 로더를 통과하고, alerts 는 10키가 전부 살아 있다.
  3) 드리프트 게이트: yaml 에 적힌 (섹션.키)는 코드가 실제로 읽는 키여야 한다(죽은 설정 금지).
"""
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
sys.path.insert(0, str(_ROOT / "scripts"))

import check_profile_drift as cpd  # noqa: E402
import tuning  # noqa: E402

_ALERT_KEYS = {"notify", "notify_cooldown_s", "backoff_factor", "backoff_max_s", "quiet_reset_s",
               "max_per_hour", "queue_max", "guard_bypass_text", "max_attempts", "backoff_cap_s"}


class StrictLoader(unittest.TestCase):
    def test_duplicate_top_level_key_rejected_with_lines(self):
        text = textwrap.dedent("""\
            alerts:
              notify: true
            proximity:
              radius_m: 3.0
            alerts:
              max_attempts: 10
        """)
        with self.assertRaises(tuning.TuningConfigError) as cm:
            tuning.load_strict(text, source="t.yaml")
        self.assertIn("'alerts'", str(cm.exception))
        self.assertIn("줄 1", str(cm.exception))
        self.assertIn("줄 5", str(cm.exception))

    def test_duplicate_nested_key_rejected(self):
        text = "detect:\n  conf:\n    person: 0.4\n    person: 0.5\n"
        with self.assertRaises(tuning.TuningConfigError):
            tuning.load_strict(text)

    def test_parse_error_is_not_swallowed_and_missing_file_is_empty(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "config").mkdir()
            with mock.patch.object(tuning, "_ROOT", root), mock.patch.object(tuning, "_CACHE", None):
                self.assertEqual(tuning.cfg(), {}, "파일 없음 = 빈 설정(기본값)")
            (root / "config" / "tuning.yaml").write_text("alerts: [unclosed\n", encoding="utf-8")
            with mock.patch.object(tuning, "_ROOT", root), mock.patch.object(tuning, "_CACHE", None):
                with self.assertRaises(tuning.TuningConfigError):
                    tuning.cfg()

    def test_real_config_and_profile_have_all_alert_keys(self):
        for rel in ("config/tuning.yaml", "deploy/academy/tuning.academy.yaml"):
            d = tuning.load_file(_ROOT / rel)
            self.assertEqual(set(d["alerts"]), _ALERT_KEYS, rel)

    def test_alert_gate_reads_file_values_not_defaults(self):
        with mock.patch.object(tuning, "_CACHE", None):
            self.assertEqual(tuning.val("alerts", "max_per_hour", 999), 6)
            self.assertEqual(tuning.val("alerts", "max_attempts", 999), 10)


class UnreadKeyGate(unittest.TestCase):
    def test_code_read_keys_cover_val_section_and_tv_patterns(self):
        keys = cpd.code_read_keys()
        self.assertIn("alerts.max_per_hour", keys)          # tuning.val("alerts", "max_per_hour", …)
        self.assertIn("track.ema_max", keys)                # tv(_tun, float, "track", "ema_max", …)
        self.assertIn("retention.*", keys)                  # tuning.section("retention") 통째로
        self.assertIn("detect.conf", keys)                  # _tun.section("detect").get("conf")

    def test_unread_keys_empty_for_real_files(self):
        for rel in ("config/tuning.yaml", "deploy/academy/tuning.academy.yaml"):
            self.assertEqual(cpd.unread_keys(_ROOT / rel), [], rel)

    def test_unread_key_is_reported(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "t.yaml"
            p.write_text("alerts:\n  max_per_hour: 6\n  bogus_key: 1\nretention:\n  anything: 1\n", encoding="utf-8")
            self.assertEqual(cpd.unread_keys(p), ["alerts.bogus_key"])


if __name__ == "__main__":
    unittest.main()
