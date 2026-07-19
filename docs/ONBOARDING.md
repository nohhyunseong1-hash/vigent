# VIGENT 온보딩 가이드 (신규 개발자용)

> 이 문서만 따라 하면 로컬에서 서버를 띄우고 핵심 흐름을 이해할 수 있도록 작성했다.
> 상세 검토·이슈 목록은 [CODE_REVIEW.md](CODE_REVIEW.md), 배포 절차는 [../DEPLOYMENT.md](../md/DEPLOYMENT.md), AI 도구 규칙은 [../CLAUDE.md](../CLAUDE.md) 참조.

---

## 1. 프로젝트 개요

**VIGENT = Vision + AI Agent 산업안전 플랫폼.** 스마트 카메라 영상에서 위험을 탐지(위험구역 침입·낙상·보호구 미착용·화재/연기·협착)하고, AI 에이전트가 그 결과로 **위험성평가서·안전보고서·TBM(작업 전 안전미팅) 회의록** 등 안전 서류 작업을 자동화한다.

**핵심 설계 2가지 (반드시 이해하고 시작):**
1. **테마 = 코드가 아니라 설정.** 신규 테마는 `themes/<name>/vision.yaml` + 프론트 1개로 추가하고 코어 로직은 건드리지 않는다. 1차 완성 테마는 **safety**(office/sports는 스캐폴드).
2. **절대 저하 없음 = 가산식 + 폴백.** 딥러닝 신호는 규칙 점수에 가산만 하고, 모델이 없거나 실패하면 휴리스틱으로 자동 폴백한다. 그래서 코드 전반에 `except Exception: # noqa: BLE001` → 폴백 패턴이 많다(버그가 아니라 의도).

**기술 스택(실측):** Python(문서상 3.11, 실제 검증 3.13) · FastAPI 0.137 · RF-DETR(객체탐지) · rtmlib/onnxruntime(포즈) · Qwen2.5-VL 로컬 VLM(mlx-vlm) · OpenAI/Anthropic LLM · sentence-transformers(한국어 법령 RAG) · OpenCV(headless). 프론트는 순수 HTML/JS + CDN(MediaPipe·TF.js).

> ⚠️ **안전 경계(코드·문서·UI에 항상 명시):** 비전 ML은 확률적이라 인증 안전기능을 대체하지 못한다. VIGENT는 **보조·감시 계층**으로 신호만 제공한다. 프레스/전단기 비상정지의 1차 책임은 인증 하드웨어(Type 4 방호장치, 안전 PLC)에 있다.

---

## 2. 로컬 개발 환경 설정 (따라 하기)

### 2.1 사전 조건
- Python **3.13.9 고정**(`.python-version`). 정본 인터프리터는 `/opt/anaconda3/bin/python3`. 시스템 기본 `python3`가 3.9이면 의존성 설치·테스트가 실패하니 반드시 정본 경로를 쓴다(README 참조).
- macOS/Linux. (배포는 Docker, 개발은 아래 방식 권장.)

### 2.2 설치
```bash
cd ~/Desktop/VIGENT

# (권장) 가상환경
python3.11 -m venv .venv && source .venv/bin/activate

# 배포 최소 의존성
pip install -r requirements.txt

# ⚠️ opencv 단일화(중요): supervision·rtmlib 등이 GUI opencv 를 전이의존으로 끌어와
#    headless 를 가린다. 설치 후 반드시 정리:
pip uninstall -y opencv-python opencv-contrib-python
pip install --force-reinstall --no-deps opencv-contrib-python-headless==4.13.0.92

# 선택 기능(로컬 VLM·RAG·클라우드 LLM)이 필요하면
pip install -r requirements-optional.txt
```

### 2.3 환경 변수
```bash
cp .env.example .env
# .env 편집: 로컬 개발은 대부분 비워도 동작(키 없으면 규칙기반 폴백).
#   OPENAI_API_KEY      — 클라우드 LLM 추론(선택)
#   VIGENT_LLM_PROVIDER — openai(기본) | anthropic
#   ROBOFLOW_API_KEY    — 학습 데이터 다운로드용(런타임 불필요)
#   RTSP_URL            — 실제 카메라 연결 시
#   VIGENT_ZONE_TILE=1  — (B9) 위험구역 한정 타일 재검출로 소형 작업자 zone_intrusion recall↑
#                          (기본 off). 켜면 프레임당 ~415ms 추가(CPU) → 아래 EVERY 로 조절·GPU 권장.
#   VIGENT_ZONE_TILE_EVERY=N — N프레임마다만 타일(기본 1). 최악 지연 N/fps초. CPU면 N≥4 권장.
```
`.env`는 `.gitignore`로 커밋되지 않는다(규칙 5). **절대 키를 코드/채팅에 쓰지 않는다.**

