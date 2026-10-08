"""OPEN_ISSUES_20261008 승인분 수정을 고정한다.

  #3 ① 테스트 러너 안에서는 alert_queue 가 운영 data/alert_queue.db 를 가리키지 않는다(VIGENT_ALERT_DB 없을 때 임시 DB).
     ② 경보 경로(relay·alert_notify.submit·dispatcher.dispatch·_notify_off_failed)를 건드리는 테스트 파일은 전부 isolate_alerts 를 쓴다(정적 검사).
     ③ 운영 큐에 2026-09-28 11:12 relay_off_failed 시험 행이 pending 으로 남아 있지 않다(개발기에서만 의미, DB 없으면 skip).
  #4 copilot.enrich_vlm: 법령 게이트가 예외를 던지면 VLM 조문을 **통과시키지 않고** '안전관리자 확인 필요' 로 치환 + ERROR 로그(fail-closed).
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core")); sys.path.insert(0, str(_ROOT / "tests"))

from _isolate import isolate_alerts  # noqa: E402


class QueueNeverRealUnderTestRunner(unittest.TestCase):
    def test_resolve_db_path_is_not_ops_db(self):
        import alert_queue
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VIGENT_ALERT_DB", None); os.environ.pop("VIGENT_ALERT_DB_ALLOW_REAL", None)
            p = alert_queue._resolve_db_path()
        self.assertNotEqual(p.resolve(), (_ROOT / "data" / "alert_queue.db").resolve(), "테스트 러너가 운영 큐를 가리킨다")
        self.assertIn("vigent_test_alert_queue_", str(p))
        with mock.patch.dict(os.environ, {"VIGENT_ALERT_DB": str(_ROOT / "tests" / "x.db")}):
            self.assertEqual(alert_queue._resolve_db_path(), _ROOT / "tests" / "x.db")
        with mock.patch.dict(os.environ, {"VIGENT_ALERT_DB_ALLOW_REAL": "1"}, clear=False):
            os.environ.pop("VIGENT_ALERT_DB", None)
            self.assertEqual(alert_queue._resolve_db_path(), _ROOT / "data" / "alert_queue.db")
        self.assertNotEqual(alert_queue._DB_PATH.resolve(), (_ROOT / "data" / "alert_queue.db").resolve(), "모듈 로드 시점 경로가 운영 DB 다")

    def test_every_alert_path_test_file_isolates(self):
        pat = re.compile(r"relay\.(turn_on|turn_off|_notify_off_failed)|alert_notify\.submit|dispatcher\.dispatch\(|_notify_off_failed\(")
        bad = []
        for f in sorted((_ROOT / "tests").glob("test_*.py")):
            s = f.read_text(encoding="utf-8", errors="replace")
            if pat.search(s) and "isolate_alerts" not in s:
                bad.append(f.name)
        self.assertEqual(bad, [], "경보 경로를 건드리는데 isolate_alerts 가 없다 — 2026-09-28 운영 큐 오염 재발 경로")

    def test_ops_queue_has_no_pending_relay_test_rows(self):
        import sqlite3
        db = _ROOT / "data" / "alert_queue.db"
        if not db.exists():
            self.skipTest("운영 큐 없음(개발기 아님)")
        with sqlite3.connect(str(db)) as c:
            n = c.execute("select count(*) from alerts where status='pending' and message like '%릴레이 OFF 실패%'").fetchone()[0]
        self.assertEqual(n, 0, "2026-09-28 시험 통보가 다시 pending 으로 남았다 — 어떤 테스트가 격리 없이 돌았는지 찾는다")


class LegalGateFailClosed(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())

    def test_gate_exception_replaces_law_text(self):
        import legal_whitelist
        from agents import copilot as cp
        c = cp.CopilotAgent({})
        vlm = {"위험요인": "x", "근거": "y", "관련법령": "산업안전보건법 제999조(환각)"}
        with mock.patch.object(legal_whitelist, "gate_vlm_text", side_effect=RuntimeError("게이트 고장")), \
             mock.patch.object(cp, "_LOG", create=True) as log:
            out = c.enrich_vlm(dict(vlm))
        self.assertNotIn("제999조", str(out.get("관련법령")))
        self.assertIn("안전관리자 확인 필요", str(out.get("관련법령")))
        self.assertTrue(out.get("_law_gate_error"), "게이트 실패가 결과에 표시돼야 보고서가 '확인 필요' 를 안다")
        self.assertTrue(log.error.called or log.exception.called, "ERROR 로그 1줄")

    def test_gate_normal_path_unchanged(self):
        import legal_whitelist
        from agents import copilot as cp
        c = cp.CopilotAgent({})
        with mock.patch.object(legal_whitelist, "gate_vlm_text", return_value="통과된 조문"):
            out = c.enrich_vlm({"관련법령": "뭔가"})
        self.assertEqual(out["관련법령"], "통과된 조문"); self.assertNotIn("_law_gate_error", out)


if __name__ == "__main__":
    unittest.main()
