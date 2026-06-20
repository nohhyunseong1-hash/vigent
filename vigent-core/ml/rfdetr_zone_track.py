"""§5 MVP 한 조각: 영상 → rf-detr 사람탐지 → trackers 추적 → PolygonZone 위험구역 침입 판정.

전부 permissive: rfdetr(Apache-2.0) · trackers(Apache-2.0) · supervision(MIT).
입력은 영상파일 / 웹캠(0) / RTSP URL 모두 가능 → 실제 카메라에 그대로 연결.

사용: python3 vigent-core/ml/rfdetr_zone_track.py <영상경로|0|rtsp://...> [출력.mp4]
출력: 박스+ID+위험구역 그린 영상 + 침입 이벤트 콘솔 출력.
"""
from __future__ import annotations

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

ROOT = Path(__file__).resolve().parent.parent.parent


def main(source: str, out: str | None = None) -> None:
    out = out or str(ROOT / "runs" / "rfdetr" / "zone_track_out.mp4")
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    # 입력 열기(파일/웹캠/RTSP)
    cap = cv2.VideoCapture(int(source) if source.isdigit() else source)
    if not cap.isOpened():
        print(f"❌ 입력 열기 실패: {source}"); return
    W = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 960
    H = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 540
    fps = cap.get(cv2.CAP_PROP_FPS) or 12

    # 위험구역(정규화 폴리곤) — 데모용 화면 좌측 60%. 나중에 vision.yaml 로 분리 예정.
    #   (실제 운영에선 사용자가 그린 구역 좌표를 주입)
    zone_poly = np.array([[0.0, 0.0], [0.6, 0.0], [0.6, 1.0], [0.0, 1.0]]) * [W, H]
    zone = sv.PolygonZone(polygon=zone_poly.astype(int))

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = RFDETRNano(device=device)
    try: model.optimize_for_inference()
    except Exception: pass
    tracker = SORTTracker()

    box_an = sv.BoxAnnotator(thickness=2)
    lbl_an = sv.LabelAnnotator()
    zone_an = sv.PolygonZoneAnnotator(zone=zone, color=sv.Color.RED, thickness=2)

    vw = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*"mp4v"), fps, (W, H))
    frame_i, intrusions, t0 = 0, 0, time.time()
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame_i += 1
        # 1) rf-detr 탐지 → 사람만
        det = model.predict(Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), threshold=0.4)
        names = np.array([COCO_CLASSES[c] for c in det.class_id])
        det = det[names == "person"]
        # 2) 추적(ID 부여)
        det = tracker.update(det)
        # 3) 위험구역 침입 판정
        in_zone = zone.trigger(det)            # 각 탐지의 구역내 여부(bool)
        n_in = int(in_zone.sum())
        if n_in > 0:
            intrusions += 1
            ids = det.tracker_id[in_zone] if det.tracker_id is not None else []
            print(f"[frame {frame_i}] ⚠ 위험구역 침입 {n_in}명 (ID={list(ids)})")
        # 4) 그리기
        labels = [f"ID:{tid} person" for tid in (det.tracker_id if det.tracker_id is not None else [-1]*len(det))]
        frame = box_an.annotate(frame, det)
        frame = lbl_an.annotate(frame, det, labels)
        frame = zone_an.annotate(frame)
        vw.write(frame)
    cap.release(); vw.release()
    dur = time.time() - t0
    print(f"\n✅ 완료: {frame_i}프레임 처리 · 침입발생 {intrusions}프레임 · "
          f"{frame_i/dur:.1f}fps(처리) · device={device}")
    print(f"   저장: {Path(out).relative_to(ROOT)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용: python3 vigent-core/ml/rfdetr_zone_track.py <영상|0|rtsp://...> [출력.mp4]")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
