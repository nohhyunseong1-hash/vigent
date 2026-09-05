# [G1-보조] COCO 사전학습(person 슬롯 백본)이 지게차를 truck/car 로 잡는지 — 대용 신호 가능성.
import json, sys
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]   # [C5] 절대경로 제거
sys.path.insert(0, str(_REPO / "vigent-core"))
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)
import cv2
from agents.guard import JUNK_LABELS, LABEL_NORMALIZE
from detectors.rfdetr_adapter import RfdetrDetector

VID = media("runs/rfdetr/accident/KakaoTalk_20260807_000632301.mp4")
det = RfdetrDetector("", LABEL_NORMALIZE, JUNK_LABELS, resolution=384)   # COCO 사전학습
cap = cv2.VideoCapture(str(VID)); n = int(cap.get(7))
VEH = {"truck", "car", "bus", "train"}
true_hits, false_hits = [], []
frames = 0
for fi in range(0, n, 15):
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, img = cap.read()
    if not ok: continue
    frames += 1
    for d in det.detect(img, conf=0.25):
        if d["label"] not in VEH: continue
        cy = (d["bbox"][1] + d["bbox"][3]) / 2
        (true_hits if cy < 0.35 else false_hits).append((d["label"], round(d["conf"], 3)))
cap.release()
from collections import Counter
res = {"frames": frames,
       "true_region_hits": len(true_hits),
       "true_recall_pct": round(100*len(true_hits)/frames, 1),
       "true_labels": dict(Counter(l for l, _ in true_hits)),
       "true_conf_max": max((c for _, c in true_hits), default=None),
       "true_conf_p50": sorted(c for _, c in true_hits)[len(true_hits)//2] if true_hits else None,
       "false_region_hits": len(false_hits),
       "false_labels": dict(Counter(l for l, _ in false_hits))}
print(json.dumps(res, ensure_ascii=False, indent=1))
Path("g1_coco_632301.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
