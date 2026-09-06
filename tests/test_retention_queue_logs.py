"""[CODE_REVIEW M6-4·M6-5] 보존 스윕 확장 — 경보 큐 행 30일 정리(최신 config_error 1건 유지) + NSSM 회전 로그 최근 50개 유지.

M6-4: data/alert_queue.db 의 sent/dead 행은 영구 누적됐다(삭제 경로 없음). retention.alert_queue_days(기본 30) 지난
      sent/dead 행을 지운다 — 단 last_error 가 config_error 인 **최신 1건은 유지**(설정 오류 진단 근거).
M6-5: NSSM 회전본(logs/vigent.err-*, vigent.out-*)은 개수 상한이 없었다(크래시 루프에 8,139개). 최근 N(기본 50)개만 유지.
공통: dry_run 이면 후보만 세고 지우지 않는다. 개인정보 아님(큐 메시지·서비스 로그).
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_queue as q  # noqa: E402
import retention  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


def _cfg(**over):
    base = {"enabled": True, "dry_run": False, "groups": {}, "alert_queue_days": 30, "logs_keep_rotated": 50}
    base.update(over)
    return base


class QueueRowPruning(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())

    def _row(self, status, age_days, last_error=""):
        rid = q.enqueue("high", f"m{age_days}")
        db = q._db()
        with q._lock:
            db.execute("UPDATE alerts SET status=?, created_at=?, last_error=? WHERE id=?",
                       (status, time.time() - age_days * 86400, last_error, rid))
            db.commit()
        return rid

    def test_old_sent_and_dead_pruned_but_latest_config_error_kept(self):
        old_sent = self._row("sent", 40)
        old_dead = self._row("dead", 45, "boom")
        old_cfg = self._row("dead", 50, "config_error: 401")
        newer_cfg = self._row("dead", 35, "config_error: 403")      # config_error 중 최신 → 유지
        fresh = self._row("sent", 3)
        pending = self._row("pending", 60)                              # pending 은 절대 안 지운다
        r = q.prune(days=30)
        remaining = {row[0] for row in q._db().execute("SELECT id FROM alerts")}
        self.assertEqual(r["deleted"], 3)
        self.assertNotIn(old_sent, remaining)
        self.assertNotIn(old_dead, remaining)
        self.assertNotIn(old_cfg, remaining)
        self.assertIn(newer_cfg, remaining, "최신 config_error 1건은 유지해야 한다")
        self.assertIn(fresh, remaining)
        self.assertIn(pending, remaining)

    def test_dry_run_counts_only(self):
        self._row("sent", 40)
        r = q.prune(days=30, execute=False)
        self.assertEqual(r["candidates"], 1)
        self.assertEqual(r["deleted"], 0)
        self.assertEqual(q.counts()["sent"], 1)


class RotatedLogPruning(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.logs = Path(self.tmp.name) / "logs"
        self.logs.mkdir()
        now = time.time()
        for i in range(60):                                # 60개 회전본(오래된 순 i=0 이 가장 오래됨)
            p = self.logs / f"vigent.err-2026090{i // 10}T{i % 10:02d}0000.000.log"
            p.write_text("x", encoding="utf-8")
            os.utime(p, (now - (60 - i) * 60, now - (60 - i) * 60))
        (self.logs / "vigent.err.log").write_text("live", encoding="utf-8")   # 현재 로그는 대상 아님
        (self.logs / "vigent.log").write_text("app", encoding="utf-8")        # 앱 로그도 대상 아님
        self._p = mock.patch.object(retention, "LOG_DIR", self.logs)
        self._p.start()
        self.addCleanup(self._p.stop)

    def test_keeps_newest_n_deletes_rest(self):
        r = retention.prune_rotated_logs(keep=50, execute=True)
        self.assertEqual(r["deleted"], 10)
        left = sorted(p.name for p in self.logs.glob("vigent.err-*"))
        self.assertEqual(len(left), 50)
        self.assertTrue((self.logs / "vigent.err.log").exists())
        self.assertTrue((self.logs / "vigent.log").exists())
        self.assertNotIn("vigent.err-20260900T000000.000.log", left, "가장 오래된 것부터 지워야 한다")

    def test_dry_run_deletes_nothing(self):
        r = retention.prune_rotated_logs(keep=50, execute=False)
        self.assertEqual(r["candidates"], 10)
        self.assertEqual(r["deleted"], 0)
        self.assertEqual(len(list(self.logs.glob("vigent.err-*"))), 60)

    def test_sweep_reports_queue_and_logs(self):
        with mock.patch.object(retention, "_retention_config", return_value=_cfg(dry_run=True)), \
                mock.patch.object(retention, "STATUS_PATH", Path(self.tmp.name) / "st.json"), \
                mock.patch.object(retention, "DELETION_LOG_DIR", Path(self.tmp.name) / "del"):
            st = retention.sweep()
        self.assertIn("logs", st)
        self.assertIn("alert_queue", st)
        self.assertEqual(st["logs"]["candidates"], 10)


if __name__ == "__main__":
    unittest.main()
