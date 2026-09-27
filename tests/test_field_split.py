"""현장 held-out 선정·카메라 분할(scripts/data/field_split.py) + 조립기 held-out 가드(finetune_rfdetr). [PPE v2 현장 경로, 2026-09-27]

★무엇을 고정하는가
  1. held-out 은 (카메라, 주야) 층마다 프레임 비례 할당 + **클립 통째로**(같은 클립 프레임이 train 에 남지 않는다), 뽑힌 클립의 음성도 포함, policy="학습 금지".
  2. split 은 카메라 단위: 같은 카메라/클립이 양쪽에 없고, held-out stem 은 어느 쪽에도 없다. 누출이면 problems(exit 3 경로).
  3. finetune_rfdetr: vigent 소스 옆 heldout.json 을 자동으로 읽어 train/valid 에서 빼고, 다른 소스가 같은 stem 을 들고 오면 SystemExit.
     ${VIGENT_FIELD_DIR} 치환 · valid_only_from · train: 기본값 키 검증 · 중간 평가 주기(should_eval_heldout).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "data")); sys.path.insert(0, str(_ROOT / "scripts" / "train"))

import field_fixture as FX  # noqa: E402
import field_split as S  # noqa: E402
import finetune_rfdetr as F  # noqa: E402


def synth_frames(cams=3, clips=4, frames=25):
    out = []
    for c in range(cams):
        for dn in ("day", "night"):
            for k in range(clips):
                for f in range(frames):
                    out.append({"stem": f"cam{c}__d__{dn}__c{k}__f{f:06d}", "camera": f"cam{c}", "daynight": dn, "clip": f"cam{c}/{dn}_{k}", "negative": f % 5 == 0})
    return out


class HeldoutSelectTest(unittest.TestCase):
    def test_stratified_clip_level(self):
        fr = synth_frames(); pos = [f for f in fr if not f["negative"]]
        h = S.select_heldout(fr, n=120, seed=1)
        self.assertEqual(h["policy"], S.POLICY); self.assertGreaterEqual(h["n_positive"], 120)
        self.assertEqual(len(h["strata"]), 6)                                     # 3 카메라 × 주야
        for k, v in h["strata"].items():
            self.assertGreaterEqual(v["taken"], v["quota"])
        # 클립 통째: held-out 클립의 모든 양성 프레임이 목록에 있고, 그 클립의 음성도 negatives 에
        hs = set(h["frames"])
        for f in pos:
            self.assertEqual(f["stem"] in hs, f["clip"] in set(h["clips"]))
        self.assertEqual(set(h["negatives"]), {f["stem"] for f in fr if f["negative"] and f["clip"] in set(h["clips"])})
        self.assertEqual(S.select_heldout(fr, 120, 1)["frames"], h["frames"])       # seed 결정적
        with self.assertRaises(SystemExit):
            S.select_heldout([f for f in fr if f["negative"]], 10, 0)

    def test_split_by_camera_and_leak(self):
        fr = synth_frames(); h = S.select_heldout(fr, 100, 0); hs = set(h["frames"]) | set(h["negatives"])
        split, problems = S.split_cameras(fr, hs, val_ratio=0.34, seed=0)
        self.assertEqual(problems, []); self.assertTrue(split["val_keys"]); self.assertTrue(split["train_keys"])
        self.assertFalse(set(split["train_keys"]) & set(split["val_keys"]))
        self.assertFalse((set(split["train"]) | set(split["val"])) & hs)
        by = {f["stem"]: f for f in fr}
        self.assertFalse({by[s]["clip"] for s in split["train"]} & {by[s]["clip"] for s in split["val"]})
        self.assertTrue(all(not by[s]["negative"] for s in split["train"] + split["val"]))
        split2, p2 = S.split_cameras(fr, hs, val_cameras=["cam2"]); self.assertEqual(p2, []); self.assertEqual(split2["val_keys"], ["cam2"])
        _, p3 = S.split_cameras(fr, hs, val_cameras=["cam9"]); self.assertTrue(p3)
        # 누출 주입: 같은 클립이 두 카메라 이름으로 → leak_check 가 '같은 영상이 양쪽에' 를 잡아야 한다
        bad = [dict(f) for f in synth_frames(cams=2, clips=2, frames=10)]
        for f in bad:
            f["clip"] = "shared/clip"
        _, p4 = S.split_cameras(bad, set(), val_ratio=0.5, seed=0); self.assertTrue(any("같은 영상" in p for p in p4), p4)

    def test_cli_files(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "prelabel"; r = FX.make_vigent(d, cams=2, clips=3, frames=10, heldout_n=8)
            self.assertGreater(r["val"], 0); self.assertGreater(r["train"], 0)
            rc = S.cmd_heldout(d, 8, 0); self.assertEqual(rc, 0)
            m = json.loads((d / "manifest.json").read_text(encoding="utf-8")); h = json.loads((d / "heldout.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(1 for f in m["frames"] if f["no_train"]), len(h["frames"]) + len(h["negatives"]))
            self.assertEqual(S.cmd_split(d, 0.25, 0, ["cam2"]), 0)
            sp = json.loads((d / "split.json").read_text(encoding="utf-8")); self.assertEqual(sp["val_keys"], ["cam2"])
            self.assertEqual(S.cmd_split(d, 0.25, 0, ["nope"]), 3)


class FinetuneHeldoutGuardTest(unittest.TestCase):
    def test_expand_and_train_defaults_and_schedule(self):
        os.environ[F.FIELD_DIR_ENV] = "Q:/fx"
        try:
            self.assertEqual(F.expand_path("${VIGENT_FIELD_DIR}/labels"), "Q:/fx/labels"); self.assertEqual(F.expand_path("plain"), "plain")
        finally:
            del os.environ[F.FIELD_DIR_ENV]
        self.assertEqual(F.expand_path("${VIGENT_FIELD_DIR}"), F.FIELD_DIR_DEFAULT)
        self.assertEqual([e for e in range(1, 51) if F.should_eval_heldout(e, 10, 50)], [10, 20, 30, 40])   # 50 은 최종 하네스
        self.assertFalse(F.should_eval_heldout(10, 0, 50))
        cmd = F.heldout_eval_cmd(Path("c.pth"), "D:/f", Path("o.json"), "epoch10", 384)
        self.assertIn("--field-only", cmd); self.assertIn("--field-heldout", cmd)

    def test_assemble_excludes_heldout_and_guard_trips(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "prelabel"; FX.make_vigent(d, cams=2, clips=2, frames=10, heldout_n=6)
            os.environ[F.FIELD_DIR_ENV] = str(d).replace("\\", "/")
            try:
                cfg = {"classes": FX.CLASSES, "sources": [{"name": "field", "kind": "vigent", "labels": "${VIGENT_FIELD_DIR}/labels",
                                                           "images": "${VIGENT_FIELD_DIR}/images", "split": "${VIGENT_FIELD_DIR}/split.json"}],
                       "exclude_manifests": ["${VIGENT_FIELD_DIR}/heldout.json"], "valid_only_from": ["field"]}
                stems, rep = F.heldout_stems(cfg)
                h = json.loads((d / "heldout.json").read_text(encoding="utf-8"))
                self.assertEqual(stems, set(h["frames"]) | set(h["negatives"])); self.assertEqual(len(rep), 1)      # 사이드카와 exclude_manifests 가 같은 파일 → 1건
                rep2 = F.assemble(cfg, Path(td) / "out", copy=False, seed=0)
                self.assertEqual(rep2["excluded_heldout"], 0)                                                          # split.json 은 이미 held-out 을 뺀 목록
                sp = json.loads((d / "split.json").read_text(encoding="utf-8"))
                self.assertEqual(rep2["train"]["images"], len(sp["train"])); self.assertEqual(rep2["valid"]["images"], len(sp["val"]))
                # 두 번째 소스가 held-out stem 을 train 에 들고 오면 → 제외(excluded_heldout>0), 가드는 exclude 뒤라 통과
                leak = Path(td) / "leak"; (leak / "labels").mkdir(parents=True)
                (leak / "split.json").write_text(json.dumps({"train": h["frames"][:3], "val": []}), encoding="utf-8")
                cfg2 = dict(cfg); cfg2["sources"] = cfg["sources"] + [{"name": "leak", "kind": "vigent", "labels": str(leak / "labels"), "images": str(d / "images"), "split": str(leak / "split.json")}]
                rep3 = F.assemble(cfg2, Path(td) / "out2", copy=False, seed=0); self.assertEqual(rep3["excluded_heldout"], 3)
                # 가드 자체: 조립 결과에 학습 금지 stem 이 남으면 SystemExit
                with self.assertRaises(SystemExit):
                    F.heldout_guard({"train": [(Path(h["frames"][0] + ".jpg"), [])], "valid": []}, stems)
                # valid_only_from: 다른 소스의 valid 는 버린다
                cfg3 = dict(cfg2); cfg3["valid_only_from"] = ["leak"]
                rep4 = F.assemble(cfg3, Path(td) / "out3", copy=False, seed=0); self.assertEqual(rep4["valid"]["images"], 0); self.assertIn("field", rep4["valid_dropped_by_policy"])
                # exclude_manifests 파일이 없으면 시작하지 않는다
                cfg4 = dict(cfg); cfg4["exclude_manifests"] = [str(Path(td) / "none.json")]
                with self.assertRaises(SystemExit):
                    F.heldout_stems(cfg4)
            finally:
                del os.environ[F.FIELD_DIR_ENV]


if __name__ == "__main__":
    unittest.main()
