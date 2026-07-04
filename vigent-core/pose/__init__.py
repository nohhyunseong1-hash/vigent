"""pose — 포즈 추정 어댑터 패키지 (T10c).

yolov8n-pose(ultralytics/AGPL, 검출+포즈 일체형) → RTMPose(rtmlib/Apache-2.0, top-down) 이관.
출력은 기존 소비층 형식과 동일: 사람별 (kp_xy[17,2] 픽셀좌표, kp_cf[17]) · COCO-17 순서 보존.
"""
