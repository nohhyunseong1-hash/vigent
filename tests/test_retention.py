"""[Z-2] 디스크 보존 정책 회귀 테스트.

핵심 보장: ①기본(enabled=false/dry_run=true)은 아무것도 안 지운다 ②pin된 증거는 어떤 실행
조건에서도 삭제되지 않는다 ③rotate_if_large가 크기상한을 넘을 때만 회전한다 ④디렉터리가
없어도 죽지 않고 경고만 남긴다.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
import data_engine  # noqa: E402
import retention  # noqa: E402


def _touch_old(path: Path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    old = time.time() - age_days * 86400
    os.utime(path, (old, old))


class TestRetentionSweep(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.evidence_dir = self.root / "evidence"
        self.recognition_dir = self.root / "recognition"
        self._root_patch = mock.patch.object(retention, "_ROOT", self.root)   # relative_to(_ROOT) 정합
        self._root_patch.start()
        self._group_dirs_patch = mock.patch.object(
            retention, "GROUP_DIRS", {"evidence": self.evidence_dir, "recognition": self.recognition_dir})
        self._group_dirs_patch.start()
        self._status_patch = mock.patch.object(retention, "STATUS_PATH", self.root / "retention_status.json")
        self._status_patch.start()
        self._dellog_patch = mock.patch.object(retention, "DELETION_LOG_DIR", self.root / "retention_audit")
        self._dellog_patch.start()
        self._evidence_root_patch = mock.patch.object(data_engine, "_EVIDENCE", self.evidence_dir)
        self._evidence_root_patch.start()
        self._pinned_patch = mock.patch.object(data_engine, "_PINNED", self.evidence_dir / "pinned.json")
        self._pinned_patch.start()

    def tearDown(self):
        mock.patch.stopall()
        self._tmp.cleanup()

    def _config(self, enabled: bool, dry_run: bool, days: dict) -> dict:
        return {"enabled": enabled, "dry_run": dry_run,
                "groups": {k: {"days": v} for k, v in days.items()}}

    def test_disabled_deletes_nothing_even_with_execute(self):
        old = self.evidence_dir / "20260101" / "ev_old.jpg"
        _touch_old(old, age_days=100)
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(False, False, {"evidence": 30})):
            result = retention.sweep(execute=True)
        self.assertTrue(old.exists())
        self.assertFalse(result["executed_delete"])

    def test_dry_run_default_deletes_nothing(self):
        old = self.evidence_dir / "20260101" / "ev_old.jpg"
        _touch_old(old, age_days=100)
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(True, True, {"evidence": 30})):
            result = retention.sweep()   # execute 인자 없음 → dry_run 설정을 따름
        self.assertTrue(old.exists())
        self.assertFalse(result["executed_delete"])
        self.assertEqual(len(result["groups"]["evidence"]["candidates"]), 1)

    def test_enabled_execute_deletes_old_unpinned_file(self):
        old = self.evidence_dir / "20260101" / "ev_old.jpg"
        recent = self.evidence_dir / "20260101" / "ev_recent.jpg"
        _touch_old(old, age_days=100)
        _touch_old(recent, age_days=1)
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(True, True, {"evidence": 30})):
            result = retention.sweep(execute=True)   # --execute 가 dry_run 설정을 덮어씀
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(result["executed_delete"])
        self.assertEqual(result["groups"]["evidence"]["deleted"], [str(old.relative_to(self.root))])

    def test_pinned_evidence_survives_execute(self):
        old = self.evidence_dir / "20260101" / "ev_pin_me.jpg"
        _touch_old(old, age_days=100)
        rel = str(old.relative_to(retention._ROOT))
        data_engine.pin_evidence(rel)
        self.assertIn(rel, data_engine.pinned_paths())
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(True, True, {"evidence": 30})):
            result = retention.sweep(execute=True)
        self.assertTrue(old.exists(), "pin된 증거는 삭제되면 안 된다")
        self.assertEqual(result["groups"]["evidence"]["candidates"], [],
                          "pin된 파일은 삭제후보 목록에도 나오면 안 된다(제외됨을 명시)")

    def test_unpin_makes_file_deletable_again(self):
        old = self.evidence_dir / "20260101" / "ev_unpin.jpg"
        _touch_old(old, age_days=100)
        rel = str(old.relative_to(retention._ROOT))
        data_engine.pin_evidence(rel)
        data_engine.unpin_evidence(rel)
        self.assertNotIn(rel, data_engine.pinned_paths())
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(True, True, {"evidence": 30})):
            result = retention.sweep(execute=True)
        self.assertFalse(old.exists())
        self.assertEqual(len(result["groups"]["evidence"]["deleted"]), 1)

    def test_missing_group_dir_warns_not_crashes(self):
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(True, True, {"evidence": 30})):
            result = retention.sweep()
        self.assertTrue(any("디렉터리 없음" in w for w in result["warnings"]))

    def test_status_written_and_readable(self):
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(False, True, {})):
            retention.sweep()
        status = retention.read_status()
        self.assertIsNotNone(status)
        self.assertIn("last_run", status)
        self.assertIn("groups", status)

    def test_low_disk_space_triggers_warning(self):
        fake_usage = mock.Mock(free=1024 ** 3)   # 1GB < WARN_FREE_BYTES(5GB)
        with mock.patch.object(retention, "_retention_config",
                                return_value=self._config(False, True, {})), \
             mock.patch("shutil.disk_usage", return_value=fake_usage):
            result = retention.sweep()
        self.assertTrue(any("디스크 여유공간" in w for w in result["warnings"]))


class TestRotateIfLarge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "test.log"

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_rotate_when_under_cap(self):
        self.path.write_bytes(b"x" * 100)
        rotated = retention.rotate_if_large(self.path, max_mb=1)
        self.assertFalse(rotated)
        self.assertTrue(self.path.exists())
        self.assertFalse(self.path.with_suffix(".log.1").exists())

    def test_rotates_when_over_cap(self):
        self.path.write_bytes(b"x" * (2 * 1024 * 1024))   # 2MB > 1MB 상한
        rotated = retention.rotate_if_large(self.path, max_mb=1)
        self.assertTrue(rotated)
        self.assertFalse(self.path.exists())   # 원본은 .1로 이름 변경됨
        backup = self.path.with_suffix(self.path.suffix + ".1")
        self.assertTrue(backup.exists())

    def test_missing_file_no_op(self):
        rotated = retention.rotate_if_large(self.path, max_mb=1)
        self.assertFalse(rotated)


if __name__ == "__main__":
    unittest.main()
