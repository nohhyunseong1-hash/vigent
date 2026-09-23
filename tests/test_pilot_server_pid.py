"""[I-2] 부하 도구의 서버 프로세스 식별 — 스텁을 재던 결함을 고정한다.

★무슨 일이 있었나 (2026-09-23 실측)
  `find_server_pid()` 가 CommandLine 이 `*uvicorn*main:app*` 인 python.exe 중 **-First 1**
  을 골랐다. `python -m uvicorn` 으로 띄우면 **두 개**가 걸린다:
      PID 25612  RSS   4.8 MB  CPU  0.00s   <- 런처 스텁
      PID 27976  RSS 2,682 MB  CPU 18.91s   <- 진짜 서버(포트를 점유한 쪽)
  스텁을 골라, 소크 리포트의 "서버 RSS"·"서버 환산코어" 가 창마다 **5.0MB·0.0156s 상수**로
  찍혔다. 즉 합격 기준 "RSS ≤ 6GB / 서버 ≤ 8.0 코어" 가 **아무것도 검증하지 못한 채**
  통과해 왔다. 같은 계열(조용히 틀린 값을 성실히 기록) 결함이 네 번째였다.

여기서 고정하는 것:
  1. 포트를 점유한 PID 를 기준으로 **트리 전체**를 합산한다(스텁 포함 — 빠뜨리지 않는다).
  2. 포트를 못 찾으면 폴백하되 **RSS 최대**를 고른다(-First 1 금지).
  3. 식별 실패·RSS 비정상(<100MB)이면 **조용히 기록하지 않고 중단**한다.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import pilot_load_test as P  # noqa: E402

# 실제로 관측된 모양: 스텁(부모) → 진짜 서버(자식)
STUB, REAL = 25612, 27976
PROCS = {
    STUB: {"ppid": 25104, "rss_mb": 4.8, "cpu_s": 0.0, "match": True},
    REAL: {"ppid": STUB, "rss_mb": 2682.6, "cpu_s": 18.91, "match": True},
}
SYS = {"sys_avail_mb": 36222.0, "sys_total_mb": 62852.0, "logical_cpus": 24}


def snap(owner):
    return {"owner": owner, "procs": dict(PROCS), "sys": dict(SYS)}


class ServerIdentification(unittest.TestCase):
    def test_port_owner_leads_to_whole_tree(self):
        with mock.patch.object(P, "_snapshot", return_value=snap(REAL)):
            st = P.proc_stats()
        self.assertEqual(st["root_pid"], STUB, "포트 점유 프로세스의 조상(트리 뿌리)이어야 한다")
        self.assertCountEqual(st["pids"], [STUB, REAL])
        self.assertAlmostEqual(st["rss_mb"], 2687.4, places=1)
        self.assertAlmostEqual(st["cpu_s"], 18.91, places=2)

    def test_fallback_picks_largest_not_first(self):
        """포트를 못 찾아도 **스텁을 고르면 안 된다.**"""
        with mock.patch.object(P, "_snapshot", return_value=snap(None)):
            st = P.proc_stats()
        self.assertIn(REAL, st["pids"])
        self.assertGreater(st["rss_mb"], P.MIN_SERVER_RSS_MB)

    def test_stub_alone_is_refused(self):
        """★스텁만 있으면 '측정 성공' 이 아니라 **중단**이어야 한다."""
        only_stub = {"owner": None, "procs": {STUB: dict(PROCS[STUB])}, "sys": dict(SYS)}
        with mock.patch.object(P, "_snapshot", return_value=only_stub):
            with self.assertRaises(SystemExit) as cm:
                P.assert_server_proc_sane()
        self.assertIn("비정상적으로 작다", str(cm.exception))

    def test_no_process_is_refused(self):
        with mock.patch.object(P, "_snapshot", return_value={"owner": None, "procs": {}, "sys": {}}):
            with self.assertRaises(SystemExit) as cm:
                P.assert_server_proc_sane()
        self.assertIn("식별하지 못했다", str(cm.exception))

    def test_sane_case_passes(self):
        with mock.patch.object(P, "_snapshot", return_value=snap(REAL)):
            st = P.assert_server_proc_sane()
        self.assertTrue(st["alive"])


class RawSampleCsv(unittest.TestCase):
    """[I-3] 원시 샘플 CSV — 0행이면 실패로 드러나야 한다."""

    def test_writes_rows_and_counts(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "raw.csv"
            P._RAW.update(f=None, w=None, n=0)
            P.raw_open(p)
            P.raw_write("pilot01", 0.4, 55.1, "ok")
            P.raw_write("pilot02", 0.5, 61.3, "ok")
            n = P.raw_close()
            self.assertEqual(n, 2)
            lines = p.read_text(encoding="utf-8-sig").strip().splitlines()
            self.assertEqual(len(lines), 3, "헤더 + 2행")
            self.assertIn("camera", lines[0])

    def test_write_without_open_is_noop(self):
        P._RAW.update(f=None, w=None, n=0)
        P.raw_write("x", 1, 2, "ok")        # 예외가 나면 안 된다
        self.assertEqual(P.raw_close(), 0)


if __name__ == "__main__":
    unittest.main()
