"""CODE_AUDIT_20260928 B-2 — 평가 경로 결정성. [2026-09-28]

★무엇을 고정하는가
  ① enable_determinism() 이 cudnn.benchmark=False · cudnn.deterministic=True · use_deterministic_algorithms(True) · CUBLAS_WORKSPACE_CONFIG 를 켠다.
  ② make_predictor / forklift load_model 이 모델을 만들기 전에 그것을 부른다(소스 순서로 고정 — GPU 없는 CI 에서도 검사된다).
  ③ 재현 테스트의 클래스별 AP50 허용이 ±0.3 이다(±0.5 로 다시 넓히면 이 테스트가 잡는다).
"""
from __future__ import annotations

import os
import re
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

import eval_v1_heldout as H  # noqa: E402


class EnableDeterminism(unittest.TestCase):
    def test_flags_and_env(self):
        import torch
        st = H.enable_determinism()
        self.assertTrue(os.environ.get(H.CUBLAS_ENV), "CUBLAS_WORKSPACE_CONFIG 가 비어 있다")   # 이미 있던 값이면 setdefault 가 유지한다
        self.assertFalse(torch.backends.cudnn.benchmark); self.assertTrue(torch.backends.cudnn.deterministic)
        self.assertTrue(torch.are_deterministic_algorithms_enabled()); self.assertTrue(st["deterministic_algorithms"]); self.assertEqual(st["note"], "")
        self.assertFalse(st["cudnn_benchmark"]); self.assertTrue(st["cudnn_deterministic"])

    def test_called_before_model_construction(self):
        src = (_ROOT / "scripts/eval/eval_v1_heldout.py").read_text(encoding="utf-8")
        body = src.split("def make_predictor(")[1].split("\ndef ")[0]
        self.assertLess(body.index("enable_determinism()"), body.index("RFDETRNano(pretrain_weights="))
        fk = (_ROOT / "scripts/eval/forklift_compare_harness.py").read_text(encoding="utf-8")
        body = fk.split("def load_model(")[1].split("\ndef ")[0]
        self.assertLess(body.index("enable_determinism()"), body.index("RFDETRNano(pretrain_weights="))

    def test_reproduction_tolerance_is_0_3(self):
        src = (_ROOT / "tests/test_ppe_compare_harness.py").read_text(encoding="utf-8")
        m = re.search(r'assertAlmostEqual\(c\["ap50"\], b\["ap50"\], delta=([0-9.]+)', src)
        self.assertIsNotNone(m); self.assertEqual(float(m.group(1)), 0.3)


if __name__ == "__main__":
    unittest.main()
