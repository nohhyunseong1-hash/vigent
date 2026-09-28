"""defaults.py — 검출 운용점의 **코드 기본값 단일 출처**. [CODE_AUDIT_20260928 #6, 2026-09-28]

★왜: guard.py 의 클래스 상수(DETECTOR_CONF person 0.35·ppe 0.55·forklift 0.55·fire 0.70, IMGSZ 960)가 config/tuning.yaml
  (person 0.40·ppe 0.35·forklift 0.002·fire_smoke 0.55, imgsz 384)과 달랐다. 정상 기동에서는 yaml 이 덮어써서 안 보이지만
  tuning.yaml 이 없거나 키가 빠지면 PPE 임계 0.55·해상도 960 으로 **조용히** 다른 운용점이 됐다.
  이제 코드 기본값은 여기 한 곳이고, 값은 tuning.yaml 과 같다(tests/test_audit_fix6_defaults.py 가 두 곳을 대조한다).
  rfdetr_service·detectors/rfdetr_adapter·scripts 도 384/0.40 을 여기서 가져온다.
운용점을 바꾸려면 config/tuning.yaml 을 바꾼다 — 이 파일은 "yaml 이 없을 때의 값"이지 튜닝 위치가 아니다.
"""
from __future__ import annotations

RES: int = 384                       # detect.imgsz — RF-DETR 로드 시점 해상도(호출별 변경 불가)
DEFAULT_CONF: float = 0.30           # 검출기 목록에 없는 슬롯의 임계(폴백)
CONF: dict[str, float] = {           # detect.conf.<slot>
    "person": 0.40,
    "ppe": 0.35,
    "forklift": 0.002,               # F-7 측정용 값 — 운용은 프로파일(academy 0.50)이 덮는다
    "fire_smoke": 0.55,
}
PERSON_THRESHOLD: float = CONF["person"]   # rfdetr_service.detect_threshold 폴백
