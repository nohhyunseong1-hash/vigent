#!/usr/bin/env python3
"""[오프라인 녹화] 영상 파일 → 현장 녹화(field_recorder)와 **같은 산출물**.

`scripts/field_recorder.py` 는 **실행 중인 서버 + 실시간 카메라**를 전제로 한다
(127.0.0.1:8010 을 폴링한다). 이미 찍어 둔 영상 파일에는 쓸 수 없다.
이 스크립트는 영상 파일을 **같은 판정 경로**(guard.detect → worker._derive)에 태워
현장 산출물과 같은 4종을 만든다.

  · overlay.mp4    검출 박스를 그린 영상(얼굴 비식별화 적용)
  · still_XXX.jpg  5초마다 낱장
  · dets.jsonl     프레임마다 detections·person_count·signals·fired
  · summary.md     장면 요약

★현장과 같게 맞춘 것
  · **판정 주기 2fps** — 운영 워커와 같다. 원본이 24fps 여도 2fps 로 솎아 넣는다.
  · guard.detect(detectors=[person, ppe]) → worker._derive 로 발화 판정.
  · 프레임마다 얼굴 비식별화(privacy.anonymize_faces) 후 박스를 그린다.

★현장과 다른 것(반드시 보고서에 적을 것)
  · 카메라가 다르다 — 현장은 Tapo C200 RTSP 640x360, 이건 휴대폰 촬영본이다.
  · 위험구역이 정의돼 있지 않고 차량·중장비가 없다 → **구역침입·근접 규칙은
    발화 자체가 불가능**하다. 그래서 두 규칙의 디바운서는 걸지 않는다(효과가 없다).

사용:
    python scripts/video_offline_recorder.py --video <파일> --scene 01_보호구착용 \\
           --out "D:/vigent_field/ladder_20260829"
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "vigent-core"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 라벨별 박스 색(BGR) — field_recorder.py 와 같은 규칙: 위반=빨강·사람=초록·착용=청록.
COLORS = {
    "person": (0, 200, 0),
    "forklift": (255, 120, 0),
    "hardhat": (200, 200, 0),
    "safety-vest": (200, 200, 0),
    "mask": (200, 200, 0),
    "no-hardhat": (0, 0, 255),
    "no-safety-vest": (0, 0, 255),
    "no-mask": (0, 100, 255),
}


def main() -> int:
    import app_state
    import cv2
    import privacy
    import worker

    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--scene", required=True, help="장면 이름(폴더명이 된다)")
    ap.add_argument("--out", required=True, help="출력 뿌리 폴더(저장소 밖을 쓸 것)")
    ap.add_argument("--fps", type=float, default=2.0, help="판정 주기(운영 워커와 같은 2fps)")
    ap.add_argument("--still-every", type=float, default=5.0)
    args = ap.parse_args()

    src = Path(args.video)
    if not src.exists():
        print(f"❌ 영상 없음: {src}")
        return 1
    out = Path(args.out) / args.scene
    out.mkdir(parents=True, exist_ok=True)

    guard = app_state.load_theme("safety")["agents"]["Guard"]
    st = guard.status()
    print(f"  검출기 {st.get('detectors_available')} · ppe_required={st.get('ppe_required')}")
    if st.get("ppe_config_warn"):
        print(f"  ★설정 경고: {st['ppe_config_warn']}")

    cap = cv2.VideoCapture(str(src))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    step = max(1, round(src_fps / args.fps))
    print(f"  원본 {w}x{h} {src_fps:.1f}fps {total}프레임 → {step}프레임마다 1장 "
          f"(판정 {src_fps / step:.2f}fps)")

    jl = (out / "dets.jsonl").open("w", encoding="utf-8")
    vw = None
    t_base = time.time()
    n = still_i = 0
    last_still = -1e9
    fired_count: dict[str, int] = {}
    label_frames: dict[str, int] = {}
    anon_fail = 0
    infer_ms: list[float] = []

    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % step:
            idx += 1
            continue
        idx += 1
        tick = (idx - 1) / src_fps                       # 영상 내 경과초

        t0 = time.perf_counter()
        res = guard.detect(frame, detectors=["person", "ppe"],
                           track_key=f"video:{args.scene}")
        infer_ms.append((time.perf_counter() - t0) * 1000)

        dets = res.get("detections", []) or []
        # ★현장과 같은 판정: 구역 없음(zone=[]) · 차량 없음 → 구역침입·근접은 발화 불가.
        fired = worker._derive(res, [], aspect_hw=h / w if w else None,
                               cid=args.scene, debouncer=None, prox_debouncer=None)

        person_boxes = [[d["bbox"][0] * w, d["bbox"][1] * h,
                         d["bbox"][2] * w, d["bbox"][3] * h]
                        for d in dets if str(d.get("label", "")).lower() == "person"]
        privacy._begin_call()
        shown = privacy.anonymize_faces(frame.copy(), person_boxes)
        if privacy.took_failure():
            anon_fail += 1

        for d in dets:
            lab = str(d.get("label", ""))
            label_frames[lab] = label_frames.get(lab, 0) + 1
            x1, y1, x2, y2 = (int(d["bbox"][0] * w), int(d["bbox"][1] * h),
                              int(d["bbox"][2] * w), int(d["bbox"][3] * h))
            c = COLORS.get(lab.lower(), (200, 200, 200))
            cv2.rectangle(shown, (x1, y1), (x2, y2), c, 2)
            cv2.putText(shown, f"{lab} {float(d.get('conf', 0)):.2f}",
                        (x1, max(14, y1 - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1, cv2.LINE_AA)
        for rule, _lvl, _note, _subj in fired:
            fired_count[rule] = fired_count.get(rule, 0) + 1
        if fired:
            cv2.putText(shown, "FIRED: " + ",".join(sorted({f[0] for f in fired})),
                        (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2, cv2.LINE_AA)
        cv2.putText(shown, f"{args.scene}  t={tick:5.1f}s", (8, h - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)

        if vw is None:
            vw = cv2.VideoWriter(str(out / "overlay.mp4"),
                                 cv2.VideoWriter_fourcc(*"mp4v"), args.fps, (w, h))
        vw.write(shown)

        if tick - last_still >= args.still_every:
            still_i += 1
            okj, buf = cv2.imencode(".jpg", shown, [cv2.IMWRITE_JPEG_QUALITY, 90])
            if okj:
                (out / f"still_{still_i:03d}.jpg").write_bytes(buf.tobytes())
            last_still = tick

        jl.write(json.dumps({
            "t": int((t_base + tick) * 1000),
            "video_t": round(tick, 3),
            "detections": [{"class": d.get("label"),
                            "score": round(float(d.get("conf", 0)), 3),
                            "bbox": [round(float(v), 4) for v in d.get("bbox", [0, 0, 0, 0])],
                            "id": d.get("tid", -1)} for d in dets],
            "person_count": len(person_boxes),
            "signals": res.get("signals", {}),
            "fired": sorted({f[0] for f in fired}),
        }, ensure_ascii=False) + "\n")
        n += 1

    cap.release()
    jl.close()
    if vw is not None:
        vw.release()

    med = sorted(infer_ms)[len(infer_ms) // 2] if infer_ms else 0.0
    lines = [
        f"# {args.scene} — 오프라인 판정 요약", "",
        f"- 원본: `{src.name}` · {w}x{h} · {src_fps:.1f}fps · {total}프레임 "
        f"({total / max(src_fps, 1):.1f}초)",
        f"- 판정: **{n}프레임** ({src_fps / step:.2f}fps 로 솎음 — 운영 워커와 같은 주기)",
        f"- 추론 시간 중앙값: {med:.0f}ms/프레임",
        f"- 얼굴 비식별화 실패 프레임: {anon_fail}", "",
        "## 검출 라벨별 프레임 수", "",
        "| 라벨 | 프레임 |", "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(label_frames.items(), key=lambda x: -x[1])]
    lines += ["", "## 발화(fired) 규칙별 프레임 수", "",
              "| 규칙 | 프레임 |", "|---|---|"]
    lines += ([f"| {k} | {v} |" for k, v in sorted(fired_count.items(), key=lambda x: -x[1])]
              or ["| (없음) | 0 |"])
    lines += [
        "", "## 이 측정의 한계", "",
        "- **안전대(하네스)는 감지 대상이 아니다** — PPE 모델 클래스에 없다.",
        "- **낙상·추락 판정 기능은 없다**(제품에서 영구 삭제됨).",
        "- 위험구역이 정의돼 있지 않고 차량·중장비가 없어 "
        "**구역침입·근접 규칙은 발화 자체가 불가능**하다.",
        "- 정답 라벨이 없다 — 아래 수치는 **시스템이 무엇을 봤는가**이지 정확도가 아니다.",
    ]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  ✅ {n}프레임 · 스틸 {still_i}장 · 추론 중앙값 {med:.0f}ms")
    print(f"     라벨 {dict(sorted(label_frames.items(), key=lambda x: -x[1]))}")
    print(f"     발화 {fired_count or '없음'}")
    print(f"     → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
