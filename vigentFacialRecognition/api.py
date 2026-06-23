"""api.py — FastAPI 라우터 (/facial/*)

VIGENT 코어(main.py)에 나중에 한 줄로 장착:
    from vigentFacialRecognition.api import router as facial_router
    app.include_router(facial_router)

옵트인(ENABLED) OFF면 상태 조회를 빼고 전부 403 → 법적 기본값 보호.
"""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Body, File, Form, HTTPException, UploadFile

from . import config, privacy
from .privacy import Consent, FacialRecognitionDisabled

router = APIRouter(prefix="/facial", tags=["facial-recognition"])


def _decode(data: bytes) -> np.ndarray:
    import cv2
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "이미지를 디코딩할 수 없습니다.")
    return img


@router.get("/status")
def status():
    """모듈 상태(옵트인·모델·암호화·등록 인원). 항상 조회 가능."""
    out = {
        "enabled": config.ENABLED,
        "models_present": config.model_files_present(),
        "threshold": config.COSINE_THRESHOLD,
        "retention_days": config.RETENTION_DAYS,
        "store_raw_face": config.STORE_RAW_FACE,
        "encryption": privacy.encryption_status(),
    }
    if config.ENABLED and config.model_files_present():
        from .enrollment import get_store
        out["persons"] = len(get_store().list_persons())
    return out


@router.post("/enroll")
async def enroll(
    person_id: str = Form(...),
    name: str = Form(...),
    purpose: str = Form(...),
    consented_by: str = Form(...),
    retention_days: int = Form(config.RETENTION_DAYS),
    images: list[UploadFile] = File(...),
):
    """사람 등록. 동의 메타(purpose·consented_by) 필수 — 없으면 422."""
    try:
        privacy.require_enabled()
        from .enrollment import get_store
        imgs = [_decode(await f.read()) for f in images]
        c = Consent(purpose=purpose, consented_by=consented_by, retention_days=retention_days)
        p = get_store().add_person(person_id, name, imgs, c)
        return {"ok": True, "person_id": p.person_id, "n_embeddings": p.n_embeddings,
                "expires_at": p.consent.expires_at()}
    except FacialRecognitionDisabled as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/identify")
async def identify_ep(image: UploadFile = File(...), threshold: float | None = Form(None)):
    """이미지 1장에서 얼굴 식별."""
    try:
        privacy.require_enabled()
        from .recognizer import identify_timed
        img = _decode(await image.read())
        matches, ms = identify_timed(img, threshold=threshold)
        return {
            "ok": True, "elapsed_ms": round(ms, 1),
            "faces": [
                {"bbox": m.bbox, "person_id": m.person_id, "name": m.name,
                 "similarity": m.similarity, "detect_score": m.detect_score}
                for m in matches
            ],
        }
    except FacialRecognitionDisabled as e:
        raise HTTPException(403, str(e))


@router.get("/persons")
def persons():
    try:
        privacy.require_enabled()
        from .enrollment import get_store
        return {"persons": get_store().list_persons()}
    except FacialRecognitionDisabled as e:
        raise HTTPException(403, str(e))


@router.delete("/persons/{person_id}")
def delete_person(person_id: str):
    """잊혀질 권리 — 완전 삭제."""
    try:
        privacy.require_enabled()
        from .enrollment import get_store
        ok = get_store().delete_person(person_id)
        if not ok:
            raise HTTPException(404, "해당 person_id 없음")
        return {"ok": True, "deleted": person_id}
    except FacialRecognitionDisabled as e:
        raise HTTPException(403, str(e))


@router.post("/purge-expired")
def purge_expired():
    """보존기간 만료자 일괄 삭제."""
    try:
        privacy.require_enabled()
        from .enrollment import get_store
        return {"ok": True, "purged": get_store().purge_expired()}
    except FacialRecognitionDisabled as e:
        raise HTTPException(403, str(e))