### 2.4 모델 가중치
가중치(`vigent-core/weights/*.pth`, `*.pt`)는 용량이 커서 git 미포함이다. `fetch_weights.py` 또는 `weights_manifest.json` 참조. **가중치가 없으면 모델이 조용히 휴리스틱으로 폴백**하므로, 검출이 안 되면 먼저 서버 로그의 `검출 슬롯: ... → LOADED` 표시를 확인한다(과거 F-8 사고: 가중치 누락→COCO 폴백).

### 2.5 실행
```bash
./run.sh                    # 로컬(127.0.0.1:8010, 무인증)
# 외부 노출 시엔 토큰 필수(미설정이면 기동 거부):
VIGENT_HOST=0.0.0.0 VIGENT_API_TOKEN=<비밀> ./run.sh
```
브라우저에서 `http://127.0.0.1:8010/home` 접속. 헬스체크는 `GET /health`.

### 2.6 테스트
```bash
# 반드시 의존성이 설치된 파이썬으로! (시스템 3.9로 돌리면 import 실패)
/opt/anaconda3/bin/python3 -m unittest discover -s tests    # 35 tests 통과가 정상
```

---

## 3. 핵심 코드 흐름 (요청 → 응답)

### 흐름 A — 라이브 프레임에서 위험 탐지 → 사건 기록
```
카메라(RTSP)/비디오
 → worker._loop (worker.py:594)               # 카메라 1대 = 워커 1개
 → guard.detect(frame, detectors)             # detectors/rfdetr_adapter 로 추론
 → proximity.detect(협착) + Fall/ErgonomicsTracker(포즈 각도)
 → 발화 위험 [(rule, level, note)] (worker.py:81 _fired)
 → data_engine.log_event(...)                 # 자동처리 콘솔 노출
```
브라우저 실시간 뷰는 별도 경로: 프론트가 `POST /detect/frame` → `guard.detect`([routers/detect.py](../vigent-core/routers/detect.py), `_DETECT_LOCK`로 직렬화).

### 흐름 B — AI 에이전트가 위험성평가서 생성
```
POST /safety/risk-assessment  (routers/safety_core.py)  # body={events:[{rule,count}], site, process}
 → STATE[theme]["agents"]["Scribe"].generate(events, ...)
 → Scribe: 규칙→위험성평가표 매핑(RULE_KB) + Copilot 법령근거 삽입
 → (narrative=true 일 때만) llm_provider.reason_text 로 '종합의견' 한 문단
 → data/risk_assessments/ 에 HTML+JSON 저장, 평가표 JSON 반환
```
연동: TBM→평가서(`POST /safety/tbm/{tid}/risk-assessment`), 자동승인(`POST /safety/auto/approve`). LLM 실패 시 규칙기반으로 폴백.

### 흐름 C — 근골격계 자세분석
```
guard.detect person 박스 → RTMPose/yolov8n-pose → COCO-17 키포인트
 → ErgonomicsTracker.update (worker.py:721)
 → ergonomics.assess(keypoints, conf, thresholds)  (ergonomics.py:52)
     ↑ 임계값은 하드코딩 아님 — themes/safety/vision.yaml 의 judgment.ergonomics.joints 주입
 → 목/허리/어깨 각도→등급(good/warn/bad)→지속 확정 시 위험 가산
```
브라우저 라이브뷰는 MediaPipe Holistic(CDN) 기반.

### 주요 엔드포인트 지도 (107개 중 대표)
- **탐지/라이브:** `POST /detect/frame` · `/rfdetr/frame` · `/rfdetr/vlm` · `/ppe/analyze-frame`
- **평가서/판단:** `POST /safety/risk-assessment` · `/safety/judge` · `/safety/manager/decide`
- **TBM:** `POST /safety/tbm` · `/safety/tbm/{tid}/risk-assessment`
- **워커:** `POST /worker/start` · `/workers/start-all` · `GET /workers`
- **사건분석:** `POST /safety/incident/analyze`
- **설정/알림:** `GET,POST /site/config` · `/notify/config` · `POST /alerts/test`
- **시스템:** `GET /health` · `/system/capabilities` · `/home` · `/hub`

---

## 3.5 vigent-core 모듈 구조 (P1-7 분할)

과거 `main.py`는 2293줄 God 파일에 모든 라우트·인라인 HTML·공유 헬퍼가 섞여 있었다. P1-7에서 **순수 이동(move-only)** 원칙으로 도메인별 `routers/` 모듈로 분할했다 — 동작·경로·응답·라우트 등록 집합(OpenAPI 106개 + WebSocket `/tapo/ws`)은 커밋마다 diff 0으로 검증했다.

