"""[5단계 마무리, 2026-09-06] 설치 단계 장치 3개의 정합을 고정한다.

① constraints.txt — requirements.txt 첫 줄 `-c constraints.txt` 로 항상 동반. opencv 4개 배포판(GUI·headless·contrib 각각)을
   requirements 의 headless 핀과 **같은 버전**으로 고정한다(실측: supervision·trackers·rtmlib 가 GUI opencv 를 하드 의존으로
   끌어와 새 venv 에서 cv2 5.0.0 이 headless 4.13 을 가렸다. constraints 는 제외는 못 해도 버전은 고정한다).
② scripts/setup_env.py — GUI 빌드 제거 후 재설치하는 headless 핀이 requirements 와 같아야 한다.
실측(2026-09-06 임시 venv): constraints 동반 requirements 설치 → cv2 4.13.0(GUI WIN32UI 동거, opencv 3종) →
setup_env.py --no-install → opencv-contrib-python-headless 하나 · GUI NONE. go2rtc 매니페스트는 test_go2rtc_manifest.py.
"""
import importlib.util
import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _pin(text: str, name: str) -> str | None:
    m = re.search(rf"^{re.escape(name)}==([0-9.]+)\s*$", text, flags=re.M)
    return m.group(1) if m else None


class InstallConstraints(unittest.TestCase):
    def setUp(self):
        self.req = (_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.con = (_ROOT / "constraints.txt").read_text(encoding="utf-8")
        self.headless = _pin(self.req, "opencv-contrib-python-headless")
        self.assertIsNotNone(self.headless, "requirements.txt 에 headless 핀이 있어야 한다")

    def test_requirements_pull_constraints_first(self):
        first = next(ln.strip() for ln in self.req.splitlines() if ln.strip() and not ln.startswith("#"))
        self.assertEqual(first, "-c constraints.txt", "첫 유효 줄이 constraints 동반이어야 pip 가 항상 적용한다")

    def test_constraints_pin_all_four_opencv_dists_to_headless_version(self):
        for name in ("opencv-python", "opencv-contrib-python", "opencv-python-headless", "opencv-contrib-python-headless"):
            self.assertEqual(_pin(self.con, name), self.headless, f"{name} 은 headless 핀 {self.headless} 과 같아야 한다")

    def test_setup_env_headless_pin_matches_requirements(self):
        spec = importlib.util.spec_from_file_location("setup_env", _ROOT / "scripts" / "setup_env.py")
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        self.assertEqual(mod.HEADLESS, f"opencv-contrib-python-headless=={self.headless}")
        self.assertNotIn("opencv-contrib-python-headless", mod.GUI_DISTS, "남기는 배포판을 지우면 안 된다")


if __name__ == "__main__":
    unittest.main()
