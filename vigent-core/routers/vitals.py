"""routers/vitals.py — rPPG(심박) 스텁 (P1-7 분할). main·app_state 미의존."""
from fastapi import APIRouter, Body

router = APIRouter()


@router.post("/vitals/rppg")
def stub_vitals(payload: dict = Body(default={})):
    return {"ok": True, "bpm": None, "note": "stub"}
