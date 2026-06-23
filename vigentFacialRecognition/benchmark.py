"""benchmark.py — 인식률(정확도) · 속도(지연) 측정

요건 검증:
  - 속도: 얼굴당 식별 < 1초 (보통 CPU에서 10~50ms).
  - 정확도: ≥ 95% (LFW류 라벨 데이터에서 genuine/impostor 분리로 측정).

사용법:
  # 1) 속도만 빠르게(라벨 데이터 불필요) — 한 장의 얼굴 사진을 N회 반복 측정
  python -m vigentFacialRecognition.benchmark --image face.jpg --runs 50

  # 2) 정확도 + 속도 — 사람별 하위폴더 구조(LFW 스타일):
  #    data_dir/홍길동/1.jpg, 2.jpg ...  data_dir/김철수/1.jpg ...
  python -m vigentFacialRecognition.benchmark --data <폴더> --threshold 0.40
"""
from __future__ import annotations

import argparse
import time
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np

from . import config
from .engine import get_engine


def _embed_file(eng, path) -> np.ndarray | None:
    img = cv2.imread(str(path))
    if img is None:
        return None
    faces = eng.detect(img)
    if not faces:
        return None
    f = max(faces, key=lambda x: x.bbox[2] * x.bbox[3])
    return eng.embed(img, f)


def speed_test(image: str, runs: int) -> None:
    eng = get_engine()
    img = cv2.imread(image)
    if img is None:
        raise SystemExit(f"이미지를 열 수 없음: {image}")
    # 워밍업
    eng.detect_and_embed(img)
    ts = []
    for _ in range(runs):
        t0 = time.perf_counter()
        eng.detect_and_embed(img)
        ts.append((time.perf_counter() - t0) * 1000)
    ts.sort()
    print("── 속도(검출+임베딩, 1프레임) ──")
    print(f"  평균 {np.mean(ts):.1f}ms · p50 {ts[len(ts)//2]:.1f}ms · "
          f"p95 {ts[int(len(ts)*0.95)]:.1f}ms · 최대 {ts[-1]:.1f}ms")
    print(f"  ≈ {1000/np.mean(ts):.0f} FPS")
    print(f"  1초 요건: {'통과 ✅' if ts[-1] < 1000 else '실패 ❌'}")


def accuracy_test(data_dir: str, threshold: float) -> None:
    eng = get_engine()
    root = Path(data_dir)
    embs: dict[str, list[np.ndarray]] = {}
    t0 = time.perf_counter()
    n_imgs = 0
    for person_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        vs = []
        for img_path in sorted(person_dir.glob("*")):
            if img_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp"}:
                continue
            v = _embed_file(eng, img_path)
            n_imgs += 1
            if v is not None:
                vs.append(v)
        if len(vs) >= 1:
            embs[person_dir.name] = vs
    elapsed = (time.perf_counter() - t0)

    # genuine(같은 사람 쌍) / impostor(다른 사람 쌍) 코사인 분포
    genuine, impostor = [], []
    people = list(embs)
    for name in people:
        for a, b in combinations(embs[name], 2):
            genuine.append(float(np.dot(a, b)))
    for i in range(len(people)):
        for j in range(i + 1, len(people)):
            for a in embs[people[i]][:3]:
                for b in embs[people[j]][:3]:
                    impostor.append(float(np.dot(a, b)))

    if not genuine or not impostor:
        print("genuine/impostor 쌍이 부족합니다. 사람당 2장 이상, 2인 이상 필요.")
        return

    g, im = np.array(genuine), np.array(impostor)
    tar = float((g >= threshold).mean())          # 본인 정확 수락률
    far = float((im >= threshold).mean())          # 타인 오수락률
    # 임계값 스윕으로 최적 정확도(균형) 탐색
    best_th, best_acc = threshold, 0.0
    for th in np.linspace(0.2, 0.6, 41):
        acc = ((g >= th).sum() + (im < th).sum()) / (len(g) + len(im))
        if acc > best_acc:
            best_acc, best_th = acc, th
    acc_at_th = ((g >= threshold).sum() + (im < threshold).sum()) / (len(g) + len(im))

    print("── 정확도 ──")
    print(f"  이미지 {n_imgs}장 · 사람 {len(people)}명 · 임베딩 {elapsed:.1f}s")
    print(f"  genuine 쌍 {len(g)} · impostor 쌍 {len(im)}")
    print(f"  임계값 {threshold:.2f} → 정확도 {acc_at_th*100:.2f}% "
          f"(본인수락 TAR {tar*100:.1f}% · 타인오수락 FAR {far*100:.2f}%)")
    print(f"  최적 임계값 {best_th:.3f} → 정확도 {best_acc*100:.2f}%")
    print(f"  95% 요건: {'통과 ✅' if best_acc >= 0.95 else '데이터/임계값 점검 필요'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--image", help="속도 측정용 얼굴 사진 1장")
    ap.add_argument("--runs", type=int, default=50)
    ap.add_argument("--data", help="정확도 측정용 폴더(사람별 하위폴더)")
    ap.add_argument("--threshold", type=float, default=config.COSINE_THRESHOLD)
    args = ap.parse_args()

    if not config.model_files_present():
        print("모델이 없습니다. `python -m vigentFacialRecognition.download_models` 먼저 실행.")
        return 1
    if args.image:
        speed_test(args.image, args.runs)
    if args.data:
        accuracy_test(args.data, args.threshold)
    if not args.image and not args.data:
        print("사용법: --image face.jpg [--runs N]  또는  --data <폴더> [--threshold 0.40]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
