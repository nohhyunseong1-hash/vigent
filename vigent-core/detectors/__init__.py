"""detectors — 검출 백엔드 어댑터 패키지 (T10a).

guard.py 가 특정 라이브러리에 직접 묶이지 않도록 슬롯별 '검출 백엔드'를 추상화한다.
  · YoloDetector   — 기존 ultralytics YOLO(.pt) 경로(AGPL). 저하0(기존 동작 보존).
  · RfdetrDetector — RF-DETR(Apache-2.0) 경로. person 등 COCO 클래스 이관 대상.
백엔드 선택은 vision.yaml `perception.backend`(슬롯→'yolo'|'rfdetr'), 기본 'yolo'.
"""
