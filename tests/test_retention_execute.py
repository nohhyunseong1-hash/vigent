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
        """첫 주기 안전장치를 통과시킨다(후보를 보여준 주기가 이미 있었다고 표시).

        [R2-fix] delete_armed 만으로는 부족하고 armed_with_candidates 도 True 여야 해제된다."""
        retention.STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        retention.STATUS_PATH.write_text(
            '{"delete_armed": true, "armed_with_candidates": true}', encoding="utf-8")


class TestFirstRunSafety(_RetentionTest):
    def test_first_cycle_deletes_nothing(self):
        """★dry_run 을 false 로 바꾼 첫 주기에는 아무것도 지우지 않는다(설정 경로)."""
        old = _touch_old(self.ev / "old.jpg", 100)
        with self._cfg():
            st = retention.sweep()          # execute=None → 설정을 따르는 자동 주기
        self.assertTrue(old.exists(), "첫 주기인데 파일이 삭제됐다")
        self.assertTrue(st["first_run_notice"])
        self.assertEqual(st["deleted_count"], 0)
        self.assertGreaterEqual(st["pending_count"], 1)   # 예정 목록은 잡혀 있다

    def test_explicit_execute_bypasses_hold(self):
        """운영자가 --execute 로 명시 실행하면 첫 주기 보류를 적용하지 않는다.

        안전장치는 '설정 한 줄 바꿨더니 대량 삭제'를 막는 것이지, 명시적 지시를 막는 게 아니다."""
        old = _touch_old(self.ev / "old.jpg", 100)
        with self._cfg():
            st = retention.sweep(execute=True)
        self.assertFalse(old.exists())
        self.assertEqual(st["deleted_count"], 1)

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
        self._arm()
        with self._cfg(), mock.patch.object(retention, "_pinned_paths", return_value={pinned.resolve()}):   # [M6-2] resolve 집합
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

    def test_default_whitelist_is_group_dirs(self):
        """기본 화이트리스트는 선언된 그룹 디렉터리 자체 — data/ 하위 전부보다 좁아 더 안전하다."""
        with mock.patch.object(retention, "_retention_config", return_value={}):
            roots = retention.allowed_roots()
        self.assertEqual([r.name for r in roots], ["evidence"])


class TestArmingRequiresCandidates(_RetentionTest):
    """[R2-fix] 보류는 '후보를 실제로 보여준 주기'에만 해제된다.

    2026-08-18 실측에서 후보 0건인 첫 주기가 돌아 **빈 목록으로 안전장치가 소진**됐다.
    실제 삭제 대상이 생기는 시점(약 17일 뒤)에는 운영자가 목록을 보지 못한 채 삭제가
    시작될 상황이었다."""

    def test_zero_candidate_cycles_keep_hold(self):
        """★후보 0건 주기를 여러 번 돌려도 보류가 유지된다."""
        fresh = _touch_old(self.ev / "fresh.jpg", 5)      # 보존기간(30일) 내 → 후보 아님
        with self._cfg():
            for _ in range(3):
                st = retention.sweep()
        self.assertTrue(fresh.exists())
        self.assertEqual(st["deleted_count"], 0)
        self.assertFalse(st["armed_with_candidates"], "후보 0건인데 보류가 해제됐다")
        self.assertFalse(st["first_run_notice"])          # 보여줄 게 없으니 안내도 없다

    def test_hold_consumed_only_when_candidates_appear(self):
        """후보가 처음 생긴 주기: 목록만·미삭제 → 그 다음 주기부터 삭제."""
        _touch_old(self.ev / "fresh.jpg", 5)
        with self._cfg():
            retention.sweep()                              # 후보 0건 — 보류 유지
            expired = _touch_old(self.ev / "expired.jpg", 45)
            st1 = retention.sweep()                        # 후보 발생 첫 주기 — 목록만
            self.assertTrue(expired.exists(), "후보 발생 첫 주기인데 삭제됐다")
            self.assertTrue(st1["first_run_notice"])
            self.assertTrue(st1["armed_with_candidates"])
            st2 = retention.sweep()                        # 다음 주기 — 실삭제
        self.assertFalse(expired.exists(), "두 번째 주기인데 삭제되지 않았다")
        self.assertEqual(st2["deleted_count"], 1)

    def test_legacy_status_migrates_back_to_hold(self):
        """★구 형식(delete_armed 만 있고 armed_with_candidates 없음)은 보류로 되돌린다.

        빈 목록으로 소진된 상태이므로 되돌리는 것이 맞다."""
        retention.STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        retention.STATUS_PATH.write_text('{"delete_armed": true}', encoding="utf-8")
        with self._cfg():
            self.assertTrue(retention.first_run_pending(), "구 형식이 보류로 되돌아가지 않았다")
            expired = _touch_old(self.ev / "expired.jpg", 45)
            st = retention.sweep()
        self.assertTrue(expired.exists(), "마이그레이션 후에도 곧바로 삭제됐다")
        self.assertTrue(st["first_run_notice"])

    def test_explicit_execute_still_bypasses(self):
        """--execute 명시 실행은 후보 유무와 무관하게 즉시 삭제한다."""
        expired = _touch_old(self.ev / "expired.jpg", 45)
        with self._cfg():
            st = retention.sweep(execute=True)
        self.assertFalse(expired.exists())
        self.assertEqual(st["deleted_count"], 1)

    def test_missing_dir_is_info_not_warning(self):
        """[R2-fix] 미사용 그룹(디렉터리 없음)은 경고가 아니라 unused_groups 로 분류된다."""
        with self._cfg(), mock.patch.object(
                retention, "GROUP_DIRS",
                {"evidence": self.ev, "tbm": self.root / "data" / "tbm"}):
            st = retention.sweep()
        self.assertIn("tbm", st["unused_groups"])
        self.assertFalse(any("디렉터리 없음" in w for w in st["warnings"]),
                         "미사용 그룹이 여전히 경고로 쌓인다")


if __name__ == "__main__":
    unittest.main()
