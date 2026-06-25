"""train_safety.py — 현장 데이터로 모델 재학습(fine-tune)

플라이휠 4단계: 라벨링이 끝난 data/dataset/ (images + labels) 로 YOLO를 재학습한다.
그 현장 환경에 맞춰 정확도가 오른 새 모델(best.pt)이 나온다.

⚠ 권장: GPU. Mac(CPU)에서도 되지만 매우 느리다. 클라우드 GPU(Colab 등) 권장.
⚠ 라벨이 충분해야 효과(수백~수천 장 권장). 적으면 과적합.

사용:  python3 tools/train_safety.py
입력:  data/dataset/images/*.jpg + data/dataset/labels/*.txt + classes.txt
출력:  runs/detect/train*/weights/best.pt  → vigent-core/weights/ 로 교체하면 적용
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DS = ROOT / "data" / "dataset"
BASE = ROOT / "vigent-core" / "weights" / "yolo11m.pt"
EPOCHS = 50
IMGSZ = 960


def main():
    classes_file = DS / "classes.txt"
    if not (DS / "images").exists() or not classes_file.exists():
        print(f"[안내] 학습 데이터가 없습니다: {DS}\n  → 수집 → tools/prelabel.py → 라벨 교정 순서를 먼저 하세요.")
        return
    names = [c for c in classes_file.read_text(encoding="utf-8").splitlines() if c.strip()]
    # data.yaml 생성(이미지=라벨 같은 폴더 구조). 간단히 train=val(소규모 파일럿) — 정식은 분리 권장.
    data_yaml = DS / "data.yaml"
    data_yaml.write_text(
        f"path: {DS}\ntrain: images\nval: images\nnc: {len(names)}\n"
        f"names: [{', '.join(repr(n) for n in names)}]\n", encoding="utf-8")
    print(f"[시작] 재학습 — 베이스 {BASE.name}, epochs={EPOCHS}, imgsz={IMGSZ}")
    print("  (GPU 없으면 매우 느립니다. 진행 표시가 나오면 정상)")
    from ultralytics import YOLO
    model = YOLO(str(BASE))
    model.train(data=str(data_yaml), epochs=EPOCHS, imgsz=IMGSZ, patience=15)
    print("[완료] runs/detect/train*/weights/best.pt 생성.")
    print("  적용: best.pt 를 vigent-core/weights/ 로 복사하고 vision.yaml 의 person 모델 경로를 교체.")


if __name__ == "__main__":
    main()
