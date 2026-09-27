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
        # ★2026-09-26 게이트 1회 실패(재현 3회 불가)의 원인: 이 테스트가 전역 RNG 에서 값을 '뽑아' 비교했는데, 앞 테스트가 남긴
        #   백그라운드 스레드(워커·통보 루프)가 그 사이 전역 RNG 를 소비하면 두 값이 어긋난다([추정 — 스레드 간섭]). 그래서
        #   값을 뽑지 않고 시드 '상태' 만 비교한다(스레드 간섭과 무관).
        import random
        F.set_all_seeds(123); a = random.getstate()
        F.set_all_seeds(123); b = random.getstate()
        self.assertEqual(a, b)
        if torch is not None:
            F.set_all_seeds(5); self.assertEqual(torch.initial_seed(), 5)
            F.set_all_seeds(7); self.assertEqual(torch.initial_seed(), 7)
            g = torch.Generator().manual_seed(5); h = torch.Generator().manual_seed(5)
            self.assertEqual(torch.rand(2, generator=g).tolist(), torch.rand(2, generator=h).tolist())   # 전용 생성기는 스레드와 무관
        with self.assertRaises(SystemExit):
            F.require_cuda(False)
        F.require_cuda(False, allow_cpu=True); F.require_cuda(True)

    def test_stratified_subsample_keeps_ratio(self):
        # 장소 3 × 지게차 유무: 있음 90 / 없음 10 → 20장 뽑으면 비율(약 9:1)·장소 유지, 시드 고정
        items = []; keys = []
        for loc in ("A", "B", "C"):
            for i in range(30):
                items.append((Path(f"{loc}{i}.jpg"), [])); keys.append((loc, i % 10 != 0))
        s1 = F.stratified_subsample(items, 20, keys, seed=1); s2 = F.stratified_subsample(items, 20, keys, seed=1)
        self.assertEqual(len(s1), 20); self.assertEqual(s1, s2)
        kd = dict(zip([str(p) for p, _ in items], keys))
        pos = sum(1 for p, _ in s1 if kd[str(p)][1]); locs = {kd[str(p)][0] for p, _ in s1}
        self.assertGreaterEqual(pos, 16); self.assertLessEqual(pos, 19); self.assertEqual(locs, {"A", "B", "C"})   # 없음 층도 최소 1장씩
        self.assertEqual(F.stratified_subsample(items, 500, keys, 1), items)

    def test_stall_detection_and_eta(self):
        self.assertTrue(F.is_stalled(newest=1000.0, now=1000.0 + 16 * 60, stall_min=15))
        self.assertFalse(F.is_stalled(newest=1000.0, now=1000.0 + 14 * 60, stall_min=15))
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); (d / "metrics.csv").write_text("epoch,step\n0,50\n0,100\n", encoding="utf-8")
            self.assertEqual(F.last_metrics_row(d / "metrics.csv"), "0,100")
            self.assertGreater(F.newest_mtime([d / "metrics.csv", d], 0.0), 0.0)
            self.assertEqual(F.newest_mtime([d / "none.csv"], 42.0), 42.0)     # 아무것도 없으면 시작 시각
        self.assertEqual(F.eta_minutes([240.0, 260.0], 10, 2), 33.3)           # 평균 250s × 8 epoch
        self.assertEqual(F.eta_minutes([], 10, 0), 0.0); self.assertEqual(F.eta_minutes([100.0], 10, 10), 0.0)

    def test_valid_limit_per_source_caps_only_that_source(self):
        # 2026-09-27: 학습 중 검증셋을 CSS valid + 507 val ≤N 으로 — 지정 소스만 시드 추림, 나머지는 그대로, train 은 불변
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            for name, val in (("s1", ["c", "d", "e"]), ("s2", ["x", "y"])):
                sd = d / name; (sd / "labels").mkdir(parents=True)
                for s in ["a", "b"] + val:
                    Image.new("RGB", (16, 16)).save(sd / f"{name}_{s}.jpg"); (sd / "labels" / f"{name}_{s}.txt").write_text("0 0.5 0.5 0.2 0.2\n", encoding="utf-8")
                (sd / "classes.txt").write_text("person\n", encoding="utf-8")
                (sd / "split.json").write_text(json.dumps({"train": [f"{name}_a", f"{name}_b"], "val": [f"{name}_{s}" for s in val]}), encoding="utf-8")
            cfg = {"classes": ["person"], "valid_limit_per_source": {"s1": 1},
                   "sources": [{"name": n, "kind": "vigent", "labels": str(d / n / "labels"), "images": str(d / n), "split": str(d / n / "split.json")} for n in ("s1", "s2")]}
            rep = F.assemble(cfg, d / "out", copy=False, seed=3)
            self.assertEqual(rep["valid_capped"], {"s1": 1, "s2": 2}); self.assertEqual(rep["valid"]["images"], 3); self.assertEqual(rep["train"]["images"], 4)
            rep2 = F.assemble(cfg, d / "out2", copy=False, seed=3)
            self.assertEqual(rep2["valid"]["images"], 3)                    # 시드 동일 → 같은 추림
            cfg.pop("valid_limit_per_source")
            self.assertEqual(F.assemble(cfg, d / "out3", copy=False, seed=3)["valid"]["images"], 5)

    def test_drop_classes_keeps_slots_but_removes_boxes(self):
        # 2026-09-27: v1 10슬롯 순서를 유지하되 Mask 류 주석은 비운다 — 카테고리는 남고 박스만 빠진다. classes 에 없는 이름이면 중단.
        from PIL import Image
        with tempfile.TemporaryDirectory() as td:
            d = Path(td); (d / "labels").mkdir()
            for s in ("a", "b"):
                Image.new("RGB", (16, 16)).save(d / f"{s}.jpg"); (d / "labels" / f"{s}.txt").write_text("0 0.5 0.5 0.2 0.2\n1 0.5 0.5 0.2 0.2\n", encoding="utf-8")
            (d / "classes.txt").write_text("Hardhat\nMask\n", encoding="utf-8")
            (d / "split.json").write_text(json.dumps({"train": ["a"], "val": ["b"]}), encoding="utf-8")
            cfg = {"classes": ["Hardhat", "Mask"], "drop_classes": ["Mask"],
                   "sources": [{"name": "s", "kind": "vigent", "labels": str(d / "labels"), "images": str(d), "split": str(d / "split.json")}]}
            rep = F.assemble(cfg, d / "out", copy=False, seed=1)
            self.assertEqual(rep["dropped_boxes_by_class_policy"], {"classes": ["Mask"], "boxes": 2})
            coco = json.loads((d / "out" / "dataset" / "train" / "_annotations.coco.json").read_text(encoding="utf-8"))
            self.assertEqual([c["name"] for c in coco["categories"]], ["Hardhat", "Mask"])      # 슬롯(카테고리)은 유지
            self.assertEqual({a["category_id"] for a in coco["annotations"]}, {1})                # Mask(2) 주석은 없음
            cfg["drop_classes"] = ["NO-Mask"]
            with self.assertRaises(SystemExit):
                F.assemble(cfg, d / "out2", copy=False, seed=1)

    def test_slot_alignment_guard(self):
        # 2026-09-27 A′ 사전 가드: 체크포인트 class_names 순서 ≠ 데이터셋 classes 순서면 거부(매핑표 포함). CSS 공백형 이름은 표준형으로 맞춰 비교.
        v1 = ["Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest", "Person", "Safety Cone", "Safety Vest", "machinery", "vehicle"]
        ok, rows = F.slot_alignment(v1, ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest"])   # A/B/D 의 배치
        self.assertFalse(ok); self.assertTrue(any("충돌" in r for r in rows)); self.assertIn("슬롯 0", rows[0])
        ok2, rows2 = F.slot_alignment(v1, ["Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety-Vest", "person", "Safety Cone", "Safety-Vest", "machinery", "vehicle"])
        self.assertTrue(ok2); self.assertFalse(any("충돌" in r for r in rows2))
        ok3, _ = F.slot_alignment(None, ["person", "forklift"])   # COCO 사전학습(헤드 재초기화) → 검사 생략
        self.assertTrue(ok3)
        self.assertFalse(F.slot_alignment(v1, v1[:5])[0])           # 길이만 달라도 거부

    def test_subsample_is_deterministic_and_bounded(self):
        items = [(Path(f"i{i}.jpg"), []) for i in range(50)]
        s1 = F.subsample(items, 10, seed=1); s2 = F.subsample(items, 10, seed=1); s3 = F.subsample(items, 10, seed=2)
        self.assertEqual(len(s1), 10); self.assertEqual(s1, s2); self.assertNotEqual(s1, s3)
        self.assertEqual(F.subsample(items, None, 1), items); self.assertEqual(F.subsample(items, 100, 1), items)


if __name__ == "__main__":
    unittest.main()
