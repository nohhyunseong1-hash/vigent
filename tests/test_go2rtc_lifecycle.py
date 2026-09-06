"""[CODE_REVIEW M5-3] go2rtc 수명 관리 — 우리가 띄운 프로세스만 핸들·PID 로 추적하고 종료 시 정리한다.

배경(C4 실측): ensure_go2rtc 가 Popen 핸들을 버려 서버 종료 후 go2rtc 가 고아로 남았고(2개 발견), 다음 기동은
포트(1984)가 잡혀 있으면 "이미 실행 중"으로 옛 프로세스를 재사용했다 — 런타임 yaml 은 매 기동 템플릿으로
덮어써도 옛 프로세스는 다시 읽지 않는다.
계약:
  ① 포트가 비어 있으면 띄우고 PID 파일(data/go2rtc.pid)·핸들을 남긴다
  ② 포트가 잡혀 있고 그 점유자가 **우리 PID 파일의 살아 있는 프로세스**면 → 종료 후 **재기동**(yaml 재로드 대신)
  ③ 포트가 잡혀 있는데 우리 것이 아니면(PID 파일 없음/불일치/죽음) → 손대지 않고 재사용 + 경고
  ④ stop_go2rtc(): 우리가 띄운 것(핸들 또는 PID 파일의 살아 있는 프로세스)만 terminate, 아니면 no-op
전부 모킹(실제 go2rtc·소켓·프로세스 미접촉).
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

from routers import cameras as C  # noqa: E402


class _FakeProc:
    def __init__(self, pid=4242):
        self.pid = pid
        self.terminated = False
        self._alive = True

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True
        self._alive = False

    def wait(self, timeout=None):
        return 0


class Go2rtcLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        (root / "bin").mkdir()
        (root / "bin" / "go2rtc.exe").write_bytes(b"")          # 존재만 확인한다(실행은 모킹)
        (root / "config").mkdir()
        (root / "config" / "go2rtc.yaml").write_text("streams: {}\n", encoding="utf-8")
        self.root = root
        self.procs: list[_FakeProc] = []
        self.killed: list[int] = []

        def _popen(*a, **k):
            p = _FakeProc(pid=5000 + len(self.procs))
            self.procs.append(p)
            return p
        ps = [mock.patch.object(C, "_G2_ROOT", root),
              mock.patch.object(C, "_G2_PROC", None),
              mock.patch.object(C, "_G2_LOGF", None),
              mock.patch("subprocess.Popen", side_effect=_popen),
              mock.patch.object(C, "_g2_port_busy", return_value=False),
              mock.patch.object(C, "_pid_alive", side_effect=lambda pid: pid in self.alive),
              mock.patch.object(C, "_terminate_pid", side_effect=lambda pid: self.killed.append(pid) or True),
              mock.patch.object(C, "_lan_ip", return_value="127.0.0.1")]
        self.alive: set[int] = set()
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        # ★patch 복원(위)보다 먼저 실행되도록 마지막에 등록(LIFO) — 패치된 전역의 로그 핸들·PID 파일을 닫고 지운 뒤 복원
        self.addCleanup(C.stop_go2rtc)

    def _pidfile(self):
        return self.root / "data" / "go2rtc.pid"

    def test_spawns_when_port_free_and_records_pid(self):
        self.assertTrue(C.ensure_go2rtc())
        self.assertEqual(len(self.procs), 1)
        self.assertEqual(self._pidfile().read_text(encoding="utf-8").strip(), str(self.procs[0].pid))
        self.assertIs(C._G2_PROC, self.procs[0])

    def test_port_busy_by_our_old_process_restarts_it(self):
        self._pidfile().parent.mkdir(parents=True, exist_ok=True)
        self._pidfile().write_text("777", encoding="utf-8")
        self.alive = {777}
        with mock.patch.object(C, "_g2_port_busy", return_value=True):
            self.assertTrue(C.ensure_go2rtc())
        self.assertEqual(self.killed, [777], "옛 go2rtc(우리 PID)를 종료해야 한다")
        self.assertEqual(len(self.procs), 1, "종료 후 새로 띄워야 yaml 이 다시 읽힌다")

    def test_port_busy_by_foreign_process_is_reused_untouched(self):
        with mock.patch.object(C, "_g2_port_busy", return_value=True), \
                self.assertLogs("vigent.cameras", level="WARNING"):
            self.assertTrue(C.ensure_go2rtc())
        self.assertEqual(self.killed, [])
        self.assertEqual(self.procs, [])

    def test_stop_terminates_only_ours(self):
        C.stop_go2rtc()                                            # 아무것도 없을 때 no-op
        self.assertEqual(self.killed, [])
        C.ensure_go2rtc()
        C.stop_go2rtc()
        self.assertTrue(self.procs[0].terminated)
        self.assertFalse(self._pidfile().exists(), "종료 후 PID 파일은 지운다")

    def test_stop_uses_pidfile_when_handle_is_gone(self):
        """서버가 재기동돼 핸들은 없지만 PID 파일의 프로세스가 살아 있으면 그것을 종료한다."""
        self._pidfile().parent.mkdir(parents=True, exist_ok=True)
        self._pidfile().write_text("888", encoding="utf-8")
        self.alive = {888}
        C.stop_go2rtc()
        self.assertEqual(self.killed, [888])


if __name__ == "__main__":
    unittest.main()
