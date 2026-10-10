"""tests/test_load_html_containment.py — 평가서 HTML 열람 경로 격리 회귀 (1단계 보안 L-2, 2026-10-10).

배경(점검 실측): `GET /safety/risk-assessment/{aid}` → scribe.load_html 의 경로 검증이
금지목록(`'/' in aid or '..' in aid`)이라 Windows 역슬래시(`..\\`)·드라이브 절대경로
(`C:\\Users\\...`)를 못 막았다 — pathlib 은 드라이브 절대경로를 만나면 앞 경로를 통째로
버리므로 저장 폴더(data/risk_assessments) 밖 임의 `.html` 읽기가 가능했다(Windows 배포
중심 프로젝트라 실질 위험). resolve + is_relative_to 격리 확인으로 교체한 수정을 잠근다.

검증은 OS 무관하게 성립하는 탈출 경로(../ 상대·절대경로)로 하고, 정상 aid 열람이
그대로 동작하는지 함께 확인한다.
"""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

from agents import scribe as _scribe  # noqa: E402


class TestLoadHtmlContainment(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix="vigent_test_ra_")
        root = Path(self._tmp.name)
        self._saved = _scribe._SAVE_DIR
        _scribe._SAVE_DIR = root / "data" / "risk_assessments"
        _scribe._SAVE_DIR.mkdir(parents=True)
        # 저장 폴더 안 정상 파일 + 폴더 밖(탈출 목표) 파일
        (_scribe._SAVE_DIR / "ra_20991231_000000.html").write_text("<p>정상 평가서</p>", encoding="utf-8")
        (root / "secret.html").write_text("비밀", encoding="utf-8")

    def tearDown(self):
        _scribe._SAVE_DIR = self._saved
        self._tmp.cleanup()

    def test_normal_aid_still_served(self):
        self.assertEqual(_scribe.ScribeAgent.load_html("ra_20991231_000000"), "<p>정상 평가서</p>")

    def test_relative_escape_blocked(self):
        self.assertIsNone(_scribe.ScribeAgent.load_html("../secret"))
        self.assertIsNone(_scribe.ScribeAgent.load_html("a/../../secret"))

    def test_absolute_path_blocked(self):
        outside = str(Path(self._tmp.name) / "secret")   # 절대경로 — pathlib 이 앞부분을 버리는 꼴
        self.assertIsNone(_scribe.ScribeAgent.load_html(outside))

    def test_nul_byte_blocked(self):
        self.assertIsNone(_scribe.ScribeAgent.load_html("ra_x\x00"))

    def test_missing_file_is_none(self):
        self.assertIsNone(_scribe.ScribeAgent.load_html("ra_없는것"))


if __name__ == "__main__":
    unittest.main()
