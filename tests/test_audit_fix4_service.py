"""CODE_AUDIT_20260928 #4 — 서비스 자가 재기동·종료 대기·Linux 유닛·워치독 유예. [2026-09-28]

★무엇을 고정하는가
  ① 기아 3단계: VIGENT_RESTART_CMD='exit:3' 이면 graceful 정리 뒤 _process_exit(3) — 서비스 관리자(NSSM)가 다시 띄운다. 'sc stop & sc start' 는 더 이상 기본이 아니다.
  ② install_service.ps1 은 AppStopMethodConsole 30000 등 정지 대기를 설정하고 restartCmd 는 exit:3 이다.
  ③ WorkerManager.stop_all 은 병렬 + 데드라인: 막힌 워커 하나가 전체를 붙잡지 않고 pending 으로 보고된다.
  ④ systemd ExecStart 가 가리키는 파일이 저장소 bin/ 에 있다. watchdog.sh 는 phase=starting 을 정상으로 보고 재기동 유예를 둔다.
"""
from __future__ import annotations

import re
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

import starvation_guard as sg  # noqa: E402
import worker  # noqa: E402


class StageThreeSelfExit(unittest.TestCase):
    def test_exit_cmd_calls_process_exit_after_graceful(self):
        order: list[str] = []
        fake_main = type("M", (), {"_shutdown": staticmethod(lambda: order.append("shutdown"))})()
        with mock.patch.object(sg, "_RESTART_CMD", "exit:3"), mock.patch.object(sg, "_process_exit", side_effect=lambda c: order.append(f"exit:{c}")), \
             mock.patch.dict(sys.modules, {"main": fake_main}):
            sg._escalate()
        self.assertEqual(order, ["shutdown", "exit:3"])

    def test_exit_cmd_default_code_and_graceful_failure_still_exits(self):
        order: list[str] = []
        bad_main = type("M", (), {"_shutdown": staticmethod(lambda: (_ for _ in ()).throw(RuntimeError("boom")))})()
        with mock.patch.object(sg, "_RESTART_CMD", "exit:"), mock.patch.object(sg, "_process_exit", side_effect=lambda c: order.append(c)), \
             mock.patch.dict(sys.modules, {"main": bad_main}):
            sg._escalate()
        self.assertEqual(order, [3])

    def test_legacy_command_still_spawns(self):
        with mock.patch.object(sg, "_RESTART_CMD", "echo hi"), mock.patch.object(sg.subprocess, "Popen") as pop:
            pop.return_value.pid = 1
            sg._escalate()
        pop.assert_called_once()


class ServiceScript(unittest.TestCase):
    def test_nssm_stop_wait_and_restart_cmd(self):
        s = (_ROOT / "deploy/windows/install_service.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("AppStopMethodConsole 30000", s); self.assertIn("$restartCmd = 'exit:3'", s)
        self.assertNotIn("sc.exe stop ' + $ServiceName + ' & sc.exe start", s)


class StopAllParallel(unittest.TestCase):
    def _stuck(self, release: threading.Event) -> worker.Worker:
        w = worker.Worker(); w.STOP_JOIN_S = 0.2; w.state.update(running=True, name="stuck")
        w._thread = threading.Thread(target=lambda: release.wait(10), daemon=True); w._thread.start(); return w

    def _good(self) -> worker.Worker:
        w = worker.Worker(); w.STOP_JOIN_S = 1.0; w.state.update(running=True, name="good")
        w._thread = threading.Thread(target=lambda: w._stop.wait(5), daemon=True); w._thread.start(); return w

    def test_deadline_and_pending(self):
        release = threading.Event(); m = worker.WorkerManager()
        m._workers = {"a": self._good(), "b": self._stuck(release), "c": self._good()}
        t0 = time.time(); r = m.stop_all(deadline_s=1.0); dt = time.time() - t0
        self.assertFalse(r["ok"]); self.assertEqual(r["pending"], ["b"]); self.assertEqual(r["stopped"], 2); self.assertEqual(r["total"], 3)
        self.assertLess(dt, 1.5, f"병렬·데드라인이면 1.5 s 안에 돌아와야 한다({dt:.2f}s)")
        release.set()

    def test_all_good(self):
        m = worker.WorkerManager(); m._workers = {"a": self._good(), "b": self._good()}
        r = m.stop_all(deadline_s=2.0)
        self.assertTrue(r["ok"]); self.assertEqual(r["pending"], []); self.assertEqual(r["stopped"], 2)


class LinuxDeploy(unittest.TestCase):
    def test_systemd_execstart_target_exists(self):
        unit = (_ROOT / "deploy/systemd/vigent-edge.service").read_text(encoding="utf-8")
        m = re.search(r"^ExecStart=/bin/bash __INSTALL_DIR__/(\S+)", unit, re.M)
        self.assertIsNotNone(m); self.assertTrue((_ROOT / m.group(1)).exists(), m.group(1))

    def test_watchdog_grace_and_starting(self):
        w = (_ROOT / "deploy/watchdog.sh").read_text(encoding="utf-8")
        self.assertIn('"starting"', w); self.assertIn("GRACE_S", w); self.assertIn('${AUTH[@]+"${AUTH[@]}"}', w); self.assertNotIn('"${AUTH[@]}" "$URL"', w)


if __name__ == "__main__":
    unittest.main()
