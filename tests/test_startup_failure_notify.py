"""[CODE_REVIEW M4-5(a)] 서버 기동 실패를 조용히 넘기지 않는다 — 통보(1시간 1회) + Windows 이벤트 로그 + 상태 파일.

배경(audit/c4_smoke §3): guard 가 가중치 부재로 FileNotFoundError 를 내면 uvicorn 이 "startup failed" 로 종료하고
NSSM 이 130초마다 재시작을 반복했다 — 3주·4,067회, 아무도 몰랐다. 계약:
  ① _startup 에서 _load_theme 이 실패하면 기록·통보를 시도한 뒤 **재raise** 한다(조용히 뜨지 않는다)
  ② data/startup_failure.json 에 누적 횟수·마지막 통보 시각을 남긴다
  ③ 통보는 첫 실패 즉시, 이후 1시간에 1회(크래시 루프에서 텔레그램 폭주 방지). 채널 없으면 통보 생략
  ④ Windows 이벤트 로그(Application, 소스 VIGENT)에 1줄 — 텔레그램 설정 자체가 원인일 때의 대비
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import main  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402


class StartupFailureNotify(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "startup_failure.json"
        self.sent: list[str] = []
        self.events: list[str] = []
        ps = [mock.patch.object(main, "_STARTUP_FAIL_STATE", self.state),
              mock.patch.object(main, "_send_startup_alert", side_effect=lambda msg: (self.sent.append(msg) or True)),
              mock.patch.object(main, "_write_windows_event", side_effect=lambda msg: (self.events.append(msg) or True))]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)

    def test_first_failure_notifies_and_records(self):
        main._notify_startup_failure(FileNotFoundError("[기동거부] rf-detr-nano.pth 없음"))
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(st["count"], 1)
        self.assertEqual(len(self.sent), 1)
        self.assertIn("기동 실패", self.sent[0])
        self.assertEqual(len(self.events), 1)

    def test_repeat_within_hour_records_but_does_not_renotify(self):
        for _ in range(5):                                   # 크래시 루프 5회
            main._notify_startup_failure(RuntimeError("boom"))
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(st["count"], 5)
        self.assertEqual(len(self.sent), 1, "1시간 안의 반복 실패는 통보를 반복하지 않는다")
        self.assertEqual(len(self.events), 5, "이벤트 로그는 매 실패마다 남긴다(로컬·무비용)")

    def test_after_an_hour_notifies_again(self):
        main._notify_startup_failure(RuntimeError("boom"))
        st = json.loads(self.state.read_text(encoding="utf-8"))
        st["last_notify_ts"] -= 3601
        self.state.write_text(json.dumps(st), encoding="utf-8")
        main._notify_startup_failure(RuntimeError("boom"))
        self.assertEqual(len(self.sent), 2)

    def test_stage_and_event_id_match_startup_layer(self):
        """[5단계 5-2 4차 실측] 런처가 남긴 stage=import·last_stderr 위에 _startup 실패가 얹히면 stage 가 import 로
        남아 "stage=import 인데 ID 1000" 으로 읽혔다. 계약: 이 경로는 stage="startup"·event_id=1000, 런처 전용 필드는 제거."""
        self.state.write_text(json.dumps({"count": 1, "last_notify_ts": 0.0, "stage": "import", "event_id": 1001,
                                          "last_stderr": "[VIGENT 보안 오류] ...", "event_log_ok": True}), encoding="utf-8")
        main._notify_startup_failure(FileNotFoundError("[기동거부] rf-detr-nano.pth 없음"))
        st = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual((st["count"], st["stage"], st["event_id"]), (2, "startup", 1000))
        self.assertNotIn("last_stderr", st, "런처 전용 필드가 남으면 원인을 잘못 읽는다")
        self.assertIn("FileNotFoundError", st["last_error"])

    def test_startup_reraises_after_notifying(self):
        with mock.patch.object(main, "_load_theme", side_effect=FileNotFoundError("weights")):
            with self.assertRaises(FileNotFoundError):
                main._startup()
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
