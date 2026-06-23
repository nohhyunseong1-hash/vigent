"""evm_server.py — 모션 확대(EVM) 웹캠 데모(독립 실행)

브라우저 웹캠 프레임을 받아 MotionMagnifier 로 미세 떨림을 증폭해 돌려준다.
원본과 증폭 영상을 나란히 보여주는 시각화 데모(저장·식별 없음, 참고용).

실행:
    cd ~/Desktop/VIGENT
    python -m vigentFacialRecognition.evm_server
  → http://127.0.0.1:8013 자동 오픈.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse, Response

from .evm import MotionMagnifier

HERE = Path(__file__).resolve().parent
DEMO_HTML = HERE / "demo" / "evm.html"

app = FastAPI(title="VIGENT EVM — Demo")
mag = MotionMagnifier()              # 1인 데모 세션(전역)


@app.get("/")
def index():
    return FileResponse(DEMO_HTML)


@app.post("/evm/frame")
async def frame(image: UploadFile = File(...), ts: float = Form(None),
                alpha: float = Form(None)):
    import cv2
    if alpha is not None:
        mag.alpha = float(alpha)
    data = np.frombuffer(await image.read(), np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        return Response(status_code=400)
    out = mag.process(img, ts)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"X-FPS": str(mag.fps)})


@app.post("/evm/reset")
def reset():
    mag.reset()
    return {"ok": True}


def main() -> None:
    host, port = "127.0.0.1", 8013
    url = f"http://{host}:{port}"
    print(f"\n  VIGENT 모션 확대(EVM) 데모 → {url}")
    print("  (미세 떨림 시각화 · 감정/거짓말 판별 아님 · 저장 안 함)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
