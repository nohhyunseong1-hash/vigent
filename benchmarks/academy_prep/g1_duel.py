# [G1 재개] 대결: forklift_boda_ax(YOLO) vs COCO 대용(truck/car/bus) — 학원 유사 영상.
#
# ★판정 기준(측정 전 선언 — audit/academy_g1g2 에 기록될 기준):
#   근접 경보(proximity)는 "지게차가 검출된 프레임"에서만 평가된다 — 놓침 = 경보 미발화.
#   C1) 주 지게차 검출 프레임 재현율 >= 80%  (2fps 에서 평균 재검출 지연 <= 0.6s)
#   C2) 최장 연속 미검출 <= 2.0s             (경보 공백의 최대 허용 시간창)
#   C3) 오탐 프레임 비율 <= 10%              (주 지게차 외 박스 — 배경 실중장비는 별도 집계)
#   위 3개를 동시에 만족하는 conf 운용점이 존재해야 채택.
#
# 정답(육안, 컨택트시트 40장 전수): 주 지게차(CLARK GTS30H)가 0~160s 전 구간 화면 내 실재.
# 판정 단순화: 프레임당 "가장 큰 vehicle 박스" = 주 지게차 후보(주 지게차가 항상 최대 크기 —
#   배경 장비는 원거리). 스팟 체크 프레임으로 이 가정 검증(비교 프레임 저장).
import json, sys
from pathlib import Path
_REPO = Path(__file__).resolve().parents[2]   # [C5] 절대경로 제거
sys.path.insert(0, str(_REPO / "vigent-core"))
from data_paths import media  # noqa: E402  [C5] 미디어는 저장소 밖(VIGENT_DATA_DIR)
import cv2
from agents.guard import JUNK_LABELS, LABEL_NORMALIZE
from detectors.rfdetr_adapter import RfdetrDetector
from detectors.yolo_adapter import YoloDetector

VID = "D:/vigent_tmp/forklift_test/forklift_test.mp4"
LOW_CONF = 0.10          # 낮게 훑고 운용점은 사후 스윕(추론 1회, 임계는 후처리)
COCO_VEH = {"truck", "car", "bus", "train"}

def collect(det, veh_labels, tag):
    cap = cv2.VideoCapture(VID)
    n = int(cap.get(7)); fps = cap.get(5)
    rows = []
    for fi in range(0, n, 12):                       # 24fps → 2fps 샘플
        cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
        ok, img = cap.read()
        if not ok: continue
        dets = det.detect(img, conf=LOW_CONF)
        vehs = [{"l": d["label"], "c": round(float(d["conf"]), 3),
                 "b": [round(v, 4) for v in d["bbox"]],
                 "area": round((d["bbox"][2]-d["bbox"][0])*(d["bbox"][3]-d["bbox"][1]), 4)}
                for d in dets if d["label"].lower() in veh_labels or d["label"] in veh_labels]
        rows.append({"t": round(fi/fps, 2), "v": vehs})
    cap.release()
    Path(f"g1_duel_{tag}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return rows

def judge(rows, conf_op):
    """운용 임계 conf_op 에서 C1~C3 판정."""
    hit = []; fp_frames = 0; confs = []
    for r in rows:
        vs = [v for v in r["v"] if v["c"] >= conf_op]
        if vs:
            main = max(vs, key=lambda v: v["area"])
            hit.append(True); confs.append(main["c"])
            if len(vs) > 1: fp_frames += 1
        else:
            hit.append(False)
    n = len(rows)
    recall = 100*sum(hit)/n
    # 최장 연속 미검출(초)
    worst = cur = 0
    for h in hit:
        cur = 0 if h else cur+1
        worst = max(worst, cur)
    return {"conf_op": conf_op, "frames": n, "recall_pct": round(recall,1),
            "worst_gap_s": round(worst*0.5, 1),
            "fp_frame_pct": round(100*fp_frames/n, 1),
            "conf_mean": round(sum(confs)/len(confs), 3) if confs else None}

def sweep(rows, tag):
    print(f"\n[{tag}] 운용점 스윕 (기준: 재현율>=80 · 최장공백<=2.0s · 오탐프레임<=10%)")
    best = None
    for c in (0.10,0.15,0.20,0.25,0.30,0.35,0.40,0.50,0.60,0.70):
        j = judge(rows, c)
        ok = j["recall_pct"]>=80 and j["worst_gap_s"]<=2.0 and j["fp_frame_pct"]<=10
        print(f"  conf>={c:.2f}: 재현율 {j['recall_pct']:5.1f}% · 최장공백 {j['worst_gap_s']:4.1f}s · "
              f"다중박스 {j['fp_frame_pct']:4.1f}% · conf평균 {j['conf_mean']} {'✅' if ok else ''}")
        if ok and (best is None or c > best["conf_op"]):
            best = j
    return best

if __name__ == "__main__":
    which = sys.argv[1]
    if which == "boda":
        det = YoloDetector(str(_REPO / "vigent-core/weights/forklift_boda_ax.pt"),
                           "cuda", 384, LABEL_NORMALIZE, JUNK_LABELS)
        rows = collect(det, {"forklift"}, "boda")
        b = sweep(rows, "boda_ax(YOLO)")
    else:
        det = RfdetrDetector("", LABEL_NORMALIZE, JUNK_LABELS, resolution=384)
        rows = collect(det, COCO_VEH, "coco")
        b = sweep(rows, "COCO 대용(truck/car/bus/train)")
    print("최적 운용점:", b)
