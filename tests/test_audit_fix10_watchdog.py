"""CODE_AUDIT_20260928 #10 + B-1 — 학습 정체 감시의 중지·심장박동, NaN 판정 fail-closed, aug_config 전달. [2026-09-28]

★무엇을 고정하는가
  ① start_stall_watchdog 는 (thread, stop_event) 를 돌려주고 stop_event.set() 뒤에는 정체가 있어도 종료하지 않는다.
  ② touch_heartbeat 가 갱신되면 정체로 보지 않는다(중간 held-out 평가 중 오판 방지). 루프 본문 예외는 감시를 죽이지 않는다.
  ③ _nonfinite 는 판정 중 예외를 True(의심)로 돌려준다.
  ④ split_train_block 은 train.aug_config 를 CLI 기본값에서 떼어 dict 로 돌려주고, 매핑이 아니면 SystemExit.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "train"))

import finetune_rfdetr as F  # noqa: E402


class WatchdogLifecycle(unittest.TestCase):
    def test_stop_event_prevents_false_abort(self):
        with tempfile.TemporaryDirectory() as td:
            ck = Path(td) / "ckpt"; ck.mkdir()
            exits: list[int] = []
            with mock.patch.object(F, "_stall_exit", side_effect=lambda c: exits.append(c)):
                th, stop = F.start_stall_watchdog(ck, stall_min=0.001, check_s=0.05)    # 0.06 s 무갱신이면 정체
                stop.set(); th.join(1.0)
                time.sleep(0.2)
            self.assertFalse(th.is_alive()); self.assertEqual(exits, [])

    def test_stall_without_heartbeat_aborts_and_with_heartbeat_does_not(self):
        with tempfile.TemporaryDirectory() as td:
            ck = Path(td) / "ckpt"; ck.mkdir()
            exits: list[int] = []
            with mock.patch.object(F, "_stall_exit", side_effect=lambda c: exits.append(c)), mock.patch.object(F, "pyspy_dump", return_value="(skip)"):
                th, stop = F.start_stall_watchdog(ck, stall_min=0.002, check_s=0.05)    # 0.12 s
                for _ in range(20):
                    if exits:
                        break
                    time.sleep(0.05)
                stop.set(); th.join(1.0)
            self.assertEqual(exits, [9]); self.assertTrue((ck / "STALL_ABORT.json").exists())
            exits.clear(); ck2 = Path(td) / "ckpt2"; ck2.mkdir()
            with mock.patch.object(F, "_stall_exit", side_effect=lambda c: exits.append(c)):
                th, stop = F.start_stall_watchdog(ck2, stall_min=0.002, check_s=0.05)
                for _ in range(8):
                    F.touch_heartbeat(ck2); time.sleep(0.05)               # 0.4 s 동안 심장박동 → 정체 아님
                stop.set(); th.join(1.0)
            self.assertEqual(exits, [])

    def test_loop_survives_exception(self):
        with tempfile.TemporaryDirectory() as td:
            ck = Path(td) / "ckpt"; ck.mkdir()
            calls = {"n": 0}

            def boom(paths, default):
                calls["n"] += 1
                raise OSError("iterdir 경합")
            with mock.patch.object(F, "newest_mtime", side_effect=boom):
                th, stop = F.start_stall_watchdog(ck, stall_min=1, check_s=0.05)
                time.sleep(0.3); stop.set(); th.join(1.0)
            self.assertGreaterEqual(calls["n"], 2, "예외 뒤에도 감시가 계속 돌아야 한다")


class NanGuardFailClosed(unittest.TestCase):
    def test_exception_is_suspicious(self):
        class Weird:
            def __init__(self):
                self.item = "not-callable"
            isfinite = None
        self.assertTrue(F._nonfinite(Weird()))
        self.assertFalse(F._nonfinite(1.0)); self.assertTrue(F._nonfinite(float("nan"))); self.assertFalse(F._nonfinite("text"))


class TrainBlockSplit(unittest.TestCase):
    def test_aug_config_separated(self):
        d, aug = F.split_train_block({"train": {"epochs": 50, "lr": 1e-4, "aug_config": {"HorizontalFlip": {"p": 0.5}}}})
        self.assertEqual(d, {"epochs": 50, "lr": 1e-4}); self.assertEqual(aug, {"HorizontalFlip": {"p": 0.5}})
        self.assertEqual(F.split_train_block({"train": {"epochs": 1}}), ({"epochs": 1}, None))
        self.assertEqual(F.split_train_block({}), ({}, None))
        with self.assertRaises(SystemExit):
            F.split_train_block({"train": {"aug_config": ["not", "a", "map"]}})

    def test_aug_yaml_parses_into_mapping(self):
        import yaml
        cfg = yaml.safe_load((_ROOT / "configs" / "finetune_field_v2_aug.yaml").read_text(encoding="utf-8"))
        d, aug = F.split_train_block(cfg)
        self.assertIn("Perspective", aug); self.assertNotIn("aug_config", d); self.assertEqual(d["epochs"], 50)
        _ = threading  # noqa: B018  (모듈 사용 확인)


if __name__ == "__main__":
    unittest.main()
