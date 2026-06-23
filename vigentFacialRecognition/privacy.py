"""privacy.py — 법적/프라이버시 준수 레이어 (개인정보보호법 대응)

얼굴 임베딩은 개인정보보호법상 '생체정보 = 민감정보'다. 본 모듈은 다음을 강제한다:
  1) 옵트인: config.ENABLED 가 꺼져 있으면 어떤 인식/등록도 거부(require_enabled).
  2) 동의 기록: 사람을 등록하려면 동의 메타(목적·동의자·시각·보존기간)가 필수.
  3) 보존기간: RETENTION_DAYS 경과 데이터는 만료 → purge 대상.
  4) 감사추적: 등록·식별·삭제·열람을 append-only 로그로 남긴다.
  5) 데이터 최소화: 기본은 임베딩만 저장(원본 얼굴 미저장), 가능하면 암호화.
  6) 잊혀질 권리: 사람 단위 완전 삭제 지원(enrollment.delete_person).

※ 코드는 기술적 안전장치일 뿐, 실제 운영에는 동의서·고지·노사협의·DPIA 등 절차가
   별도로 필요하다. README 의 '법적 체크리스트' 참조.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from . import config

KST = timezone(timedelta(hours=9))


class FacialRecognitionDisabled(RuntimeError):
    """옵트인이 꺼져 있는데 인식/등록을 시도할 때."""


def now_iso() -> str:
    return datetime.now(KST).isoformat(timespec="seconds")


def require_enabled() -> None:
    """얼굴 인식이 명시적으로 켜져 있지 않으면 막는다(법적 기본값=OFF)."""
    if not config.ENABLED:
        raise FacialRecognitionDisabled(
            "얼굴 인식이 비활성 상태입니다. 동의·고지 절차를 갖춘 뒤 "
            "환경변수 VIGENT_FR_ENABLED=1 로만 활성화하세요."
        )


@dataclass
class Consent:
    """한 사람의 생체정보 처리 동의 기록."""
    purpose: str                       # 처리 목적(예: '현장 출입통제')
    consented_by: str                  # 동의자/책임자 식별
    consented_at: str = field(default_factory=now_iso)
    retention_days: int = field(default_factory=lambda: config.RETENTION_DAYS)

    def expires_at(self) -> str:
        base = datetime.fromisoformat(self.consented_at)
        return (base + timedelta(days=self.retention_days)).isoformat(timespec="seconds")

    def is_expired(self) -> bool:
        if self.retention_days <= 0:
            return False
        return datetime.now(KST) > datetime.fromisoformat(self.expires_at())


def audit(action: str, **detail) -> None:
    """감사 로그 1줄 추가(append-only). 실패해도 본 기능을 막지 않는다."""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        rec = {"ts": now_iso(), "action": action, **detail}
        with open(config.AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            os.chmod(config.AUDIT_LOG, 0o600)
        except OSError:
            pass
    except Exception:
        pass


# ── 임베딩 암호화(선택) ──────────────────────────────────────
# cryptography 가 설치돼 있고 키가 있으면 Fernet 로 암호화. 없으면 평문+파일권한 폴백.
def _fernet():
    key = config.ENCRYPTION_KEY
    if not key:
        return None
    try:
        import base64
        import hashlib

        from cryptography.fernet import Fernet
    except Exception:
        return None
    # 사용자가 임의 문자열을 줘도 되도록 32바이트로 파생.
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_bytes(raw: bytes) -> tuple[bytes, bool]:
    """(데이터, 암호화됨?) — 키·라이브러리 있으면 암호화, 없으면 원본 그대로."""
    f = _fernet()
    if f is None:
        return raw, False
    return f.encrypt(raw), True


def decrypt_bytes(data: bytes, encrypted: bool) -> bytes:
    if not encrypted:
        return data
    f = _fernet()
    if f is None:
        raise RuntimeError("암호화된 데이터인데 복호화 키(VIGENT_FR_KEY)가 없습니다.")
    return f.decrypt(data)


def encryption_status() -> str:
    if not config.ENCRYPTION_KEY:
        return "off (키 미설정 — 평문+파일권한 0600 저장)"
    return "on (Fernet)" if _fernet() is not None else "키는 있으나 cryptography 미설치 → 폴백"
