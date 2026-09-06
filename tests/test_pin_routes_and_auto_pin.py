"""[CODE_REVIEW M6-3·M6-10] pin/unpin 라우트 + 발송된 critical/high 경보의 증거·인식 로그 자동 pin.

M6-3: POST /recognition/pin·/unpin — 증거(data/evidence)·인식 로그(data/recognition) 아래만, 경로 탈출 거부.
M6-10: alert_queue.mark_sent(critical/high) → 증거 JPEG + 그날 events_YYYYMMDD.jsonl 을 사유 "alert:<id>" 로 pin.
       medium/log 등급·미발송은 pin 하지 않는다. 보존 스윕에서 pin 된 인식 로그는 후보가 아니다.
"""
import datetime
import os
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import alert_queue as q  # noqa: E402
import data_engine  # noqa: E402
import main  # noqa: E402
import retention  # noqa: E402
from _isolate import isolate_alerts, isolate_data_dirs  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


class PinRoutes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._saved_token = main._API_TOKEN
        main._API_TOKEN = ""
        cls.addClassCleanup(isolate_alerts())
        cls.addClassCleanup(isolate_data_dirs())
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        main._API_TOKEN = cls._saved_token

    def test_pin_and_unpin_roundtrip(self):
        r = self.client.post("/recognition/pin", json={"path": "data\\evidence\\20260901\\ev_x.jpg"}).json()
        self.assertTrue(r["ok"])
        self.assertEqual(r["path"], "data/evidence/20260901/ev_x.jpg")
        self.assertEqual(data_engine.pinned_map()["data/evidence/20260901/ev_x.jpg"], "manual")
        r2 = self.client.post("/recognition/unpin", json={"path": "data/evidence/20260901/ev_x.jpg"}).json()
        self.assertTrue(r2["ok"])
        self.assertNotIn("data/evidence/20260901/ev_x.jpg", data_engine.pinned_map())

    def test_rejects_paths_outside_evidence_and_recognition(self):
        for bad in ("data/cameras.json", "../.env", "data/evidence/../../.env", "C:/x/y.jpg", ""):
            r = self.client.post("/recognition/pin", json={"path": bad})
            self.assertEqual(r.status_code, 400, f"거부돼야 한다: {bad!r}")


class AutoPinSentAlerts(unittest.TestCase):
    def setUp(self):
        self.addCleanup(isolate_alerts())
        self.addCleanup(isolate_data_dirs())

    def test_sent_critical_pins_evidence_and_day_log(self):
        ts = time.time()
        rid = q.enqueue("critical", "지게차 협착", {"evidence": "data\\evidence\\20260906\\ev_a.jpg", "ts": ts})
        q.mark_sent(rid)
        pins = data_engine.pinned_map()
        day = datetime.datetime.fromtimestamp(ts, data_engine.KST).strftime("%Y%m%d")
        self.assertEqual(pins.get("data/evidence/20260906/ev_a.jpg"), f"alert:{rid}")
        self.assertEqual(pins.get(f"data/recognition/events_{day}.jsonl"), f"alert:{rid}")

    def test_isolate_alerts_alone_keeps_live_pin_file_untouched(self):
        """[2026-09-06 실측 재발 방지] isolate_alerts() 만 쓴 테스트의 mark_sent 가 운영 pinned.json 을 건드리면 안 된다."""
        live = Path(__file__).resolve().parent.parent / "data" / "retention" / "pinned.json"
        before = live.read_bytes() if live.exists() else None
        restore = isolate_alerts()
        try:
            self.assertNotEqual(data_engine._PINNED, live)
            rid = q.enqueue("critical", "격리 확인", {"ts": time.time()})
            q.mark_sent(rid)
            self.assertTrue(data_engine.pinned_map(), "임시 pin 목록에는 기록돼야 한다")
        finally:
            restore()
        after = live.read_bytes() if live.exists() else None
        self.assertEqual(before, after, "운영 pinned.json 이 테스트로 바뀌었다")

    def test_medium_or_no_evidence_does_not_pin_evidence(self):
        rid = q.enqueue("medium", "기록 전용", {"evidence": "data/evidence/20260906/ev_b.jpg"})
        q.mark_sent(rid)
        self.assertNotIn("data/evidence/20260906/ev_b.jpg", data_engine.pinned_map())

    def test_pinned_day_log_survives_sweep(self):
        root = data_engine._ROOT
        rec = root / "data" / "recognition"
        rec.mkdir(parents=True, exist_ok=True)
        f = rec / "events_20260101.jsonl"
        f.write_text("{}\n", encoding="utf-8")
        old = time.time() - 100 * 86400
        os.utime(f, (old, old))
        rid = q.enqueue("high", "x", {"ts": datetime.datetime(2026, 1, 1, 12, 0, tzinfo=data_engine.KST).timestamp()})
        q.mark_sent(rid)
        from unittest import mock
        with mock.patch.object(retention, "_ROOT", root), \
                mock.patch.dict(retention.GROUP_DIRS, {"recognition": rec}):
            info = retention.scan_group("recognition", 30)
        self.assertEqual(info["candidates"], [], "발송 경보의 인식 로그가 삭제 후보에 올랐다")


if __name__ == "__main__":
    unittest.main()
