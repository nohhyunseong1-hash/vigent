"""webcam_bench.py — 웹캠(out-of-domain) 종합 실측 (VIGENT-MAX Phase 1).

측정 전용. 임계·모델·guard·프론트 무수정. 서버 HTTP(/detect/frame) stateless = 배포.
realtime_core.js 캡처 재현: 원본 → maxW=640 다운스케일(비율유지) + JPEG 0.72 → image_base64.

PPE 착용/미착용 분리 평가(css_safety 10클래스, guard 정규화 라벨 기준):
  착용   Hardhat / Safety Vest / Mask   → positive 착용 recall
  미착용 NO-Hardhat / NO-Safety Vest / NO-Mask → 미착용 감지 recall(안전목적)
  Person + 기타(Safety Cone/machinery/vehicle/forklift/fire/smoke) → negative FAR 유형

입력: webcam_bench/raw/ + labels.json. 산출: negative FAR(유형별), positive recall(거리별), conf 분포, latency.
실행: python3 benchmarks/webcam_bench.py --port 8011 --stack rfdetr
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import time
from collections import defaultdict
from pathlib import Path

import env_guard

_ROOT = Path(__file__).resolve().parent.parent
_RAW = _ROOT / "data/datasets/webcam_bench/raw"
_LABELS = _ROOT / "data/datasets/webcam_bench/labels.json"

# 반환 라벨(소문자) → (표준 클래스, 착용상태). guard 정규화: 공백→하이픈, 소문자.
_NORM = {
    "hardhat": ("hardhat", "worn"), "no-hardhat": ("hardhat", "none"),
    "safety vest": ("vest", "worn"), "safety-vest": ("vest", "worn"),
    "no-safety vest": ("vest", "none"), "no-safety-vest": ("vest", "none"),
    "mask": ("mask", "worn"), "no-mask": ("mask", "none"),
    "person": ("person", None),
}
_OTHER = {"safety cone", "safety-cone", "machinery", "vehicle", "forklift", "fire", "smoke"}
_PPE = ["hardhat", "vest", "mask"]


def _encode_640(img_path: Path) -> str:
    """realtime_core.js 재현: maxW=640 다운스케일(비율유지) + JPEG 0.72 → base64."""
    from PIL import Image
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    scale = min(1.0, 640 / (W or 640))
    if scale < 1.0:
        im = im.resize((max(1, round(W * scale)), max(1, round(H * scale))), Image.BILINEAR)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode()


def _post_detect(port: int, b64: str) -> dict:
    """서버 /detect/frame(stateless=측정=배포). ppe 안전모드 + reset_tracks."""
    import urllib.request
    body = json.dumps({"image_base64": b64, "ppe": True, "safety_only": True,
                       "reset_tracks": True, "imgsz": 640}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/detect/frame",
                                 data=body, headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        out = json.loads(r.read())
    out["_latency_ms"] = round((time.time() - t0) * 1000, 1)
    return out


# ── (B) 구 YOLO 백엔드: "그때 그 설정" 복원(측정 전용, 배포 무영향) ──
# 구 배포 임계(tuning 주석): ppe 0.62 + override(NO-* 하향), forklift 0.68, fire_smoke 0.55.
_YOLO_THR = {
    "hardhat": 0.62, "mask": 0.62, "safety vest": 0.62, "person": 0.62,
    "no-hardhat": 0.30, "no-mask": 0.50, "no-safety vest": 0.50,
    "safety cone": 0.62, "machinery": 0.62, "vehicle": 0.62,
    "forklift": 0.68, "load": 0.68,
    "fire": 0.55, "smoke": 0.55, "default": 0.55,
}
_YOLO_MODELS = None


def _load_yolo():
    global _YOLO_MODELS
    if _YOLO_MODELS is None:
        from ultralytics import YOLO
        arch = _ROOT / "VIGENT_archive/VIGENT_safety/vigent-core/weights"
        _YOLO_MODELS = {
            "ppe": YOLO(str(_ROOT / "vigent-core/weights/ppe_css_v1.pt")),
            "forklift": YOLO(str(arch / "forklift_boda_ax.pt")),
            "fire_smoke": YOLO(str(arch / "fire_smoke_boda.pt")),
        }
    return _YOLO_MODELS


def _predict_yolo(img_path: Path) -> dict:
    """구 YOLO 3종 추론 → 구 임계(override) 적용 → detections(서버와 동일 형식). 640 입력(측정=배포)."""
    import time
    from PIL import Image
    im = Image.open(img_path).convert("RGB")
    W, H = im.size
    scale = min(1.0, 640 / (W or 640))
    if scale < 1.0:
        im = im.resize((max(1, round(W * scale)), max(1, round(H * scale))), Image.BILINEAR)
    models = _load_yolo()
    dets = []
    t0 = time.time()
    for m in models.values():
        res = m.predict(im, conf=0.01, verbose=False)[0]
        for b in res.boxes:
            cls = m.names[int(b.cls)]
            sc = float(b.conf)
            if sc < _YOLO_THR.get(cls.lower(), 0.5):   # 구 클래스별 임계
                continue
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            dets.append({"class": cls, "score": sc, "bbox": [x1, y1, x2 - x1, y2 - y1]})
    return {"detections": dets, "_latency_ms": round((time.time() - t0) * 1000, 1)}


def _presence(dets: list) -> tuple[dict, list]:
    """detections → {('hardhat','worn'):conf, ('person',None):conf, ('other','<lbl>'):conf} 최대conf."""
    p = defaultdict(float)
    other = []
    for d in dets:
        lbl = (d.get("class") or "").strip().lower()
        conf = float(d.get("score") or 0.0)
        if lbl in _NORM:
            cls, worn = _NORM[lbl]
            p[(cls, worn)] = max(p[(cls, worn)], conf)
        elif lbl in _OTHER:
            p[("other", lbl)] = max(p[("other", lbl)], conf)
            other.append(lbl)
    return dict(p), other


def _has(pres: dict, cls: str, worn) -> float:
    return pres.get((cls, worn), 0.0)


def main():
    env_guard.warn_if_docker_running("webcam_bench")
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8011)
    ap.add_argument("--backend", default="server", choices=["server", "yolo"], help="server=RF-DETR(8011), yolo=구YOLO 직접")
    ap.add_argument("--stack", default="rfdetr")
    ap.add_argument("--raw", default=str(_RAW))
    ap.add_argument("--labels", default=str(_LABELS))
    ap.add_argument("--out", default=None)
    ap.add_argument("--warmup", type=int, default=1, help="첫 N장 latency 집계 제외(모델 warmup)")
    args = ap.parse_args()

    raw_dir = Path(args.raw)
    labels = json.loads(Path(args.labels).read_text()) if Path(args.labels).exists() else {}
    imgs = sorted(p for p in raw_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not imgs:
        print(f"[webcam_bench] 이미지 없음: {raw_dir} — 촬영 후 재실행")
        return

    records = []
    for i, p in enumerate(imgs):
        out = _predict_yolo(p) if args.backend == "yolo" else _post_detect(args.port, _encode_640(p))
        pres, other = _presence(out.get("detections", []))
        gt = labels.get(p.name, {})
        records.append({"file": p.name, "kind": gt.get("kind"), "distance": gt.get("distance"),
                        "state": gt.get("state"),
                        "gt": {k: gt.get(k) for k in _PPE + ["person"]},
                        "pred": {f"{c}:{w}": round(v, 3) for (c, w), v in pres.items()},
                        "dets": [{"class": d.get("class"), "score": round(float(d.get("score") or 0), 3),
                                  "bbox": [round(x) for x in d.get("bbox", [])]}
                                 for d in out.get("detections", [])],   # ③ 좌표 어긋남 진단 재료
                        "other": other, "n_det": len(out.get("detections", [])),
                        "latency_ms": out.get("_latency_ms"), "_pres": pres})

    negs = [r for r in records if r["kind"] == "neg"]
    poss = [r for r in records if r["kind"] == "pos"]
    lat = sorted(r["latency_ms"] for i, r in enumerate(records) if i >= args.warmup and r["latency_ms"])

    summary = {"stack": args.stack, "n_images": len(records), "n_neg": len(negs), "n_pos": len(poss),
               "latency_p50_ms": lat[len(lat)//2] if lat else None,
               "latency_p95_ms": lat[int(len(lat)*0.95)] if lat else None}

    # negative FAR: 사람 없는 이미지에서 person/PPE(착용·미착용)/기타 검출 = 오탐. 유형·conf 기록.
    far = {"any_detection_pct": round(len([r for r in negs if r["n_det"] > 0])/len(negs)*100, 1) if negs else None}
    for cls in _PPE:
        fp = [r for r in negs if _has(r["_pres"], cls, "worn") > 0]
        far[f"{cls}(worn)"] = {"fp": len(fp), "far_pct": round(len(fp)/len(negs)*100, 1) if negs else None,
                               "conf": sorted(round(_has(r["_pres"], cls, "worn"), 3) for r in fp)}
    fp_person = [r for r in negs if _has(r["_pres"], "person", None) > 0]
    far["person"] = {"fp": len(fp_person), "far_pct": round(len(fp_person)/len(negs)*100, 1) if negs else None,
                     "conf": sorted(round(_has(r["_pres"], "person", None), 3) for r in fp_person)}
    # forklift/fire/smoke/기타 클래스별 FAR% + conf 분포(②의 forklift 저임계 오탐 정량 포함)
    for cls in ["forklift", "fire", "smoke", "vehicle", "machinery", "safety cone"]:
        fp = [r for r in negs if r["_pres"].get(("other", cls), 0) > 0]
        if fp or cls in ("forklift", "fire", "smoke"):
            far[cls] = {"fp": len(fp), "far_pct": round(len(fp)/len(negs)*100, 1) if negs else None,
                        "conf": sorted(round(r["_pres"][("other", cls)], 3) for r in fp)}
    summary["negative_FAR"] = far

    # positive: 착용 recall(gt=worn→Worn검출) + 미착용 감지 recall(gt=none&person→NO-검출)
    def recall(subset, cls, gt_state, pred_worn):
        gtset = [r for r in subset if r["gt"].get(cls) == gt_state and (gt_state != "none" or r["gt"].get("person"))]
        hit = [r for r in gtset if _has(r["_pres"], cls, pred_worn) > 0]
        return {"n_gt": len(gtset), "recall": round(len(hit)/len(gtset)*100, 1) if gtset else None}
    summary["positive_worn_recall"] = {c: recall(poss, c, "worn", "worn") for c in _PPE}
    summary["positive_none_detect"] = {c: recall(poss, c, "none", "none") for c in _PPE}
    summary["person_recall"] = {"n_gt": len([r for r in poss if r["gt"].get("person")]),
                                "recall": round(len([r for r in poss if r["gt"].get("person") and _has(r["_pres"], "person", None) > 0])
                                                 / max(1, len([r for r in poss if r["gt"].get("person")]))*100, 1)}
    summary["by_distance"] = {
        dist: {"worn": {c: recall([r for r in poss if r["distance"] == dist], c, "worn", "worn") for c in _PPE}}
        for dist in ("near", "mid", "far")}

    # ★ pos_bare 주변 오탐: 사람만 있는(맨몸) 프레임에서 forklift(사람오인)/PPE worn(없는데) 오탐 정량
    bare = [r for r in poss if r["state"] == "bare"]
    spur = {"n_bare": len(bare)}
    for cls in ["forklift", "fire", "smoke"]:
        fp = [r for r in bare if r["_pres"].get(("other", cls), 0) > 0]
        spur[cls] = {"fp": len(fp), "pct": round(len(fp)/len(bare)*100, 1) if bare else None,
                     "conf": sorted(round(r["_pres"][("other", cls)], 3) for r in fp)}
    for cls in _PPE:
        fp = [r for r in bare if _has(r["_pres"], cls, "worn") > 0]
        spur[f"{cls}(worn)"] = {"fp": len(fp), "pct": round(len(fp)/len(bare)*100, 1) if bare else None,
                                "conf": sorted(round(_has(r["_pres"], cls, "worn"), 3) for r in fp)}
    summary["pos_bare_spurious"] = spur

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for r in records:
        r.pop("_pres", None)
    out_path = Path(args.out) if args.out else _ROOT / "benchmarks/results" / f"webcam_{args.stack}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2))
    print(f"\n저장: {out_path}")


if __name__ == "__main__":
    main()
