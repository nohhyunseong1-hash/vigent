#!/usr/bin/env python3
"""[검증] 특정 라벨이 검출된 **모든 프레임**을 스틸로 뽑아 육안 전수 확인에 쓴다.

★왜 필요한가
  "NO-Hardhat 이 34프레임 떴다"는 것은 **시스템이 그렇게 봤다**는 뜻일 뿐이다.
  그 34개가 실제로 안전모 미착용 순간인지는 **사람이 눈으로 세야** 안다.
  규칙(ppe.required)을 바꾸기 전에 이 확인을 먼저 한다 — 근거 없이 규칙을 바꾸면
  무엇이 좋아졌는지 말할 수 없다.

산출:
  · <라벨>_<장면>/f###_t##.#s.jpg   프레임마다 1장(해당 라벨 박스만 강조)
  · <라벨>_<장면>/전체프레임/...     같은 순간의 화면 전체(맥락 확인용)
  · <라벨>_<장면>/대조표.md          idx·시각·confidence + **사람이 채울 빈 칸**
  · <라벨>_<장면>/모아보기.jpg        한 장에 모은 판(전수 훑기용)

사용:
  python scripts/extract_rule_frames.py --video <mp4> --dets <dets.jsonl> \\
         --label NO-Hardhat --out <폴더> --fps 2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CROP_H = 420          # 잘라낸 조각의 세로 크기(픽셀)
TILE_W = 300          # 타일 가로(모아보기 격자를 고르게 하려고 고정한다)
PAD = 0.9             # 박스 대비 여유(머리 위·몸통까지 보이게)


def _imwrite(path, img, q: int = 90) -> None:
    """★한글 경로에 쓴다.

    `cv2.imwrite` 는 경로에 한글이 있으면 **예외 없이 False 를 돌려주고 조용히 실패**한다
    (2026-08-29 실측: 34장을 썼다고 출력했는데 파일이 0개였다).
    그래서 메모리에서 인코딩한 뒤 파이썬으로 쓰고, **쓴 결과를 확인**한다.
    """
    import cv2
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    if not ok:
        raise RuntimeError(f"JPEG 인코딩 실패: {path}")
    path.write_bytes(buf.tobytes())
    if not path.exists() or path.stat().st_size == 0:
        raise RuntimeError(f"파일이 쓰이지 않았다: {path}")


def main() -> int:
    import cv2
    import numpy as np
    import privacy

    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--dets", required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--fps", type=float, default=2.0, help="dets 를 만들 때 쓴 판정 주기")
    ap.add_argument("--cols", type=int, default=6)
    args = ap.parse_args()

    rows = [json.loads(x) for x in Path(args.dets).read_text(encoding="utf-8").splitlines()
            if x.strip()]
    want = [(i, r) for i, r in enumerate(rows)
            if any(d["class"] == args.label for d in r["detections"])]
    if not want:
        print(f"❌ {args.label} 이 검출된 프레임이 없다")
        return 1

    out = Path(args.out)
    (out / "전체프레임").mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(args.video)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    step = max(1, round(src_fps / args.fps))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    tiles: list = []
    table = ["| # | 시각(초) | conf | 사람박스 높이 | ★실제 미착용인가 | ★아니면 무엇으로 오인했나 |",
             "|---|---|---|---|---|---|"]
    for n, (i, r) in enumerate(want, 1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i * step)
        ok, frame = cap.read()
        if not ok:
            print(f"  ⚠ 프레임 {i * step} 을 못 읽었다 — 건너뛴다")
            continue
        boxes = [d for d in r["detections"] if d["class"] == args.label]
        pboxes = [d for d in r["detections"] if d["class"] == "person"]
        conf = max(d["score"] for d in boxes)
        ph = max((d["bbox"][3] - d["bbox"][1] for d in pboxes), default=0.0)

        # ★얼굴 비식별화는 그대로 적용한다(개인정보). 안전모는 머리 위라 모자이크 위로 보인다.
        privacy._begin_call()
        px = [[d["bbox"][0] * w, d["bbox"][1] * h, d["bbox"][2] * w, d["bbox"][3] * h]
              for d in pboxes]
        shown = privacy.anonymize_faces(frame.copy(), px)

        for d in boxes:
            x1, y1, x2, y2 = (int(d["bbox"][0] * w), int(d["bbox"][1] * h),
                              int(d["bbox"][2] * w), int(d["bbox"][3] * h))
            cv2.rectangle(shown, (x1, y1), (x2, y2), (0, 0, 255), 2)
        for d in pboxes:
            x1, y1, x2, y2 = (int(d["bbox"][0] * w), int(d["bbox"][1] * h),
                              int(d["bbox"][2] * w), int(d["bbox"][3] * h))
            cv2.rectangle(shown, (x1, y1), (x2, y2), (0, 200, 0), 1)
        _imwrite(out / "전체프레임" / f"f{n:03d}.jpg", shown, 88)

        # 사람 + 라벨 박스를 아우르는 영역을 여유 있게 잘라낸다
        allb = [d["bbox"] for d in boxes] + [d["bbox"] for d in pboxes]
        bx1 = min(b[0] for b in allb) * w
        by1 = min(b[1] for b in allb) * h
        bx2 = max(b[2] for b in allb) * w
        by2 = max(b[3] for b in allb) * h
        cw, ch = bx2 - bx1, by2 - by1
        mx, my = cw * PAD, ch * PAD * 0.25
        x1 = max(0, int(bx1 - mx)); x2 = min(w, int(bx2 + mx))
        y1 = max(0, int(by1 - my)); y2 = min(h, int(by2 + my))
        crop = shown[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # ★타일 크기를 고정한다 — 비율을 유지해 맞춘 뒤 어두운 판 가운데에 놓는다.
        #   (고정하지 않으면 사람이 아주 작게 잡힌 프레임이 통째로 확대돼 폭이 제각각이 되고,
        #    모아보기 판이 검은 여백 투성이가 돼 전수 훑기가 불가능해진다 — 2026-08-29 실측)
        sc = min(CROP_H / crop.shape[0], TILE_W / crop.shape[1])
        crop = cv2.resize(crop, (max(1, int(crop.shape[1] * sc)),
                                 max(1, int(crop.shape[0] * sc))))
        canvas = np.full((CROP_H, TILE_W, 3), 30, np.uint8)
        oy = (CROP_H - crop.shape[0]) // 2
        ox = (TILE_W - crop.shape[1]) // 2
        canvas[oy:oy + crop.shape[0], ox:ox + crop.shape[1]] = crop
        crop = canvas
        bar = np.full((26, crop.shape[1], 3), 30, np.uint8)
        cv2.putText(bar, f"#{n}  t={r['video_t']:.1f}s  {args.label} {conf:.2f}",
                    (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        tile = np.vstack([bar, crop])
        _imwrite(out / f"f{n:03d}_t{r['video_t']:.1f}s.jpg", tile)
        tiles.append(tile)
        table.append(f"| {n} | {r['video_t']:.1f} | {conf:.2f} | {ph:.3f} |  |  |")
    cap.release()

    # 모아보기 판 — 타일 폭을 맞춰 격자로 붙인다
    if tiles:
        padded = tiles                       # 타일 크기가 이미 같다
        cols = args.cols
        grid = []
        for k in range(0, len(padded), cols):
            row = padded[k:k + cols]
            while len(row) < cols:
                row.append(np.full_like(padded[0], 30))
            grid.append(np.hstack(row))
        _imwrite(out / "모아보기.jpg", np.vstack(grid), 88)

    table += ["", f"- 총 {len(tiles)}프레임 · 라벨 `{args.label}` · 원본 `{Path(args.video).name}`",
              "- 빨간 박스 = 해당 라벨 · 초록 박스 = person",
              "- ★오른쪽 두 칸은 **사람이 눈으로 채우는 칸**이다. 시스템이 채우면 검증이 아니다.",
              "- 얼굴은 비식별화(모자이크)돼 있다. 안전모는 머리 위라 모자이크 위로 보인다."]
    (out / "대조표.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    made = len(list(out.glob("f*.jpg")))
    if made != len(tiles):
        print(f"  ❌ 쓰기 누락: 만든 {len(tiles)} vs 디스크 {made}")
        return 1
    print(f"  ✅ {args.label}: {made}프레임(디스크 확인) → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
