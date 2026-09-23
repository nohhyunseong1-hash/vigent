"""[CODE_REVIEW M6-6] field_eval(현장 평가 프레임 530장) — 저장소 밖(VIGENT_DATA_DIR)으로 이동 + 보존 그룹 E(365일) + 보호 폴더 편입.

대표 결정(2026-09-06): 이동(D:\\vigent_private_data\\field_eval, 참조 코드는 data_paths.media()) + 보존 그룹 A 와 별도로
field_eval 그룹(365일) 신설 + privacy 보호 폴더(암호화 검사 대상) 편입.
보존 스윕은 저장소 안 그룹만 다루던 코드라(경로를 _ROOT 상대로 표기·복원), 저장소 밖 그룹은 절대경로로 다룬다.
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import data_paths  # noqa: E402
import privacy  # noqa: E402
import retention  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent


def _usage(free_gb: float):
    """shutil.disk_usage 대체 — total/used/free 를 가진 결과. 실제 디스크와 무관하게 만든다.

    ★왜: retention.sweep 은 `shutil.disk_usage(_ROOT).free` 를 읽어 5GB 미만이면 경고를 낸다.
      2026-09-23 실제 사고 — 개발기 C: 여유가 15.6GB → 4.0GB 로 떨어지자(CUDA 커널 캐시 +4GB)
      이 파일의 테스트가 **코드 변경 없이** 실패했다. 테스트가 기계 상태에 의존하면 안 된다.
    """
    import collections
    U = collections.namedtuple("usage", "total used free")
    free = int(free_gb * 1024**3)
    return lambda _path: U(total=free * 4, used=free * 3, free=free)


class FieldEvalGroup(unittest.TestCase):
    def test_group_registered_outside_repo_with_365_days(self):
        self.assertIn("field_eval", retention.GROUP_DIRS)
        self.assertEqual(retention.GROUP_DIRS["field_eval"], data_paths.media("field_eval"))
        with self.assertRaises(ValueError, msg="field_eval 은 저장소 밖이어야 한다"):
            retention.GROUP_DIRS["field_eval"].relative_to(retention._ROOT)
        self.assertEqual(retention.group_days("field_eval"), 365, "config/tuning.yaml retention.groups.field_eval")
        self.assertNotIn("field_eval", retention.PINNABLE_GROUPS)
        self.assertIn(data_paths.media("field_eval").resolve(), retention.allowed_roots())

    def test_scan_and_delete_group_outside_root(self):
        self.addCleanup(isolate_alerts())            # sweep() 이 alert_queue.prune 을 부른다 — 운영 DB 격리
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        outside = Path(tmp.name) / "private" / "field_eval"
        (outside / "frames").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        old = outside / "frames" / "old.jpg"
        old.write_bytes(b"x")
        t = time.time() - 400 * 86400
        os.utime(old, (t, t))
        new = outside / "frames" / "new.jpg"
        new.write_bytes(b"x")
        cfg = {"enabled": True, "dry_run": False, "groups": {"field_eval": {"days": 365}}}
        with mock.patch.object(retention, "_ROOT", root), \
                mock.patch.object(retention, "GROUP_DIRS", {"field_eval": outside}), \
                mock.patch.object(retention, "_retention_config", return_value=cfg), \
                mock.patch.object(retention, "STATUS_PATH", root / "data" / "st.json"), \
                mock.patch.object(retention, "DELETION_LOG_DIR", root / "data" / "retention"), \
                mock.patch.object(retention, "LOG_DIR", root / "logs"), \
                mock.patch.object(retention.shutil, "disk_usage", _usage(100)):   # 여유 100GB 고정 — 환경 무관
            info = retention.scan_group("field_eval", 365)
            self.assertTrue(Path(info["dir"]).is_absolute(), info["dir"])
            self.assertEqual([Path(c["path"]).name for c in info["candidates"]], ["old.jpg"])
            self.assertTrue(Path(info["candidates"][0]["path"]).is_absolute())
            st = retention.sweep(execute=True)
        self.assertFalse(old.exists(), "365일 초과 프레임은 지워져야 한다")
        self.assertTrue(new.exists())
        self.assertEqual(st["groups"]["field_eval"]["deleted"], [str(old)])
        self.assertEqual(st["warnings"], [])

    def test_low_disk_free_produces_one_warning(self):
        """★경고 기능 자체를 검증한다 — 여유 4GB 로 고정하면 경고가 **정확히 1건** 나야 한다.

        위 테스트가 여유를 100GB 로 고정해 '경고 없음' 만 보게 됐으므로, 경고가 조용히
        사라져도 아무 테스트도 못 잡는다. 이 테스트가 그 반대편을 잡는다.
        """
        self.addCleanup(isolate_alerts())
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name) / "repo"
        outside = Path(tmp.name) / "private" / "field_eval"
        (outside / "frames").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        cfg = {"enabled": True, "dry_run": True, "groups": {"field_eval": {"days": 365}}}
        with mock.patch.object(retention, "_ROOT", root), \
                mock.patch.object(retention, "GROUP_DIRS", {"field_eval": outside}), \
                mock.patch.object(retention, "_retention_config", return_value=cfg), \
                mock.patch.object(retention, "STATUS_PATH", root / "data" / "st.json"), \
                mock.patch.object(retention, "DELETION_LOG_DIR", root / "data" / "retention"), \
                mock.patch.object(retention, "LOG_DIR", root / "logs"), \
                mock.patch.object(retention.shutil, "disk_usage", _usage(4)):
            st = retention.sweep(execute=False)
        self.assertEqual(len(st["warnings"]), 1, st["warnings"])
        self.assertIn("4.0GB", st["warnings"][0])
        self.assertIn("5GB", st["warnings"][0])

    def test_protected_dirs_include_field_eval(self):
        self.assertIn(data_paths.media("field_eval"), privacy._protected_dirs())

    def test_benchmarks_use_field_eval_router_and_repo_has_labels_only(self):
        """[M6-6 정정] 이미지는 저장소 밖, 라벨(txt/json/md)은 저장소 data/field_eval 정본 — 스크립트는 data_paths.field_eval() 만 쓴다."""
        bad = sorted(p.name for p in (_REPO / "benchmarks").rglob("*.py")
                     if any(s in p.read_text(encoding="utf-8", errors="replace")
                            for s in ('_ROOT / "data" / "field_eval"', 'media("field_eval")')))
        self.assertEqual(bad, [], "field_eval 참조는 data_paths.field_eval(...) 로")
        repo_fe = _REPO / "data" / "field_eval"
        self.assertEqual([p.name for p in repo_fe.rglob("*.jpg")], [], "저장소 data/field_eval 에 이미지가 있으면 안 된다")
        self.assertTrue(any((repo_fe / "labels").glob("*.txt")), "정답 라벨은 저장소가 정본(git 추적)")


class FieldEvalRouting(unittest.TestCase):
    """data_paths.field_eval(rel): 이미지(확장자·이미지 디렉터리) → VIGENT_DATA_DIR, 그 외 파일·labels* → 저장소."""

    def setUp(self):
        self.priv = data_paths.media("field_eval")
        self.repo = _REPO / "data" / "field_eval"

    def test_images_go_private_labels_go_repo(self):
        fe = data_paths.field_eval
        self.assertEqual(fe("frames"), self.priv / "frames")
        self.assertEqual(fe("frames/a.jpg"), self.priv / "frames" / "a.jpg")
        self.assertEqual(fe("labels"), self.repo / "labels")
        self.assertEqual(fe("labels/a.txt"), self.repo / "labels" / "a.txt")
        self.assertEqual(fe("classes.txt"), self.repo / "classes.txt")
        self.assertEqual(fe("dev_test_split.json"), self.repo / "dev_test_split.json")
        self.assertEqual(fe("labels_draft_preview"), self.priv / "labels_draft_preview")   # 미리보기 jpg 폴더
        self.assertEqual(fe("labels_draft"), self.repo / "labels_draft")
        self.assertEqual(fe("rest89/labels_backup_20260808"), self.repo / "rest89" / "labels_backup_20260808")

    def test_mixed_dir_is_routed_per_child(self):
        fe = data_paths.field_eval
        out = fe("pilot20")
        self.assertEqual(out / "images", self.priv / "pilot20" / "images")
        self.assertEqual(out / "hints", self.priv / "pilot20" / "hints")
        self.assertEqual(out / "labels", self.repo / "pilot20" / "labels")
        self.assertEqual(out / "classes.txt", self.repo / "pilot20" / "classes.txt")
        self.assertEqual(os.fspath(out), str(self.repo / "pilot20"))
        root = fe()
        self.assertEqual(root / "frames", self.priv / "frames")
        self.assertEqual(root / "labels", self.repo / "labels")

    def test_montage_dir_mixed_by_extension(self):
        fe = data_paths.field_eval
        self.assertEqual(fe("s1_miss_montage"), self.priv / "s1_miss_montage")
        self.assertEqual(fe("s1_miss_montage/no_hardhat_judge_sheet.jpg"), self.priv / "s1_miss_montage" / "no_hardhat_judge_sheet.jpg")
        self.assertEqual(fe("s1_miss_montage/no_hardhat_judge_sheet.json"), self.repo / "s1_miss_montage" / "no_hardhat_judge_sheet.json")


if __name__ == "__main__":
    unittest.main()
