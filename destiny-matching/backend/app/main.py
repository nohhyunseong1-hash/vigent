from __future__ import annotations

from fastapi import FastAPI

from backend.app.models import CompatibilityRequest, ReadingRequest
from backend.app.services.matching_engine import score_compatibility
from backend.app.services.reading_service import create_reading


app = FastAPI(title="운명 매칭 API", version="0.1.0")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/reading")
def reading(request: ReadingRequest):
    return create_reading(request)


@app.post("/api/v1/compatibility")
def compatibility(request: CompatibilityRequest):
    return score_compatibility(request.left, request.right)
