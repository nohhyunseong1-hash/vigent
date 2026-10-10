"""tests/test_a3_sender_missing_preserved.py — 전송기 미주입 시 경보 보존 회귀 (2단계 A-3, 2026-10-10).

배경(점검 실측): 선기록-후전송(B5)의 '선기록'은 dispatcher.dispatch **안에서** 일어난다.
main 기동이 꼬여 Dispatcher 가 None 이면 ① _wire_alert_notify 가 start() 를 건너뛰고
② 워커의 submit() 이 지연 start() 로 sender 없는 소비 스레드를 띄워, 모든 경보가
"기록은 유지됨"이라는 **사실과 반대인** WARNING 한 줄만 남기고 소멸했다.
→ sender 미주입 분기에서 직접 alert_queue 에 pending 보존하도록 수정. sender 가 나중에
주입되면 재시도 스레드가 이어받고, 끝내 없으면 /health pending 으로 드러난다.
"""
import sys
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))
sys.path.insert(0, str(ROOT / "tests"))      # 단독 실행(-m unittest tests.xxx)에서도 _isolate 가 잡히게

from _isolate import isolate_alerts  # noqa: E402


class TestSenderMissingPreserved(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())    # 임시 DB + 스레드/전송기 초기화(운영 불변)

    def test_alert_preserved_as_pending_when_sender_missing(self):
        import alert_notify
        import alert_queue
        self.assertIsNone(alert_notify._sender)            # 격리 직후 = 미주입 상태(사고 조건)
        r = alert_notify.submit("cam1", "fire_smoke", "high", "화재 감지 테스트")
        self.assertTrue(r["queued"])
        deadline = time.time() + 5.0                        # 소비 스레드가 처리할 때까지 대기
        while time.time() < deadline:
            if alert_queue.counts().get("pending", 0) >= 1:
                break
            time.sleep(0.05)
        c = alert_queue.counts()
        self.assertGreaterEqual(c.get("pending", 0), 1,
                                f"sender 미주입이어도 경보는 pending 으로 보존돼야 한다: {c}")

    def test_preserved_row_carries_message(self):
        import sqlite3

        import alert_notify
        import alert_queue
        alert_notify.submit("cam1", "zone_intrusion", "high", "침입-보존-확인")
        deadline = time.time() + 5.0
        row = None
        while time.time() < deadline and row is None:
            try:
                con = sqlite3.connect(str(alert_queue._DB_PATH))
                try:
                    row = con.execute("SELECT level, message, status FROM alerts LIMIT 1").fetchone()
                finally:
                    con.close()
            except sqlite3.OperationalError:   # 소비 스레드가 아직 테이블을 안 만들었음 — 계속 대기
                row = None
            if row is None:
                time.sleep(0.05)
        self.assertIsNotNone(row, "경보 행이 DB 에 남아야 한다")
        self.assertEqual(row[0], "high")
        self.assertIn("침입-보존-확인", row[1])
        self.assertEqual(row[2], "pending")


if __name__ == "__main__":
    unittest.main()
