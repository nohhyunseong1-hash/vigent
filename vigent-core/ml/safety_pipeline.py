"""§5 통합 MVP — 영상 → rf-detr 탐지 → trackers 추적 → PolygonZone 침입 →
   (침입 시) mlx-vlm 위험요약 JSON. 전부 permissive · 로컬(MLX), 외부전송 없음.

사용: python3 vigent-core/ml/safety_pipeline.py <영상|0|rtsp://...> [--no-vlm]
출력: 주석 영상 + 침입 이벤트별 위험요약 JSON(runs/safety/events.jsonl)
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
import torch
from PIL import Image

from rfdetr import RFDETRNano
from rfdetr.util.coco_classes import COCO_CLASSES
from trackers import SORTTracker

from rfdetr_zone_track import load_zone_config   # 설정 로더 재사용

ROOT = Path(__file__).resolve().parent.parent.parent
VLM_COOLDOWN_S = 8.0          # 같은 이벤트 반복 호출 방지(VLM 무거움)


def main(source: str, use_vlm: bool = True) -> None:
    out_dir = ROOT / "runs" / "safety"
    out_dir.mkdir(parents=True, exist_ok=True)
    events_log = out_dir / "events.jsonl"

    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        print(f"❌ 입력 열기 실패: {source}"); return
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 960
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 540
    fps = cap.get(cv2.CAP_PROP_FPS) or 12

    pts_norm, threshold = load_zone_config("safety")
    if len(pts_norm) < 3:
        pts_norm = [(0.0, 0.0), (0.6, 0.0), (0.6, 1.0), (0.0, 1.0)]
    zone = sv.PolygonZone(polygon=(np.array(pts_norm) * [W, H]).astype(int))

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = RFDETRNano(device=device)
    try: model.optimize_for_inference()
    except Exception: pass
    tracker = SORTTracker()

    # VLM 은 옵션(무거움). 필요할 때만 1회 로드.
    vlm = None
    if use_vlm:
        from vlm_risk_summary import RiskVLM
        vlm = RiskVLM()

    box_an = sv.BoxAnnotator(thickness=2)
    lbl_an = sv.LabelAnnotator()
    zone_an = sv.PolygonZoneAnnotator(zone=zone, color=sv.Color.RED, thickness=2)
    vw = cv2.VideoWriter(str(out_dir / "pipeline_out.mp4"),
                         cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))

    last_vlm = 0.0
    frame_i = 0
    with open(events_log, "w", encoding="utf-8") as elog:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            frame_i += 1
            det = model.predict(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)),
                                threshold=threshold)
            names = np.array([COCO_CLASSES[c] for c in det.class_id])
            det = det[names == "person"]
            det = tracker.update(det)
            in_zone = zone.trigger(det)
            n_in = int(in_zone.sum())

            labels = [f"ID:{t}" for t in (det.tracker_id if det.tracker_id is not None else [-1] * len(det))]
            frame = box_an.annotate(frame, det)
            frame = lbl_an.annotate(frame, det, labels)
            frame = zone_an.annotate(frame)

            # 침입 발생 → 이벤트 기록 (+ 쿨다운 지나면 VLM 위험요약)
            if n_in > 0:
                ids = list(det.tracker_id[in_zone]) if det.tracker_id is not None else []
                event = {"frame": frame_i, "ts": round(frame_i / fps, 2),
                         "rule": "zone_intrusion", "count": n_in, "ids": [int(i) for i in ids]}
                now = time.time()
                if vlm is not None and now - last_vlm >= VLM_COOLDOWN_S:
                    last_vlm = now
                    snap = out_dir / f"event_{frame_i}.jpg"
                    cv2.imwrite(str(snap), frame)
                    t = time.time()
                    event["vlm"] = vlm.summarize(str(snap))
                    print(f"[frame {frame_i}] ⚠ 침입 {n_in}명 → VLM 요약 {time.time()-t:.1f}s: "
                          f"{event['vlm'].get('위험등급','?')} · {event['vlm'].get('위험요인','')[:40]}")
                else:
                    print(f"[frame {frame_i}] ⚠ 침입 {n_in}명 (ID={ids})")
                elog.write(json.dumps(event, ensure_ascii=False) + "\n"); elog.flush()
            vw.write(frame)
    cap.release(); vw.release()
    print(f"\n✅ 완료: {frame_i}프레임 · 이벤트로그 {events_log.relative_to(ROOT)} · "
          f"영상 {(out_dir/'pipeline_out.mp4').relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python3 vigent-core/ml/safety_pipeline.py <영상|0|rtsp://...> [--no-vlm]")
        sys.exit(1)
    main(sys.argv[1], use_vlm=("--no-vlm" not in sys.argv))
