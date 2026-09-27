#!/usr/bin/env python3
"""scripts/data/field_prelabel.py — 현장 녹화(영상/사진)를 2fps 프레임으로 풀고 v1 으로 초벌 박스를 달아 CVAT 1.1 XML + VIGENT 라벨을 만든다. [PPE v2 현장 경로 ①, 2026-09-27]

입력  --in <루트>: 카메라별 하위 폴더(폴더명 = 카메라 ID). 영상(.mp4/.avi/.mkv/.mov/.h264/.264/.dav — DVR/NVR 내보내기 포함) 또는 사진(.jpg/.png).
      루트 바로 아래 파일은 카메라 'cam0' 으로 본다.
출력  --out <폴더> (★얼굴 포함 → 저장소 밖 D:\\vigent_private_data\\field\\ 아래만 허용, 저장소 안이면 거부):
      images/<stem>.jpg · labels/<stem>.txt(YOLO, classes.txt 순) · labels_meta/<stem>.json · cvat/<카메라>.xml(CVAT 1.1)
      negatives/<stem>.jpg(v1 이 사람을 못 본 프레임 — 음성 평가용, 라벨 없음) · manifest.json · classes.txt
파일명 stem = <카메라>__<YYYYMMDD>__<day|night|unk>__<원본 stem>__f<프레임번호>  (사진은 프레임번호 없음) — 카메라·날짜·주야를 이름에 보존.
날짜·시각은 파일명/폴더명의 숫자(YYYYMMDD[_HHMMSS])에서, 없으면 파일 mtime(메타에 date_source 로 표시). 주야는 폴더/파일명의 night|야간·day|주간,
없으면 시각(06~18 = day), 그것도 없으면 unk. --daynight 로 일괄 지정 가능.
초벌 박스: v1(ppe_rfdetr_v1) conf ≥ --conf(기본 0.4), 우리 5클래스(person·Hardhat·NO-Hardhat·Safety-Vest·NO-Safety-Vest)만. 검수는 CVAT 에서 한다.
규칙 11: 쓴 파일 수·크기를 같은 실행에서 세고 다르면 실패(exit 1).
사용:
    python scripts/data/field_prelabel.py --in D:/vigent_field/raw --out D:/vigent_private_data/field/prelabel [--conf 0.4] [--dry-run] [--limit 50]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from xml.sax.saxutils import escape

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VIDEO_EXTS = (".mp4", ".avi", ".mkv", ".mov", ".h264", ".264", ".dav", ".ts")
IMG_EXTS = (".jpg", ".jpeg", ".png", ".bmp")
CLASSES = ["person", "Hardhat", "NO-Hardhat", "Safety-Vest", "NO-Safety-Vest"]          # VIGENT 표준 5클래스(변환기와 같은 순서)
PRIVATE_ROOT_DEFAULT = Path("D:/vigent_private_data/field")
_DATE = re.compile(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?:[-_T ]?(\d{2})[-:_]?(\d{2})[-:_]?(\d{2}))?")
Predictor = Callable[[Any], list[tuple[str, list[float], float]]]     # PIL image → [(표준 클래스명, [x1,y1,x2,y2], conf)]


# ── 이름·메타 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def sanitize(s: str) -> str:
    s = re.sub(r"[^0-9A-Za-z가-힣_-]+", "_", s).strip("_")
    return s or "x"


def parse_when(path: Path, root: Path) -> dict[str, Any]:
    """파일명·상위 폴더명에서 날짜/시각을 읽는다. 없으면 mtime. → {date:'YYYYMMDD', hour:int|None, date_source}"""
    rel = path.relative_to(root) if root in path.parents else path
    texts = [path.stem] + list(rel.parts[:-1])            # 파일명 먼저, 그다음 상위 폴더명(루트 제외)
    for t in texts:
        m = _DATE.search(t)
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                hour = int(m.group(4)) if m.group(4) is not None and int(m.group(4)) < 24 else None
                return {"date": f"{y:04d}{mo:02d}{d:02d}", "hour": hour, "date_source": "name"}
    t = time.localtime(path.stat().st_mtime)
    return {"date": time.strftime("%Y%m%d", t), "hour": t.tm_hour, "date_source": "mtime"}


def daynight_of(path: Path, root: Path, hour: int | None, override: str = "") -> tuple[str, str]:
    """→ (day|night|unk, 근거). 우선순위: --daynight > 이름 토큰 > 시각(06~18 day) > unk"""
    if override:
        return override, "cli"
    rel = path.relative_to(root) if root in path.parents else path
    text = "/".join(rel.parts).lower()
    sep = r"(?:^|[_\-/ .()])"; end = r"(?:$|[_\-/ .()])"
    if re.search(sep + r"(?:night|야간|n)" + end, text):
        return "night", "name"
    if re.search(sep + r"(?:day|주간|d)" + end, text):
        return "day", "name"
    if hour is not None:
        return ("day" if 6 <= hour < 18 else "night"), "hour"
    return "unk", "none"


def camera_of(path: Path, root: Path) -> str:
    rel = path.relative_to(root)
    return sanitize(rel.parts[0]) if len(rel.parts) > 1 else "cam0"


def list_inputs(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTS + IMG_EXTS)


# ── 프레임 추출 ───────────────────────────────────────────────────────────────────────────────────────────────────────
def frame_step(fps: float, target_fps: float = 2.0) -> int:
    if not fps or fps != fps or fps <= 0:
        fps = 25.0
    return max(1, int(round(fps / target_fps)))


def iter_video_frames(path: Path, target_fps: float = 2.0):
    """(frame_idx, BGR ndarray, info) 를 target_fps 로 낸다. fps 를 못 읽으면 25 로 가정(info.fps_assumed=True)."""
    import cv2
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"열 수 없음: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    assumed = not fps or fps <= 0 or fps != fps
    step = frame_step(fps, target_fps)
    info = {"fps": (25.0 if assumed else round(fps, 3)), "fps_assumed": assumed, "step": step}
    idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if idx % step == 0:
                yield idx, frame, info
            idx += 1
    finally:
        cap.release()


# ── 출력 형식 ─────────────────────────────────────────────────────────────────────────────────────────────────────────
def to_yolo(boxes: list[tuple[str, list[float], float]], W: int, H: int) -> str:
    lines = []
    for name, (x1, y1, x2, y2), _c in boxes:
        if name not in CLASSES or x2 <= x1 or y2 <= y1:
            continue
        x1, y1, x2, y2 = max(0.0, x1), max(0.0, y1), min(float(W), x2), min(float(H), y2)
        lines.append(f"{CLASSES.index(name)} {(x1 + x2) / 2 / W:.6f} {(y1 + y2) / 2 / H:.6f} {(x2 - x1) / W:.6f} {(y2 - y1) / H:.6f}\n")
    return "".join(lines)


def cvat_xml(task_name: str, images: list[dict[str, Any]]) -> str:
    """CVAT 1.1 images 형식. images[i] = {name, width, height, boxes:[(label,[x1,y1,x2,y2],conf)]}. source='auto' 로 초벌임을 남긴다."""
    L = ['<?xml version="1.0" encoding="utf-8"?>', "<annotations>", "  <version>1.1</version>", "  <meta>", "    <task>",
         f"      <name>{escape(task_name)}</name>", f"      <size>{len(images)}</size>", "      <mode>annotation</mode>", "      <labels>"]
    for c in CLASSES:
        L += ["        <label>", f"          <name>{escape(c)}</name>", "          <attributes>", "            <attribute>", "              <name>conf</name>",
              "              <mutable>false</mutable>", "              <input_type>text</input_type>", "              <default_value></default_value>",
              "              <values></values>", "            </attribute>", "          </attributes>", "        </label>"]
    L += ["      </labels>", "    </task>", "  </meta>"]
    for i, im in enumerate(images):
        L.append(f'  <image id="{i}" name="{escape(im["name"])}" width="{im["width"]}" height="{im["height"]}">')
        for label, (x1, y1, x2, y2), conf in im["boxes"]:
            L.append(f'    <box label="{escape(label)}" occluded="0" source="auto" xtl="{x1:.2f}" ytl="{y1:.2f}" xbr="{x2:.2f}" ybr="{y2:.2f}" z_order="0">')
            L.append(f'      <attribute name="conf">{conf:.3f}</attribute>'); L.append("    </box>")
        L.append("  </image>")
    L.append("</annotations>")
    return "\n".join(L) + "\n"


def assert_private_out(out: Path, allow_in_repo: bool = False) -> None:
    """얼굴 포함 산출물은 저장소 안에 두지 않는다(규칙 10). 저장소 하위면 거부."""
    o = out.resolve()
    try:
        o.relative_to(_ROOT.resolve())
        inside = True
    except ValueError:
        inside = False
    if inside and not allow_in_repo:
        raise SystemExit(f"★출력 폴더가 저장소 안이다({o}) — 얼굴 포함 데이터는 {PRIVATE_ROOT_DEFAULT} 아래에 둔다(--allow-in-repo 는 테스트 전용)")


def make_v1_predictor(weights: str, res: int = 384) -> Predictor:
    """v1 체크포인트 → PIL 이미지에서 표준 5클래스 박스를 내는 함수(eval_v1_heldout 과 같은 규약)."""
    import torch
    from rfdetr import RFDETRNano
    sys.path.insert(0, str(_ROOT / "scripts" / "train"))
    from finetune_rfdetr import std_name
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    m = RFDETRNano(pretrain_weights=weights, device=dev, resolution=res)
    try:
        m.optimize_for_inference()
    except Exception:  # noqa: BLE001
        pass
    names = [std_name(n) for n in (getattr(m, "class_names", None) or CLASSES)]

    def predict(im) -> list[tuple[str, list[float], float]]:
        det = m.predict(im, threshold=0.05)
        out = []
        for box, cid, conf in zip(det.xyxy, det.class_id, det.confidence):
            cid = int(cid)
            if 0 <= cid < len(names) and names[cid] in CLASSES:
                out.append((names[cid], [float(v) for v in box], float(conf)))
        return out
    return predict


# ── 본 처리 ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def run(inp: Path, out: Path, predictor: Predictor | None, conf: float = 0.4, target_fps: float = 2.0, daynight: str = "",
        limit: int = 0, dry_run: bool = False, jpeg_q: int = 95) -> dict[str, Any]:
    """전체 파이프라인. predictor=None 이면 dry-run(계획만). 반환 = manifest dict(카운트 포함)."""
    import cv2
    import numpy as np
    from PIL import Image
    files = list_inputs(inp)
    plan = [{"file": str(p), "camera": camera_of(p, inp), "kind": "video" if p.suffix.lower() in VIDEO_EXTS else "image", **parse_when(p, inp)} for p in files]
    for pl, p in zip(plan, files):
        pl["daynight"], pl["daynight_source"] = daynight_of(p, inp, pl["hour"], daynight)
    cams = Counter(pl["camera"] for pl in plan)
    print(f"[prelabel] 입력 {len(files)}개 (영상 {sum(1 for pl in plan if pl['kind'] == 'video')} · 사진 {sum(1 for pl in plan if pl['kind'] == 'image')}) · 카메라 {dict(cams)} · out {out}")
    if dry_run or predictor is None:
        for pl in plan[:20]:
            print(f"   {pl['camera']:8s} {pl['date']} {pl['daynight']:5s} ({pl['daynight_source']}/{pl['date_source']}) {pl['kind']:5s} {Path(pl['file']).name}")
        return {"dry_run": True, "inputs": plan, "cameras": dict(cams)}
    if not files:
        raise SystemExit("★입력 파일 0개 — 실패(폴더·확장자 확인)")

    for sub in ("images", "labels", "labels_meta", "negatives", "cvat"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    frames: list[dict[str, Any]] = []; per_cam_xml: dict[str, list[dict[str, Any]]] = {}
    counts: Counter = Counter(); t0 = time.time(); n_total = 0

    def handle(stem: str, bgr, pl: dict[str, Any], clip: str, frame_idx: int | None, vinfo: dict[str, Any] | None) -> None:
        nonlocal n_total
        H, W = bgr.shape[:2]
        im = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        boxes = [b for b in predictor(im) if b[2] >= conf]
        n_person = sum(1 for b in boxes if b[0] == "person")
        negative = n_person == 0
        dst = out / ("negatives" if negative else "images") / f"{stem}.jpg"
        ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, jpeg_q])
        if not ok:
            counts["encode_fail"] += 1; return
        buf.tofile(str(dst))
        meta = {"stem": stem, "camera": pl["camera"], "date": pl["date"], "hour": pl["hour"], "daynight": pl["daynight"], "daynight_source": pl["daynight_source"],
                "date_source": pl["date_source"], "clip": clip, "source_file": pl["file"], "frame_idx": frame_idx, "video": vinfo, "width": W, "height": H,
                "negative": negative, "n_person": n_person, "n_boxes": len(boxes), "prelabel": {"model": "ppe_rfdetr_v1", "conf": conf},
                "boxes": [{"cls": n, "box": [round(v, 1) for v in b], "conf": round(c, 3)} for n, b, c in boxes]}
        if not negative:
            (out / "labels" / f"{stem}.txt").write_text(to_yolo(boxes, W, H), encoding="utf-8")
            (out / "labels_meta" / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            per_cam_xml.setdefault(pl["camera"], []).append({"name": f"{stem}.jpg", "width": W, "height": H, "boxes": boxes})
            counts["positive"] += 1
        else:
            counts["negative"] += 1
        for n, _b, _c in boxes:
            counts[f"box:{n}"] += 1
        frames.append({k: meta[k] for k in ("stem", "camera", "date", "daynight", "clip", "negative", "n_person", "n_boxes", "frame_idx", "source_file")})
        n_total += 1
        if n_total % 100 == 0:
            print(f"   {n_total} 프레임 ({time.time() - t0:.0f}s) · 양성 {counts['positive']} · 음성 {counts['negative']}", flush=True)

    for pl, p in zip(plan, files):
        if limit and n_total >= limit:
            break
        base = f"{pl['camera']}__{pl['date']}__{pl['daynight']}__{sanitize(p.stem)}"
        if pl["kind"] == "video":
            clip = f"{pl['camera']}/{sanitize(p.stem)}"
            try:
                for idx, frame, vinfo in iter_video_frames(p, target_fps):
                    if limit and n_total >= limit:
                        break
                    handle(f"{base}__f{idx:06d}", frame, pl, clip, idx, vinfo)
                counts["videos"] += 1
            except RuntimeError as e:
                print(f"   ★{e}"); counts["video_open_fail"] += 1
        else:
            hb = f"{pl['date']}_{(pl['hour'] if pl['hour'] is not None else 99):02d}"     # 사진 = 같은 날짜·같은 시(時) 를 한 clip(시간대) 으로
            arr = cv2.imdecode(np.fromfile(str(p), dtype=np.uint8), cv2.IMREAD_COLOR)     # 한글 경로 안전
            if arr is None:
                counts["image_read_fail"] += 1; continue
            handle(base, arr, pl, f"{pl['camera']}/{hb}", None, None); counts["images"] += 1

    for cam, ims in per_cam_xml.items():
        (out / "cvat" / f"{cam}.xml").write_text(cvat_xml(f"vigent_field_{cam}", ims), encoding="utf-8")
    manifest = {"created": time.strftime("%Y-%m-%d %H:%M:%S"), "input_root": str(inp), "classes": CLASSES, "conf": conf, "target_fps": target_fps,
                "counts": dict(counts), "cameras": dict(cams), "frames": frames,
                "note": "negative = v1 conf≥conf 에서 person 0개(음성 평가용, 검수 대상). heldout/no_train 표시는 field_split.py heldout 이 붙인다"}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    # 규칙 11: 실제 파일 수·크기
    n_img = len(list((out / "images").glob("*.jpg"))); n_lbl = len(list((out / "labels").glob("*.txt"))); n_neg = len(list((out / "negatives").glob("*.jpg")))
    n_xml = len(list((out / "cvat").glob("*.xml"))); zero = [p.name for sub in ("images", "negatives") for p in (out / sub).glob("*.jpg") if p.stat().st_size == 0]
    ok = n_img == counts["positive"] == n_lbl and n_neg == counts["negative"] and n_xml == len(per_cam_xml) and not zero
    print(f"[prelabel] 프레임 {n_total} = 양성 {counts['positive']}(images {n_img}·labels {n_lbl}) + 음성 {counts['negative']}(negatives {n_neg}) · cvat {n_xml} · 0바이트 {len(zero)} · "
          f"{time.time() - t0:.0f}s → {out}  {'✓' if ok else '★불일치'}")
    manifest["verified"] = ok
    if not ok:
        raise SystemExit(1)
    return manifest


def main() -> int:
    ap = argparse.ArgumentParser(description="현장 녹화 → 2fps 프레임 + v1 초벌 라벨(CVAT 1.1)")
    ap.add_argument("--in", dest="inp", required=True); ap.add_argument("--out", default=str(PRIVATE_ROOT_DEFAULT / "prelabel"))
    ap.add_argument("--weights", default=str(_ROOT / "vigent-core" / "weights" / "ppe_rfdetr_v1.pth")); ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--conf", type=float, default=0.4); ap.add_argument("--fps", type=float, default=2.0)
    ap.add_argument("--daynight", choices=("", "day", "night"), default="", help="주야 일괄 지정(비우면 이름/시각으로 추정)")
    ap.add_argument("--limit", type=int, default=0, help="시험용: 총 프레임 상한"); ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--allow-in-repo", action="store_true", help="테스트 전용")
    a = ap.parse_args()
    out = Path(a.out); assert_private_out(out, a.allow_in_repo)
    if a.dry_run:
        run(Path(a.inp), out, None, a.conf, a.fps, a.daynight, a.limit, dry_run=True); return 0
    pred = make_v1_predictor(a.weights, a.res)
    run(Path(a.inp), out, pred, a.conf, a.fps, a.daynight, a.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
