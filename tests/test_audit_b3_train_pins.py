"""CODE_AUDIT_20260928 B-3 — 학습 의존성 핀·numpy/cv2 가드. [2026-09-28]

★무엇을 고정하는가
  ① requirements-train.txt 는 학습 조합(pytorch-lightning·torchmetrics·albumentations·albucore·peft 등)을 `==` 로 핀하고, `rfdetr[train]` 활성 줄이 없다.
  ② 개발기(설치돼 있으면)의 설치 버전이 그 핀과 같다 — 다르면 "문서상 조합 ≠ 실제 조합" 이므로 실패. 미설치(CI)는 skip.
  ③ setup_env.check_pins 는 미설치·불일치를 사유로 돌려주고, requirement_pins 는 주석·-r/-c 줄을 무시한다. main 은 그 검사를 부른다.
"""
from __future__ import annotations

import importlib.metadata as md
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import setup_env as SE  # noqa: E402

TRAIN_PKGS = ("pytorch-lightning", "torchmetrics", "albumentations", "albucore", "peft", "accelerate", "transformers", "scipy", "py-spy",
              "faster-coco-eval", "pycocotools")


def _train_pins() -> dict[str, str]:
    return SE.requirement_pins(_ROOT / "requirements-train.txt")


class TrainRequirements(unittest.TestCase):
    def test_train_pins_present_and_no_extras_line(self):
        pins = _train_pins(); raw = (_ROOT / "requirements-train.txt").read_text(encoding="utf-8")
        for n in TRAIN_PKGS:
            self.assertIn(n, pins, f"{n} 핀 없음")
        active = [ln for ln in raw.splitlines() if ln.split("#", 1)[0].strip().startswith("rfdetr[")]
        self.assertEqual(active, [], "rfdetr[train] 은 활성 줄로 두지 않는다(numpy 강등·cv2 교체 실측)")

    def test_installed_matches_pins_when_installed(self):
        pins = _train_pins(); checked = 0
        for n in TRAIN_PKGS:
            try:
                have = md.version(n)
            except md.PackageNotFoundError:
                continue
            self.assertEqual(have, pins[n], f"{n}: 설치 {have} != 핀 {pins[n]} — 핀을 실제 조합으로 고치거나 설치를 맞춘다")
            checked += 1
        if checked == 0:
            self.skipTest("학습 의존성 미설치 기계(CI)")


class PinGuard(unittest.TestCase):
    def test_check_pins(self):
        pins = {"numpy": "2.4.6", "opencv-contrib-python-headless": "4.13.0.92"}
        self.assertEqual(SE.check_pins({"numpy": "2.4.6", "opencv-contrib-python-headless": "4.13.0.92"}, pins), [])
        bad = SE.check_pins({"numpy": "1.26.4"}, pins)
        self.assertEqual(len(bad), 2); self.assertIn("numpy: 설치 1.26.4 != 핀 2.4.6", bad); self.assertTrue(any("미설치" in b for b in bad))
        self.assertEqual(SE.check_pins({}, {}), [], "핀이 없는 이름은 검사하지 않는다")

    def test_requirement_pins_parse(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "r.txt"
            f.write_text("-c constraints.txt\n-r base.txt\n# numpy==9.9.9\nnumpy==2.4.6   # 주석\nOpenCV-Contrib-Python-Headless==4.13.0.92\ntorch>=2.0\n", encoding="utf-8")
            self.assertEqual(SE.requirement_pins(f), {"numpy": "2.4.6", "opencv-contrib-python-headless": "4.13.0.92"})

    def test_main_calls_pin_guard(self):
        src = (_ROOT / "scripts/setup_env.py").read_text(encoding="utf-8")
        body = src.split("def main(")[1]
        self.assertIn("check_pins(installed_versions(), requirement_pins())", body)
        self.assertEqual(SE.PROTECTED_PINS, ("numpy", "opencv-contrib-python-headless"))


if __name__ == "__main__":
    unittest.main()
