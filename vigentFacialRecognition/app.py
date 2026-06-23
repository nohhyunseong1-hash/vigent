"""app.py — 통합 데모 서버 (얼굴인식 · 동요지표 · 모션확대 하나로)

세 데모를 각각 띄우지 않고 하나의 서버(포트 8010) + 탭 페이지로 합친다.
기존 라우터/엔진을 그대로 재사용한다(중복 로직 없음).

  /                → 탭 허브(hub.html)
  /demo/facial     → 얼굴 인식 데모(index.html)      + /facial/*  (api.router)
  /demo/wellbeing  → 동요/피로 지표 데모             + /wellbeing/*
  /demo/evm        → 모션 확대(EVM) 데모             + /evm/*

실행:
    cd ~/Desktop/VIGENT
    python -m vigentFacialRecognition.app
  → http://127.0.0.1:8010 자동 오픈.

⚠ 데모 편의로 얼굴인식 옵트인을 강제 ON(운영 금지). README 법적 체크리스트 참조.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, Response

from . import config
from .agitation import AgitationMonitor
from .api import router as facial_router
from .evm import MotionMagnifier

config.ENABLED = True                 # 데모 한정(운영 금지 — demo_server 와 동일 주석)

HERE = Path(__file__).resolve().parent
DEMO = HERE / "demo"

app = FastAPI(title="VIGENT Vision Demos")
app.include_router(facial_router)     # /facial/*

monitor = AgitationMonitor()          # 동요/피로(1인 세션)
mag = MotionMagnifier()               # 모션 확대(1인 세션)


# ── 페이지 ────────────────────────────────────────────────────
@app.get("/")
def hub():
    return FileResponse(DEMO / "hub.html")


@app.get("/demo/facial")
def page_facial():
    return FileResponse(DEMO / "index.html")


@app.get("/demo/wellbeing")
def page_wellbeing():
    return FileResponse(DEMO / "wellbeing.html")


@app.get("/demo/evm")
def page_evm():
    return FileResponse(DEMO / "evm.html")


# ── 동요/피로 엔드포인트 ──────────────────────────────────────
@app.post("/wellbeing/frame")
async def wb_frame(image: UploadFile = File(...), ts: float = Form(None)):
    import cv2
    img = cv2.imdecode(np.frombuffer(await image.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return {"face": False, "error": "decode"}
    return monitor.update(img, ts)


@app.post("/wellbeing/reset")
def wb_reset():
    monitor.reset()
    return {"ok": True}


# ── 모션 확대 엔드포인트 ──────────────────────────────────────
@app.post("/evm/frame")
async def evm_frame(image: UploadFile = File(...), ts: float = Form(None),
                    alpha: float = Form(None)):
    import cv2
    if alpha is not None:
        mag.alpha = float(alpha)
    img = cv2.imdecode(np.frombuffer(await image.read(), np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return Response(status_code=400)
    out = mag.process(img, ts)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"X-FPS": str(mag.fps)})


@app.post("/evm/reset")
def evm_reset():
    mag.reset()
    return {"ok": True}


def main() -> None:
    if not config.model_files_present():
        print("모델이 없습니다. 먼저: python -m vigentFacialRecognition.download_models")
        return
    host, port = "127.0.0.1", 8010
    url = f"http://{host}:{port}"
    print(f"\n  VIGENT 통합 비전 데모 → {url}")
    print("  탭: 얼굴인식 · 동요지표 · 모션확대  (데모 모드)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
