# VIGENT 배포 이미지 (C-S2). python slim 베이스, 가중치는 이미지 미포함(볼륨 + fetch_weights).
#   빌드:  docker build -t vigent:0.2.0 .
#   실행:  docker run --rm -p 8010:8010 \
#            -v $PWD/vigent-core/weights:/app/vigent-core/weights \
#            -v $PWD/.env:/app/.env:ro \
#            -e VIGENT_HOST=0.0.0.0 -e VIGENT_API_TOKEN=<비밀> vigent:0.2.0
#   ⚠️ 0.0.0.0 노출 시 VIGENT_API_TOKEN 필수(미설정이면 기동 거부).
#   ★[S2-수정, 2026-08-10] 이 이미지는 VIGENT_REQUIRE_TOKEN=1 기본값 — 127.0.0.1 로컬
#     바인딩이어도 VIGENT_API_TOKEN 을 안 주면 기동 자체가 거부된다(엣지박스 배포 프로파일,
#     md/DEPLOYMENT.md §VIGENT_API_TOKEN 참고). 순수 로컬 테스트가 필요하면
#     `-e VIGENT_REQUIRE_TOKEN=0`으로 이 기본값을 덮어쓸 것(용도를 알고 쓸 것 — 운영 배포엔 권장 안 함).
# 멀티아치: linux/amd64·linux/arm64 모두 slim 베이스 존재. torch 는 아치별 휠이 자동 선택되나,
#   CUDA/Jetson 은 기기용 torch 를 별도 설치해야 함(아래 requirements 의 torch 를 기기 휠로 교체).
FROM python:3.11-slim

# opencv-headless·onnxruntime 런타임 라이브러리
RUN apt-get update && apt-get install -y --no-install-recommends \
        libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 의존성 먼저(레이어 캐시). 배포 requirements 만 — 측정/선택 도구는 미포함.
COPY requirements.txt .
# ⚠️ opencv 단일화: supervision·ultralytics·trackers 가 opencv-python(GUI)을, rtmlib 가
#   opencv-contrib-python 을 전이의존으로 끌어와 headless 를 가린다(cv2 가 GUI 5.x 로 로드됨).
#   → 설치 후 GUI 변종을 제거하고 headless 를 강제 재설치해 cv2 를 headless 하나로 고정.
RUN python -m pip install --no-cache-dir -U pip && \
    python -m pip install --no-cache-dir -r requirements.txt && \
    python -m pip uninstall -y opencv-python opencv-contrib-python || true && \
    python -m pip install --no-cache-dir --force-reinstall --no-deps opencv-contrib-python-headless==4.13.0.92

# 앱 코드(가중치 제외 — .dockerignore 로 weights 차단, 런타임 볼륨 마운트)
COPY vigent-core/ ./vigent-core/
COPY themes/ ./themes/
COPY config/ ./config/
COPY bin/ ./bin/
COPY VERSION weights_manifest.json fetch_weights.py ./

# 기본: 로컬 바인딩(외부 노출은 -e VIGENT_HOST=0.0.0.0 + 토큰). 엣지 자동감시 on.
# [S2-수정] VIGENT_REQUIRE_TOKEN=1 — 엣지박스 배포 프로파일은 로컬 바인딩이어도 토큰 상시
#   요구(개발 환경은 uvicorn 직접 실행 시 이 변수가 없어 기존 동작 그대로 — 훼손 없음).
ENV VIGENT_HOST=127.0.0.1 \
    VIGENT_PORT=8010 \
    VIGENT_EDGE=1 \
    VIGENT_REQUIRE_TOKEN=1 \
    VIGENT_LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1

EXPOSE 8010

# 헬스체크(확장 /health)
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${VIGENT_PORT}/health" || exit 1

WORKDIR /app/vigent-core
CMD ["sh", "-c", "python -m uvicorn main:app --host ${VIGENT_HOST} --port ${VIGENT_PORT}"]
