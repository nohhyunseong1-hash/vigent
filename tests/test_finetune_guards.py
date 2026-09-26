"""재학습 스크립트의 v1 사고 재발 방지 장치(scripts/train/finetune_rfdetr.py). [2026-09-26]

★무엇을 고정하는가 — provenance §9-2·§9-5 의 v1 사고 항목 하나씩
  1. NaN 감시: 배치 손실·epoch 지표에 NaN/inf 가 있으면 NanAbort + NAN_ABORT.json (49 epoch 완주 사고 방지). 정상이면 아무 일 없음.
  2. build_trainer 래핑: Trainer 에 우리 콜백이 덧붙는다(rfdetr 1.8 은 외부 콜백 인자를 받지 않는다).
  3. notes: resolution·seed·lr·git·버전·수량 등 필수 키 전부 + JSON 직렬화.
  4. 체크포인트 검증: notes 누락·resolution 불일치·NaN 텐서를 잡고, 정상 파일은 통과.
  5. seed 고정 함수가 random/numpy/torch 를 실제로 고정. CUDA 강제.
  6. train 상한 추림이 결정적이다.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "train"))

import finetune_rfdetr as F  # noqa: E402

try:
    import torch
except Exception:  # noqa: BLE001
    torch = None


class NanGuardTest(unittest.TestCase):
    def test_first_nonfinite_detects_float_and_tensor(self):
        self.assertIsNone(F.first_nonfinite({"loss": 1.5, "loss_ce": 0.2, "n": 3}))
        self.assertEqual(F.first_nonfinite({"loss": 1.0, "loss_ce": float("nan")}), "loss_ce")
        self.assertEqual(F.first_nonfinite({"loss": float("inf")}), "loss")
        if torch is not None:
            self.assertEqual(F.first_nonfinite({"a": torch.tensor(1.0), "b": torch.tensor([1.0, float("nan")])}), "b")
            self.assertIsNone(F.first_nonfinite({"a": torch.tensor([0.0, 2.0])}))

    def test_core_aborts_and_writes_marker(self):
        with tempfile.TemporaryDirectory() as td:
            core = F.NanGuardCore(td)
            core.check_batch({"loss": 0.7}, epoch=0, batch_idx=3)              # 정상 → 통과
            core.check_batch(0.3, epoch=0, batch_idx=4)                        # 텐서/스칼라 형태도 통과
            with self.assertRaises(F.NanAbort):
                core.check_batch({"loss": float("nan")}, epoch=1, batch_idx=0)  # v1 사고: epoch 1 NaN
            info = json.loads((Path(td) / "NAN_ABORT.json").read_text(encoding="utf-8"))
            self.assertEqual(info["metric"], "loss"); self.assertIn("epoch 1", info["where"])
            with self.assertRaises(F.NanAbort):
                core.check_metrics({"val/loss": float("inf")}, epoch=2)

    def test_wrap_build_trainer_appends_guard(self):
        class FakeTrainer:
            def __init__(self):
                self.callbacks = ["ckpt"]
        calls = []
        def orig(cfg, mcfg, **kw):
            calls.append((cfg, mcfg, kw)); return FakeTrainer()
        wrapped = F.wrap_build_trainer(orig, "NANGUARD")
        t = wrapped("tc", "mc", accelerator="gpu")
        self.assertEqual(t.callbacks, ["ckpt", "NANGUARD"])
        self.assertEqual(calls[0][2], {"accelerator": "gpu"})
        self.assertIs(wrapped.__wrapped__, orig)


class ProvenanceTest(unittest.TestCase):
    def _args(self, **kw):
        base = dict(res=384, seed=7, epochs=2, batch=4, grad_accum=2, lr=1e-4, init="coco", config="configs/x.yaml", max_train=0)
        base.update(kw)
        return argparse.Namespace(**base)

    def test_notes_have_all_required_keys_and_serialize(self):
        notes = F.build_notes(self._args(), {"classes": ["person", "forklift"], "harness": "forklift", "max_train": 5000}, {"train": {"images": 10}})
        for k in F.NOTES_REQUIRED:
            self.assertIn(k, notes, k)
        self.assertEqual(notes["resolution"], 384); self.assertEqual(notes["seed"], 7); self.assertEqual(notes["max_train"], 5000)
        json.dumps(notes)

    @unittest.skipIf(torch is None, "torch 없음")
    def test_verify_checkpoint_catches_missing_meta_and_nan(self):
        with tempfile.TemporaryDirectory() as td:
            good_notes = F.build_notes(self._args(), {"classes": ["forklift"]}, {})
            ok = Path(td) / "ok.pth"
            torch.save({"model": {"w": torch.ones(3)}, "args": {"seed": 7, "notes": good_notes}}, ok)
            self.assertEqual(F.verify_checkpoint(ok, 384, 7), [])
            bad = Path(td) / "bad.pth"
            torch.save({"model": {"w": torch.tensor([1.0, float("nan")])}, "args": {"seed": 7}}, bad)   # v1: notes 없음 + NaN
            problems = F.verify_checkpoint(bad, 384, 7)
            self.assertTrue(any("notes" in p for p in problems)); self.assertTrue(any("NaN" in p for p in problems))
            mism = Path(td) / "mism.pth"
            torch.save({"state_dict": {"w": torch.ones(2)}, "args": {"notes": {**good_notes, "resolution": 560}}}, mism)
            self.assertTrue(any("resolution" in p for p in F.verify_checkpoint(mism, 384, 7)))

    def test_seed_and_cuda_guard(self):
        import random
        F.set_all_seeds(123); a = random.random()
        F.set_all_seeds(123); b = random.random()
        self.assertEqual(a, b)
        if torch is not None:
            F.set_all_seeds(5); x = torch.rand(2).tolist()
            F.set_all_seeds(5); y = torch.rand(2).tolist()
            self.assertEqual(x, y)
        with self.assertRaises(SystemExit):
            F.require_cuda(False)
        F.require_cuda(False, allow_cpu=True); F.require_cuda(True)

    def test_subsample_is_deterministic_and_bounded(self):
        items = [(Path(f"i{i}.jpg"), []) for i in range(50)]
        s1 = F.subsample(items, 10, seed=1); s2 = F.subsample(items, 10, seed=1); s3 = F.subsample(items, 10, seed=2)
        self.assertEqual(len(s1), 10); self.assertEqual(s1, s2); self.assertNotEqual(s1, s3)
        self.assertEqual(F.subsample(items, None, 1), items); self.assertEqual(F.subsample(items, 100, 1), items)


if __name__ == "__main__":
    unittest.main()
