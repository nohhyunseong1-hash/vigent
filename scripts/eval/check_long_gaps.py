#!/usr/bin/env python3
"""scripts/eval/check_long_gaps.py — 1fps 정답지의 '긴 간격' 17구간에 정말 사람이 없었는지 확인한다.

배경: `frames_manifest.json` 의 인접 간격은 대부분 1,000ms 인데 17구간은 2,000~7,000ms 다.
  "그 사이 프레임에 사람이 없어 라벨이 없다" 는 것은 **추측이었다**(샘플링 규칙 문서 없음).
  추측인 채로 보간에서 건너뛰면, 실제로 사람이 있었을 경우 정답지에 구멍이 남는다.

무엇을 하나:
  구간마다 **원본 24fps 영상에서 중간 시점 프레임을 뽑아** 저장하고,
  같은 시점에 검출기를 낮은 임계로 돌려 person 후보를 센다(사람 눈 판정의 보조).
  ★검출기 결과는 **참고**다 — 최종 판정은 사람이 프레임을 보고 한다(규칙 7).

재현:
    python scripts/eval/check_long_gaps.py --write --json audit/long_gaps_20260922.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))

PROBE_CONF = 0.10       # 낮게 잡아 '있었는데 놓쳤다' 를 최대한 드러낸다


def main() -> int:
    ap = argparse.ArgumentParser(description="긴 간격 구간의 사람 유무 확인")
    ap.add_argument("--write", action="store_true", help="프레임 이미지를 저장한다")
    ap.add_argument("--json", default="")
    a = ap.parse_args()

    import cv2
    import vision_loader
    from agents.guard import GuardAgent
    from data_paths import media
    from interpolate_gt_2fps import load_video_frames
    from isolated_detect import detect_isolated

    fe = _ROOT / "data" / "field_eval"
    manifest = json.loads((fe / "frames_manifest.json").read_text(encoding="utf-8"))
    byv = load_video_frames(manifest, fe / "labels")
    videos = media("") / "runs" / "rfdetr" / "accident"
    out_dir = media("field_eval") / "long_gap_check"

    gaps: list[dict[str, Any]] = []
    for v, frs in byv.items():
        for x, y in zip(frs, frs[1:]):
            gap = y["t_ms"] - x["t_ms"]
            if gap == 1000:
                continue
            gaps.append({"video": v, "from_ms": x["t_ms"], "to_ms": y["t_ms"], "gap_ms": gap,
                         "n_person_from": len(x["boxes"]), "n_person_to": len(y["boxes"])})
    print(f"긴 간격 구간 {len(gaps)}개\n")

    # 추적기를 우회해 원 검출을 본다(고립 프레임은 매번 '첫 프레임'이라 추적기가 전부 버린다)
    import agents.guard as GM
    orig = GM.GuardAgent._track
    GM.GuardAgent._track = lambda self, fresh, track_key: list(fresh)
    try:
        guard = GuardAgent(vision_loader.load_vision("safety"))
        for g in gaps:
            vid = videos / f"{g['video']}.mp4"
            # 구간 안의 500ms 격자 시점들(양끝 제외)
            times = [g["from_ms"] + t for t in range(500, int(g["gap_ms"]), 500)]
            g["probe_times_ms"] = times
            g["frames"] = []
            cap = cv2.VideoCapture(str(vid))
            fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
            for t_ms in times:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
                ok, img = cap.read()
                if not ok or img is None:
                    g["frames"].append({"t_ms": t_ms, "error": "프레임 읽기 실패"})
                    continue
                dets = detect_isolated(guard, img, detectors=["person", "ppe"], conf=PROBE_CONF)
                ps = [float(d.get("conf", 0)) for d in dets.get("detections", [])
                      if str(d.get("label", "")).lower() == "person"]
                rec: dict[str, Any] = {"t_ms": t_ms, "n_person_probe": len(ps),
                                       "max_conf": round(max(ps), 3) if ps else 0.0}
                if a.write:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    fn = out_dir / f"{g['video']}_{int(t_ms)}ms.jpg"
                    if not cv2.imwrite(str(fn), img) or not fn.exists() or fn.stat().st_size == 0:
                        rec["save"] = "★저장 실패"
                    else:
                        rec["save"] = str(fn.name)
                g["frames"].append(rec)
            cap.release()
    finally:
        GM.GuardAgent._track = orig
    print(f"운영 동작 원복: {GM.GuardAgent._track is orig}\n")

    print(f"{'영상':10} {'구간(ms)':>16} {'길이':>6} {'양끝 person':>11} {'중간 시점':>8} "
          f"{'person 검출된 시점':>16} {'최대conf':>8}")
    n_with = n_without = 0
    for g in gaps:
        hit = [f for f in g["frames"] if f.get("n_person_probe", 0) > 0]
        g["has_person"] = bool(hit)
        n_with += bool(hit)
        n_without += (not hit)
        mx = max((f.get("max_conf", 0) for f in g["frames"]), default=0)
        print(f"{g['video'][-6:]:10} {g['from_ms']:>7.0f}~{g['to_ms']:<8.0f} {g['gap_ms']:>6.0f} "
              f"{g['n_person_from']:>5}/{g['n_person_to']:<5} {len(g['frames']):>8} "
              f"{len(hit):>16} {mx:>8.3f}")
    print(f"\n★사람 후보가 있는 구간 {n_with}개 · 없는 구간 {n_without}개 (총 {len(gaps)})")
    print("※검출기 결과는 참고다 — 최종 판정은 사람이 프레임을 보고 한다(규칙 7).")
    if a.write:
        print(f"프레임 저장 위치: {out_dir}")

    if a.json:
        p = _ROOT / a.json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"probe_conf": PROBE_CONF, "n_gaps": len(gaps),
                                 "n_with_person": n_with, "n_without_person": n_without,
                                 "gaps": gaps}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"저장: {p} ({p.stat().st_size:,} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
