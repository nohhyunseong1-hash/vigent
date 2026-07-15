"""rf-detr(Apache-2.0) 최소 동작 — 이미지 1장에서 사람 탐지 → 박스 그려 저장.

AGPL(ultralytics) 대체용 permissive 탐지기 검증. 기존 코드는 건드리지 않는 독립 스크립트.
사용: python3 vigent-core/ml/rfdetr_detect.py <이미지경로>
출력: runs/rfdetr/<파일명>_out.jpg
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from PIL import Image
from rfdetr import RFDETRNano
from rfdetr.util.coco_classes import COCO_CLASSES

ROOT = Path(__file__).resolve().parent.parent.parent


def main(img_path: str) -> None:
    out_dir = ROOT / "runs" / "rfdetr"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 모델 로드(Nano — 허용 범위, 최초 1회 가중치 다운로드)
    #    Apple GPU(MPS) 사용 + 추론 최적화 → CPU 대비 빠름
    import torch
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    t0 = time.time()
    model = RFDETRNano(device=device)
    try:
        model.optimize_for_inference()      # 그래프 최적화(가능하면)
    except Exception:
        pass
    print(f"[rf-detr] 모델 로드 {time.time()-t0:.1f}s · device={device}")

    # 2) 추론
    image = Image.open(img_path).convert("RGB")
    t1 = time.time()
    det = model.predict(image, threshold=0.4)
    infer_ms = (time.time() - t1) * 1000
    print(f"[rf-detr] 추론 {infer_ms:.0f}ms · 전체 탐지 {len(det)}개")

    # 3) 사람만 필터
    names = [COCO_CLASSES[c] for c in det.class_id]
    person_idx = [i for i, n in enumerate(names) if n == "person"]
    print(f"[rf-detr] 사람(person) {len(person_idx)}명 탐지: "
          f"{[round(float(det.confidence[i]), 2) for i in person_idx]}")

    # 4) 박스 그려 저장(supervision)
    img = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
    labels = [f"{names[i]} {det.confidence[i]:.2f}" for i in range(len(det))]
    img = sv.BoxAnnotator(thickness=2).annotate(img.copy(), det)
    img = sv.LabelAnnotator().annotate(img, det, labels)
    out = out_dir / f"{Path(img_path).stem}_out.jpg"
    cv2.imwrite(str(out), img)
    print(f"✅ 저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python3 vigent-core/ml/rfdetr_detect.py <이미지경로>")
        sys.exit(1)
    main(sys.argv[1])
