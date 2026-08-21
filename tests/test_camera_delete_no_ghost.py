"""[2026-08-21] 카메라 삭제 후 /health 에 유령이 남지 않는지.

증상: `DELETE /cameras/{id}` 후 `/cameras`·`data/cameras.json` 은 비는데
`/health.cameras` 에는 `status: stopped` 로 남고 `last_detect_age_s` 가 무한히 증가했다
(관측 40,544초). WorkerManager.stop() 이 워커를 멈추기만 하고 `_workers` dict 에서
빼지 않았기 때문이다.

피해가 둘이었다:
  ① 현장에서 카메라를 지웠는데 목록에 보여 오독한다
  ② 측정 오염 — capacity_probe 가 그 stale age 를 '1대 기준 검출주기'로 잡아
     지연 판정이 무력화되고 "한계 1대"라는 거짓 결과가 나왔다

★`disable` 은 반대다 — 꺼져 있음을 운영자가 봐야 하므로 **항목이 남아야** 맞다.
그 구분이 지켜지는지도 함께 잠근다.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import worker  # noqa: E402


class _FakeWorker:
    def __init__(self):
        self.stopped = False
        self.state = {"running": True}

    def stop(self):
        self.stopped = True
        self.state["running"] = False
        return {"ok": True}

    def status(self):
        return {"status": "stopped" if self.stopped else "ok"}


class TestDeletedCameraLeavesNoGhost(unittest.TestCase):

    def setUp(self):
        self.mgr = worker.WorkerManager()
        self.w = _FakeWorker()
        self.mgr._workers["cam1"] = self.w

    def test_remove_stops_and_delists(self):
        r = self.mgr.remove("cam1")
        self.assertTrue(r.get("ok"))
        self.assertTrue(self.w.stopped, "워커가 정지되지 않았다")
        self.assertNotIn("cam1", self.mgr.status()["cameras"],
                         "삭제했는데 /health 목록에 유령이 남는다")

    def test_remove_unknown_is_reported(self):
        r = self.mgr.remove("없는카메라")
        self.assertFalse(r.get("ok"))

    def test_remove_is_idempotent(self):
        self.mgr.remove("cam1")
        r = self.mgr.remove("cam1")          # 두 번째는 없음 처리, 예외 없이
        self.assertFalse(r.get("ok"))
        self.assertEqual(self.mgr.status()["cameras"], {})

    def test_stop_keeps_entry_for_disable(self):
        """★disable 은 항목이 남아야 한다 — '꺼져 있음'을 운영자가 봐야 하기 때문."""
        r = self.mgr.stop("cam1")
        self.assertTrue(r.get("ok"))
        self.assertTrue(self.w.stopped)
        self.assertIn("cam1", self.mgr.status()["cameras"],
                      "disable 인데 항목이 사라지면 꺼진 카메라를 볼 수 없다")
        self.assertEqual(self.mgr.status()["cameras"]["cam1"]["status"], "stopped")

    def test_delete_route_uses_remove_not_stop(self):
        """라우트가 stop() 으로 되돌아가면 유령이 부활한다 — 소스로 잠근다."""
        src = (Path(__file__).resolve().parent.parent
               / "vigent-core" / "routers" / "cameras.py").read_text(encoding="utf-8")
        i = src.index("def cameras_delete")
        body_ = src[i:i + 400]
        self.assertIn("manager.remove(cid)", body_)
        self.assertNotIn("manager.stop(cid)", body_,
                         "삭제 경로가 stop() 을 쓰면 유령이 남는다")


if __name__ == "__main__":
    unittest.main()
