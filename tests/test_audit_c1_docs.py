"""CODE_AUDIT_20260928 C-1·C-2 — 문서·죽은 설정 정정. [2026-09-28]

★무엇을 고정하는가
  C-1 ① ALGORITHM_TRUTH 에 "person 만 통과" 서술이 없다 ② CLAUDE.md 기술 스택 줄에 ultralytics 가 스택으로 적혀 있지 않다
      ③ main.py docstring 포트 8010 ④ vision.yaml(두 프로파일)에 cooldown_sec 키가 없다(코드에서 읽는 곳 0)
      ⑤ make_prelabels 폐기 표시 ⑥ usb_installer_design 에 실기 미검증 표
  C-2 CODE_AUDIT 문서에 A 그룹 완료 상태 표(커밋 11개 해시)가 있다.
"""
from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def _t(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


class C1(unittest.TestCase):
    def test_algorithm_truth_person_only_removed(self):
        s = _t("docs/review/ALGORITHM_TRUTH_20260926.md")
        self.assertNotRegex(s, r"COCO 80종 중 `person` 만 통과 \|"); self.assertIn("COCO 80종이 전부 최종 검출에 남는다", s)

    def test_claude_stack_no_ultralytics(self):
        line = next(ln for ln in _t("CLAUDE.md").splitlines() if ln.startswith("Python 3.11 · FastAPI"))
        self.assertNotIn("ultralytics(YOLO11/8, AGPL 주의", line); self.assertIn("RF-DETR", line)

    def test_main_docstring_port(self):
        head = _t("vigent-core/main.py").split('"""')[1]
        self.assertNotIn("--port 8000", head); self.assertIn("--port 8010", head)

    def test_vision_yaml_no_dead_cooldown(self):
        import yaml
        for rel in ("themes/safety/vision.yaml", "deploy/academy/vision.academy.yaml"):
            d = yaml.safe_load(_t(rel))
            self.assertNotIn("cooldown_sec", d.get("vlm") or {}, rel)
        src = [p for p in (_ROOT / "vigent-core").rglob("*.py") if "cooldown_sec" in p.read_text(encoding="utf-8", errors="replace")]
        self.assertEqual(src, [], "코드가 cooldown_sec 를 읽기 시작했다면 yaml 에 되살리고 이 테스트를 고친다")

    def test_make_prelabels_deprecated(self):
        s = _t("scripts/make_prelabels.py")
        self.assertIn("★[폐기", s); self.assertIn("field_prelabel.py", s); self.assertIn('print("★[폐기]', s)

    def test_usb_design_unverified_table(self):
        s = _t("docs/deploy/usb_installer_design.md")
        self.assertIn("## 8-2. ★실기 미검증 항목", s)
        for k in ("NSSM 자가 재기동", "AppStopMethodConsole 30000", "go2rtc DELETE 파라미터", "-ExtraEnv"):
            self.assertIn(k, s, k)


if __name__ == "__main__":
    unittest.main()
