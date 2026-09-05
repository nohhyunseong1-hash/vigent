# [G5] 지게차 운전자 처리 실측 — 운영 person 슬롯(RF-DETR COCO)이 탑승 운전자를 잡는가,
#   잡히면 boda 지게차 박스에 얼마나 포함되는가(제외 로직 설계 근거).
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
PERSON_CONF = 0.40          # 운영 임계(tuning detect.conf.person)

def containment(p, f):
    """person 박스가 forklift 박스에 포함된 비율 = 교집합 / person 면적."""
    ix = max(0.0, min(p[2], f[2]) - max(p[0], f[0]))
    iy = max(0.0, min(p[3], f[3]) - max(p[1], f[1]))
    pa = max(1e-9, (p[2]-p[0]) * (p[3]-p[1]))
    return ix * iy / pa

pdet = RfdetrDetector("", LABEL_NORMALIZE, JUNK_LABELS, resolution=384)
fdet = YoloDetector(str(_REPO / "vigent-core/weights/forklift_boda_ax.pt"),
                    "cuda", 384, LABEL_NORMALIZE, JUNK_LABELS)
cap = cv2.VideoCapture(VID)
n = int(cap.get(7)); fps = cap.get(5)
rows = []
for fi in range(0, n, 12):
    cap.set(cv2.CAP_PROP_POS_FRAMES, fi)
    ok, img = cap.read()
    if not ok: continue
    persons = [{"c": round(float(d["conf"]),3), "b": [round(v,4) for v in d["bbox"]]}
               for d in pdet.detect(img, conf=PERSON_CONF) if d["label"] == "person"]
    forks = [{"c": round(float(d["conf"]),3), "b": [round(v,4) for v in d["bbox"]]}
             for d in fdet.detect(img, conf=0.50) if d["label"].lower() == "forklift"]
    main_f = max(forks, key=lambda v: (v["b"][2]-v["b"][0])*(v["b"][3]-v["b"][1])) if forks else None
    for p in persons:
        p["cont"] = round(containment(p["b"], main_f["b"]), 3) if main_f else None
    rows.append({"t": round(fi/fps,2), "persons": persons, "fork": main_f})
cap.release()
Path("g5_driver.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")

# 요약
n_frames = len(rows)
frames_with_fork = [r for r in rows if r["fork"]]
onboard = []          # cont >= 0.6 person 이 있는 프레임
partial = []
for r in frames_with_fork:
    cs = [p["cont"] for p in r["persons"] if p["cont"] is not None]
    if any(c >= 0.6 for c in cs): onboard.append(r)
    elif any(0.2 <= c < 0.6 for c in cs): partial.append(r)
det_rate = 100*len(onboard)/len(frames_with_fork) if frames_with_fork else 0
confs = [p["c"] for r in onboard for p in r["persons"] if (p["cont"] or 0) >= 0.6]
print(f"프레임 {n_frames} · 지게차 검출 {len(frames_with_fork)}")
print(f"★탑승 운전자(person, 포함률>=0.6) 검출 프레임: {len(onboard)} ({det_rate:.1f}%)")
print(f"  운전자 conf: 평균 {sum(confs)/len(confs):.3f} · 최소 {min(confs):.2f} · 최대 {max(confs):.2f}" if confs else "  없음")
print(f"부분 포함(0.2~0.6) 프레임: {len(partial)}")
# 포함률 분포(제외 임계 설계용)
allc = sorted(p["cont"] for r in frames_with_fork for p in r["persons"] if p["cont"] is not None)
if allc:
    import statistics
    print("포함률 분포:", {q: round(allc[int(len(allc)*q/100)],2) for q in (5,25,50,75,95)})
