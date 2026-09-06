"""prelabel.py — 수집한 프레임을 현재 모델로 '자동 사전 라벨링'(반자동 라벨링)

플라이휠 2→3단계: data/dataset/images/ 의 이미지에 현재 YOLO 모델이 예측한 박스를
YOLO 라벨 형식(.txt)으로 저장한다. 사람이 라벨링 도구(예: labelImg, Roboflow)에서
이 사전라벨을 '교정'만 하면 되므로 라벨링 시간을 크게 줄인다.

사용:  python training/prelabel.py   (2026-09-06 감사: tools/ → training/ 이동, ROOT 깊이 동일)
출력:  data/dataset/labels/<같은이름>.txt  (class cx cy w h, 0~1 정규화)
       data/dataset/classes.txt
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "data" / "dataset" / "images"
LBL = ROOT / "data" / "dataset" / "labels"
MODEL = ROOT / "vigent-core" / "weights" / "yolo11m.pt"


def main():
    from ultralytics import YOLO
    if not IMG.exists():
        print(f"[안내] 수집 폴더가 없습니다: {IMG}\n  → 먼저 데이터 수집 모드로 워커를 돌려 프레임을 모으세요.")
        return
    imgs = sorted([p for p in IMG.glob("*.jpg")])
    if not imgs:
        print("[안내] 수집된 이미지가 없습니다. 데이터 수집 모드를 켜고 며칠 돌리세요.")
        return
    LBL.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(MODEL))
    names = model.names
    (ROOT / "data" / "dataset" / "classes.txt").write_text(
        "\n".join(names[i] for i in sorted(names)), encoding="utf-8")
    n = 0
    for p in imgs:
        r = model.predict(str(p), verbose=False, conf=0.35, device="cpu")[0]
        lines = []
        for b in r.boxes:
            cls = int(b.cls[0])
            x, y, w, h = (float(v) for v in b.xywhn[0])     # 정규화 cx,cy,w,h
            lines.append(f"{cls} {x:.6f} {y:.6f} {w:.6f} {h:.6f}")
        (LBL / (p.stem + ".txt")).write_text("\n".join(lines), encoding="utf-8")
        n += 1
    print(f"[완료] {n}장 사전라벨 생성 → {LBL}")
    print("다음: labelImg/Roboflow 등에서 이 라벨을 '교정'한 뒤 training/train_safety.py 로 재학습하세요.")


if __name__ == "__main__":
    main()
