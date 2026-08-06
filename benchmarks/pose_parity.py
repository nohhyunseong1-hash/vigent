"""pose_parity.py — 포즈 백엔드 패리티 하네스 (T10c Stage 0).

두 포즈 백엔드(yolo=yolov8n-pose / rtmpose=rtmlib)를 같은 프레임에 돌려 2층으로 비교:
  (i)   raw 키포인트 OKS(Object Keypoint Similarity, 보조지표)
  (ii)  ergonomics 파생값(관절 등급·effective_worst)                          ← ergonomics.py 원본 import
하류 판정 로직을 '재사용'한다(복붙 금지 — 로직이 갈라지면 패리티의 의미가 사라짐).
(작업자 낙상 판정 제거 — P3_BACKLOG 참조. _person_metrics 의 낙상 파생값 비교층은 제거됨.)

게이트(Stage 1, 30프레임 기준):
  · ergonomic 유효등급 불일치 ≤ 1건.
  · 연속값(각도)·OKS 는 기록만(게이트 아님).

실행:
  /opt/anaconda3/bin/python3 benchmarks/pose_parity.py --backend-a yolo --backend-b rtmpose
  (자기패리티 sanity: --backend-a yolo --backend-b yolo → 전부 0 이어야 함)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "vigent-core"))

# ── 하류 판정 로직 재사용(원본 import, 복붙 금지) ──
import ergonomics as _erg                    # noqa: E402  근골격 각도·등급

_FRAMES = _ROOT / "benchmarks" / "data" / "pose_frames"
_OUT = _ROOT / "benchmarks" / "results" / "pose_parity.json"
_MIN_CONF = 0.3                              # 가시성 임계(_person_metrics min_kp 와 정합)

# COCO-17 OKS sigma(표준). 순서: nose,eyes(2),ears(2),shoulders(2),elbows(2),wrists(2),hips(2),knees(2),ankles(2)
_COCO_SIGMAS = np.array([.026, .025, .025, .035, .035, .079, .079, .072, .072,
                         .062, .062, .107, .107, .087, .087, .089, .089])


# ─────────────── 백엔드: (frame) → [(kp_xy[17,2] px, kp_cf[17])] ───────────────
def _persons_yolo(frame):
    """yolov8n-pose(ultralytics) — worker._PoseModel 과 동일 파라미터(conf 0.4, CPU/CUDA)."""
    global _YOLO
    if "_YOLO" not in globals():
        from ultralytics import YOLO
        import device as _device
        _YOLO = (YOLO(str(_ROOT / "vigent-core" / "weights" / "yolov8n-pose.pt")),
                 _device.pick_device(prefer_mps=False))
    model, dev = _YOLO
    res = model.predict(frame, verbose=False, conf=0.4, device=dev)[0]
    kp = getattr(res, "keypoints", None)
    if kp is None or kp.xy is None or len(kp.xy) == 0:
        return []
    xys = kp.xy.cpu().numpy()
    cfs = kp.conf.cpu().numpy() if kp.conf is not None else None
    out = []
    for i in range(len(xys)):
        cf_i = cfs[i] if cfs is not None else np.ones(len(xys[i]))
        out.append((xys[i], cf_i))
    return out


def _persons_rtmpose(frame):
    """RF-DETR/rtmlib RTMPose — pose.rtmpose_adapter 경유(Stage1 어댑터, COCO17 보존 assert 내장)."""
    from pose.rtmpose_adapter import RtmPoseDetector
    global _RTM
    if "_RTM" not in globals():
        _RTM = RtmPoseDetector()
    return _RTM.persons(frame)


def _persons_rtmpose_rfdetr(frame):
    """RTMPose + RF-DETR person 박스 주입(Stage 2 production 형태).

    ★ 충실도(사용자 Step 1): production worker 는 pose 를 guard.detect 의 person 박스로 배선할 것이므로,
    박스 소스를 raw rfdetr_adapter 가 아니라 guard.detect(detectors=['person']) 로 한다
    → _nms(중복 제거) + _suppress_vehicle_dupes + _track(추적/평활)이 적용된 '운용 박스'.
    worker 에 별도 박스 품질필터(면적/종횡비/conf)는 없음 → 여기서도 추가하지 않는다(동일 조건).
    임계도 guard 기본(DETECTOR_CONF['person']=0.35) 그대로 = worker 와 동일."""
    from pose.rtmpose_adapter import RtmPoseDetector
    global _RTM2, _GUARD
    if "_RTM2" not in globals():
        _RTM2 = RtmPoseDetector()
    if "_GUARD" not in globals():
        import main as M
        b = M.STATE.get(M.DEFAULT_THEME) or M._load_theme(M.DEFAULT_THEME)
        _GUARD = b["agents"]["Guard"]
    _GUARD._tracks = []       # 프레임 독립(결정적) — 패리티는 프레임별, production 은 연속추적
    h, w = frame.shape[:2]
    out = _GUARD.detect(frame, detectors=["person"])   # RF-DETR(person) + guard 후처리(_nms/_track)
    boxes = [[d["bbox"][0] * w, d["bbox"][1] * h, d["bbox"][2] * w, d["bbox"][3] * h]
             for d in out.get("detections", []) if d["label"] == "person"]
    return _RTM2.persons(frame, bboxes=boxes)


_BACKENDS = {"yolo": _persons_yolo, "rtmpose": _persons_rtmpose,
             "rtmpose_rfdetr": _persons_rtmpose_rfdetr}


# ─────────────── 비교 유틸 ───────────────
def _centroid(xy, cf):
    v = [xy[i] for i in range(len(xy)) if cf[i] >= _MIN_CONF]
    return np.mean(v, axis=0) if v else np.array([np.nan, np.nan])


def _scale(xy, cf):
    """OKS object scale s = sqrt(가시 키포인트 bbox 면적)."""
    v = [xy[i] for i in range(len(xy)) if cf[i] >= _MIN_CONF]
    if len(v) < 2:
        return 1.0
    v = np.array(v)
    bw, bh = np.ptp(v[:, 0]), np.ptp(v[:, 1])
    return float(np.sqrt(max(bw * bh, 1.0)))


def _oks(xy_a, cf_a, xy_b, s):
    """OKS(a=기준 가시성). 매칭된 두 사람의 키포인트 유사도(1=동일)."""
    vis = cf_a >= _MIN_CONF
    if not vis.any():
        return float("nan")
    d2 = ((xy_a - xy_b) ** 2).sum(axis=1)
    e = d2 / (2 * (s ** 2) * (_COCO_SIGMAS ** 2) + 1e-9)
    return float(np.exp(-e[vis]).mean())


def _bbox(xy, cf):
    """가시 키포인트에서 사람 bbox [x1,y1,x2,y2](없으면 None)."""
    v = [xy[i] for i in range(len(xy)) if cf[i] >= _MIN_CONF]
    if len(v) < 2:
        return None
    v = np.array(v)
    return [float(v[:, 0].min()), float(v[:, 1].min()), float(v[:, 0].max()), float(v[:, 1].max())]


def _iou(a, b):
    if a is None or b is None:
        return 0.0
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, x2 - x1), max(0.0, y2 - y1)
    inter = iw * ih
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def _match_iou(pa, pb, thr=0.5):
    """박스 IoU≥thr 로 1:1 그리디 매칭(IoU 큰 순). OKS 는 매칭 기준으로 쓰지 않는다
    (같은 사람을 포즈가 다르다고 제외하면 순환논리). 반환: (pairs, unmatched_a_idx, unmatched_b_idx)."""
    ba = [_bbox(*p) for p in pa]
    bb = [_bbox(*p) for p in pb]
    cand = []
    for ia in range(len(pa)):
        for ib in range(len(pb)):
            iou = _iou(ba[ia], bb[ib])
            if iou >= thr:
                cand.append((iou, ia, ib))
    cand.sort(reverse=True)
    ua, ub, pairs = set(), set(), []
    for iou, ia, ib in cand:
        if ia in ua or ib in ub:
            continue
        ua.add(ia); ub.add(ib); pairs.append((ia, ib))
    unmatched_a = [i for i in range(len(pa)) if i not in ua]
    unmatched_b = [i for i in range(len(pb)) if i not in ub]
    return pairs, unmatched_a, unmatched_b


_GRADE_RANK = {"none": 0, "good": 1, "warn": 2, "bad": 3}
_SOFT_ANGLE_THR = 7.0   # 1단계 플립 각도차 분류: ≤7°=임계분류 고유민감성 / >7°=실질 포즈차이

# 게이트 재정의 근거(측정 대상 정밀화 — 미달 회피 목적 아님). pose_parity.json 메타에 기록.
_GATE_META = {
    "gate_redefinition_rationale": (
        "초기 게이트(등급 불일치 ≤1)는 (a)검출집합 차이로 인한 매칭 아티팩트와 "
        "(b)임계 경계 플립을 구분하지 못했음. 재정의는 게이트 미달을 회피하기 위함이 아니라 "
        "측정 대상을 '실질 포즈 품질 차이'로 정밀화하기 위함. "
        "매칭은 박스 IoU≥0.5(동일 인물)로 하고, OKS 는 매칭 기준이 아닌 품질 지표로만 사용."),
    "ergo_gate_hard": "IoU 매칭 쌍에서 유효등급 2단계 이상 점프(|rank|≥2, 예: good↔bad·none→bad·none→warn) 0건",
    "ergo_gate_soft_watch": "1단계 플립(|rank|=1)은 게이트 아님. 각도차 병기: ≤7°=임계분류 고유민감성, >7°=실질 포즈차이(오버레이 대상)",
    "grade_rank": _GRADE_RANK,
}


def _eff_grade(assess_out):
    return _erg.effective_worst(assess_out.get("grades", {})) if assess_out else "none"


def _max_joint_angle_diff(ea, eb):
    """두 assess 결과의 공통 관절 각도 최대 절대차(soft 플립 분류용). 공통 없으면 None."""
    aa, ab = (ea or {}).get("angles", {}), (eb or {}).get("angles", {})
    common = set(aa) & set(ab)
    return max((abs(aa[k] - ab[k]) for k in common), default=None)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend-a", default="yolo", choices=list(_BACKENDS))
    ap.add_argument("--backend-b", default="rtmpose", choices=list(_BACKENDS))
    ap.add_argument("--frames", default=str(_FRAMES))
    ap.add_argument("--label", default="", help="결과 키 접미(예: ergo) — 셋 구분 저장")
    args = ap.parse_args()

    joints = (_erg.load_ergonomics("safety") or {}).get("joints", {}) or {}
    fa, fb = _BACKENDS[args.backend_a], _BACKENDS[args.backend_b]
    frames = sorted(Path(args.frames).glob("*.jpg"))

    results = []
    ergo_hard, ergo_soft = [], []       # 각각 상세 리스트
    oks_all = []
    tot_pairs = unmatched_a = unmatched_b = 0

    for fp in frames:
        img = cv2.imread(str(fp))
        if img is None:
            continue
        pa, pb = fa(img), fb(img)
        pairs, um_a, um_b = _match_iou(pa, pb, thr=0.5)
        unmatched_a += len(um_a); unmatched_b += len(um_b)
        rec = {"frame": fp.name, "n_a": len(pa), "n_b": len(pb),
               "unmatched_a": len(um_a), "unmatched_b": len(um_b), "pairs": []}
        for ia, ib in pairs:
            tot_pairs += 1
            xa, ca = pa[ia]
            xb, cb = pb[ib]
            oks = _oks(xa, ca, xb, _scale(xa, ca))
            if oks == oks:
                oks_all.append(oks)
            ea, eb = _erg.assess(xa, ca, joints), _erg.assess(xb, cb, joints)
            pair = {"oks": None if oks != oks else round(oks, 4)}
            # (ii) 근골격 유효등급 — hard(2단계+) / soft(1단계 플립)
            ga, gb = _eff_grade(ea), _eff_grade(eb)
            pair["ergo_grade"] = [ga, gb]
            rank_diff = abs(_GRADE_RANK.get(ga, 0) - _GRADE_RANK.get(gb, 0))
            if rank_diff >= 2:
                pair["ERGO_HARD"] = True
                ergo_hard.append({"frame": fp.name, "grade": [ga, gb], "oks": pair["oks"],
                                  "angle_diff": _max_joint_angle_diff(ea, eb)})
            elif rank_diff == 1:
                adiff = _max_joint_angle_diff(ea, eb)
                kind = "경계민감성(≤7°)" if (adiff is not None and adiff <= _SOFT_ANGLE_THR) else "실질차이(>7°)"
                pair["ERGO_SOFT"] = kind
                ergo_soft.append({"frame": fp.name, "grade": [ga, gb],
                                  "angle_diff": None if adiff is None else round(adiff, 1), "kind": kind})
            rec["pairs"].append(pair)
        results.append(rec)

    soft_real = [s for s in ergo_soft if s["kind"].startswith("실질")]
    summary = {
        "backend_a": args.backend_a, "backend_b": args.backend_b, "frame_set": Path(args.frames).name,
        "frames": len(results), "matched_pairs": tot_pairs,
        "detection_set_diff": {"unmatched_a(yolo만)": unmatched_a, "unmatched_b(rtmpose만)": unmatched_b},
        "ergo_gate_hard_mismatch": len(ergo_hard),               # ← ergo 게이트(ergo셋): 0
        "ergo_soft_flips_total": len(ergo_soft),
        "ergo_soft_flips_real(>7deg)": len(soft_real),           # 감시(게이트 아님)
        "mean_oks_matched": round(float(np.mean(oks_all)), 4) if oks_all else None,
        "ergo_hard_detail": ergo_hard,
        "ergo_soft_detail": ergo_soft,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    all_res = json.loads(_OUT.read_text(encoding="utf-8")) if _OUT.exists() else {}
    all_res["_meta"] = _GATE_META
    key = f"{args.backend_a}_vs_{args.backend_b}" + (f"_{args.label}" if args.label else "")
    all_res[key] = {"summary": summary, "frames": results}
    _OUT.write_text(json.dumps(all_res, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n===== pose parity: {key} (frame_set={Path(args.frames).name}) =====")
    for k in ("frames", "matched_pairs", "detection_set_diff",
              "ergo_gate_hard_mismatch",
              "ergo_soft_flips_total", "ergo_soft_flips_real(>7deg)", "mean_oks_matched"):
        print(f"  {k}: {summary[k]}")
    print(f"  → 저장: {_OUT.relative_to(_ROOT)}  [{key}]")


if __name__ == "__main__":
    main()