```
vigent-core/
  main.py            (302줄) 앱 인프라만: app 생성 · include_router 13개 · 미들웨어 3개
                     (_auth_guard·_theme_gate·_no_cache_dynamic) · 예외핸들러 · startup/shutdown
                     · static/evidence 마운트 · `/` 루트 1개
  app_state.py       공유 런타임 상태: STATE · DETECT_LOCK · DEFAULT_THEME · load_theme · _START_TS
  web_util.py        공유 웹 헬퍼: 이미지 디코드·박스·zone·안전라벨·웹훅 화이트리스트·_tpl·
                     _env_or_dotenv·_evidence_url·_product_version·_TBM_CSS
  routers/
    tapo.py(3) vitals.py(1) zone.py(7) sports.py(6) office.py(5) system.py(2) detect.py(4)
    incident.py(3) tbm.py(6) ppe.py(7) recognition.py(4) dispatch.py(1) safety_core.py(57)
```
파일 옆 숫자 = 라우트 데코레이터 수. **routers 합계 106** + main의 `/` 루트 1 = OpenAPI 107개 라우트 (그중 `/tapo/ws`는 WebSocket이라 OpenAPI 경로집계 106에는 빠지고 별도 추적).

**핵심 규칙(구조 유지 시 반드시):**
- **라우터는 `main`을 import하지 않는다(순환 금지).** 공유가 필요하면 런타임 상태는 `app_state`, 웹 헬퍼는 `web_util`에 둔다 — 둘 다 main을 import하지 않는다. 여러 도메인이 쓰는 헬퍼를 새로 발견하면 `web_util`로 올린다(예: `_TBM_CSS`는 tbm·safety_core 두 도메인이 공유해서 web_util에 상주).
- **`/` 루트는 의도적으로 main.py에 잔류한다.** `app.version`(FastAPI 인스턴스)을 직접 참조하는 유일한 라우트라, 라우터로 옮기면 순환이 되거나 `app.version`을 다른 표현으로 바꿔야 해(move-only 위반) 그대로 둔다.
- **`/{theme}` 캐치올 순서:** safety_core를 include 목록 **맨 마지막**에 등록하고 모듈 내 소스 순서를 보존해야 `/health` 같은 리터럴 경로를 가리지 않는다.
- **회귀 검증:** 라우트를 옮기거나 추가하면 `scripts/check_openapi_diff.py`(경로·메서드 집합 + WebSocket 무변경)로 확인한다.

---

## 4. 조심해야 할 영역 (건드리기 전에 읽을 것)

| 영역 | 주의 | 근거 |
|---|---|---|
| **[main.py](../vigent-core/main.py) + [routers/](../vigent-core/routers/)** | ✅ P1-7에서 302줄(앱 인프라만)로 분할 — 라우트는 도메인별 `routers/*.py`에 있다(§3.5). 라우트를 옮기거나 추가하면 라우터가 `main`을 import하지 않게 하고(순환 금지), `scripts/check_openapi_diff.py`로 회귀를 확인. `/` 루트는 `app.version` 참조로 main에 잔류. | §3.5 · CODE_REVIEW §2.1 |
| **가중치 폴백** | 모델 파일이 없으면 **조용히** 휴리스틱으로 폴백해 정확도가 급락하지만 서버는 정상 기동한다. 검출 이상 시 로그의 `→ LOADED` 먼저 확인. | CLAUDE.md F-8 |
| **[worker.py](../vigent-core/worker.py) `_loop`** | 162줄에 캡처·트래커·루프가 뭉쳐 있고 `except: pass`가 많아 캡처 실패가 은폐될 수 있다. 수정 시 로깅부터 붙일 것. | CODE_REVIEW §2.4 |
| **VLM 호출부** | P1-6에서 `rfdetr_service.vlm_text()`(텍스트 요약)로 일부 흡수. **dict(구조화) 반환이 필요한 소비처 11곳은 `summarize_bgr` 직접 호출 유지**(의도적 범위 제외 → [P3_BACKLOG.md](P3_BACKLOG.md) B6). 이 관용구를 고칠 땐 전체 검색으로 확인. | CODE_REVIEW §2.2 · P1-6 |
| **증거 경로(scribe)** | `evidence_paths` path traversal — ✅ **P0-1(e8d590f)에서 해소**: `_safe_evidence_path()` 로 `data/evidence` 하위 격리(`is_relative_to`). 이 경로 근처를 만질 땐 격리검사 유지. | CODE_REVIEW §3.1 |
| **[rig_monitor.py](../vigent-core/rig_monitor.py)** | **로직만 존재·파이프라인 미배선**(어떤 라이브 경로도 호출 안 함, 유닛테스트 5만 사용). 핵심 경보(하물 높이) 실영상 검증은 **적합 footage(근접 카메라 인양 1사이클) 확보 대기** — 광역 CCTV 는 하물/후크 미가시(작업자 26~64px 실측, F-13). "동작한다"·"제품 기능" 가정 금지. | FINDINGS F-13 · CODE_REVIEW §2.3 |
| **포즈 슬롯 주석** | vision.yaml의 pose/tracker/temporal 슬롯(rtmpose·ByteTrack·mmaction2)은 "미설치·미사용" 정직 표기. 실동작은 yolov8n-pose + MediaPipe. yaml만 보고 판단 금지. | vision.yaml 주석 |
| **의존성 취약점** | pillow·torch·requests 등 16건(pip-audit 확인). 업그레이드는 검출 회귀 테스트와 함께(규칙 §6: 저하 금지). | CODE_REVIEW §3.2 |
| **config/ 는 읽기전용 시드** | 위험구역·PPE 규칙 등 **런타임 가변 설정은 `data/config/`(gitignore)에 저장**되고 `config/*.json\|yaml`은 커밋된 기본값(시드)일 뿐이다(B2, `runtime_config.py`). 읽기=런타임 우선→시드 폴백, 쓰기=항상 data/. **config/ 파일에 런타임 write 를 새로 추가하지 말 것**(git 오염) — `runtime_config.read_path/runtime_path` 경유. | [P3_BACKLOG.md](P3_BACKLOG.md) B2 |
| **읽기 전용 MVP** | `~/Desktop/사업계획서/AX안전`은 원본 MVP로 **읽기 전용**. 자산은 복사만. 수정·삭제 금지(규칙 1). | CLAUDE.md |
| **동시 세션** | 여러 백그라운드 세션은 반드시 git worktree로 격리(공유 워킹트리 checkout 금지). 커밋 전 `git branch --show-current` 확인. | CLAUDE.md §8 |

