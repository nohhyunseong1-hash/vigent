"""[2026-08-26] 워커를 되살리거나 만드는 **모든 입구**가 등록부를 존중하는지.

배경 — 같은 유형이 세 번 나왔다:
  1) 2026-08-21 `WorkerManager.stop()` 이 워커를 목록에 남겨 삭제 후에도 /health 에 유령이
     보였다 → `remove()` 신설로 수정.
  2) 2026-08-26 그 수정을 **우회**하는 경로 발견: `DELETE /cameras/{id}` 가
     `remove → g2_unregister → reg.delete` 순서였는데, `_g2_unregister` 는 go2rtc 가 없으면
     **최대 3초를 기다린다**(timeout=3). 그 사이 등록부에는 카메라가 살아 있어
     기아 감시(starvation_guard)가 `_start(cid)` 로 **되살렸다**. 결과: 등록부에 없는데
     돌고 있는 워커가 죽은 주소로 15초마다 재접속하며 /health 를 영구 unhealthy 로 만들었다.
  3) 전수 확인에서 **세 번째**: `POST /worker/start` 는 등록부를 아예 거치지 않고
     `manager.start` 를 직접 불렀다. 그렇게 만든 워커는 `/cameras` 에 없어
     `DELETE /cameras/{id}` 가 404 → **지울 방법이 재시작뿐**이었다.

여기서 고정하는 계약:
  - 삭제는 **등록부를 가장 먼저** 지운다(경합 창을 없앤다).
  - 워커를 되살리는 경로는 등록부에 없으면 **되살리지 않고 거둔다**.
  - 워커를 만드는 경로는 등록부에 **반드시 흔적을 남긴다**(회수 가능해야 한다).
"""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))
sys.path.insert(0, str(ROOT / "tests"))

import worker  # noqa: E402
from _source_probe import code_of  # noqa: E402


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


class TestDeleteOrderClosesRace(unittest.TestCase):
    """삭제 라우트가 등록부를 **먼저** 지우는지 — 소스로 잠근다."""

    def setUp(self):
        # ★고정 길이 절단은 쓰지 않는다 — 주석이 길어지면 검사 대상이 밀려 오탐이 난다
        #   (2026-08-26 실제 발생). 함수 경계까지 뽑고 주석은 걷어낸다.
        self.body = code_of("vigent-core/routers/cameras.py", "cameras_delete")

    def test_registry_delete_comes_before_worker_remove(self):
        pos_reg = self.body.find("_reg.delete(cid)")
        pos_rm = self.body.find("manager.remove(cid)")
        self.assertNotEqual(pos_reg, -1, "_reg.delete 호출이 없다")
        self.assertNotEqual(pos_rm, -1, "manager.remove 호출이 없다")
        self.assertLess(pos_reg, pos_rm,
                        "★등록부 삭제가 워커 제거보다 **뒤에** 있다 — "
                        "_g2_unregister(3초 대기) 사이에 기아 감시가 워커를 되살릴 수 있다")

    def test_delete_still_removes_worker(self):
        self.assertIn("manager.remove(cid)", self.body,
                      "워커 제거가 사라졌다 — /health 에 유령이 남는다")


class TestStarvationDoesNotResurrect(unittest.TestCase):
    """기아 감시가 등록부에 없는 카메라를 되살리지 않는지."""

    def setUp(self):
        self.body = code_of("vigent-core/starvation_guard.py", "_restart_worker")

    def test_checks_registry_before_restart(self):
        self.assertIn("camera_registry", self.body, "등록부를 조회하지 않는다")
        self.assertTrue(re.search(r"_reg\.get\(cid\)\s+is\s+None", self.body),
                        "★등록부에 없는 카메라를 걸러내지 않는다 — 삭제된 카메라가 되살아난다")

    def test_reaps_ghost_instead_of_restarting(self):
        idx_guard = self.body.find("is None")
        idx_start = self.body.find("_cam_start(cid)")
        self.assertNotEqual(idx_guard, -1)
        self.assertNotEqual(idx_start, -1)
        self.assertLess(idx_guard, idx_start,
                        "등록부 검사가 _cam_start 보다 뒤에 있으면 의미가 없다")
        self.assertIn("manager.remove(cid)", self.body,
                      "유령 워커를 거두지 않는다")


class TestWorkerStartRegisters(unittest.TestCase):
    """POST /worker/start 로 만든 워커도 등록부에 남아 회수 가능한지."""

    def test_worker_start_upserts_registry(self):
        body = code_of("vigent-core/routers/safety_core.py", "worker_start")
        self.assertIn("_reg.upsert(", body,
                      "★등록부에 남기지 않는다 — 그렇게 만든 워커는 DELETE 가 404 라 "
                      "재시작 말고는 지울 방법이 없다")
        pos_up = body.find("_reg.upsert(")
        pos_start = body.find("manager.start(")
        self.assertLess(pos_up, pos_start, "등록이 start 보다 뒤면 경합이 남는다")


class TestManagerRemoveStillWorks(unittest.TestCase):
    """2026-08-21 수정이 살아 있는지(회귀 방지)."""

    def test_remove_delists_but_stop_keeps(self):
        mgr = worker.WorkerManager()
        w1, w2 = _FakeWorker(), _FakeWorker()
        mgr._workers["a"] = w1
        mgr._workers["b"] = w2
        mgr.remove("a")
        mgr.stop("b")
        cams = mgr.status()["cameras"]
        self.assertNotIn("a", cams, "remove 했는데 목록에 남는다")
        self.assertIn("b", cams, "stop(disable)인데 목록에서 사라진다")
        self.assertTrue(w1.stopped and w2.stopped)


if __name__ == "__main__":
    unittest.main()
