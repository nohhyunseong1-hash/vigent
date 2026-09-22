#!/usr/bin/env python3
"""scripts/eval/cvat_to_gt.py — CVAT for video XML → VIGENT 정답지 스키마 변환.

배경(2026-09-22): 라벨링을 **CVAT 자체 설치**로 전환했다(`docs/labeling/cvat_setup.md`).
  추적 ID 라벨링이 필요한데 Roboflow 는 검출 전용이고, 얼굴이 있는 현장 영상을 외부
  클라우드에 올릴 수 없어 Docker 자체 호스팅으로 간다.

왜 XML(CVAT for video 1.1)인가:
  · `<track id=.. label=..>` 아래 `<box frame= outside= keyframe= xtl= ytl= xbr= ybr=>`
    구조라 **track ID 가 보존**된다. YOLO·COCO 로 내보내면 트랙이 사라진다.
  · `keyframe` 속성이 있어 **사람이 찍은 프레임과 CVAT 이 보간한 프레임을 구분**할 수 있다.
    → source 를 `human_verified` / `cvat_interp` 로 정확히 나눌 수 있다.

★2fps 샘플링은 **라벨 후 여기서** 한다. CVAT 에는 원본 fps 그대로 올린다
  (트랙 보간이 영상 단위로 동작해야 하므로).

사용:
    python scripts/eval/cvat_to_gt.py --xml annotations.xml --fps 2 \
        --out data/field_eval/labels_field_2fps
    python scripts/eval/cvat_to_gt.py --xml annotations.xml --dry-run   # 집계만
"""
from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 기존 정답지와 **같은 순서**여야 한다(data/field_eval/classes.txt)
CLASSES = ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest"]

# ★의도적으로 제외한 클래스 — 버그가 아니다. 조용히 건너뛰되 집계에는 남긴다.
#
#   사유(실측 근거: reports/현장테스트_보고서_20260827_v1.2.md §7-1, 2026-08-27 학원 현장):
#     보호구 경보 490건 중 **87건이 "마스크 미착용" 단독**으로 발화했고, 그중 **81건이
#     보호구를 갖춰 입은 04·07 장면**에 몰려 있었다. **야외 중장비 실습장에서 마스크는
#     필수 보호구가 아니다.** 즉 마스크 단독 발화가 사실상 전부 오탐이었다.
#   조치(2026-08-28): 학원 프로파일에 `ppe.required = [NO-Hardhat, NO-Safety-Vest]`.
#     **필수 보호구 규칙에 마스크가 없다** — 그래서 정답지에도 라벨할 이유가 없다.
#     전후 재집계에서 안전모·조끼 경보는 365건 그대로, 손실 0.
#   ⚠**전역 기본값은 3종(안전모·조끼·마스크) 그대로 둔다.** 실내 분진 작업 등 다른 현장에서는
#     마스크가 필수일 수 있다. 이 제외는 **이 현장(학원) 정답지에 한정**된다.
#   ※클래스 매핑 오류가 **아니다.** 현장 조건에 따른 운용 결정이다.
EXCLUDED_CLASSES = ["Mask", "NO-Mask"]

UNRESOLVABLE_ATTRS = {"unresolvable", "판정불가", "low_quality"}


def parse_cvat(xml_path: Path) -> dict[str, Any]:
    """CVAT for video XML → {meta, tracks:[{id,label,boxes:[...]}]}."""
    root = ET.parse(xml_path).getroot()
    meta = root.find("meta")
    task = meta.find("task") if meta is not None else None

    def _t(node: Any, tag: str, default: str = "") -> str:
        el = node.find(tag) if node is not None else None
        return (el.text or default) if el is not None else default

    info = {"name": _t(task, "name"), "size": int(_t(task, "size", "0") or 0),
            "fps": float(_t(task.find("original_size") if task is not None else None, "fps", "0") or 0)}
    # fps 는 보통 meta/task/original_size 가 아니라 meta/task/... 위치가 버전마다 다르다 — 둘 다 본다
    if not info["fps"]:
        for path in ("original_size/fps", "fps"):
            v = _t(task, path)
            if v:
                info["fps"] = float(v)
                break

    tracks: list[dict[str, Any]] = []
    for tr in root.findall("track"):
        boxes = []
        for b in tr.findall("box"):
            if b.get("outside") == "1":
                continue                       # 그 프레임엔 없다 — 내보내지 않는다
            attrs = {a.get("name", "").strip().lower(): (a.text or "").strip().lower()
                     for a in b.findall("attribute")}
            unres = any(k in UNRESOLVABLE_ATTRS or v in UNRESOLVABLE_ATTRS for k, v in attrs.items())
            boxes.append({"frame": int(b.get("frame", "0")),
                          "keyframe": b.get("keyframe") == "1",
                          "xtl": float(b.get("xtl", "0")), "ytl": float(b.get("ytl", "0")),
                          "xbr": float(b.get("xbr", "0")), "ybr": float(b.get("ybr", "0")),
                          "unresolvable": unres})
        tracks.append({"id": int(tr.get("id", "0")), "label": tr.get("label", ""), "boxes": boxes})
    return {"meta": info, "tracks": tracks}


