"""demo_server.py — 얼굴 인식 웹캠 데모(독립 실행)

VIGENT 코어(main.py)와 분리된 자체 서버다. 기존 api.py 라우터를 그대로 재사용해
브라우저 웹캠 데모(등록·실시간 식별)를 띄운다.

실행:
    cd ~/Desktop/VIGENT
    python -m vigentFacialRecognition.demo_server
  → 브라우저가 http://127.0.0.1:8011 로 자동으로 열린다.

⚠ 데모 편의를 위해 옵트인(VIGENT_FR_ENABLED)을 자동으로 켠다. 실제 운영에서는
   동의·고지 등 절차(README 법적 체크리스트)를 갖춘 뒤에만 켜야 한다.
"""
from __future__ import annotations

import os

# config 가 임포트되기 전에 옵트인을 켠다(데모 한정).
os.environ.setdefault("VIGENT_FR_ENABLED", "1")

import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse

from . import config
from .api import router as facial_router

# 데모 한정으로 옵트인을 강제 ON. (패키지 __init__ 가 config 를 먼저 임포트하므로
# 환경변수만으로는 늦을 수 있어 여기서 직접 켠다.) 운영에선 절대 이렇게 하지 말 것.
config.ENABLED = True

HERE = Path(__file__).resolve().parent
DEMO_HTML = HERE / "demo" / "index.html"

app = FastAPI(title="VIGENT Facial Recognition — Demo")
app.include_router(facial_router)


@app.get("/")
def index():
    return FileResponse(DEMO_HTML)


def main() -> None:
    if not config.model_files_present():
        print("모델이 없습니다. 먼저: python -m vigentFacialRecognition.download_models")
        return
    host, port = "127.0.0.1", 8011
    url = f"http://{host}:{port}"
    print(f"\n  VIGENT 얼굴 인식 데모 → {url}")
    print("  (데모 모드: 옵트인 자동 ON. 운영 전 README 법적 체크리스트 확인)\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
