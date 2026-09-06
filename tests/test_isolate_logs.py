"""[5단계 마무리, 2026-09-06] tests/_isolate.isolate_logs — 테스트가 운영 logs/(vigent.log·events.jsonl)에 쓰지 못하게 한다.

실측: test_machine_guard·test_bypass_paths_gated 가 /dispatch/relay 로 vlog.log_event 를 타 운영 logs/events.jsonl 에
dispatch_relay 행 3개를 남겼다. 계약: 격리 중 log_event 는 임시 디렉터리에만 쓰고, 원복 뒤에는 원래 경로로 돌아간다.
isolate_alerts() 는 isolate_logs() 를 포함한다.
"""
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import vlog  # noqa: E402
from _isolate import isolate_alerts, isolate_logs  # noqa: E402


class IsolateLogs(unittest.TestCase):
    def test_log_event_goes_to_temp_and_restores(self):
        real_dir = vlog._LOG_DIR
        real_events = real_dir / "events.jsonl"
        before = real_events.stat().st_size if real_events.exists() else -1
        restore = isolate_logs()
        try:
            tmp_dir = vlog._LOG_DIR
            self.assertNotEqual(tmp_dir, real_dir)
            vlog.log_event({"type": "test_isolation_probe", "n": 1})
            written = (tmp_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertIn("test_isolation_probe", written, "격리 중 이벤트는 임시 파일로")
            for h in logging.getLogger().handlers:      # 루트 파일 핸들러는 운영 logs/ 아래를 가리키면 안 된다
                base = getattr(h, "baseFilename", "")
                if base:
                    self.assertFalse(Path(base).resolve().is_relative_to(real_dir.resolve()), base)
        finally:
            restore()
        self.assertEqual(vlog._LOG_DIR, real_dir)
        self.assertIsNone(vlog._event_logger, "원복 뒤 다음 log_event 가 원래 경로에 새 핸들러를 만든다")
        after = real_events.stat().st_size if real_events.exists() else -1
        self.assertEqual(after, before, "운영 events.jsonl 크기가 변하면 격리가 깨진 것")

    def test_isolate_alerts_includes_logs(self):
        real_dir = vlog._LOG_DIR
        restore = isolate_alerts()
        try:
            self.assertNotEqual(vlog._LOG_DIR, real_dir, "isolate_alerts 는 logs/ 격리를 포함한다")
        finally:
            restore()
        self.assertEqual(vlog._LOG_DIR, real_dir)

    def test_temp_dir_is_removed_on_restore(self):
        restore = isolate_logs()
        tmp_dir = vlog._LOG_DIR
        vlog.log_event({"type": "probe"})
        self.assertTrue((tmp_dir / "events.jsonl").exists())
        restore()
        self.assertFalse(tmp_dir.exists(), "임시 로그 디렉터리는 cleanup 에서 지워진다(핸들러가 닫혀야 Windows 에서 삭제된다)")


if __name__ == "__main__":
    unittest.main()
