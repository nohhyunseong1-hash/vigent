"""wellbeing_server.py — 동요/피로 지표 웹캠 데모(독립 실행)

VIGENT 코어와 분리된 자체 서버. 브라우저 웹캠 프레임을 받아 AgitationMonitor 로
동요 지수·rPPG 심박을 실시간 표시한다. 신원 식별/저장은 하지 않는다(참고용 신호).

실행:
    cd ~/Desktop/VIGENT
    python -m vigentFacialRecognition.wellbeing_server
  → http://127.0.0.1:8012 자동 오픈.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse

from .agitation import AgitationMonitor

HERE = Path(__file__).resolve().parent
DEMO_HTML = HERE / "demo" / "wellbeing.html"

app = FastAPI(title="VIGENT Wellbeing — Demo")
monitor = AgitationMonitor()          # 데모는 1인 세션 가정(전역 모니터)


@app.get("/")
def index():
    return FileResponse(DEMO_HTML)


@app.post("/wellbeing/frame")
async def frame(image: UploadFile = File(...), ts: float = Form(None)):
    import cv2
    data = np.frombuffer(await image.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return {"face": False, "error": "decode"}
    return monitor.update(img, ts)


@app.post("/wellbeing/reset")
def reset():
    monitor.reset()
    return {"ok": True}


def main() -> None:
    host, port = "127.0.0.1", 8012
    url = f"http://{host}:{port}"
    print(f"\n  VIGENT 동요/피로 지표 데모 → {url}")
    print("  (참고용 advisory 신호 · 감정/거짓말 판별 아님 · 저장 안 함)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
