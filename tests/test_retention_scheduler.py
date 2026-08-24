"""[F6] 보존 스윕 자동 실행 스레드 — 검출을 막지 않고, 안전장치를 우회하지 않는다.

배경(설치 전 안전 리뷰 F6): `retention.sweep()` 은 구현돼 있었으나 **부르는 주체가 없어서**
사람이 손으로 돌려야 했다(main 스레드 0건 · schtasks 0건 · last_run 3일 전). 문서가 말하던
"자동 파기"가 사실이 아니었고, 디스크가 차면 [F2] 와 결합해 기록·통보가 함께 죽는 경로였다.

★여기서 고정하는 계약 4가지:
  1) 스윕 실패가 스레드를 죽이지 않는다 — 한 번 죽으면 이후 영영 안 돈다.
  2) 안전장치를 우회하지 않는다 — `sweep()` 을 execute 인자 없이 부른다(설정·첫 주기 보류 유지).
  3) 검출을 막지 않는다 — 별도 데몬 스레드이고 DETECT_LOCK·GPU 를 건드리지 않는다.
  4) 돌고 있는지 /health 로 보인다 — thread_alive=false 면 "설정만 있고 아무도 안 돌리는" 상태.
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import retention_scheduler as rs  # noqa: E402


def cfg(**kw):
    vals = {"auto_sweep": True, "sweep_interval_s": 86400.0,
            "sweep_initial_delay_s": 600.0, **kw}
    return mock.patch.object(rs.tuning, "val",
                             side_effect=lambda s, k, d, env=None: vals.get(k, d))


class TestSweepCall(unittest.TestCase):
    """계약 2 — 안전장치를 우회하지 않는다."""

    def setUp(self):
        rs._reset_for_test()

    def test_calls_sweep_without_execute_argument(self):
        """★execute 를 넘기면 [P1b] 첫 주기 보류가 우회된다 — 절대 넘기지 않는다."""
        fake = mock.Mock()
        fake.is_enabled.return_value = True
        fake.sweep.return_value = {"deleted_count": 0, "deleted_bytes": 0,
                                   "pending_count": 3, "elapsed_sec": 0.1}
        with mock.patch.dict(sys.modules, {"retention": fake}), cfg():
            rs._run_once()
        fake.sweep.assert_called_once_with()
        self.assertEqual(fake.sweep.call_args.args, ())
        self.assertEqual(fake.sweep.call_args.kwargs, {})

    def test_skips_when_retention_disabled(self):
        """보존 정책 자체가 꺼져 있으면 스윕하지 않는다."""
        fake = mock.Mock()
        fake.is_enabled.return_value = False
        with mock.patch.dict(sys.modules, {"retention": fake}), cfg():
            rs._run_once()
        fake.sweep.assert_not_called()

    def test_counts_successful_run(self):
        fake = mock.Mock()
        fake.is_enabled.return_value = True
        fake.sweep.return_value = {"deleted_count": 2, "deleted_bytes": 1024,
                                   "pending_count": 0, "elapsed_sec": 0.5,
                                   "warnings": ["디스크 여유공간 부족"]}
        with mock.patch.dict(sys.modules, {"retention": fake}), cfg():
            rs._run_once()
        self.assertEqual(rs.status()["runs"], 1)


class TestFailureIsolation(unittest.TestCase):
    """계약 1·3 — 실패해도 스레드가 살아 있고 서비스에 영향이 없다."""

    def setUp(self):
        rs._reset_for_test()

    def tearDown(self):
        rs.stop()
        rs._reset_for_test()

    def test_sweep_exception_does_not_kill_thread(self):
        """★스윕이 폭발해도 다음 주기가 온다 — 한 번 죽으면 영영 안 돈다."""
        fake = mock.Mock()
        fake.is_enabled.return_value = True
        fake.sweep.side_effect = OSError("disk failure")
        with mock.patch.dict(sys.modules, {"retention": fake}), \
             cfg(sweep_initial_delay_s=0.0, sweep_interval_s=60.0):
            rs.start()
            for _ in range(60):
                if rs.status()["failures"]:
                    break
                time.sleep(0.05)
        st = rs.status()
        self.assertGreaterEqual(st["failures"], 1, "실패가 기록되지 않았다")
        self.assertTrue(st["thread_alive"], "★스윕 실패로 스레드가 죽었다")
        self.assertIn("OSError", st["last_error"])

    def test_thread_is_daemon(self):
        """계약 3 — 데몬이라 종료를 막지 않는다."""
        fake = mock.Mock()
        fake.is_enabled.return_value = True
        fake.sweep.return_value = {"deleted_count": 0, "deleted_bytes": 0,
                                   "pending_count": 0, "elapsed_sec": 0.0}
        with mock.patch.dict(sys.modules, {"retention": fake}), \
             cfg(sweep_initial_delay_s=0.0, sweep_interval_s=3600.0):
            t = rs.start()
        self.assertIsNotNone(t)
        self.assertTrue(t.daemon)

    def test_does_not_touch_detect_lock(self):
        """★검출 직렬화 락·모델을 잡지 않는다 — 잡으면 스윕 동안 검출이 멈춘다.

        ★주석·docstring 에는 설명 목적으로 그 이름들이 등장하므로(설계 근거 기록),
        **실행되는 코드만** 남기고 본다 — 문자열 매칭으로 검사하면 자기 설명에 걸린다.
        """
        import ast
        src = (Path(__file__).resolve().parent.parent
               / "vigent-core" / "retention_scheduler.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Import):
                names.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
        for forbidden in ("DETECT_LOCK", "app_state", "guard", "torch", "cv2", "numpy"):
            self.assertNotIn(forbidden, names,
                             f"스윕 스레드가 {forbidden} 를 실제로 참조한다(검출 간섭 위험)")


class TestRollbackAndStatus(unittest.TestCase):
    """계약 4 — 롤백 경로와 가시성."""

    def setUp(self):
        rs._reset_for_test()

    def tearDown(self):
        rs.stop()
        rs._reset_for_test()

    def test_auto_sweep_false_does_not_start(self):
        """롤백: retention.auto_sweep=false 면 구 동작(수동 실행만)."""
        with cfg(auto_sweep=False):
            t = rs.start()
        self.assertIsNone(t)
        self.assertFalse(rs.status()["thread_alive"])

    def test_status_exposes_liveness_and_next_run(self):
        fake = mock.Mock()
        fake.is_enabled.return_value = True
        fake.sweep.return_value = {"deleted_count": 0, "deleted_bytes": 0,
                                   "pending_count": 0, "elapsed_sec": 0.0}
        with mock.patch.dict(sys.modules, {"retention": fake}), \
             cfg(sweep_initial_delay_s=3600.0, sweep_interval_s=86400.0):
            rs.start()
            st = rs.status()
        self.assertTrue(st["auto_sweep"])
        self.assertTrue(st["thread_alive"])
        self.assertEqual(st["interval_h"], 24.0)
        self.assertIsNotNone(st["next_run_in_s"], "다음 예정 시각이 안 보인다")

    def test_start_is_idempotent(self):
        fake = mock.Mock()
        fake.is_enabled.return_value = True
        fake.sweep.return_value = {"deleted_count": 0, "deleted_bytes": 0,
                                   "pending_count": 0, "elapsed_sec": 0.0}
        with mock.patch.dict(sys.modules, {"retention": fake}), \
             cfg(sweep_initial_delay_s=3600.0):
            a = rs.start()
            b = rs.start()
        self.assertIs(a, b, "중복 호출로 스레드가 두 개 떴다")

    def test_interval_has_floor(self):
        """설정 실수로 0 을 넣어도 폭주하지 않는다(최소 60초)."""
        with cfg(sweep_interval_s=0.0):
            self.assertGreaterEqual(rs.interval_s(), 60.0)

    def test_main_wires_scheduler(self):
        """호출부 계약 — main 예열 배선에서 실제로 start() 를 부른다."""
        src = (Path(__file__).resolve().parent.parent
               / "vigent-core" / "main.py").read_text(encoding="utf-8")
        self.assertIn("import retention_scheduler", src)
        self.assertIn("retention_scheduler.start()", src)

    def test_health_exposes_sweep_status(self):
        src = (Path(__file__).resolve().parent.parent
               / "vigent-core" / "routers" / "system.py").read_text(encoding="utf-8")
        self.assertIn('"retention_sweep": retention_sweep,', src)


class TestZoneSeedIsEmpty(unittest.TestCase):
    """[F5 후속] 배포 시드에 개발용 구역 좌표가 남아 있으면 안 된다."""

    def test_seed_has_no_coordinates(self):
        import json
        p = Path(__file__).resolve().parent.parent / "config" / "danger_zone.json"
        if not p.exists():
            return                      # 파일 자체가 없어도 동작상 동일(빈 목록 반환)
        pts = json.loads(p.read_text(encoding="utf-8")).get("points") or []
        self.assertEqual(pts, [], "시드에 개발용 구역 좌표가 남아 있다(F5 재발 위험)")


if __name__ == "__main__":
    unittest.main()
