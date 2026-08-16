"""[P1b] 자동 파기 실동작 테스트 — 보존기간 초과분만 지워지는가, 안전장치가 작동하는가.

배경(감사 🟠C2): `retention.dry_run: true` 라 정책은 켜져 있는데 **실제로는 아무것도 지우지
않고 있었다**. 개인영상정보를 기한 없이 보관하는 상태였다.

검증:
  1. 보존기간 초과분만 삭제되고 기간 내 파일은 남는다
  2. ★첫 주기 안전장치 — dry_run 을 false 로 바꾼 **첫 주기에는 아무것도 지우지 않는다**
  3. ★경로 화이트리스트 — 목록 밖 경로는 어떤 경우에도 삭제되지 않는다
  4. pin 된 증거는 기간이 지나도 삭제되지 않는다(기존 보장 유지)
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import retention  # noqa: E402


def _touch_old(p: Path, age_days: float, size: int = 128) -> Path:
    """age_days 만큼 오래된 파일 생성(mtime 조작)."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    old = time.time() - age_days * 86400
    os.utime(p, (old, old))
    return p


class _RetentionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.data = self.root / "data"
        self.ev = self.data / "evidence"
        # 모듈 전역 경로를 임시 폴더로 갈아끼운다(실제 data/ 를 건드리지 않기 위해)
        self._patches = [
            mock.patch.object(retention, "_ROOT", self.root),
            mock.patch.object(retention, "GROUP_DIRS", {"evidence": self.ev}),
            mock.patch.object(retention, "GROUP_LABEL", {"evidence": "A"}),
            mock.patch.object(retention, "STATUS_PATH", self.data / "retention_status.json"),
            mock.patch.object(retention, "DELETION_LOG_DIR", self.data / "retention"),
            mock.patch.object(retention, "_pinned_paths", return_value=set()),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()

    def _cfg(self, **kw):
        base = {"enabled": True, "dry_run": False, "allowed_roots": ["data"],
                "groups": {"evidence": {"days": 30}}}
        base.update(kw)
        return mock.patch.object(retention, "_retention_config", return_value=base)

    def _arm(self):
        """첫 주기 안전장치를 통과시킨다(이미 한 번 돌았다고 표시)."""
        retention.STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        retention.STATUS_PATH.write_text('{"delete_armed": true}', encoding="utf-8")


class TestFirstRunSafety(_RetentionTest):
    def test_first_cycle_deletes_nothing(self):
        """★dry_run 을 false 로 바꾼 첫 주기에는 아무것도 지우지 않는다."""
        old = _touch_old(self.ev / "old.jpg", 100)
        with self._cfg():
            st = retention.sweep()
        self.assertTrue(old.exists(), "첫 주기인데 파일이 삭제됐다")
        self.assertTrue(st["first_run_notice"])
        self.assertEqual(st["deleted_count"], 0)
        self.assertGreaterEqual(st["pending_count"], 1)   # 예정 목록은 잡혀 있다

    def test_second_cycle_deletes(self):
        """첫 주기 이후에는 실제로 삭제된다."""
        old = _touch_old(self.ev / "old.jpg", 100)
        with self._cfg():
            retention.sweep()          # 1주기: 보류
            self.assertTrue(old.exists())
            st = retention.sweep()     # 2주기: 실삭제
        self.assertFalse(old.exists(), "두 번째 주기인데도 삭제되지 않았다")
        self.assertEqual(st["deleted_count"], 1)


class TestAgeBasedDeletion(_RetentionTest):
    def test_only_expired_deleted(self):
        """보존기간(30일) 초과분만 삭제되고 기간 내 파일은 남는다."""
        expired = _touch_old(self.ev / "expired.jpg", 45)
        fresh = _touch_old(self.ev / "fresh.jpg", 5)
        self._arm()
        with self._cfg():
            st = retention.sweep()
        self.assertFalse(expired.exists(), "만료 파일이 남아 있다")
        self.assertTrue(fresh.exists(), "보존기간 내 파일이 삭제됐다")
        self.assertEqual(st["deleted_count"], 1)
        self.assertGreater(st["deleted_bytes"], 0)

    def test_dry_run_true_deletes_nothing(self):
        expired = _touch_old(self.ev / "expired.jpg", 45)
        self._arm()
        with self._cfg(dry_run=True):
            st = retention.sweep()
        self.assertTrue(expired.exists())
        self.assertEqual(st["deleted_count"], 0)

    def test_disabled_deletes_nothing(self):
        expired = _touch_old(self.ev / "expired.jpg", 45)
        self._arm()
        with self._cfg(enabled=False):
            retention.sweep()
        self.assertTrue(expired.exists())

    def test_pinned_evidence_survives(self):
        """pin 된 증거는 기간이 지나도 삭제되지 않는다(기존 보장 유지)."""
        pinned = _touch_old(self.ev / "pinned.jpg", 100)
        rel = str(pinned.relative_to(self.root))
        self._arm()
        with self._cfg(), mock.patch.object(retention, "_pinned_paths", return_value={rel}):
            retention.sweep()
        self.assertTrue(pinned.exists(), "pin 된 증거가 삭제됐다")


class TestPathWhitelist(_RetentionTest):
    def test_outside_whitelist_is_refused(self):
        """★화이트리스트 밖 경로는 삭제되지 않는다(되돌릴 수 없는 작업의 마지막 방어선)."""
        outside = self.root / "elsewhere" / "important.jpg"
        _touch_old(outside, 100)
        with self._cfg(allowed_roots=["data"]):
            self.assertFalse(retention.is_path_allowed(outside))
            self.assertTrue(retention.is_path_allowed(self.ev / "x.jpg"))

    def test_sweep_refuses_outside_paths(self):
        """그룹 경로가 화이트리스트 밖으로 잘못 설정돼도 삭제하지 않고 경고만 남긴다."""
        outside_dir = self.root / "elsewhere"
        victim = _touch_old(outside_dir / "victim.jpg", 100)
        self._arm()
        with self._cfg(allowed_roots=["data"]), \
             mock.patch.object(retention, "GROUP_DIRS", {"evidence": outside_dir}):
            st = retention.sweep()
        self.assertTrue(victim.exists(), "화이트리스트 밖 파일이 삭제됐다")
        self.assertEqual(st["deleted_count"], 0)
        self.assertTrue(any("화이트리스트" in w for w in st["warnings"]))

    def test_default_whitelist_is_data_dir(self):
        with mock.patch.object(retention, "_retention_config", return_value={}):
            roots = retention.allowed_roots()
        self.assertEqual([r.name for r in roots], ["data"])


if __name__ == "__main__":
    unittest.main()
