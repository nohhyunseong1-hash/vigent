"""[CODE_REVIEW M7-8·M6-9] 보존 스윕 초기 지연 — 마지막 실행이 주기보다 오래됐으면 기동 후 곧바로(60s) 돈다.

배경: 첫 실행이 기동 10분 뒤·24h 주기 고정이라, 프로세스가 10분을 못 넘기는 재기동 반복(M4-5 크래시 루프 같은 계열)에서는
스윕이 영영 안 돈다(status.json last_run 08-26 실측). status.json 의 last_run 을 보고 **밀린 상태면** 초기 지연을
sweep_overdue_delay_s(기본 60)로 줄인다. 처음 설치(기록 없음)나 최근에 돌았으면 기존 10분 그대로.
"""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import retention  # noqa: E402
import retention_scheduler as rs  # noqa: E402
import tuning  # noqa: E402


def _status(age_h: float) -> dict:
    return {"last_run": (datetime.now(retention.KST) - timedelta(hours=age_h)).isoformat(timespec="seconds")}


class OverdueInitialDelay(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(tuning, "_CACHE", {"retention": {"sweep_interval_s": 86400, "sweep_initial_delay_s": 600,
                                                                "sweep_overdue_delay_s": 60}})
        p.start()
        self.addCleanup(p.stop)

    def test_no_record_keeps_default_delay(self):
        with mock.patch.object(retention, "read_status", return_value=None):
            self.assertEqual(rs.initial_delay_s(), 600.0)

    def test_recent_run_keeps_default_delay(self):
        with mock.patch.object(retention, "read_status", return_value=_status(5)):
            self.assertEqual(rs.initial_delay_s(), 600.0)

    def test_overdue_run_shortens_delay(self):
        with mock.patch.object(retention, "read_status", return_value=_status(24 + 2)):   # 주기+1h 초과
            self.assertEqual(rs.initial_delay_s(), 60.0)
        with mock.patch.object(retention, "read_status", return_value=_status(24 * 11)):  # 실측 사례(11일)
            self.assertEqual(rs.initial_delay_s(), 60.0)

    def test_broken_timestamp_is_not_fatal(self):
        with mock.patch.object(retention, "read_status", return_value={"last_run": "not-a-date"}):
            self.assertEqual(rs.initial_delay_s(), 600.0)

    def test_status_exposes_overdue_flag(self):
        with mock.patch.object(retention, "read_status", return_value=_status(24 * 3)):
            self.assertTrue(rs.status()["overdue"])
        with mock.patch.object(retention, "read_status", return_value=_status(1)):
            self.assertFalse(rs.status()["overdue"])


if __name__ == "__main__":
    unittest.main()