---

## 5. 협업 규칙 (현재 상태 + 권장)

- **커밋:** 의미 있는 진행마다 커밋, 메시지는 **한국어**. 히스토리 품질은 양호하니 이 관례를 유지.
- **브랜치:** 목적별 브랜치 관례 존재(`audit/*`·`eval/*`·`design/*`). 아직 문서화된 규칙은 없음 → 팀 합의 후 이 문서에 추가 권장.
- **막혔을 때:** 추측하지 말고 질문한다. 측정 안 한 수치(정확도 %)는 지어내지 않는다(규칙 7).

---

## 6. 검증 게이트 (P0~P2 완료 — 변경 시 반드시 통과)

CODE_REVIEW.md §5의 조치 목록(P0~P2)이 완료됐다. 코드를 바꾸면 아래 게이트를 모두 통과시킨 뒤 커밋한다(각 항목은 로컬 명령 = CI 스텝과 동일).

| 게이트 | 명령 | 기준 |
|---|---|---|
| **ruff**(린트) | `ruff check vigent-core tests` | 출력 0(P1-5 도입, 룰 `pyproject.toml`) |
| **mypy**(점진 타입) | `python -m mypy` | 화이트리스트 0 에러(P2-12: app_state·web_util strict + 라우터·worker·main 관대) |
| **단위 테스트** | `/opt/anaconda3/bin/python3 -m unittest discover -s tests` | **55 tests** 통과(P2-14로 엔드포인트 스모크·worker 테스트 추가) |
| **OpenAPI 무변경** | `python scripts/check_openapi_diff.py` | 경로·메서드 **106** == baseline + WebSocket `/tapo/ws` 불변 |
| **CI** | `.github/workflows/ci.yml` | push/PR(main) 시 위 4개 자동 실행(P2-14). ★첫 실제 런 green 은 원격 연결 후 확인 필요 → [P3_BACKLOG.md](P3_BACKLOG.md) B1 |

> **주의:** `-> dict`/`-> str` 같은 **라우트 핸들러 반환 타입은 붙이지 않는다** — FastAPI(≥0.89)가 이를 `response_model`로 채택해 OpenAPI 응답 스키마가 바뀐다(동작 변경). 라우터는 mypy '관대' 모드로 본문만 검사한다(P2-12).

- **린터/타입 관례:** `except Exception: # noqa: BLE001`, 영문 식별자 + 한국어 주석 관례 유지. ruff format 훅은 보류(밀집 스타일).
- **남은 후속 작업:** P0~P2 완료 후 미룬 항목은 [P3_BACKLOG.md](P3_BACKLOG.md)에 우선순위·리스크와 함께 정리돼 있다.
