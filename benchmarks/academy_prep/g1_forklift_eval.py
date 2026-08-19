# [G1] forklift_rfdetr_v1(F-7) 실측 — 저장소 유일 지게차 영상(632301)에서 conf 분포·오탐.
#   지게차는 화면 상단(y<0.35) 고정 위치에 실재 — 그 영역 검출 = 정탐 후보, 그 외 = 오탐.
import json, sys
from pathlib import Path
sys.path.insert(0, "D:/vigent_original/vigent-core")
import cv2
from agents.guard import JUNK_LABELS, LABEL_NORMALIZE
from detectors.rfdetr_adapter import RfdetrDetector

VID = Path("D:/vigent_original/runs/rfdetr/accident/KakaoTalk_20260807_000632301.mp4")
det = RfdetrDetector("D:/vigent_original/vigent-core/weights/forklift_rfdetr_v1.pth",
                     LABEL_NORMALIZE, JUNK_LABELS, resolution=384)
cap = cv2.VideoCapture(str(VID))
n = int(cap.get(7))
hits_true, hits_false = [], []
frames_checked = 0
for fi in range(0, n, 15):          # 2fps 상당 샘플링(30fps 영상)
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, img = cap.read()
    if not ok:
        continue
    frames_checked += 1
    # 운용 임계 0.002(F-7 병적 운용점) 그대로 — 나오는 전부를 본다
    for d in det.detect(img, conf=0.002):
        cy = (d["bbox"][1] + d["bbox"][3]) / 2
        (hits_true if cy < 0.35 else hits_false).append(round(d["conf"], 4))
cap.release()
res = {
    "video": VID.name, "frames": frames_checked,
    "true_region": {"n": len(hits_true),
                    "recall_frames_pct": round(100*len(hits_true)/frames_checked, 1),
                    "conf_max": max(hits_true) if hits_true else None,
                    "conf_p50": sorted(hits_true)[len(hits_true)//2] if hits_true else None},
    "false_region": {"n": len(hits_false),
                     "per_frame": round(len(hits_false)/frames_checked, 2),
                     "conf_max": max(hits_false) if hits_false else None},
}
print(json.dumps(res, ensure_ascii=False, indent=1))
Path("g1_rfdetr_632301.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
