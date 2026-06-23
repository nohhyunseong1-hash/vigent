"""config.py — VIGENT 얼굴 인식 설정 (임계값·경로·법적 토글)

설계 원칙(VIGENT 공통):
  - 절대 저하 없음 = 가산식 + 폴백: 모델이 없거나 실패하면 모듈만 비활성, 코어는 무중단.
  - 옵트인 기본: 얼굴 인식은 '민감정보' 처리이므로 환경변수로 명시 활성화하지 않으면 꺼져 있다.
  - 비밀키·경로는 코드가 아니라 환경변수(.env)로 주입.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── 경로 ─────────────────────────────────────────────────────
HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
DATA_DIR = HERE / "data"

# OpenCV Zoo 공개 모델(상용 허용 라이선스). download_models.py 로 받는다.
YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"      # 검출, MIT
SFACE_PATH = MODELS_DIR / "face_recognition_sface_2021dec.onnx"    # 인식, Apache-2.0

# 등록(갤러리) 저장 위치
GALLERY_META = DATA_DIR / "gallery.json"        # 사람 메타 + 동의 정보
GALLERY_EMB = DATA_DIR / "embeddings.npz"       # 얼굴 임베딩(생체 템플릿)
AUDIT_LOG = DATA_DIR / "fr_audit.jsonl"         # 감사추적(누가·언제·무엇을)

# ── 인식 임계값 ──────────────────────────────────────────────
# SFace 코사인 유사도: 같은 사람 ≈ 0.4~1.0, 다른 사람 ≈ 0~0.3.
# OpenCV 권장 0.363. 오인식(타인을 본인으로)을 줄이려고 기본을 약간 높게 둔다.
COSINE_THRESHOLD = float(os.environ.get("VIGENT_FR_THRESHOLD", "0.40"))

# 검출 신뢰도(낮으면 검출↑/오검출↑). 0.7 권장.
DETECT_SCORE_THRESHOLD = float(os.environ.get("VIGENT_FR_DET_SCORE", "0.7"))
DETECT_NMS_THRESHOLD = 0.3
DETECT_TOP_K = 5000

# ── 법적/프라이버시 토글 (개인정보보호법 대응) ───────────────
# 얼굴 인식 자체를 켜는 마스터 스위치. 기본 OFF(옵트인). API는 OFF면 403.
ENABLED = os.environ.get("VIGENT_FR_ENABLED", "0") == "1"

# 원본 얼굴 이미지를 저장할지. 기본 False(데이터 최소화 — 임베딩만 저장).
STORE_RAW_FACE = os.environ.get("VIGENT_FR_STORE_RAW", "0") == "1"

# 생체정보 보존기간(일). 지나면 purge 대상. 0 이하면 무기한(권장 안 함).
RETENTION_DAYS = int(os.environ.get("VIGENT_FR_RETENTION_DAYS", "365"))

# 임베딩 암호화 키(있으면 cryptography 로 암호화 저장). 없으면 평문+파일권한 0600 폴백.
ENCRYPTION_KEY = os.environ.get("VIGENT_FR_KEY", "")

# 한 사람당 보관할 최대 임베딩 수(여러 각도/조명으로 정확도↑, 과다 저장 방지).
MAX_EMB_PER_PERSON = 10

# ── 얼굴 품질 게이트 (정확도↑: 작거나 기울어진 얼굴 배제) ─────
# 얼굴 최소 한 변 픽셀. 너무 작은 얼굴은 임베딩 품질이 낮아 오인식 유발.
MIN_FACE_PX = int(os.environ.get("VIGENT_FR_MIN_FACE_PX", "60"))
# 두 눈을 잇는 선의 최대 기울기(도). 초과하면 과회전/역상으로 보고 배제.
MAX_EYE_TILT_DEG = float(os.environ.get("VIGENT_FR_MAX_TILT", "30"))


def model_files_present() -> bool:
    """검출·인식 모델 파일이 모두 있는지(없으면 download_models.py 안내)."""
    return YUNET_PATH.exists() and SFACE_PATH.exists()
