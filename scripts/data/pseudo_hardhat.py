#!/usr/bin/env python3
"""scripts/data/pseudo_hardhat.py — Hardhat(착용) 양성 **준라벨**(pseudo-label) 생성기. [2026-09-26 대표 결정 1]

왜 이것인가
  · 507 에는 "안전모 착용 머리" 박스 클래스가 없고, WO-01 상단 N% 파생은 A-4 진단으로 **폐기**했다(검출기 박스와 IoU 중앙 0.18).
  · 그래서 Hardhat 양성은 **현재 검출기(ppe_rfdetr_v1) 가 conf ≥ 0.6 으로 낸 박스**를 준라벨로 쓴다.
    이것은 [추정] 이다 — 검출기 출력을 정답으로 삼는 것이므로 **무작위 100장을 audit/ 에 그려 육안 확인 후 채택**한다.

무엇을 만드는가
  out/
    classes.txt             aihub_to_vigent.CLASSES 그대로(Hardhat = 1)
    labels/<stem>.txt       준라벨 Hardhat 줄만(`1 cx cy w h`) — 박스가 1개 이상인 이미지만 쓴다(0개면 "착용자 없음"이 아니라 "검출 실패"일 수 있어 음성으로 가르치지 않는다)
    labels_meta/<stem>.json 사이드카 {file, source:"pseudo:v1", boxes:[{cls, box, conf, source:"pseudo:v1", derived:true, derive_rule}]}
    split.json              전부 train(준라벨은 검증에 쓰지 않는다) · manifest.json
  --merge-into <vigent_507>  같은 stem 의 기존 라벨(labels/<stem>.txt)·사이드카에 **덧붙인다**(person·NO-Hardhat 옆에 Hardhat 추가). 없는 stem 은 out/ 에만.
  --preview-n 100 --preview-dir audit/pseudo_hardhat_check  박스를 그린 jpg + preview_index.json(번호·stem·conf) — 대표가 번호로 채택/기각.

사용:
    python scripts/data/pseudo_hardhat.py --images D:/vigent_private_data/aihub/docs_507 --out D:/vigent_private_data/aihub/pseudo_507 \
        [--merge-into D:/vigent_private_data/aihub/vigent_507] [--conf 0.6] [--preview-n 100] [--limit 0]
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(_ROOT / "scripts" / "eval"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from aihub_to_vigent import CLASSES  # noqa: E402

IMG_EXTS = (".jpg", ".jpeg", ".png")
SOURCE = "pseudo:v1"
HARDHAT = CLASSES.index("Hardhat")
# [2026-09-27] 여러 클래스 준라벨(조끼 착용/미착용 등)로 일반화 — 기본은 Hardhat 하나(기존 동작·테스트 불변).
CSS_TO_STD = {"Hardhat": "Hardhat", "Safety Vest": "Safety-Vest", "NO-Safety Vest": "NO-Safety-Vest", "NO-Hardhat": "NO-Hardhat"}
ACTIVE_CLASSES: list[str] = ["Hardhat"]
ACTIVE_SOURCE: str = SOURCE          # Hardhat 단독이면 "pseudo:v1", 그 외는 "pseudo:v1:<클래스+...>" — 병합 중복 검사 키


def set_active(classes: list[str]) -> None:
    global ACTIVE_CLASSES, ACTIVE_SOURCE
    ACTIVE_CLASSES = list(classes)
    ACTIVE_SOURCE = SOURCE if classes == ["Hardhat"] else f"{SOURCE}:{'+'.join(classes)}"


def derive_rule(conf_min: float) -> str:
    return f"ppe_rfdetr_v1 {'/'.join(ACTIVE_CLASSES)} conf>={conf_min:.2f} [추정: 검출기 출력을 정답으로 — 육안 확인 후 채택]"


def pseudo_boxes(dets: list, W: int, H: int, conf_min: float) -> list[dict[str, Any]]:
    """dets 항목 = (x1,y1,x2,y2 px, conf) [Hardhat 로 간주] 또는 (cls_idx, box, conf). → 정규화 박스 dict(conf≥conf_min 만). 좌표는 이미지 안으로 자른다."""
    out = []
    for d in dets:
        cls, box, conf = (HARDHAT, d[0], d[1]) if len(d) == 2 else (int(d[0]), d[1], d[2])
        if conf < conf_min:
            continue
        x1, y1, x2, y2 = (max(0.0, min(W, box[0])), max(0.0, min(H, box[1])), max(0.0, min(W, box[2])), max(0.0, min(H, box[3])))
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        out.append({"cls": cls, "box": [round((x1 + x2) / 2 / W, 6), round((y1 + y2) / 2 / H, 6), round((x2 - x1) / W, 6), round((y2 - y1) / H, 6)],
                    "conf": round(float(conf), 4), "source": ACTIVE_SOURCE, "derived": True, "derive_rule": derive_rule(conf_min)})
    return out


def _lines(boxes: list[dict[str, Any]]) -> str:
    return "".join(f"{b['cls']} {' '.join(f'{v:.6f}' for v in b['box'])}\n" for b in boxes)


def write_pseudo(stem: str, file_name: str, boxes: list[dict[str, Any]], out: Path, merge_into: Path | None) -> dict[str, Any]:
    """out/ 에 준라벨을 쓰고, merge_into 에 같은 stem 라벨이 있으면 거기에도 덧붙인다(중복 덧붙임 방지: 사이드카 source 로 확인)."""
    (out / "labels").mkdir(parents=True, exist_ok=True); (out / "labels_meta").mkdir(exist_ok=True)
    (out / "labels" / f"{stem}.txt").write_text(_lines(boxes), encoding="utf-8")
    meta = {"file": file_name, "source": ACTIVE_SOURCE, "boxes": boxes}
    (out / "labels_meta" / f"{stem}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    rep = {"stem": stem, "n_boxes": len(boxes), "merged": False}
    if merge_into is not None:
        lb = merge_into / "labels" / f"{stem}.txt"; mt = merge_into / "labels_meta" / f"{stem}.json"
        if lb.exists():
            m = json.loads(mt.read_text(encoding="utf-8")) if mt.exists() else {"boxes": []}
            if any(b.get("source") == ACTIVE_SOURCE for b in m.get("boxes", [])):
                rep["merged"] = "already"          # 두 번 돌려도 두 배로 붙지 않는다(같은 클래스 묶음 기준)
            else:
                with lb.open("a", encoding="utf-8") as f:
                    f.write(_lines(boxes))
                m.setdefault("boxes", []).extend(boxes); m.setdefault("pseudo_merges", []).append({"source": ACTIVE_SOURCE, "n": len(boxes)})
                mt.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
                rep["merged"] = True
    return rep


def draw_preview(img_path: Path, boxes: list[dict[str, Any]], dst: Path, W: int, H: int) -> bool:
    import cv2
    import numpy as np
    data = np.fromfile(str(img_path), dtype=np.uint8)            # 한글 경로 대응
    im = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if im is None:
        return False
    for b in boxes:
        cx, cy, w, h = b["box"]
        x1, y1, x2, y2 = int((cx - w / 2) * W), int((cy - h / 2) * H), int((cx + w / 2) * W), int((cy + h / 2) * H)
        cv2.rectangle(im, (x1, y1), (x2, y2), (0, 200, 255), 2)
        cv2.putText(im, f"{CLASSES[int(b.get('cls', HARDHAT))]} {b['conf']:.2f}", (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 200, 255), 1)
    ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        return False
    buf.tofile(str(dst))
    return dst.exists() and dst.stat().st_size > 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="원천 이미지 루트(재귀)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--merge-into", default="", help="같은 stem 라벨이 있는 vigent_507 폴더 — 있으면 덧붙인다")
    ap.add_argument("--conf", type=float, default=0.6)
    ap.add_argument("--res", type=int, default=384)
    ap.add_argument("--preview-n", type=int, default=100)
    ap.add_argument("--preview-dir", default=str(_ROOT / "audit" / "pseudo_hardhat_check"))
    ap.add_argument("--seed", type=int, default=20260926)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stems-from", default="", help="이 폴더(labels/*.txt)에 라벨이 있는 stem 만 처리 — 변환본 학습 프레임에만 준라벨을 붙일 때")
    ap.add_argument("--classes", default="Hardhat", help="준라벨 클래스(쉼표). 예: Hardhat,Safety-Vest,NO-Safety-Vest — 2026-09-27 라벨 누락 메우기용")
    a = ap.parse_args()
    set_active([c.strip() for c in a.classes.split(",") if c.strip()])
    from aihub_smoke_eval import class_names_of, load_model
    from PIL import Image
    out = Path(a.out); merge = Path(a.merge_into) if a.merge_into else None
    imgs = sorted(p for p in Path(a.images).rglob("*") if p.suffix.lower() in IMG_EXTS)
    if a.stems_from:
        want = {p.stem for p in Path(a.stems_from).glob("*.txt")}
        imgs = [p for p in imgs if p.stem in want]
        print(f"  --stems-from {a.stems_from}: 라벨 있는 stem {len(want)} → 이미지 {len(imgs)}장으로 제한")
    if a.limit:
        imgs = imgs[: a.limit]
    print(f"[pseudo_hardhat] 이미지 {len(imgs)}장 — {a.images} · conf≥{a.conf} · 병합 대상 {merge or '없음'}")
    if not imgs:
        print("★이미지 0장 — 실패"); return 2
    model, dev = load_model("ppe", a.res)
    cn = class_names_of(model)
    id_to_cls = {k: CLASSES.index(CSS_TO_STD[v]) for k, v in cn.items() if CSS_TO_STD.get(v) in ACTIVE_CLASSES}
    hat_ids = set(id_to_cls)
    print(f"  ppe 모델 class_names {cn} → 준라벨 클래스 {ACTIVE_CLASSES} id {sorted(hat_ids)} · source {ACTIVE_SOURCE} · device {dev}")
    if not hat_ids:
        print("★모델에 요청한 클래스가 없다 — 실패"); return 2
    reps, t0 = [], time.time()
    n_boxes = 0; confs = []
    for i, p in enumerate(imgs, 1):
        im = Image.open(p).convert("RGB"); W, H = im.size
        det = model.predict(im, threshold=a.conf)
        dets = [(id_to_cls[int(cid)], [float(v) for v in box], float(c)) for box, cid, c in zip(det.xyxy, det.class_id, det.confidence) if int(cid) in hat_ids]
        boxes = pseudo_boxes(dets, W, H, a.conf)
        if boxes:
            rep = write_pseudo(p.stem, p.name, boxes, out, merge); rep.update({"path": str(p), "W": W, "H": H}); reps.append(rep)
            n_boxes += len(boxes); confs += [b["conf"] for b in boxes]
        if i % 200 == 0:
            print(f"  {i}/{len(imgs)} ({time.time() - t0:.0f}s) 박스 {n_boxes}")
    (out / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    stems = [r["stem"] for r in reps]
    (out / "split.json").write_text(json.dumps({"key": "pseudo", "train": stems, "val": [], "train_keys": ["pseudo"], "val_keys": []},
                                               ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"source": ACTIVE_SOURCE, "classes": ACTIVE_CLASSES, "conf_min": a.conf, "rule": derive_rule(a.conf), "images_scanned": len(imgs),
                                                   "images_with_boxes": len(reps), "boxes": n_boxes, "frames": reps}, ensure_ascii=False, indent=1), encoding="utf-8")
    # 규칙 11: 디스크 확인
    n_disk = len(list((out / "labels").glob("*.txt")))
    merged = sum(1 for r in reps if r["merged"] is True); already = sum(1 for r in reps if r["merged"] == "already")
    print(f"  결과: 박스 있는 이미지 {len(reps)}/{len(imgs)} · 박스 {n_boxes}(conf 중앙 {sorted(confs)[len(confs) // 2] if confs else '-'}) · "
          f"labels {n_disk}개(기대 {len(reps)}) · 병합 {merged}(이미 병합 {already}) → {out}")
    if n_disk != len(reps):
        print("★라벨 개수 불일치 — 실패"); return 1
    # 미리보기(육안 확인용) — 커밋 금지 폴더
    if a.preview_n and reps:
        pv = Path(a.preview_dir); pv.mkdir(parents=True, exist_ok=True)
        rnd = random.Random(a.seed); pick = rnd.sample(reps, min(a.preview_n, len(reps)))
        index = []; ok = 0
        for k, r in enumerate(pick, 1):
            boxes = json.loads((out / "labels_meta" / f"{r['stem']}.json").read_text(encoding="utf-8"))["boxes"]
            dst = pv / f"{k:03d}_{r['stem']}.jpg"
            if draw_preview(Path(r["path"]), boxes, dst, r["W"], r["H"]):
                ok += 1
            index.append({"no": k, "stem": r["stem"], "n_boxes": len(boxes), "conf": [b["conf"] for b in boxes], "file": dst.name})
        (pv / "preview_index.json").write_text(json.dumps({"conf_min": a.conf, "rule": derive_rule(a.conf), "items": index}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  미리보기 {ok}/{len(pick)}장 저장 → {pv} (preview_index.json 의 번호로 채택/기각을 알려주면 된다) ★커밋 금지")
        if ok != len(pick):
            print("★미리보기 저장 개수 불일치"); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
