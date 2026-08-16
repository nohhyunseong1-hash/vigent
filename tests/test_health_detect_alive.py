"""[B2] 검출 생존 3단계 판정 테스트 — /health 가 stale_detect·degraded 를 잡는가.

배경: 기존 /health 는 워커를 보지 않아 P0(영상 생존·검출 사망)에서도 200 OK 였다.
여기서는 health_status 의 판정 로직을 워커 status() 형태의 입력으로 직접 검증한다
(실카메라·실서버 없이 재현 가능해야 회귀를 막을 수 있다).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "vigent-core"))

import health_status  # noqa: E402


def _st(running=True, frame_age=0.4, detect_age=0.9, uptime=500.0, **kw):
    """worker.Worker.status() 모양의 최소 입력. uptime 은 startup grace 판정 기준."""
    d = {
        "running": running,
        "uptime_s": uptime,
        "last_frame_secs_ago": frame_age,
        "last_detect_secs_ago": detect_age,
        "last_detect_ms": 120.0,
        "session_generation": 1,
        "dropped_frames": 0,
        "reconnects": 0,
        "hangs": 0,
    }
    d.update(kw)
    return d


class TestCameraStatus(unittest.TestCase):
    def test_ok(self):
        c = health_status.camera_status(_st())
        self.assertEqual(c["status"], health_status.OK)

    def test_stale_detect_is_p0_fingerprint(self):
        """★핵심: 프레임은 신선(0.5s)한데 검출만 늙음(412s) → stale_detect.

        이것이 P0(go2rtc 세션 선점으로 검출 워커만 기아)의 지문이다. 이 분기가 깨지면
        '영상은 나오는데 안전 검출이 죽은' 상태를 다시 놓치게 된다."""
        c = health_status.camera_status(_st(frame_age=0.5, detect_age=412.0))
        self.assertEqual(c["status"], health_status.STALE_DETECT)
        self.assertEqual(c["last_frame_age_s"], 0.5)
        self.assertEqual(c["last_detect_age_s"], 412.0)

    def test_stale_frame_when_input_dead(self):
        """프레임 자체가 끊기면 stale_frame — 원인이 카메라·네트워크 쪽임을 구분."""
        c = health_status.camera_status(_st(frame_age=300.0, detect_age=300.0))
        self.assertEqual(c["status"], health_status.STALE_FRAME)

    def test_starting_within_grace(self):
        """기동 직후(검출 이력 없음)는 유예 안에서 starting — 재시작 유발 금지."""
        c = health_status.camera_status(_st(frame_age=3.0, detect_age=None, uptime=10.0))
        self.assertEqual(c["status"], health_status.STARTING)

    def test_no_detect_after_grace_with_stale_frame_is_stale_frame(self):
        """유예를 넘겼고 프레임도 안 들어오면 stale_frame — 원인은 입력이지 추론이 아니다.

        실서버 확인 중 발견한 오분류(카메라 전원 off 가 stale_detect 로 보고됨)의 회귀 방지."""
        c = health_status.camera_status(_st(frame_age=999.0, detect_age=None, uptime=999.0))
        self.assertEqual(c["status"], health_status.STALE_FRAME)

    def test_frames_fresh_but_never_detected_is_stale_detect(self):
        """★프레임은 계속 신선한데 추론이 한 번도 안 끝난 상태.

        grace 기준을 frame_age 로 잡으면 frame_age 가 늘 작아 **영원히 starting** 에 머물러
        조용한 실패가 된다. uptime 기준이라야 유예 후 stale_detect 로 잡힌다."""
        c = health_status.camera_status(_st(frame_age=0.5, detect_age=None, uptime=600.0))
        self.assertEqual(c["status"], health_status.STALE_DETECT)

    def test_stopped(self):
        c = health_status.camera_status(_st(running=False))
        self.assertEqual(c["status"], health_status.STOPPED)


class TestOverall(unittest.TestCase):
    def test_healthy(self):
        cams = {"c1": health_status.camera_status(_st())}
        self.assertEqual(health_status.overall(cams, True), health_status.HEALTHY)

    def test_degraded_when_one_of_two_dead(self):
        cams = {"c1": health_status.camera_status(_st()),
                "c2": health_status.camera_status(_st(frame_age=0.5, detect_age=400.0))}
        self.assertEqual(health_status.overall(cams, True), health_status.DEGRADED)

    def test_unhealthy_when_all_dead(self):
        cams = {"c1": health_status.camera_status(_st(frame_age=0.5, detect_age=400.0))}
        self.assertEqual(health_status.overall(cams, True), health_status.UNHEALTHY)

    def test_unhealthy_when_model_missing(self):
        cams = {"c1": health_status.camera_status(_st())}
        self.assertEqual(health_status.overall(cams, False), health_status.UNHEALTHY)

    def test_stopped_cameras_do_not_make_it_unhealthy(self):
        """중지된 카메라는 장애가 아니다(운영자가 껐을 수 있음)."""
        cams = {"c1": health_status.camera_status(_st(running=False))}
        self.assertEqual(health_status.overall(cams, True), health_status.HEALTHY)

    def test_alert_backlog_degrades(self):
        """[B5 예약] 미전송 경보가 남아 있으면 degraded."""
        cams = {"c1": health_status.camera_status(_st())}
        self.assertEqual(health_status.overall(cams, True, alert_backlog=3),
                         health_status.DEGRADED)

    def test_no_cameras_is_healthy(self):
        self.assertEqual(health_status.overall({}, True), health_status.HEALTHY)


class TestBuild(unittest.TestCase):
    def test_build_from_worker_manager_shape(self):
        ws = {"site": "", "cameras": {"cam1": _st(), "cam2": _st(frame_age=0.5, detect_age=500.0)}}
        overall, cams = health_status.build(ws, model_loaded=True)
        self.assertEqual(overall, health_status.DEGRADED)
        self.assertEqual(cams["cam1"]["status"], health_status.OK)
        self.assertEqual(cams["cam2"]["status"], health_status.STALE_DETECT)

    def test_build_never_leaks_source(self):
        """자격증명이 든 source 는 /health 로 새어나가면 안 된다."""
        ws = {"cameras": {"cam1": _st(source="rtsp://user:pw@1.2.3.4/s")}}
        _, cams = health_status.build(ws, model_loaded=True)
        self.assertNotIn("source", cams["cam1"])


if __name__ == "__main__":
    unittest.main()
