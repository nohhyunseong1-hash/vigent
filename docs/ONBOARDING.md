# VIGENT 온보딩 가이드 (신규 개발자용)

> 이 문서만 따라 하면 로컬에서 서버를 띄우고 핵심 흐름을 이해할 수 있도록 작성했다.
> 상세 검토·이슈 목록은 [CODE_REVIEW.md](CODE_REVIEW.md), 배포 절차는 [../DEPLOYMENT.md](../DEPLOYMENT.md), AI 도구 규칙은 [../CLAUDE.md](../CLAUDE.md) 참조.

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
- Python **3.11 이상**(이 저장소 검증 환경은 3.13). 시스템 기본 `python3`가 3.9이면 의존성 설치·테스트가 실패하니 3.11+ 인터프리터를 쓴다.
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
python -m unittest discover -s tests        # 30 tests 통과가 정상
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
브라우저 실시간 뷰는 별도 경로: 프론트가 `POST /detect/frame` → `guard.detect`([main.py](../vigent-core/main.py), `_DETECT_LOCK`로 직렬화).

### 흐름 B — AI 에이전트가 위험성평가서 생성
```
POST /safety/risk-assessment  (main.py:498)   # body={events:[{rule,count}], site, process}
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

## 4. 조심해야 할 영역 (건드리기 전에 읽을 것)

| 영역 | 주의 | 근거 |
|---|---|---|
| **[main.py](../vigent-core/main.py)** | 2293줄 God 파일. 6개 도메인 라우트 + 인라인 HTML이 섞여 있어 변경 영향범위가 넓다. 도메인별로 국소 수정하고, 리팩터 시 라우트 회귀를 반드시 확인. | CODE_REVIEW §2.1 |
| **가중치 폴백** | 모델 파일이 없으면 **조용히** 휴리스틱으로 폴백해 정확도가 급락하지만 서버는 정상 기동한다. 검출 이상 시 로그의 `→ LOADED` 먼저 확인. | CLAUDE.md F-8 |
| **[worker.py](../vigent-core/worker.py) `_loop`** | 162줄에 캡처·트래커·루프가 뭉쳐 있고 `except: pass`가 많아 캡처 실패가 은폐될 수 있다. 수정 시 로깅부터 붙일 것. | CODE_REVIEW §2.4 |
| **VLM 호출부** | 6개 모듈에 관용구가 복붙되어 있다. 한 곳만 고치면 나머지 5곳이 남는다. `vlm_text()` 헬퍼화 전까지는 전체 검색으로 일괄 반영. | CODE_REVIEW §2.2 |
| **증거 경로(scribe)** | `POST /safety/risk-assessment`의 `evidence_paths`가 파일시스템에 무검증으로 도달한다(**path traversal, 미수정**). 이 경로 근처를 만질 땐 격리검사부터. | CODE_REVIEW §3.1 |
| **[rig_monitor.py](../vigent-core/rig_monitor.py)** | 완성됐지만 파이프라인에 **미배선**(테스트만 사용). "동작한다" 가정 금지 — 실영상 대기 상태. | CODE_REVIEW §2.3 |
| **포즈 슬롯 주석** | vision.yaml의 pose/tracker/temporal 슬롯(rtmpose·ByteTrack·mmaction2)은 "미설치·미사용" 정직 표기. 실동작은 yolov8n-pose + MediaPipe. yaml만 보고 판단 금지. | vision.yaml 주석 |
| **의존성 취약점** | pillow·torch·requests 등 16건(pip-audit 확인). 업그레이드는 검출 회귀 테스트와 함께(규칙 §6: 저하 금지). | CODE_REVIEW §3.2 |
| **읽기 전용 MVP** | `~/Desktop/사업계획서/AX안전`은 원본 MVP로 **읽기 전용**. 자산은 복사만. 수정·삭제 금지(규칙 1). | CLAUDE.md |
| **동시 세션** | 여러 백그라운드 세션은 반드시 git worktree로 격리(공유 워킹트리 checkout 금지). 커밋 전 `git branch --show-current` 확인. | CLAUDE.md §8 |

---

## 5. 협업 규칙 (현재 상태 + 권장)

- **커밋:** 의미 있는 진행마다 커밋, 메시지는 **한국어**. 히스토리 품질은 양호하니 이 관례를 유지.
- **브랜치:** 목적별 브랜치 관례 존재(`audit/*`·`eval/*`·`design/*`). 아직 문서화된 규칙은 없음 → 팀 합의 후 이 문서에 추가 권장.
- **린터/CI:** 현재 없음(P1 도입 대상). 도입 전까지 `except Exception: # noqa: BLE001`, 영문 식별자 + 한국어 주석 관례를 수동 준수.
- **막혔을 때:** 추측하지 말고 질문한다. 측정 안 한 수치(정확도 %)는 지어내지 않는다(규칙 7).
