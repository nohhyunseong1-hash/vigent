#!/usr/bin/env python3
"""학습 완료된 best.pt를 검증셋으로 평가 — 전체 + 클래스별 지표 출력.
실행: python3 tools/ppe_eval.py
"""
import os, sys

RUN = os.path.expanduser("~/Desktop/VIGENT/runs/ppe_train/merged_v1")
BEST = os.path.join(RUN, "weights", "best.pt")
DATA = os.path.expanduser("~/Desktop/VIGENT/data/datasets/ppe_merged/data.yaml")

if not os.path.exists(BEST):
    print("ERROR: best.pt 없음 ->", BEST)
    sys.exit(1)

try:
    from ultralytics import YOLO
except Exception as e:
    print("ERROR: ultralytics import 실패:", e)
    sys.exit(1)

model = YOLO(BEST)
m = model.val(data=DATA, split="val", verbose=False)

names = model.names  # {idx: name}
print("=== 전체 ===")
print("mAP50      %.4f" % m.box.map50)
print("mAP50-95   %.4f" % m.box.map)
print("precision  %.4f" % m.box.mp)
print("recall     %.4f" % m.box.mr)
print()
print("=== 클래스별 (mAP50 / mAP50-95 / P / R) ===")
# m.box.maps: per-class mAP50-95 ; ap_class_index maps row->class idx
try:
    for i, c in enumerate(m.box.ap_class_index):
        p, r, ap50, ap = m.box.class_result(i)
        print("%-18s  %.3f / %.3f / %.3f / %.3f" % (names[c], ap50, ap, p, r))
except Exception as e:
    print("(클래스별 출력 생략:", e, ")")
