#!/usr/bin/env python3
"""scripts/eval/measure_gt_quality.py — 사고영상 정답지의 **화질 조건**을 잰다(Q-2).

배경(2026-09-22): 검수자가 "화질이 낮아 같은 사람인지 판단이 어렵다" 고 했다.
  정답지의 화질 조건은 검출기 재현율 71.3% 가 **어떤 조건의 값인지**를 결정한다.
  눈대중이 아니라 재서 README 의 '알려진 한계' 에 싣는다(규칙 9·11).

재는 것:
  1) 영상별 해상도 · fps · 코덱 · 비트레이트(파일 크기 ÷ 길이)
  2) person 라벨 박스의 **픽셀 높이** 분포(중앙값 · 하위 25% · 40px 미만 비율)
     - 원본 해상도 기준 / **검출기 입력 해상도 기준**(IMGSZ 로 축소된 뒤) 둘 다
  3) FN 91건(audit/fn_origin_20260922.json) 중 검출기 입력 기준 40px 미만이 몇 건인지

재현:
    python scripts/eval/measure_gt_quality.py --json audit/gt_quality_20260922.json
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

SMALL_PX = 40.0          # 이 미만을 '작은 박스' 로 본다(지시받은 값)


def _fourcc(cap: Any) -> str:
    import cv2
    v = int(cap.get(cv2.CAP_PROP_FOURCC))
    return "".join(chr((v >> (8 * i)) & 0xFF) for i in range(4)).strip() or "?"


def main() -> int:
    ap = argparse.ArgumentParser(description="정답지 화질 실측")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    import cv2
    import vision_loader
    from agents.guard import GuardAgent
    from data_paths import media
    from interpolate_gt_2fps import load_video_frames

    fe = _ROOT / "data" / "field_eval"
    manifest = json.loads((fe / "frames_manifest.json").read_text(encoding="utf-8"))
    byv = load_video_frames(manifest, fe / "labels")        # person 만(PERSON_ONLY)
    videos = media("") / "runs" / "rfdetr" / "accident"
    imgsz = int(getattr(GuardAgent(vision_loader.load_vision("safety")), "IMGSZ", 384))
    print(f"검출기 입력 해상도(IMGSZ) = {imgsz}px\n")

    out: dict[str, Any] = {"imgsz": imgsz, "small_px": SMALL_PX, "videos": {}}
    print(f"{'영상':8} {'해상도':>11} {'fps':>5} {'코덱':>6} {'길이s':>6} {'Mbps':>6} "
          f"{'박스':>4} {'원본px 중앙':>10} {'입력px 중앙':>10} {'입력<40px':>9}")
    all_in: list[float] = []
    for v, frs in byv.items():
        vid = videos / f"{v}.mp4"
        cap = cv2.VideoCapture(str(vid))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
        nfr = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        codec = _fourcc(cap)
        cap.release()
        dur = nfr / fps if fps else 0.0
        mbps = (vid.stat().st_size * 8 / dur / 1e6) if dur else 0.0
        # 박스 픽셀 높이: 정규화 h × 영상 높이 / 검출기는 긴 변을 imgsz 로 맞춘다(종횡비 유지)
        scale = imgsz / max(w, h) if max(w, h) else 1.0
        px_src = [b["box"][3] * h for fr in frs for b in fr["boxes"]]
        px_in = [x * scale for x in px_src]
        all_in += px_in
        small = sum(1 for x in px_in if x < SMALL_PX)
        rec = {"w": w, "h": h, "fps": round(fps, 2), "codec": codec,
               "duration_s": round(dur, 1), "mbps": round(mbps, 2), "n_boxes": len(px_src),
               "px_src_median": round(st.median(px_src), 1) if px_src else None,
               "px_src_q25": round(sorted(px_src)[len(px_src) // 4], 1) if px_src else None,
               "px_in_median": round(st.median(px_in), 1) if px_in else None,
               "px_in_q25": round(sorted(px_in)[len(px_in) // 4], 1) if px_in else None,
               "px_in_lt40": small,
               "px_in_lt40_pct": round(small / len(px_in) * 100, 1) if px_in else None}
        out["videos"][v] = rec
        print(f"{v[-6:]:8} {w:>5}x{h:<5} {fps:>5.1f} {codec:>6} {dur:>6.1f} {mbps:>6.2f} "
              f"{len(px_src):>4} {rec['px_src_median']:>10} {rec['px_in_median']:>10} "
              f"{small:>4}/{len(px_in)} {rec['px_in_lt40_pct']:>5}%")

    small_all = sum(1 for x in all_in if x < SMALL_PX)
    out["overall"] = {"n_boxes": len(all_in),
                      "px_in_median": round(st.median(all_in), 1),
                      "px_in_q25": round(sorted(all_in)[len(all_in) // 4], 1),
                      "px_in_lt40": small_all,
                      "px_in_lt40_pct": round(small_all / len(all_in) * 100, 1)}
    print(f"\n전체 {len(all_in)}박스 · 입력 기준 중앙값 {out['overall']['px_in_median']}px · "
          f"하위25% {out['overall']['px_in_q25']}px · 40px 미만 {small_all}건 "
          f"({out['overall']['px_in_lt40_pct']}%)")

    # ── FN 91건 중 40px 미만 ────────────────────────────────────────────────
    fnp = _ROOT / "audit" / "fn_origin_20260922.json"
    if fnp.exists():
        fn = json.loads(fnp.read_text(encoding="utf-8"))["b"]
        vh = {v: out["videos"][v]["h"] for v in out["videos"]}
        vs = {v: out["imgsz"] / max(out["videos"][v]["w"], out["videos"][v]["h"]) for v in out["videos"]}
        rows = []
        for it in fn["items"]:
            v = it.get("video")
            if v not in vh:
                continue
            # bbox 는 xyxy 정규화(to_xyxy 적용분) — 높이 = y2-y1
            hh = (it["bbox"][3] - it["bbox"][1]) * vh[v] * vs[v]
            rows.append({"file": it["file"], "px_in": round(hh, 1), "bucket": it.get("bucket")})
        small_fn = [r for r in rows if r["px_in"] < SMALL_PX]
        out["fn"] = {"n": len(rows), "lt40": len(small_fn),
                     "lt40_pct": round(len(small_fn) / len(rows) * 100, 1) if rows else None,
                     "px_in_median": round(st.median([r["px_in"] for r in rows]), 1) if rows else None,
                     "by_bucket": {}}
        from collections import Counter
        out["fn"]["by_bucket"] = dict(Counter(r["bucket"] for r in small_fn))
        print(f"\nFN {len(rows)}건 중 검출기 입력 기준 40px 미만: **{len(small_fn)}건** "
              f"({out['fn']['lt40_pct']}%) · FN 박스 높이 중앙값 {out['fn']['px_in_median']}px")
        for k, n in out["fn"]["by_bucket"].items():
            print(f"    {k}: {n}건")

    # ── Q-3: 화질 최악 영상이 검수 부담 큰 두 편인가 ──────────────────────────
    worst = min(out["videos"].items(), key=lambda kv: kv[1]["px_in_median"] or 9e9)
    print(f"\n[Q-3] 입력 기준 박스 높이 **중앙값이 가장 낮은 영상**: {worst[0][-6:]} "
          f"({worst[1]['px_in_median']}px)")
    out["q3_worst_video"] = worst[0]
    if worst[0][-6:] in ("438282", "552920"):
        print("  ★검수 시간이 가장 많이 드는 두 영상(438282·552920) 중 하나다 — 보고 대상.")
    else:
        print("  → 438282·552920 은 아니다.")

    print("\n※화질은 잰 값이다. '판단이 어렵다' 는 검수자 소견과는 별개 근거다(규칙 7).")
    if a.json:
        p = _ROOT / a.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {p} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
