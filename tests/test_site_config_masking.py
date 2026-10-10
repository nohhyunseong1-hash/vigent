"""tests/test_site_config_masking.py — /site/config 카메라 자격증명 마스킹 회귀 (1단계 보안 M-3, 2026-10-10).

배경(점검 실측): `GET /site/config`(설정 화면용)가 site.yaml 의 cameras 를 **원문 그대로**
반환했다 — `rtsp://admin:비번@host/...` 의 계정·비밀번호가 응답에 실렸다. `/cameras` 쪽은
camera_registry.mask_source 로 이미 가리고 있었는데 이 경로만 빠져 있었다(XSS 와 결합 시
카메라 계정 탈취 경로). read_site 마스킹 + write_site 의 마스킹값 round-trip 보존
(설정 화면이 읽은 값을 통째로 재저장해도 원본이 깨지지 않게)을 회귀 잠금한다.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import main  # noqa: E402
import setup_console  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

RAW = "rtsp://admin:supersecret@192.168.0.10:554/stream1"
MASKED = "rtsp://***:***@192.168.0.10:554/stream1"


class TestSiteConfigMasking(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self._prev_token = os.environ.get("VIGENT_API_TOKEN")
        os.environ.pop("VIGENT_API_TOKEN", None)
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_site_")
        self._saved_site = setup_console._SITE
        setup_console._SITE = Path(self._tmp.name) / "site.yaml"

    def tearDown(self):
        setup_console._SITE = self._saved_site
        self._tmp.cleanup()
        if self._prev_token is not None:
            os.environ["VIGENT_API_TOKEN"] = self._prev_token

    def _seed(self):
        r = self.client.post("/site/config", json={
            "site": "테스트현장",
            "cameras": [{"id": "cam1", "name": "입구", "source": RAW, "fps": 2}]})
        self.assertEqual(r.status_code, 200)

    def test_get_masks_credentials(self):
        self._seed()
        body = self.client.get("/site/config").json()
        self.assertEqual(body["cameras"][0]["source"], MASKED)
        self.assertNotIn("supersecret", str(body))

    def test_roundtrip_of_masked_source_preserves_original(self):
        """설정 화면 흐름 재현: GET(마스킹본) → 이름만 고쳐 POST → 저장된 원본 주소는 불변."""
        self._seed()
        got = self.client.get("/site/config").json()
        got["cameras"][0]["name"] = "입구-수정"
        r = self.client.post("/site/config", json=got)
        self.assertEqual(r.status_code, 200)
        saved = setup_console._SITE.read_text(encoding="utf-8")
        self.assertIn("supersecret", saved)          # 원본 보존
        self.assertNotIn("***", saved)               # 마스킹 문자열이 저장되면 안 된다
        self.assertIn("입구-수정", saved)             # 이름 변경은 반영

    def test_new_raw_source_still_saves(self):
        """주소를 실제로 바꾸는 정상 흐름은 그대로 동작."""
        self._seed()
        r = self.client.post("/site/config", json={
            "site": "s", "cameras": [{"id": "cam1", "source": "rtsp://u2:p2@10.0.0.9/s2"}]})
        self.assertEqual(r.status_code, 200)
        self.assertIn("u2:p2@10.0.0.9", setup_console._SITE.read_text(encoding="utf-8"))

    def test_masked_source_for_unknown_id_rejected(self):
        """보존할 원본이 없는 새 카메라에 마스킹 값이 오면 400 — 조용한 파손 방지."""
        self._seed()
        r = self.client.post("/site/config", json={
            "site": "s", "cameras": [{"id": "new-cam", "source": MASKED}]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("마스킹", r.json().get("detail", ""))

    def test_credential_free_source_passes_through(self):
        """자격증명 없는 source(웹캠 번호 '0'·파일 경로)는 마스킹 대상 아님 — 원문 그대로."""
        r = self.client.post("/site/config", json={
            "site": "s", "cameras": [{"id": "cam0", "source": "0"}]})
        self.assertEqual(r.status_code, 200)
        body = self.client.get("/site/config").json()
        self.assertEqual(body["cameras"][0]["source"], "0")


if __name__ == "__main__":
    unittest.main()
