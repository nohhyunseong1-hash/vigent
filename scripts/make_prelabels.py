#!/usr/bin/env python3
"""★[폐기, 2026-09-28 CODE_AUDIT C-1] 2026-08-29 라벨링 1회용 도구 — 현재는 `scripts/data/field_prelabel.py`(CVAT 1.1 + YOLO, 표준 5클래스)가
  대체한다. 이 파일의 클래스 순서(forklift 가 2번)는 정본(labels.STD5)과 다르므로 **새 라벨 작업에 쓰지 말 것**. 참고용으로만 남긴다.

[라벨링] 현재 검출(dets.jsonl)을 **밑그림**으로 바꿔 라벨링 도구에 넣는다.

★왜 밑그림을 쓰나
  빈 화면에 박스를 처음부터 그리는 것보다, 이미 있는 박스를 **고치는 쪽**이 훨씬 빠르다.
  다만 밑그림은 **틀린 것을 그대로 믿게 만드는 위험**도 있다. 그래서
  · 밑그림은 회색 계열 한 가지로 넣어 "확정 라벨"처럼 보이지 않게 하고,
  · 검출이 없는 프레임도 **빠뜨리지 않고** 이미지를 뽑아 목록에 남긴다.

출력(LabelMe 형식 — `pip install labelme` 로 바로 열린다. CVAT 도 이 형식을 읽는다):
  <out>/<장면>/f####.jpg        라벨링할 이미지
  <out>/<장면>/f####.json       밑그림(LabelMe shapes)
  <out>/밑그림없음.md            검출이 하나도 없어 처음부터 그려야 하는 프레임 목록
  <out>/작업목록.md              장면·프레임·밑그림 박스 수

사용:
  python scripts/make_prelabels.py --video <mp4> --dets <dets.jsonl> --scene 01_x \\
         --out D:/vigent_field/labeling_20260829 [--every 4] [--fps 2]

★주의: `--video` 에 **박스가 그려진 overlay.mp4 를 넣지 마라.** 라벨러가 그 박스를 보고
  따라 그리게 되어 정답지가 오염된다. 반드시 **원본(주석 없는) 영상**을 넣는다.
  이 스크립트는 그것을 자동으로 판별할 수 없다 — 넣는 사람이 확인해야 한다.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

LABELS = ["person", "forklift", "Hardhat", "NO-Hardhat",
          "Safety-Vest", "NO-Safety-Vest", "Mask", "NO-Mask"]


def _imwrite(path: Path, img, q: int = 92) -> None:
    """★규칙 11 — 쓴 뒤 실제로 있는지 확인한다(cv2.imwrite 는 한글 경로에서 조용히 실패한다)."""
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise RuntimeError(f"인코딩 실패: {path}")
    path.write_bytes(buf.tobytes())
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"파일이 쓰이지 않았다: {path}")


def main() -> int:
    print("★[폐기] make_prelabels.py 는 2026-08-29 1회용 도구입니다 — 새 라벨 작업은 scripts/data/field_prelabel.py 를 쓰세요(클래스 순서가 다릅니다).", file=sys.stderr)
    import cv2

    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, help="★주석 없는 원본 영상")
    ap.add_argument("--dets", required=True)
    ap.add_argument("--scene", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=2.0, help="dets 를 만든 판정 주기")
    ap.add_argument("--every", type=int, default=1,
                    help="dets 행을 N개마다 1개만 뽑는다(2fps 원본에서 4면 0.5fps)")
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.dets).read_text(encoding="utf-8").splitlines()
            if x.strip()]
    out = Path(args.out) / args.scene
    out.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    step = max(1, round(src_fps / args.fps))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    made = 0
    blank: list[str] = []
    counts: list[int] = []
    for i, r in enumerate(rows):
        if i % args.every:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ok, frame = cap.read()
        if not ok:
            print(f"  ⚠ 프레임 {i * step} 을 못 읽었다 — 건너뛴다")
            continue
        name = f"f{i:04d}"
        _imwrite(out / f"{name}.jpg", frame)

        shapes = []
        for d in r["detections"]:
            if d["class"] not in LABELS:
                continue
            b = d["bbox"]
            shapes.append({
                "label": d["class"],
                "points": [[round(b[0] * w, 1), round(b[1] * h, 1)],
                           [round(b[2] * w, 1), round(b[3] * h, 1)]],
                "group_id": None, "shape_type": "rectangle", "flags": {},
                # ★밑그림임을 남긴다 — 사람이 고친 것과 구분되게.
                "description": f"밑그림 conf={d['score']:.2f}",
            })
        (out / f"{name}.json").write_text(json.dumps({
            "version": "5.0.1", "flags": {}, "shapes": shapes,
            "imagePath": f"{name}.jpg", "imageData": None,
            "imageHeight": h, "imageWidth": w,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        counts.append(len(shapes))
        if not shapes:
            blank.append(f"{args.scene}/{name}")
        made += 1
    cap.release()

    # ★규칙 11 — 메모리가 아니라 디스크를 센다
    on_disk = len(list(out.glob("f*.jpg")))
    if on_disk != made:
        print(f"  ❌ 쓰기 누락: 만든 {made} vs 디스크 {on_disk}")
        return 1

    root = Path(args.out)
    with (root / "작업목록.md").open("a", encoding="utf-8") as f:
        f.write(f"| {args.scene} | {made} | {sum(counts)} | "
                f"{sum(counts) / max(made, 1):.1f} | {len(blank)} |\n")
    if blank:
        with (root / "밑그림없음.md").open("a", encoding="utf-8") as f:
            f.write("\n".join(f"- {x}" for x in blank) + "\n")

    print(f"  ✅ {args.scene}: {on_disk}장(디스크 확인) · 밑그림 박스 {sum(counts)}개 · "
          f"밑그림 없는 프레임 {len(blank)}개 → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
