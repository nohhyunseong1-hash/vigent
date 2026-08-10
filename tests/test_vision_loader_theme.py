"""[S2-수정] vision_loader.theme_yaml_path 테마명 화이트리스트 회귀 테스트.

HTTP 레벨(TestClient/curl)에서는 ".." 이 클라이언트 측에서 정규화돼 실제 요청 전에
사라지는 경우가 많아(경험적으로 확인, curl --path-as-is 로만 재현 가능) 이 파일에서
함수 단위로 직접 검증한다 — path traversal 방어의 핵심은 이 함수다.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

import vision_loader  # noqa: E402


class TestThemeYamlPathWhitelist(unittest.TestCase):
    def test_valid_theme_resolves(self):
        p = vision_loader.theme_yaml_path("safety")
        self.assertEqual(p.as_posix().rsplit("/", 3)[-3:], ["themes", "safety", "vision.yaml"])

    def test_traversal_dots_rejected(self):
        for bad in ("..", ".", "../../etc"):
            with self.subTest(theme=bad):
                with self.assertRaises(FileNotFoundError):
                    vision_loader.theme_yaml_path(bad)

    def test_uppercase_and_special_chars_rejected(self):
        for bad in ("SAFETY", "safety;rm", "safety/etc", "safety\\etc", "", "safety "):
            with self.subTest(theme=bad):
                with self.assertRaises(FileNotFoundError):
                    vision_loader.theme_yaml_path(bad)

    def test_hyphen_and_underscore_allowed(self):
        # 실제 존재 여부와 무관하게(파일 없어도 OK), 화이트리스트 통과는 확인
        p = vision_loader.theme_yaml_path("smart-city_test")
        self.assertIn("smart-city_test", str(p))


if __name__ == "__main__":
    unittest.main()
