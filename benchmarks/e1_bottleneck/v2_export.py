#!/usr/bin/env python3
"""[V2] 같은 RF-DETR 가중치를 ONNX 로 export — 가중치 교체가 아니라 '실행기'만 바꾼다.

기존 ppe_rfdetr_v1.onnx 와 같은 절차(benchmarks/onnx_cpu_bench.md §재현 방법):
    RFDETRNano(device='cpu', pretrain_weights=<pth>, resolution=384).export(format='onnx')
출력 파일명이 `rfdetr-nano.onnx` 로 고정이라 슬롯 이름으로 rename 한다.

★person 슬롯 주의: vision.yaml 에 `rfdetr_weights.person` 항목이 없다(COCO 사전학습을 그대로
  쓴다). 어댑터는 `Path(weights).with_suffix('.onnx')` 로 onnx 경로를 만들기 때문에
  (rfdetr_adapter.py:147) **weights 가 없는 person 은 현재 배선으로는 ONNX 가 절대 적용되지
  않는다.** 여기서는 측정 목적으로만 COCO 베이스를 export 한다(배선 변경은 하지 않음).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path

W = Path("D:/vigent_original/vigent-core/weights")

# (슬롯, 원본 pth, 출력 onnx) — None 이면 COCO 사전학습(person)
TARGETS: list[tuple[str, Path | None, Path]] = [
    ("fire_smoke", W / "fire_smoke_rfdetr_v1_e17.pth", W / "fire_smoke_rfdetr_v1_e17.onnx"),
    ("forklift",   W / "forklift_rfdetr_v1.pth",       W / "forklift_rfdetr_v1.onnx"),
    ("person",     None,                                W / "person_rfdetr_coco_MEASURE_ONLY.onnx"),
]


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    from rfdetr import RFDETRNano

    out: list[dict] = []
    for slot, pth, dst in TARGETS:
        if only and slot != only:
            continue
        if dst.exists():
            print(f"  [{slot}] 이미 존재 — 건너뜀: {dst.name}", flush=True)
            out.append({"slot": slot, "onnx": dst.name, "skipped": True,
                        "onnx_sha256": sha256(dst),
                        "src_pth_sha256": sha256(pth) if pth else None})
            continue
        kwargs: dict = {"device": "cpu", "resolution": 384}
        if pth is not None:
            if not pth.exists():
                print(f"  [{slot}] 원본 pth 없음 — 건너뜀: {pth}", flush=True)
                continue
            kwargs["pretrain_weights"] = str(pth)
        print(f"  [{slot}] export 시작 (원본: {pth.name if pth else 'COCO 사전학습'})", flush=True)
        m = RFDETRNano(**kwargs)
        # ★어댑터가 ONNX 메타데이터 rfdetr_notes 의 class_names 를 요구한다
        #   (rfdetr_adapter.py:82 — 없으면 로드 자체가 실패해 torch 로 폴백).
        #   기존 ppe_rfdetr_v1.onnx 와 같은 형식으로 맞춘다.
        import datetime
        import onnx as _onnx
        import onnxruntime as _ort
        import rfdetr as _rf
        import torch as _torch
        cnames = list(getattr(m, "class_names", None) or getattr(m.model, "class_names", []))
        if not cnames:
            print(f"  [{slot}] ★class_names 를 못 읽음 — 중단", flush=True)
            continue
        notes = {
            "class_names": cnames,
            "source_pth": (f"vigent-core/weights/{pth.name}" if pth else "COCO(rf-detr-nano)"),
            "source_pth_sha256": (sha256(pth) if pth else None),
            "resolution": 384,
            "opset_version": 17,
            "exported_with": {"rfdetr": getattr(_rf, "__version__", "?"),
                              "onnx": _onnx.__version__, "onnxruntime": _ort.__version__,
                              "torch": _torch.__version__},
            "export_date": datetime.date.today().isoformat(),
            "export_command": (f'RFDETRNano(pretrain_weights="vigent-core/weights/{pth.name}", '
                               'resolution=384, device="cpu").export(output_dir="<dir>", '
                               'format="onnx", opset_version=17, notes=<this>)') if pth else
                              ('RFDETRNano(resolution=384, device="cpu").export(...)  '
                               '# COCO 사전학습, 측정 전용'),
        }
        with tempfile.TemporaryDirectory() as td:
            m.export(output_dir=td, format="onnx", opset_version=17, verbose=False,
                     notes=json.dumps(notes, ensure_ascii=False))
            produced = list(Path(td).glob("*.onnx"))
            if not produced:
                print(f"  [{slot}] ★export 실패 — .onnx 산출물 없음", flush=True)
                continue
            src = max(produced, key=lambda p: p.stat().st_size)
            shutil.copy2(src, dst)
        rec = {"slot": slot, "onnx": dst.name, "skipped": False, "class_names": cnames,
               "onnx_bytes": dst.stat().st_size, "onnx_sha256": sha256(dst),
               "src_pth": pth.name if pth else "COCO(rf-detr-nano)",
               "src_pth_sha256": sha256(pth) if pth else None}
        out.append(rec)
        print(f"  [{slot}] 완료: {dst.name} {rec['onnx_bytes']:,}B sha={rec['onnx_sha256'][:16]}", flush=True)

    Path("v2_export.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
