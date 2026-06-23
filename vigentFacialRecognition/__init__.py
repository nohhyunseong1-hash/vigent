"""vigentFacialRecognition — VIGENT 얼굴 인식 모듈

상용 허용 라이선스(YuNet MIT + SFace Apache-2.0) 기반의 얼굴 검출·인식.
개인정보보호법(생체정보=민감정보) 대응: 옵트인 기본 OFF, 동의 기록, 보존기간,
감사추적, 데이터 최소화, 잊혀질 권리.

빠른 시작:
    1) 모델 받기:   python -m vigentFacialRecognition.download_models
    2) 옵트인 켜기:  export VIGENT_FR_ENABLED=1   (동의 절차 완료 후에만)
    3) 코드:
        from vigentFacialRecognition import enroll_person, identify
        identify(frame)   # -> [Match, ...]
"""
from .config import COSINE_THRESHOLD, ENABLED, model_files_present
from .privacy import Consent, FacialRecognitionDisabled
from .recognizer import Match, identify, identify_timed


def enroll_person(person_id, name, images, *, purpose, consented_by, retention_days=None):
    """간편 등록 헬퍼. images=BGR ndarray 리스트."""
    from . import config
    from .enrollment import get_store
    c = Consent(purpose=purpose, consented_by=consented_by,
                retention_days=retention_days or config.RETENTION_DAYS)
    return get_store().add_person(person_id, name, images, c)


__all__ = [
    "identify", "identify_timed", "enroll_person", "Match", "Consent",
    "FacialRecognitionDisabled", "ENABLED", "COSINE_THRESHOLD", "model_files_present",
]
