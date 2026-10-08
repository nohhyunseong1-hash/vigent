"""[D4] 모자이크 실패 시 정책 — 현행(원본 저장) 유지 + 세 가지 조건.

★결정(2026-08-24 사용자): 실패해도 **저장은 계속한다**. 증거를 버리면 사고를 증명할 수
없기 때문이다. 대신 조건 3가지를 단다:
  ① 실패율이 임계(기본 분당 5건)를 넘으면 **통보 채널로 경보**
  ② 원본이 저장된 사실을 **이벤트 기록에 표시**(사후 선별 삭제가 가능하게)
  ③ **법무 검토 대상 꼬리표** 유지

★②가 없으면 "원본이 섞여 있는데 어느 건인지 모르는" 상태가 되어 전량 폐기밖에 수가 없다.
★전례: YuNet 락 누락 때 실서비스에서 **분당 145~160건** 실패해 그때마다 원본이 나갔다.
"""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import data_engine  # noqa: E402
import privacy  # noqa: E402
from _isolate import isolate_alerts  # noqa: E402  [OPEN_ISSUES #3] 운영 큐 격리


class FailureAlerting(unittest.TestCase):
    """① 잦은 실패는 통보된다."""

    def setUp(self):
        self.addCleanup(isolate_alerts())
        privacy._fail_times.clear()
        privacy._fail_total = 0
        privacy._last_alert_at = 0.0
        privacy._tls.failed = False

    def test_below_threshold_does_not_alert(self):
        """★한두 건으로 통보하면 그것도 폭주다 — 임계 미만은 조용히 센다."""
        with mock.patch("alert_notify.submit") as sub:
            for _ in range(privacy._fail_threshold() - 1):
                privacy._note_failure()
        sub.assert_not_called()
        self.assertEqual(privacy.failure_status()["anonymize_failures_per_min"],
                         privacy._fail_threshold() - 1)

    def test_threshold_triggers_alert(self):
        with mock.patch("alert_notify.submit") as sub:
            for _ in range(privacy._fail_threshold()):
                privacy._note_failure()
        self.assertTrue(sub.called, "★임계를 넘었는데 통보가 안 나갔다")
        msg = sub.call_args.kwargs.get("message", "")
        self.assertIn("원본", msg, "통보 문구에 '원본이 저장됐다'는 사실이 없다")

    def test_alert_itself_is_throttled(self):
        """★통보가 폭주하면 안 된다 — 10분에 1회."""
        with mock.patch("alert_notify.submit") as sub:
            for _ in range(privacy._fail_threshold() * 10):
                privacy._note_failure()
        self.assertEqual(sub.call_count, 1, f"통보가 {sub.call_count}회 — 스로틀이 안 된다")

    def test_alert_failure_never_propagates(self):
        """★통보 실패가 검출·저장을 막으면 안 된다."""
        with mock.patch("alert_notify.submit", side_effect=RuntimeError("boom")):
            for _ in range(privacy._fail_threshold()):
                privacy._note_failure()      # 예외가 올라오면 테스트 실패

    def test_health_exposes_status_and_legal_tag(self):
        """③ 법무 검토 대상 꼬리표."""
        st = privacy.failure_status()
        self.assertFalse(st["legal_review_required"], "실패가 없는데 법무 꼬리표가 붙었다")
        privacy._note_failure()
        st = privacy.failure_status()
        self.assertTrue(st["legal_review_required"], "★원본이 나갔는데 법무 꼬리표가 없다")
        self.assertTrue(st["legal_review_note"].strip(), "꼬리표에 설명이 없다")


class RecordMarking(unittest.TestCase):
    """② 원본 저장 사실이 기록에 남는다 — 선별 삭제의 전제."""

    def setUp(self):
        self.addCleanup(isolate_alerts())
        from _isolate import isolate_data_dirs
        self.addCleanup(isolate_data_dirs())   # [4단계 ④] 운영 data/recognition/events_*.jsonl 에 쓰지 않는다

    def test_marked_only_when_failed(self):
        clean = data_engine.log_event(rule="t", level="low", note="정상")
        dirty = data_engine.log_event(rule="t", level="low", note="실패", privacy_failed=True)
        self.assertNotIn("privacy_failed", clean, "정상 건에 표시가 붙었다(선별이 무의미해진다)")
        self.assertTrue(dirty.get("privacy_failed"), "★원본 저장 건에 표시가 없다 — 선별 삭제 불가")

    def test_flag_is_consumed_once(self):
        """플래그는 1회성 — 다음 이벤트까지 딸려가면 정상 건이 오염된다."""
        privacy._tls.failed = False
        privacy._note_failure()
        self.assertTrue(privacy.took_failure(), "실패 직후인데 플래그가 없다")
        self.assertFalse(privacy.took_failure(), "★플래그가 소비되지 않아 다음 건까지 오염된다")

    def test_flag_is_thread_local(self):
        """★다른 스레드의 실패가 이 스레드 기록에 붙으면 안 된다.

        anonymize_faces 는 워커와 스냅샷이 **동시에** 부른다(그 동시성이 YuNet 락 사고의
        원인이었다). 전역 플래그였다면 스냅샷 실패가 워커 이벤트에 붙어 **엉뚱한 건이
        '원본 저장'으로 표시**된다 — 선별 삭제가 틀린 파일을 지우게 된다.
        """
        import threading
        privacy._tls.failed = False
        done = threading.Event()

        def other():
            with mock.patch("alert_notify.submit"):
                privacy._note_failure()      # 다른 스레드에서 실패
            done.set()

        threading.Thread(target=other, daemon=True).start()
        done.wait(3)
        self.assertFalse(privacy.took_failure(), "★다른 스레드의 실패가 내 플래그에 붙었다")

    def test_worker_passes_flag_through(self):
        """호출부 계약 — worker 가 실제로 privacy_failed 를 넘기는가."""
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "worker.py").read_text(encoding="utf-8")
        self.assertIn("privacy_failed=privacy_failed", src, "worker 가 표시를 기록으로 안 넘긴다")
        self.assertIn("evidence, privacy_failed = _frame_to_dataurl(", src)


if __name__ == "__main__":
    unittest.main()
