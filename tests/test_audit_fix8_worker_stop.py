"""CODE_AUDIT_20260928 #8 — 워커 stop 은 join 결과를 확인하고, 살아 있으면 재기동하지 않는다. [2026-09-28]

★무엇을 고정하는가
  ① 메인 루프가 정지 신호를 무시하고 살아 있으면 stop() 은 ok=False·running 유지·stop_pending=True 를 돌려준다.
  ② 그 상태에서 manager.start(같은 cam) 는 거부된다(이중 Worker·이중 RTSP 세션 금지). 스레드가 끝나면 다시 stop() 이 ok=True.
  ③ 정상 워커(정지 신호를 따르는 루프)는 ok=True.
  ④ 구역 저장(cameras)·기아 2단계(starvation)는 stop 이 ok=False 면 재시작하지 않는다.
"""
from __future__ import annotations

import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import starvation_guard  # noqa: E402
import worker  # noqa: E402


def _worker_with_thread(target) -> worker.Worker:
    w = worker.Worker()
    w.STOP_JOIN_S = 0.2
    w.state.update(running=True, name="t-cam")
    w._thread = threading.Thread(target=target, daemon=True); w._thread.start()
    return w


class StopChecksJoin(unittest.TestCase):
    def test_stuck_thread_makes_stop_fail_and_blocks_restart(self):
        release = threading.Event()
        w = _worker_with_thread(lambda: release.wait(10))          # 정지 신호를 무시하는 루프
        r = w.stop()
        self.assertFalse(r["ok"]); self.assertTrue(w.state["running"]); self.assertTrue(w.state["stop_pending"]); self.assertIn("stop 미완료", r["error"])
        m = worker.WorkerManager(); m._workers["cam-x"] = w
        s = m.start(guard=None, infer_lock=None, cam_id="cam-x", source="rtsp://x")
        self.assertFalse(s["ok"]); self.assertIn("정지 미완료", s["error"])
        release.set(); w._thread.join(2.0)
        r2 = w.stop()
        self.assertTrue(r2["ok"]); self.assertFalse(w.state["running"]); self.assertFalse(w.state["stop_pending"])

    def test_cooperative_thread_stops_ok(self):
        w = worker.Worker(); w.STOP_JOIN_S = 1.0; w.state.update(running=True, name="t")
        w._thread = threading.Thread(target=lambda: w._stop.wait(5), daemon=True); w._thread.start()
        r = w.stop()
        self.assertTrue(r["ok"]); self.assertFalse(w.state["running"]); self.assertFalse(w.is_alive())

    def test_stop_releases_capture_to_unblock(self):
        cap = mock.Mock()
        w = worker.Worker(); w.STOP_JOIN_S = 0.5; w._cap = cap; w.state.update(running=True)
        w._thread = threading.Thread(target=lambda: w._stop.wait(5), daemon=True); w._thread.start()
        self.assertTrue(w.stop()["ok"]); cap.release.assert_called_once()


class CallersRespectStopResult(unittest.TestCase):
    def test_starvation_restart_skips_when_stop_fails(self):
        with mock.patch.object(starvation_guard, "_w") if hasattr(starvation_guard, "_w") else mock.patch.dict(sys.modules, {}):
            pass
        src = (Path(__file__).resolve().parent.parent / "vigent-core" / "starvation_guard.py").read_text(encoding="utf-8")
        self.assertIn('r = _w.manager.stop(cid)', src); self.assertIn('정지 미완료 — 재시작 보류', src)
        cams = (Path(__file__).resolve().parent.parent / "vigent-core" / "routers" / "cameras.py").read_text(encoding="utf-8")
        self.assertIn('r = _w.manager.stop(cid)', cams); self.assertIn('restart_error', cams)

    def test_manager_stop_propagates_result(self):
        release = threading.Event()
        w = _worker_with_thread(lambda: release.wait(10))
        m = worker.WorkerManager(); m._workers["c"] = w
        self.assertFalse(m.stop("c")["ok"])
        release.set(); w._thread.join(2.0)
        self.assertTrue(m.stop("c")["ok"])


if __name__ == "__main__":
    unittest.main()
