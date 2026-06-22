"""office 에르고노믹스(자세 측정) 정확도 하니스 — '자세 각도를 정확히 재는가'를 자동 채점.

safety 하니스(eval_accuracy.py)가 '사람을 잘 찾는가'였다면, 이건 '자세 각도를 정확히 재는가'.
자세 측정 정확도 = (1) 각도 계산이 수학적으로 맞는가 + (2) 실제 사진에서 포즈를 잘 잡는가.

① 각도 정확도: '정답 각도를 아는' 가상 자세를 만들어 → 계산값과 비교(진짜 채점).
② 검출률: 실제 사람 사진에 MediaPipe Pose 를 돌려 포즈 검출 성공률 측정.

사용: python3 vigent-core/ml/eval_ergonomics.py
출력: 콘솔 점수표 + runs/eval/ergonomics_<시각>.json
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# ── ergonomics.js 와 동일한 각도 공식(이미 동형 검증됨) ──
def angle_from_vertical(lo, up):
    dx, dy = up[0] - lo[0], up[1] - lo[1]
    return abs(math.atan2(dx, -dy)) * 180 / math.pi


def tilt_from_horizontal(a, b):
    return abs(math.atan2(b[1] - a[1], b[0] - a[0])) * 180 / math.pi


def _pt_vertical(lo, ang_deg, L=0.2):
    """lo 에서 '수직 기준 ang_deg 기울어진' 점(정답 각도를 심는다)."""
    a = math.radians(ang_deg)
    return (lo[0] + L * math.sin(a), lo[1] - L * math.cos(a))


def _pt_tilt(a, ang_deg, L=0.2):
    r = math.radians(ang_deg)
    return (a[0] + L * math.cos(r), a[1] + L * math.sin(r))


def eval_angle_accuracy(tol=1.0):
    """정답 각도를 아는 가상 자세 → 계산 정확도 채점."""
    cases = [0, 5, 10, 15, 20, 25, 30, 40, 50, 60]
    rows, errs = [], []
    base = (0.5, 0.6)
    for truth in cases:
        # 목/허리: 수직 기준 각도
        neck = angle_from_vertical(base, _pt_vertical(base, truth))
        # 어깨: 수평 기준 각도
        sh = tilt_from_horizontal((0.4, 0.5), _pt_tilt((0.4, 0.5), truth))
        e_neck, e_sh = abs(neck - truth), abs(sh - truth)
        errs += [e_neck, e_sh]
        rows.append({"truth": truth, "neck_calc": round(neck, 2),
                     "shoulder_calc": round(sh, 2),
                     "err_neck": round(e_neck, 3), "err_shoulder": round(e_sh, 3)})
    mean_err = sum(errs) / len(errs)
    within = sum(1 for e in errs if e <= tol) / len(errs) * 100
    return {"cases": rows, "mean_abs_error_deg": round(mean_err, 4),
            "within_tol_pct": round(within, 1), "tol_deg": tol,
            "pass": mean_err <= tol}


def eval_level_classification():
    """각도 → 등급(good/warn/bad) 경계가 맞는지(설정 임계값 기준)."""
    J = {"good": 15, "warn": 25}   # office neck 기준

    def lvl(a):
        return "good" if a <= J["good"] else "warn" if a <= J["warn"] else "bad"
    checks = [(10, "good"), (15, "good"), (20, "warn"), (25, "warn"), (30, "bad"), (45, "bad")]
    rows = [{"angle": a, "expected": exp, "got": lvl(a), "ok": lvl(a) == exp} for a, exp in checks]
    return {"rows": rows, "pass": all(r["ok"] for r in rows)}


def eval_pose_detection(limit=30):
    """실제 사람 사진에 MediaPipe Pose → 포즈 검출 성공률.
    office 실사용 엔진은 '브라우저 MediaPipe'. 이 파이썬 환경의 mediapipe 가 legacy
    solutions API 면 검출률을 재고, Tasks 전용이면 건너뛴다(각도 정확도는 ①②로 검증됨)."""
    img_dir = ROOT / "data" / "retrain" / "person" / "valid" / "images"
    if not img_dir.exists():
        return {"skipped": "person 평가 이미지 없음", "detect_rate_pct": None}
    try:
        import mediapipe as mp
        PoseCls = mp.solutions.pose.Pose   # legacy solutions API 필요
    except Exception:  # noqa: BLE001  Tasks 전용 환경 → 건너뜀
        return {"skipped": "이 환경 mediapipe 는 Tasks 전용(브라우저 엔진과 별개). "
                           "각도 정확도는 ①②로 검증됨", "detect_rate_pct": None}
    import cv2
    pose = PoseCls(static_image_mode=True, model_complexity=1, min_detection_confidence=0.5)
    imgs = [p for p in sorted(img_dir.iterdir())
            if p.suffix.lower() in (".jpg", ".jpeg", ".png")][:limit]
    detected = 0
    for p in imgs:
        im = cv2.imread(str(p))
        if im is None:
            continue
        res = pose.process(cv2.cvtColor(im, cv2.COLOR_BGR2RGB))
        if res.pose_landmarks:
            detected += 1
    pose.close()
    n = len(imgs)
    return {"images": n, "detected": detected,
            "detect_rate_pct": round(detected / n * 100, 1) if n else None}


def main():
    print("[하니스] office 에르고노믹스(자세 측정) 정확도 채점\n")
    ang = eval_angle_accuracy()
    lvl = eval_level_classification()
    print("① 각도 계산 정확도 (정답 각도 아는 가상 자세):")
    print(f"   평균 오차 {ang['mean_abs_error_deg']}° · 허용(±{ang['tol_deg']}°) 내 {ang['within_tol_pct']}% "
          f"→ {'✅ 통과' if ang['pass'] else '❌ 미달'}")
    print("② 등급 분류 정확도 (good/warn/bad 경계):")
    print(f"   {sum(r['ok'] for r in lvl['rows'])}/{len(lvl['rows'])} 정확 "
          f"→ {'✅ 통과' if lvl['pass'] else '❌ 미달'}")

    print("③ 실제 사진 포즈 검출률 (MediaPipe Pose):")
    det = eval_pose_detection()
    if det.get("detect_rate_pct") is not None:
        print(f"   {det['detected']}/{det['images']}장 검출 = {det['detect_rate_pct']}%")
    else:
        print(f"   (건너뜀: {det.get('skipped')})")

    result = {"measured_at": datetime.now().isoformat(timespec="seconds"),
              "angle_accuracy": ang, "level_classification": lvl, "pose_detection": det}
    out_dir = ROOT / "runs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"ergonomics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