def to_gt(parsed: dict[str, Any], target_fps: float, width: int, height: int,
          video_role: str = "full") -> dict[int, dict[str, Any]]:
    """원본 fps 에서 target_fps 격자 프레임만 추려 프레임별 정답지로 만든다."""
    src_fps = parsed["meta"]["fps"] or 0.0
    if src_fps <= 0:
        raise ValueError("원본 fps 를 XML 에서 읽지 못했다 — --src-fps 로 준다")
    step = src_fps / target_fps
    n = parsed["meta"]["size"]
    wanted = {int(round(i * step)) for i in range(int(n / step) + 1) if int(round(i * step)) < n}

    out: dict[int, dict[str, Any]] = {}
    for tr in parsed["tracks"]:
        if tr["label"] in EXCLUDED_CLASSES:
            continue                           # ★의도적 제외 — 경고하지 않는다(집계는 호출부에서)
        if tr["label"] not in CLASSES:
            continue                           # 스키마 밖 라벨 — 호출부가 경고하고 파일로 남긴다
        cls = CLASSES.index(tr["label"])
        for b in tr["boxes"]:
            if b["frame"] not in wanted:
                continue
            cx = (b["xtl"] + b["xbr"]) / 2 / width
            cy = (b["ytl"] + b["ybr"]) / 2 / height
            w = (b["xbr"] - b["xtl"]) / width
            h = (b["ybr"] - b["ytl"]) / height
            rec: dict[str, Any] = {
                "cls": cls, "box": [cx, cy, w, h],
                "track_id": tr["id"],
                # ★사람이 찍은 키프레임만 human_verified. CVAT 이 채운 것은 따로 표시한다.
                "source": "human_verified" if b["keyframe"] else "cvat_interp",
                "parent_track_id": None}
            if b["unresolvable"]:
                rec.update({"verdict": "unresolvable", "reason": "low_quality", "track_id": None})
            out.setdefault(b["frame"], {"frame": b["frame"],
                                        "t_ms": round(b["frame"] / src_fps * 1000),
                                        "video_role": video_role, "boxes": []})
            out[b["frame"]]["boxes"].append(rec)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="CVAT for video XML → VIGENT 정답지")
    ap.add_argument("--xml", required=True)
    ap.add_argument("--fps", type=float, default=2.0, help="목표 샘플링 fps(라벨 후 추림)")
    ap.add_argument("--src-fps", type=float, default=0.0, help="XML 에서 못 읽을 때 원본 fps 지정")
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    ap.add_argument("--video-role", default="full", choices=["full", "detector_only"])
    ap.add_argument("--out", default="", help="프레임별 JSON 을 쓸 폴더(없으면 집계만)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    parsed = parse_cvat(Path(a.xml))
    if a.src_fps:
        parsed["meta"]["fps"] = a.src_fps
    # 해상도: XML meta 에 없으면 인자로 받는다
    root = ET.parse(a.xml).getroot()
    osz = root.find("./meta/task/original_size")
    w = a.width or int((osz.findtext("width") if osz is not None else "0") or 0)
    h = a.height or int((osz.findtext("height") if osz is not None else "0") or 0)
    if not (w and h):
        print("★해상도를 못 읽었다 — --width/--height 를 준다")
        return 2

    labels = Counter(t["label"] for t in parsed["tracks"])
    excluded = {k: v for k, v in labels.items() if k in EXCLUDED_CLASSES}
    unmapped = {k: v for k, v in labels.items() if k not in CLASSES and k not in EXCLUDED_CLASSES}
    print(f"XML: {a.xml}")
    print(f"  원본 {w}x{h} · {parsed['meta']['fps']}fps · {parsed['meta']['size']}프레임")
    print(f"  트랙 {len(parsed['tracks'])}개 · 라벨 {dict(labels)}")
    if excluded:
        # ★의도적 제외 — 경고가 아니라 집계다(사유는 EXCLUDED_CLASSES 주석 참조)
        print(f"  제외 클래스 {sum(excluded.values())}건(의도적): {excluded}")
    if unmapped:
        # 제외 목록에도 없는 라벨 — 오타인지 새 클래스인지 사람이 봐야 한다. 경고하고 파일로 남긴다.
        print(f"  ★스키마 밖 라벨 {sum(unmapped.values())}건 — 버려진다. 확인 필요: {unmapped}")
        up = Path(a.out or ".") / "unmapped_labels.json"
        up.parent.mkdir(parents=True, exist_ok=True)
        up.write_text(json.dumps(
            {"xml": str(a.xml), "unmapped": unmapped, "known": CLASSES,
             "excluded_intentionally": EXCLUDED_CLASSES,
             "note": "스키마에 없고 의도적 제외 목록에도 없는 라벨이다. 오타인지 새 클래스인지 확인할 것."},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"    → {up}")

    frames = to_gt(parsed, a.fps, w, h, a.video_role)
    src = Counter(b["source"] for f in frames.values() for b in f["boxes"])
    unres = sum(1 for f in frames.values() for b in f["boxes"] if b.get("verdict") == "unresolvable")
    tids = {b["track_id"] for f in frames.values() for b in f["boxes"] if b.get("track_id") is not None}
    print(f"\n{a.fps}fps 추림: 프레임 {len(frames)}장 · 박스 {sum(len(f['boxes']) for f in frames.values())}개")
    print(f"  source: {dict(src)}")
    print(f"  track_id {len(tids)}종 · 판정 불가 {unres}개(track_id 없음)")

    if a.out and not a.dry_run:
        od = Path(a.out)
        od.mkdir(parents=True, exist_ok=True)
        n = 0
        for fr, rec in sorted(frames.items()):
            p = od / f"frame_{fr:06d}.json"
            p.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
            n += p.exists() and p.stat().st_size > 0
        print(f"\n저장: {od} — 기대 {len(frames)} · 실제 {n}")
        if n != len(frames):
            print("★개수가 다르다 — 실패로 본다(규칙 11)")
            return 1
    elif not a.out:
        print("\n--out 을 주지 않아 집계만 했다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
