#!/usr/bin/env python3
"""scripts/train/finetune_rfdetr.py — RF-DETR Nano 재학습(개발기 RTX 5070 Ti 로컬) + 학습 후 비교 하네스 자동 호출. [A-5, 2026-09-26]

★★ 실행 금지 상태(대표 지시): 한 번도 돌리지 않았다. `--dry-run` 만 허용.
   실제 학습은 대표 승인 뒤 — 순서: 데이터 조립 검증 → 학습 → 하네스(전/후 비교) → (PPE 는) 현장 정답지 판정.
   ★우선순위(2026-09-26): 1순위 forklift(510, `configs/finetune_aihub_forklift_v2.yaml`) · 2순위 NO-Hardhat(507, `configs/finetune_aihub_v2.yaml`).

무엇을 하는가
  1. 데이터 조립: 소스(우리 정답지 스키마 = labels/*.txt + images + split.json) 여러 개를 COCO 형식
     `out/dataset/{train,valid,test}/_annotations.coco.json` 으로 합친다(rfdetr 가 이 형식을 읽는다).
       · CSS v27(YOLO, data.yaml) · AI Hub 507/510 변환본 · pseudo_hardhat 준라벨 · (나중에) 현장 정답지
       · `exclude_files` 의 held-out stem 은 어느 분할에도 넣지 않는다 — 하네스 "전/후" 비교 집합
       · `max_train` 이 있으면 train 을 시드로 결정적 추림(스모크 파인튜닝 상한)
  2. 학습: RFDETRNano(...).train(...) — **v1 사고 재발 방지 장치**(provenance §9-2·§9-5: MPS·loss NaN 49 epoch 완주·seed 없음·resolution 미기록):
       · NaN 감시: 배치 손실 또는 epoch 지표에 NaN/inf 가 나오면 **즉시 중단**(`NAN_ABORT.json` 기록). 직전 epoch 체크포인트(`last.ckpt`/`checkpoint_*.pth`)는 그대로 남는다
       · seed 고정(random·numpy·torch·lightning) + `train(seed=)`
       · `notes` 로 **resolution·seed·args 전부**를 체크포인트 `args.notes` 에 기록하고, 학습 뒤 체크포인트를 열어 **기록됐는지·NaN 텐서가 없는지 확인**(규칙 11)
       · CUDA 가 아니면 시작하지 않는다(`--allow-cpu` 로만 우회)
  3. 학습 후: config `harness`(ppe|forklift)에 따라 `scripts/eval/eval_v1_heldout.py` 또는 `scripts/eval/forklift_compare_harness.py` 자동 호출.

사용:
    python scripts/train/finetune_rfdetr.py --config configs/finetune_aihub_forklift_v2.yaml --dry-run    # 조립·계획만
    python scripts/train/finetune_rfdetr.py --config configs/finetune_aihub_forklift_v2.yaml --epochs 20 --out runs/finetune/fk_510  (★승인 후)
★학습 의존성: rfdetr 1.8 의 train() 은 pytorch_lightning 이 필요하다(`pip install "rfdetr[train,loggers]"`) — 2026-09-26 현재 .venv 에 **없음**. 설치는 대표 승인 뒤.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

_ROOT = Path(__file__).resolve().parent.parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IMG_EXTS = (".jpg", ".jpeg", ".png")
NOTES_REQUIRED = ("resolution", "seed", "epochs", "batch", "grad_accum", "lr", "init", "classes", "config", "git_commit",
                  "rfdetr_version", "torch_version", "host", "timestamp", "assembly", "script")


# ---------------------------------------------------------------------------------------------------------------------
# 데이터 조립
# ---------------------------------------------------------------------------------------------------------------------
def _img_size(p: Path) -> tuple[int, int]:
    from PIL import Image
    with Image.open(p) as im:
        return im.width, im.height


def _read_yolo(txt: Path, names: list[str], classes: list[str]) -> list[tuple[int, list[float]]]:
    out = []
    for ln in txt.read_text(encoding="utf-8", errors="replace").splitlines():
        t = ln.split()
        if len(t) < 5:
            continue
        name = names[int(t[0])] if int(t[0]) < len(names) else None
        name = {"Safety Vest": "Safety-Vest", "NO-Safety Vest": "NO-Safety-Vest", "Person": "person"}.get(name, name)  # CSS 공백형 → 표준형
        if name not in classes:
            continue
        out.append((classes.index(name), [float(x) for x in t[1:5]]))
    return out


def collect_source(src: dict[str, Any], classes: list[str]) -> dict[str, list[tuple[Path, list[tuple[int, list[float]]]]]]:
    """소스 하나 → {split: [(이미지경로, [(cls, [cx,cy,w,h])])]}"""
    kind = src["kind"]
    out: dict[str, list] = {"train": [], "valid": []}
    if kind == "yolo_yaml":
        import yaml
        y = yaml.safe_load(Path(src["path"]).read_text(encoding="utf-8")); names = y["names"]
        base = Path(src["path"]).parent
        for split, sub in src.get("splits", {"train": "train", "valid": "valid"}).items():
            for img in sorted((base / sub / "images").glob("*")):
                if img.suffix.lower() not in IMG_EXTS:
                    continue
                lb = base / sub / "labels" / (img.stem + ".txt")
                out[split].append((img, _read_yolo(lb, names, classes) if lb.exists() else []))
    elif kind == "vigent":
        labels = Path(src["labels"]); images = Path(src["images"])
        names = (labels.parent / "classes.txt").read_text(encoding="utf-8").split() if (labels.parent / "classes.txt").exists() else classes
        idx = {p.stem: p for p in images.rglob("*") if p.suffix.lower() in IMG_EXTS}
        sp = json.loads(Path(src["split"]).read_text(encoding="utf-8"))
        for split, key in (("train", "train"), ("valid", "val")):
            for stem in sp.get(key, []):
                if stem in idx:
                    lb = labels / f"{stem}.txt"
                    out[split].append((idx[stem], _read_yolo(lb, names, classes) if lb.exists() else []))
    else:
        raise ValueError(f"알 수 없는 kind: {kind}")
    return out


def subsample(items: list, max_n: int | None, seed: int) -> list:
    """train 상한(스모크 파인튜닝) — 시드로 결정적. max_n 이 없거나 크면 그대로."""
    if not max_n or len(items) <= max_n:
        return list(items)
    rnd = random.Random(seed)
    idx = sorted(rnd.sample(range(len(items)), max_n))
    return [items[i] for i in idx]


def stratified_subsample(items: list, n: int, keys: list[tuple], seed: int) -> list:
    """층화 표본(학습 중 검증셋 축소용, 2026-09-26): keys[i]=(장소, 지게차있음) 층마다 비례 배분(최소 1)·시드 고정.
    n 이 전체 이상이면 그대로. 층 비율(지게차 있음/없음·장소)은 원본과 같게 유지한다."""
    if not n or len(items) <= n:
        return list(items)
    groups: dict[tuple, list[int]] = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    rnd = random.Random(seed)
    total = len(items); take: dict[tuple, int] = {}
    for k, idxs in groups.items():
        take[k] = max(1, int(round(len(idxs) * n / total)))
    # 반올림 합이 n 과 어긋나면 큰 층부터 보정
    diff = n - sum(take.values())
    for k in sorted(groups, key=lambda g: -len(groups[g])):
        if diff == 0:
            break
        step = 1 if diff > 0 else -1
        if take[k] + step >= 1 and take[k] + step <= len(groups[k]):
            take[k] += step; diff -= step
    chosen: list[int] = []
    for k, idxs in groups.items():
        chosen.extend(rnd.sample(idxs, min(take[k], len(idxs))))
    return [items[i] for i in sorted(chosen)]


def strat_key(img: Path, boxes: list, classes: list[str], meta_dirs: list[Path]) -> tuple:
    """(장소ID, 지게차 있음) — 장소는 변환기 사이드카 labels_meta/<stem>.json 에서, 없으면 'na'."""
    loc = "na"
    for d in meta_dirs:
        p = d / f"{img.stem}.json"
        if p.exists():
            try:
                loc = str(json.loads(p.read_text(encoding="utf-8")).get("location_id") or "na"); break
            except Exception:  # noqa: BLE001
                pass
    fk = classes.index("forklift") if "forklift" in classes else -1
    return (loc, any(c == fk for c, _ in boxes))


def build_coco(items: list[tuple[Path, list]], classes: list[str], dst: Path, copy: bool) -> dict[str, Any]:
    """rfdetr 가 읽는 COCO 폴더(dst/_annotations.coco.json + 이미지)를 만든다. 카테고리 id 는 1부터."""
    dst.mkdir(parents=True, exist_ok=True)
    images, anns = [], []
    stats = Counter()
    for i, (img, boxes) in enumerate(items, 1):
        W, H = _img_size(img)
        name = f"{img.stem}{img.suffix}"
        if copy:
            shutil.copy2(img, dst / name)
        images.append({"id": i, "file_name": name, "width": W, "height": H})
        for cls, (cx, cy, w, h) in boxes:
            anns.append({"id": len(anns) + 1, "image_id": i, "category_id": cls + 1,
                         "bbox": [round((cx - w / 2) * W, 2), round((cy - h / 2) * H, 2), round(w * W, 2), round(h * H, 2)],
                         "area": round(w * W * h * H, 2), "iscrowd": 0})
            stats[classes[cls]] += 1
    coco = {"images": images, "annotations": anns,
            "categories": [{"id": i + 1, "name": c, "supercategory": "vigent"} for i, c in enumerate(classes)]}
    (dst / "_annotations.coco.json").write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
    return {"images": len(images), "boxes": len(anns), "per_class": dict(stats)}


def assemble(cfg: dict[str, Any], out: Path, copy: bool, seed: int = 0, max_train: int | None = None, val_subsample: int = 0) -> dict[str, Any]:
    classes = cfg["classes"]
    exclude = set()
    ex = cfg.get("exclude_files")
    if ex:
        j = json.loads((_ROOT / ex).read_text(encoding="utf-8"))
        exclude = {Path(f).stem for f in j.get("heldout_files", [])}
    merged: dict[str, list] = {"train": [], "valid": []}
    report: dict[str, Any] = {"sources": {}, "excluded_heldout": 0}
    for src in cfg["sources"]:
        got = collect_source(src, classes)
        for split in merged:
            kept = []
            for img, boxes in got[split]:
                if img.stem in exclude:
                    report["excluded_heldout"] += 1; continue
                kept.append((img, boxes))
            merged[split].extend(kept)
        report["sources"][src["name"]] = {s: len(v) for s, v in got.items()}
    # 누출 검사: 같은 stem 이 train·valid 양쪽에 있으면 실패
    ts = {i.stem for i, _ in merged["train"]}; vs = {i.stem for i, _ in merged["valid"]}
    if ts & vs:
        raise SystemExit(f"★누출: train·valid 양쪽에 같은 stem {len(ts & vs)}개 — 조립 중단")
    n_before = len(merged["train"])
    merged["train"] = subsample(merged["train"], max_train or cfg.get("max_train"), seed)
    report["train_subsampled"] = {"before": n_before, "after": len(merged["train"])}
    # 학습 중 검증셋 축소(층화: 장소 × 지게차 유무) — 최종 하네스는 전체 val 을 따로 쓴다(2026-09-26 정체 사고 후 조치)
    if val_subsample and len(merged["valid"]) > val_subsample:
        meta_dirs = [Path(s["labels"]).parent / "labels_meta" for s in cfg["sources"] if s.get("kind") == "vigent"]
        keys = [strat_key(img, boxes, classes, meta_dirs) for img, boxes in merged["valid"]]
        before = len(merged["valid"]); pos_before = sum(1 for k in keys if k[1])
        merged["valid"] = stratified_subsample(merged["valid"], val_subsample, keys, seed)
        keys2 = [strat_key(img, boxes, classes, meta_dirs) for img, boxes in merged["valid"]]
        report["valid_subsampled"] = {"before": before, "after": len(merged["valid"]), "forklift_present_before": pos_before,
                                      "forklift_present_after": sum(1 for k in keys2 if k[1]), "locations_after": len({k[0] for k in keys2})}
    for split, items in merged.items():
        report[split] = build_coco(items, classes, out / "dataset" / split, copy)
    # rfdetr 는 test 폴더도 기대한다 — valid 를 그대로 복제(기준선 판정은 하네스가 별도로 한다)
    report["test"] = build_coco(merged["valid"], classes, out / "dataset" / "test", copy)
    return report


# ---------------------------------------------------------------------------------------------------------------------
# v1 사고 재발 방지 장치: NaN 감시 · seed · 메타 기록·확인 · CUDA 강제
# ---------------------------------------------------------------------------------------------------------------------
class NanAbort(RuntimeError):
    """손실/지표에 NaN·inf — 학습을 즉시 중단한다(49 epoch 완주 사고 방지)."""


def _nonfinite(v: Any) -> bool:
    try:
        if hasattr(v, "isfinite") and hasattr(v, "numel"):       # torch.Tensor
            return bool((~v.detach().isfinite()).any().item()) if v.numel() else False
        if isinstance(v, bool):
            return False
        if isinstance(v, (int, float)):
            return not math.isfinite(v)
        if hasattr(v, "item"):                                    # numpy scalar
            return not math.isfinite(float(v.item()))
    except Exception:  # noqa: BLE001
        return False
    return False


def first_nonfinite(values: dict[str, Any]) -> str | None:
    """{이름: 값} 에서 처음 발견한 NaN/inf 이름. 없으면 None."""
    for k, v in values.items():
        if _nonfinite(v):
            return str(k)
    return None


def outputs_to_map(outputs: Any) -> dict[str, Any]:
    if outputs is None:
        return {}
    if isinstance(outputs, dict):
        return {str(k): v for k, v in outputs.items()}
    return {"loss": outputs}


class NanGuardCore:
    """프레임워크 무관 핵심: 검사 → 기록 → 예외. PTL 콜백(NanGuard)이 이를 감싼다."""

    def __init__(self, output_dir: Path | str):
        self.output_dir = Path(output_dir)
        self.abort_file = self.output_dir / "NAN_ABORT.json"

    def _abort(self, where: str, name: str) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        info = {"where": where, "metric": name, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                "note": "손실/지표 NaN·inf → 즉시 중단. 직전 epoch 체크포인트는 보존됨(v1 사고: epoch 1 NaN 뒤 49 epoch 완주)"}
        self.abort_file.write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        raise NanAbort(f"★NaN/inf {where} ({name}) — 학습 중단, {self.abort_file}")

    def check_batch(self, outputs: Any, epoch: int, batch_idx: int) -> None:
        bad = first_nonfinite(outputs_to_map(outputs))
        if bad:
            self._abort(f"epoch {epoch} batch {batch_idx}", bad)

    def check_metrics(self, metrics: dict[str, Any], epoch: int) -> None:
        bad = first_nonfinite(metrics)
        if bad:
            self._abort(f"epoch {epoch} 지표", bad)


def eta_minutes(epoch_times_s: list[float], epochs_total: int, epochs_done: int) -> float:
    """남은 예상 시간(분) = 평균 epoch 시간 × 남은 epoch."""
    if not epoch_times_s or epochs_done >= epochs_total:
        return 0.0
    return round(sum(epoch_times_s) / len(epoch_times_s) * (epochs_total - epochs_done) / 60, 1)


def nan_guard_callback(output_dir: Path | str, epochs_total: int = 0):
    """pytorch_lightning.Callback 서브클래스를 런타임에 만든다(테스트·dry-run 에서는 PTL 을 import 하지 않기 위해).
    NaN 감시 + epoch 소요·남은 예상(metrics.csv 의 epoch_time_s / eta_min 열 + 로그 줄)."""
    import pytorch_lightning as pl

    class NanGuard(pl.Callback):
        def __init__(self) -> None:
            super().__init__()
            self.core = NanGuardCore(output_dir)
            self.t_epoch = 0.0; self.epoch_times: list[float] = []

        def on_train_epoch_start(self, trainer, pl_module) -> None:  # noqa: ANN001
            self.t_epoch = time.time()

        def on_train_epoch_end(self, trainer, pl_module) -> None:  # noqa: ANN001
            dt = time.time() - self.t_epoch; self.epoch_times.append(dt)
            done = int(trainer.current_epoch) + 1
            eta = eta_minutes(self.epoch_times, epochs_total or int(trainer.max_epochs or 0), done)
            try:
                pl_module.log("epoch_time_s", round(dt, 1), on_step=False, on_epoch=True, sync_dist=False)
                pl_module.log("eta_min", eta, on_step=False, on_epoch=True, sync_dist=False)
            except Exception:  # noqa: BLE001
                pass
            print(f"[epoch] {done}/{epochs_total or trainer.max_epochs} 소요 {dt / 60:.1f}분 · 남은 예상 {eta}분 · 예상 종료 "
                  f"{time.strftime('%H:%M', time.localtime(time.time() + eta * 60))} ({time.strftime('%H:%M:%S')})", file=sys.stderr, flush=True)

        def on_train_batch_end(self, trainer, pl_module, outputs, batch, batch_idx) -> None:  # noqa: ANN001
            try:
                self.core.check_batch(outputs, int(trainer.current_epoch), int(batch_idx))
            except NanAbort:
                trainer.should_stop = True
                raise

        def on_validation_epoch_end(self, trainer, pl_module) -> None:  # noqa: ANN001
            try:
                self.core.check_metrics({k: v for k, v in dict(trainer.callback_metrics).items() if "loss" in str(k)}, int(trainer.current_epoch))
            except NanAbort:
                trainer.should_stop = True
                raise

    return NanGuard()


def wrap_build_trainer(orig: Callable[..., Any], guard: Any) -> Callable[..., Any]:
    """rfdetr.training.build_trainer 를 감싸 Trainer 에 우리 콜백을 덧붙인다(rfdetr 1.8 은 외부 콜백 인자를 받지 않는다)."""
    def wrapped(*a: Any, **k: Any) -> Any:
        trainer = orig(*a, **k)
        trainer.callbacks.append(guard)
        return trainer
    wrapped.__wrapped__ = orig  # type: ignore[attr-defined]
    return wrapped


def install_nan_guard(output_dir: Path | str, epochs_total: int = 0) -> None:
    import rfdetr.training as RT
    RT.build_trainer = wrap_build_trainer(RT.build_trainer, nan_guard_callback(output_dir, epochs_total))


# ── 정체 감시(2026-09-26 사고: metrics.csv 가 18:28 에 멈춘 채 2시간, 알림 없음) ───────────────────────────────────
def newest_mtime(paths: list[Path], default: float) -> float:
    """감시 대상(metrics.csv·체크포인트 폴더의 파일들) 중 가장 최근 수정 시각. 아무것도 없으면 default(시작 시각)."""
    m = default
    for p in paths:
        try:
            if p.is_dir():
                for f in p.iterdir():
                    m = max(m, f.stat().st_mtime)
            elif p.exists():
                m = max(m, p.stat().st_mtime)
        except OSError:
            pass
    return m


def is_stalled(newest: float, now: float, stall_min: float) -> bool:
    return (now - newest) > stall_min * 60


def last_metrics_row(csv_path: Path) -> str:
    try:
        lines = csv_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-1] if len(lines) > 1 else ""
    except OSError:
        return ""


def pyspy_dump(pid: int) -> str:
    """py-spy 가 있으면 스택 문자열, 없으면 사유."""
    exe = Path(sys.executable).parent / ("py-spy.exe" if os.name == "nt" else "py-spy")
    if not exe.exists():
        return "py-spy 없음"
    try:
        r = subprocess.run([str(exe), "dump", "--pid", str(pid)], capture_output=True, text=True, timeout=60)
        return (r.stdout or "") + (r.stderr or "")
    except Exception as e:  # noqa: BLE001
        return f"py-spy 실패: {e}"


def start_stall_watchdog(ckpt_dir: Path, stall_min: float, check_s: float = 30.0):
    """metrics.csv/체크포인트가 stall_min 분 넘게 갱신되지 않으면 STALL_ABORT.json(마지막 step·시각·py-spy 스택)을 쓰고 프로세스를 종료(exit 9).
    메인 스레드가 CPU 작업에 갇혀 있어도 감시 스레드는 돈다 → 알림 없이 몇 시간 멈추는 일을 막는다."""
    import threading
    t0 = time.time(); csv_path = ckpt_dir / "metrics.csv"

    def loop() -> None:
        while True:
            time.sleep(check_s)
            newest = newest_mtime([csv_path, ckpt_dir], t0)
            if is_stalled(newest, time.time(), stall_min):
                info = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "stall_min": stall_min, "last_update": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(newest)),
                        "last_metrics_row": last_metrics_row(csv_path), "pyspy": pyspy_dump(os.getpid()),
                        "note": "metrics.csv/체크포인트 갱신 정체 → 감시 스레드가 강제 종료(exit 9). 마지막 체크포인트는 보존"}
                ckpt_dir.mkdir(parents=True, exist_ok=True)
                (ckpt_dir / "STALL_ABORT.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"★정체 {stall_min}분 — STALL_ABORT.json 기록 후 종료(exit 9): 마지막 행 {info['last_metrics_row']!r}", file=sys.stderr, flush=True)
                os._exit(9)

    th = threading.Thread(target=loop, name="stall-watchdog", daemon=True); th.start()
    return th


def set_all_seeds(seed: int) -> dict[str, bool]:
    done = {"random": True, "numpy": False, "torch": False, "lightning": False}
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed); done["numpy"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        import torch
        torch.manual_seed(seed); torch.cuda.manual_seed_all(seed); done["torch"] = True
    except Exception:  # noqa: BLE001
        pass
    try:
        import pytorch_lightning as pl
        pl.seed_everything(seed, workers=True); done["lightning"] = True
    except Exception:  # noqa: BLE001
        pass
    return done


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=str(_ROOT), text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def build_notes(a: argparse.Namespace, cfg: dict[str, Any], rep: dict[str, Any]) -> dict[str, Any]:
    """체크포인트 args.notes 에 남길 출처 정보 — v1 에 없던 것(resolution·seed·lr·장치·데이터 수량)을 전부 적는다."""
    try:
        import rfdetr
        rf_v = getattr(rfdetr, "__version__", "?")
    except Exception:  # noqa: BLE001
        rf_v = "not-installed"
    try:
        import torch
        t_v = torch.__version__; dev = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001
        t_v, dev = "not-installed", "?"
    notes = {"resolution": a.res, "seed": a.seed, "epochs": a.epochs, "batch": a.batch, "grad_accum": a.grad_accum, "lr": a.lr,
             "init": a.init, "classes": list(cfg["classes"]), "config": str(a.config), "git_commit": _git_commit(),
             "rfdetr_version": rf_v, "torch_version": t_v, "device": dev, "host": platform.node(), "os": platform.platform(),
             "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), "assembly": rep, "script": "scripts/train/finetune_rfdetr.py",
             "harness": cfg.get("harness", "ppe"), "max_train": a.max_train or cfg.get("max_train")}
    json.dumps(notes)   # 직렬화 가능해야 rfdetr 가 저장한다
    return notes


def _state_dict_of(ck: dict[str, Any]) -> dict[str, Any]:
    for k in ("state_dict", "model", "ema_model", "model_ema"):
        v = ck.get(k)
        if isinstance(v, dict) and v:
            return v
    return {}


def verify_checkpoint(path: Path | str, expect_res: int, expect_seed: int) -> list[str]:
    """학습 산출물 검증(규칙 11): notes 필수 키·resolution/seed 일치·NaN 텐서 0. 문제 목록을 돌려준다(빈 목록 = 통과)."""
    import torch
    problems: list[str] = []
    ck = torch.load(str(path), map_location="cpu", weights_only=False)
    args = ck.get("args") or {}
    if hasattr(args, "__dict__") and not isinstance(args, dict):
        args = vars(args)
    notes = args.get("notes") if isinstance(args, dict) else None
    if not isinstance(notes, dict):
        problems.append("args.notes 없음(출처 메타 미기록)")
    else:
        missing = [k for k in NOTES_REQUIRED if k not in notes]
        if missing:
            problems.append(f"notes 필수 키 누락: {missing}")
        if notes.get("resolution") != expect_res:
            problems.append(f"notes.resolution {notes.get('resolution')} ≠ {expect_res}")
        if notes.get("seed") != expect_seed:
            problems.append(f"notes.seed {notes.get('seed')} ≠ {expect_seed}")
    sd = _state_dict_of(ck)
    if not sd:
        problems.append("가중치 dict 없음(state_dict/model)")
    else:
        bad = [k for k, v in sd.items() if hasattr(v, "isfinite") and v.numel() and not bool(v.isfinite().all())]
        if bad:
            problems.append(f"NaN/inf 텐서 {len(bad)}개: {bad[:3]}")
    return problems


def require_cuda(available: bool, allow_cpu: bool = False) -> None:
    """v1 은 맥 MPS 에서 발산했다(provenance §9-2). CUDA 가 아니면 시작하지 않는다."""
    if not available and not allow_cpu:
        raise SystemExit("★CUDA 없음 — 학습을 시작하지 않는다(MPS/CPU 학습 금지, --allow-cpu 로만 우회)")


# ---------------------------------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="조립 설정 yaml(classes·sources·exclude_files·harness·init·max_train)")
    ap.add_argument("--out", default=str(_ROOT / "runs" / "finetune" / time.strftime("aihub_%Y%m%d_%H%M")))
    ap.add_argument("--epochs", type=int, default=30); ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--grad-accum", type=int, default=2); ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--res", type=int, default=384, help="운용 해상도와 같게")
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--init", default="", help="시작 가중치 경로 또는 'coco'(기본: config init → 없으면 ppe v1)")
    ap.add_argument("--max-train", type=int, default=0, help="train 상한(0=config max_train 또는 무제한)")
    ap.add_argument("--val-subsample", type=int, default=800, help="학습 중 검증셋 층화 표본 수(장소×지게차 유무 비율 유지, 0=전체). 최종 하네스는 전체 val")
    ap.add_argument("--eval-interval", type=int, default=2, help="검증 주기(epoch)")
    ap.add_argument("--num-workers", type=int, default=0, help="데이터로더 워커(0=메인 프로세스)")
    ap.add_argument("--stall-min", type=float, default=15.0, help="metrics.csv/체크포인트가 이 시간(분) 넘게 갱신되지 않으면 STALL_ABORT 후 종료")
    ap.add_argument("--eval-max-dets", type=int, default=100, help="검증 시 이미지당 최대 검출(rfdetr 기본 500 → COCO 표준 100; 2026-09-26 정체 원인이 검출 수 비례 변환)")
    ap.add_argument("--label", default="", help="하네스 비교표의 '후' 열 이름(기본 out 폴더명)")
    ap.add_argument("--dev74", action="store_true", help="(ppe 하네스) 사고영상 dev 74 도 채점")
    ap.add_argument("--copy-images", action="store_true", help="이미지를 dataset/ 에 복사(기본은 복사 없이 계획만 — dry-run 용)")
    ap.add_argument("--allow-cpu", action="store_true", help="(비권장) CUDA 없이도 진행")
    ap.add_argument("--dry-run", action="store_true", help="조립 통계·계획만 출력하고 학습하지 않는다")
    a = ap.parse_args()
    import yaml
    cfg = yaml.safe_load(Path(a.config).read_text(encoding="utf-8"))
    a.init = a.init or cfg.get("init") or str(_ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth")
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    seeds = set_all_seeds(a.seed)

    rep = assemble(cfg, out, copy=a.copy_images and not a.dry_run, seed=a.seed, max_train=a.max_train or None, val_subsample=a.val_subsample)
    notes = build_notes(a, cfg, rep)
    notes.update({"val_subsample": a.val_subsample, "eval_interval": a.eval_interval, "num_workers": a.num_workers, "stall_min": a.stall_min, "eval_max_dets": a.eval_max_dets})
    plan = {"config": a.config, "out": str(out), "epochs": a.epochs, "batch": a.batch, "grad_accum": a.grad_accum, "lr": a.lr,
            "res": a.res, "seed": a.seed, "seeds_set": seeds, "init": a.init, "classes": cfg["classes"], "harness": cfg.get("harness", "ppe"),
            "val_subsample": a.val_subsample, "eval_interval": a.eval_interval, "num_workers": a.num_workers, "stall_min": a.stall_min,
            "assembly": rep, "notes_keys": sorted(notes.keys()),
            "guards": ["NaN 감시(배치 손실·epoch 지표) → 즉시 중단", "seed 고정", "notes(resolution·seed·args) 체크포인트 기록 + 학습 후 검증", "CUDA 강제",
                       f"정체 감시 {a.stall_min}분 → STALL_ABORT.json(py-spy 스택) + exit 9", "epoch 소요·남은 예상 → metrics.csv epoch_time_s/eta_min + 로그"],
            "note": "held-out 은 exclude_files 로 제외 · 학습 후 하네스 자동 호출 · PPE 최종 판정은 현장 정답지(미확보)"}
    (out / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(plan, ensure_ascii=False, indent=1))
    if a.dry_run:
        print("--dry-run: 학습하지 않았다(실행 금지 상태)")
        return 0

    # ── 학습(승인 후에만 도달) ──
    import torch
    require_cuda(torch.cuda.is_available(), a.allow_cpu)
    try:
        import pytorch_lightning  # noqa: F401
    except ModuleNotFoundError:
        print('★pytorch_lightning 없음 — rfdetr 1.8 train() 은 `pip install "rfdetr[train,loggers]"` 가 필요하다(설치는 대표 승인 뒤)'); return 2
    from rfdetr import RFDETRNano
    install_nan_guard(out / "ckpt", a.epochs)
    m = RFDETRNano(resolution=a.res) if a.init == "coco" else RFDETRNano(pretrain_weights=a.init, resolution=a.res)
    t0 = time.time()
    start_stall_watchdog(out / "ckpt", a.stall_min)
    print(f"[train] 시작 {time.strftime('%H:%M:%S')} · epochs {a.epochs} · valid {rep['valid']['images']}장(학습 중) · eval_interval {a.eval_interval} · "
          f"num_workers {a.num_workers} · 정체 감시 {a.stall_min}분", flush=True)
    try:
        m.train(dataset_dir=str(out / "dataset"), epochs=a.epochs, batch_size=a.batch, grad_accum_steps=a.grad_accum, lr=a.lr,
                device="cuda", output_dir=str(out / "ckpt"), tensorboard=False, early_stopping=False, seed=a.seed, notes=notes,
                eval_interval=a.eval_interval, num_workers=a.num_workers, progress_bar=None, checkpoint_interval=1, eval_max_dets=a.eval_max_dets)
    except NanAbort as e:
        print(str(e)); print("★학습 실패(NaN) — 산출물을 하네스에 넘기지 않는다"); return 3
    print(f"[train] done {(time.time() - t0) / 3600:.2f}h → {out / 'ckpt'}")
    best = next(iter(sorted((out / "ckpt").glob("checkpoint_best_total.pth"))), None) or next(iter(sorted((out / "ckpt").glob("checkpoint*.pth"))), None)
    if best is None:
        print("★체크포인트가 없다 — 학습 실패로 본다"); return 1
    problems = verify_checkpoint(best, a.res, a.seed)
    if problems:
        print("★체크포인트 검증 실패:", problems); return 4
    print(f"[verify] {best.name}: notes 기록·resolution {a.res}·seed {a.seed}·NaN 0 — 통과")
    # ── 하네스: 전/후 비교 ──
    if cfg.get("harness", "ppe") == "forklift":
        cmd = [sys.executable, str(_ROOT / "scripts" / "eval" / "forklift_compare_harness.py"), "--weights", str(best), "--label", a.label or out.name, "--res", str(a.res)]
        for k, v in (cfg.get("harness_args") or {}).items():
            cmd += [f"--{k.replace('_', '-')}", str(v)]
    else:
        cmd = [sys.executable, str(_ROOT / "scripts" / "eval" / "eval_v1_heldout.py"), "--weights", str(best), "--label", a.label or out.name]
        if a.dev74:
            cmd.append("--dev74")
    print("[harness]", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(_ROOT), env={**os.environ})


if __name__ == "__main__":
    sys.exit(main())
