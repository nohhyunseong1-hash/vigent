# VIGENT 코드베이스 검토 보고서

> 작성: 2026-07-15 · 대상 브랜치: `main` (HEAD `7382364`) · 방식: 정적 검토 + 실제 실행(테스트·pip-audit)
> 범위: `vigent-core/` 코어 및 진입점. 사본/아카이브(`VIGENT USB/`, `VIGENT_archive/`, `vigent-landing 2/`, `backup/`)는 제외.
> 원칙: 이 보고서의 모든 수치·경로는 실제로 읽고 측정·실행한 결과다. 확인 못 한 항목은 "미확인"으로 표기했다.

---

## 0. 한눈 요약

| 영역 | 상태 | 근거 |
|---|---|---|
| 시크릿 관리 | **양호** | `.env` 미추적 + git 히스토리에도 없음, 하드코딩 시크릿 0건 |
| 아키텍처 | 양호(단, main.py God 파일) | 테마=설정 분기, 가산식+폴백 설계 일관 |
| 코드 품질 | 중간 | bare except 0·dead code 없음(양호) / God 파일·중복 관용구(개선 필요) |
| 보안 | 조치 필요 → ✅ **대부분 해소** | path traversal(P0-1 `e8d590f`), 취약 의존성 4패키지(P0-2a). torch CVE 는 도달불가 조사(F-15) |
| 협업 준비 | 미비 → 개선 | README ✅(P1-4)·ruff ✅(P1-5)·`.python-version` ✅(P0-0). CI 는 아직 없음 |
| 테스트 | 통과 | 올바른 파이썬에서 **35 tests OK**(P0/P1 신규 5) (아래 §4 주의) |

---

> ### 📌 해소 현황 (이 스냅샷 이후 P0/P1 라운드 반영, 2026-07-15)
> 아래 §들의 지적은 **작성 시점(HEAD `7382364`) 기준**이며, 다수가 P0/P1 라운드에서 해소됐다:
> - **§3.1 path traversal** → ✅ `_safe_evidence_path` 격리(P0-1 `e8d590f`), 회귀 테스트 4.
> - **§ 취약 의존성** → ✅ pillow/requests/dotenv/setuptools(P0-2a `808ab00`), torch 는 도달불가(F-15).
> - **§ 토큰 비교** → ✅ `hmac.compare_digest` + 무토큰 경고(P0-3 `32c1b34`).
> - **README/린터/파이썬 고정** → ✅ P1-4/P1-5/P0-0.
> - **rig_monitor 미배선** → 문서 명시(P1-10). **main.py God 파일(§2.1)** → P1-7 분할 진행 중.
> 세부 findings 는 이력 보존을 위해 원문 그대로 둔다(해소분은 위 마커로 판별).



## 1. 아키텍처 개요

진입점은 [vigent-core/main.py](../vigent-core/main.py) — FastAPI 앱. `uvicorn main:app`으로 기동([run.sh](../run.sh) / [Dockerfile](../Dockerfile)).

```
                      ┌─────────────────────────────────────────┐
   카메라(RTSP)  ───▶ │ worker.py  (카메라 1대 = 워커 1개)        │
   비디오/이미지       │  _loop → guard.detect → 위험판정 →        │
                      │  data_engine.log_event                   │
                      └───────────────┬─────────────────────────┘
                                      │
   브라우저 라이브 ──▶ POST /detect/frame ─▶ guard.detect (main.py, _DETECT_LOCK 직렬화)
                                      │
                      ┌───────────────▼─────────────────────────┐
                      │ 6-에이전트 루프 (agents/)                 │
                      │  Guard[감지] → Analyst[판단] →           │
                      │  Scribe[보고서] ← Copilot[법령근거]      │
                      │  Dispatcher[알림] · SafetyManager[승인]  │
                      └───────────────┬─────────────────────────┘
                                      │
     외부: OpenAI/Anthropic(llm_provider) · 로컬VLM(rfdetr_service) · 텔레그램/웹훅(dispatcher)
```

**테마 = 코드가 아니라 설정.** [vision_loader.py](../vigent-core/vision_loader.py)가 `themes/{safety,office,sports}/vision.yaml`을 읽어 슬롯별 모델 존재검사→없으면 fallback 강등→`PipelineConfig` 생성. [main.py](../vigent-core/main.py) `_load_theme`가 이를 `build_agents`와 묶어 `STATE[theme]` 번들로 캐시. 1차 완성 테마는 **safety**.

**설계 철학(코드에서 실제 관철됨):** 딥러닝 신호는 규칙 점수에 가산만 하고, 모델이 없거나 실패하면 휴리스틱으로 폴백해 기능이 죽지 않는다. 예외 처리 규율(§2.4)과 `vision_loader`의 슬롯 강등이 이를 뒷받침한다.

**모듈 지도(요약):**

| 파일 | 책임 |
|---|---|
| [main.py](../vigent-core/main.py) | FastAPI 전 라우트(107개)·테마 번들 로드·추론 직렬화 락 |
| [worker.py](../vigent-core/worker.py) | 서버사이드 추론 워커(RTSP/비디오 → 탐지 → 위험판정 → 기록) |
| [rfdetr_service.py](../vigent-core/rfdetr_service.py) | 웹용 RF-DETR 백엔드 싱글톤 + 로컬 VLM(mlx-vlm) |
| [agents/](../vigent-core/agents/) | Guard/Analyst/Scribe/Copilot/Dispatcher/Coach/SafetyManager |
| [detectors/](../vigent-core/detectors/) | RF-DETR(배포)·YOLO(롤백) 백엔드 어댑터 |
| [safety_brain.py](../vigent-core/safety_brain.py) | "무엇이 있어야 하는데 없다" 지식 추론 |
| [incident.py](../vigent-core/incident.py) | 재해 영상 사후 원인분석 초안 |
| [ergonomics.py](../vigent-core/ergonomics.py) | 근골격계 자세 각도→등급 평가 |
| [ppe_check.py](../vigent-core/ppe_check.py) | 보호구 점검(모델 + VLM 2단계) |
| [safety_rag.py](../vigent-core/safety_rag.py) | 법령/가이드 근거 검색(폐쇄망, 외부의존 0) |
| [llm_provider.py](../vigent-core/llm_provider.py) | LLM 어댑터(openai 기본 / anthropic), 실패시 None 폴백 |

> 상세 흐름도·엔드포인트 전체 목록은 [ONBOARDING.md](ONBOARDING.md) §3~4 참조.

---

## 2. 코드 품질 (AST 실측)

### 2.1 God 파일 / 긴 함수 — [높음]
- **[높음] [main.py](../vigent-core/main.py) 2293줄 · 라우트 107개 · 함수 129개.** 한 파일이 페이지 서빙(HTML), 위험구역, 워커 오케스트레이션, 안전판정, TBM, PPE, 사고분석, office, sports, rPPG, Tapo WebRTC/WebSocket을 전부 담당. 경로가 `/safety/*`·`/office/*`·`/sports/*`·`/tapo/*`·`/vitals/*`·`/zone/*` 6개 이상 도메인에 걸침.
  - 비대의 상당 부분이 **파이썬에 인라인된 전체 HTML**: `_TBM_NEW_HTML`([main.py:777](../vigent-core/main.py#L777), 129줄), `_AUTO_HTML`([main.py:910](../vigent-core/main.py#L910), 89줄).
- **가장 긴 함수(200줄 초과 함수는 없음 — 비대함은 파일 단위):**
  - [worker.py:594](../vigent-core/worker.py#L594) `_loop` — **162줄** [높음]. 캡처셋업+수집모드+낙상/무동작/근골격 트래커+프레임루프 혼재.
  - [agents/scribe.py:389](../vigent-core/agents/scribe.py#L389) `render_html` — 149줄 [중간]
  - [dashboard.py:86](../vigent-core/dashboard.py#L86) `render_terminal` — 135줄 [중간]
  - [incident.py:143](../vigent-core/incident.py#L143) `analyze` — 114줄 [중간]

### 2.2 중복 코드 — [높음/중간]
- **[높음] VLM 호출 관용구가 6개 모듈에 복붙(14곳).** 매 호출부가 (1) 지역 `import rfdetr_service`, (2) `rfdetr_service.vlm.summarize_bgr(...)`, (3) `if not isinstance(data, dict) or data.get("_error")` 가드, (4) `data.get("raw") or " ".join(...)` 추출을 반복.
  - 위치: [safety_brain.py:54/97/136](../vigent-core/safety_brain.py), [scene_vlm.py:44/111](../vigent-core/scene_vlm.py), [incident.py:70](../vigent-core/incident.py#L70), [behavior.py:153](../vigent-core/behavior.py#L153), [ppe_check.py:96](../vigent-core/ppe_check.py#L96), [vlm_confirm.py:107/134](../vigent-core/vlm_confirm.py), [main.py:630/1889/2051](../vigent-core/main.py).
  - 개선: `vlm_text(image, prompt) -> str | None` 헬퍼 1개로 흡수.
- **[중간] 위험구역 로딩 3벌 분산.** [worker.py:62](../vigent-core/worker.py#L62) `_load_zone`, [rfdetr_service.py:19](../vigent-core/rfdetr_service.py#L19) `_load_zone`(동명·다른 구현), [main.py:369~385](../vigent-core/main.py#L369) `_zone_*`. 같은 `config/danger_zone.json`을 3벌 코드가 각자 읽음.
- **[양호]** 디바이스 선택은 [device.py:18](../vigent-core/device.py#L18) `pick_device`로 중앙화되어 재사용 중.

### 2.3 Dead code / 잔재 — [낮음, 대체로 양호]
- 주석처리된 코드 블록, 미사용 import(`from __future__` 외), TODO/FIXME 마커 **없음**(AST 스캔).
- **단, 배선 안 된 완성 모듈 존재:** [rig_monitor.py](../vigent-core/rig_monitor.py)(줄걸이 상태기계)는 로직 완성이나 main.py·worker.py에 **미연결**, `tests/test_rig_monitor.py`에서만 사용(커밋 메시지 "실영상 footage 대기"와 일치). [pose/rtmpose_adapter.py](../vigent-core/pose/rtmpose_adapter.py)·ByteTrack·mmaction2는 vision.yaml 주석에 "미설치·미사용"으로 정직 표기, 실동작은 worker의 yolov8n-pose + 브라우저 MediaPipe.

### 2.4 에러 처리 — [중간]
- **[양호]** bare `except:` **0건**. 전 파일이 `except Exception:  # noqa: BLE001`로 통일 — 대부분 "모델 실패→휴리스틱 폴백"이라는 의도적 설계.
- **[중간] 침묵 삼킴(`except: pass`) 다수** — main.py 9, worker.py 9, safety_brain.py 2, guard.py 2. 특히 worker의 캡처/스레드 삼킴([worker.py:413,452,626,672,681,709](../vigent-core/worker.py))은 로그 없이 넘어가 실제 캡처 실패를 가릴 수 있음 → 최소 로깅 권장.
- **[중간] `except Exception` 총량 큼**(main.py 26, worker.py 19) — 폴백 전략의 일부지만 오타·타입에러까지 삼킬 위험.

### 2.5 타입 힌트 — [중간]
- 편차 큼. 유틸 모듈은 양호(`vlm_confirm.py` 6/6, `evaluator.py` 4/4), **핵심은 빈약**: [main.py](../vigent-core/main.py) 반환타입 14/129, [worker.py](../vigent-core/worker.py) 13/35.

### 2.6 네이밍 — [낮음]
- 식별자 영문, 주석/프롬프트 한국어로 대체로 일관.
- 한국어 식별자 소량 누출: [agents/copilot.py:95](../vigent-core/agents/copilot.py#L95) `법령=`, [hazard_rules.py:72](../vigent-core/hazard_rules.py#L72) `항목=`. `_load_zone` 동명이인(§2.2)도 혼동 유발.

---

## 3. 보안 (읽기 전용 점검 + pip-audit 실제 실행)

### 3.1 임의 파일 읽기(path traversal) — [높음] ★종단 간 확인
- 체인: `POST /safety/risk-assessment` → [main.py:488](../vigent-core/main.py#L488) `RiskAssessmentIn.events: list[dict]`(주석에 "추가검증 없음" 명시) → [scribe.py:271~276](../vigent-core/agents/scribe.py#L271) 사용자 `evidence_paths`/`evidence`/`evidence_items[].path` → [scribe.py:210](../vigent-core/agents/scribe.py#L210) `p = _ROOT / relpath`(**격리검사 없음**) → `p.read_bytes()` → base64로 응답에 임베드.
- 영향: `evidence_paths=["../../../../etc/passwd"]` 또는 `../.env` 지정 시 서버 내 임의 파일(≤4MB)이 생성 문서에 담겨 반환됨.
- `use_vlm` 경로의 [scribe.py:284](../vigent-core/agents/scribe.py#L284) `cv2.imread(str(_ROOT / pairs[0][0]))`도 동일.
- 완화 요인: 4MB 상한, 로컬 기본 바인딩. 그러나 토큰 인증된 원격 사용자도 자기 권한을 넘는 파일을 읽을 수 있음.
- **개선:** `Path(_ROOT/relpath).resolve()`가 `(_ROOT/"data"/"evidence").resolve()` 하위인지 `is_relative_to`로 강제.

### 3.2 취약 의존성 16건/5패키지 — [높음] ★pip-audit 실제 실행 결과
| 패키지 | 현재 | 취약점 | 수정 버전 |
|---|---|---|---|
| pillow | 12.0.0 | 11건(PYSEC-2026-165/2249~2257/2874) | 12.3.0 |
| torch | 2.12.0 | CVE-2025-3000 | (미표기) |
| requests | 2.32.5 | PYSEC-2026-2275 | 2.33.0 |
| python-dotenv | 1.1.0 | PYSEC-2026-2270 | 1.2.2 |
| setuptools | 81.0.0 | PYSEC-2026-3447 | 83.0.0 |

> `/opt/anaconda3/bin/python3 -m pip_audit -r requirements.txt` 결과(2026-07-15). 배포/파일럿 전 업그레이드 후 회귀 테스트 권장(규칙 §6: 저하 없는 방향으로).

### 3.3 로컬 기본 무인증 + DNS rebinding — [중간]
- 외부 바인딩 시 토큰 강제 기동거부는 **실재**([main.py:78~84](../vigent-core/main.py#L78)). 토큰 설정 시 전 라우트 Bearer 검증([main.py:125~133](../vigent-core/main.py#L125)).
- 그러나 토큰 **미설정** 로컬모드에서는 전 라우트 무인증 + Host 헤더 미검증 → DNS rebinding으로 피해자 브라우저가 `127.0.0.1:8010`의 제어 엔드포인트(`/worker/start`, `/site/config`, `/notify/config`)에 도달 가능.
- **개선:** 공유/파일럿 환경에서는 `VIGENT_API_TOKEN` 상시 설정, 가능하면 Host 화이트리스트 추가.

### 3.4 토큰 비상수시간 비교 — [낮음]
- [main.py:131](../vigent-core/main.py#L131) `!=` 문자열 비교(비상수시간). `hmac.compare_digest`로 교체 권장.

### 3.5 이상 없음(양호)
- `eval`/`exec`/`os.system`/`subprocess`/`shell=True`/`pickle.load`/`torch.load` **0건**.
- YAML 전 사용처 `yaml.safe_load`(비안전 로더 없음).
- CORS 미들웨어 미설정 = 동일출처만 허용(과다허용 없음).
- 요청유도 SSRF 없음 — 웹훅 URL은 운영자 설정 + `_webhook_allowed` 화이트리스트(fail-closed, [main.py:99](../vigent-core/main.py#L99)).
- 파일 업로드(`UploadFile`) 미사용 — 프레임은 JSON base64로만 수신.
- **시크릿: `.env` 미추적 + git 히스토리에도 없음 + 하드코딩 0건.** (협업 전 최대 관심사였으나 무결)

---

## 4. 협업 준비 상태

| 항목 | 상태 | 근거 |
|---|---|---|
| README(로컬 실행 안내) | **없음** | 루트 README 부재. `DEPLOYMENT.md`가 일부 대체하나 신규 개발자 온보딩용 아님 |
| 코드 컨벤션 문서 | **없음** | CONTRIBUTING/STYLE/CONVENTIONS 부재 |
| 린터/포매터 설정 | **없음** | pyproject.toml·ruff·flake8·black·mypy·pre-commit **전무** (단, `# noqa: BLE001` 규율은 수동 준수 중) |
| 타입 체커 | 없음 | mypy 설정 없음, 힌트 편차 큼(§2.5) |
| 테스트 | **미비** | 5파일 383줄 / 소스 85파일. 35 tests 통과하나 커버리지 낮음 |
| CI | **없음** | `.github/workflows` 부재 |
| Git 히스토리 | **양호** | 342커밋, 한국어 서술형 메시지 일관, 거대·무의미 커밋 없음 |
| 브랜치 전략 | 문서화 안 됨 | `audit/*`·`eval/*`·`design/*`·`c-sprint`·`t10b-cloud` 등 목적별 브랜치 존재하나 규칙 미문서화 |
| 워킹트리 위생 | **미비** | 미추적 44항목 — 사본 폴더(`VIGENT USB/`·`VIGENT_archive/`·`vigent-landing 2/`), 워크트리 잔재(`vigent-core/vigent-core/weights` 빈 디렉토리) |

**테스트 실행 주의(중요):** 시스템 `python3`(3.9)에는 의존성이 없어 `import yaml` 단계에서 실패한다. 반드시 의존성이 설치된 파이썬(이 환경은 `/opt/anaconda3/bin/python3`, **3.13**)으로 실행해야 35 tests가 통과한다. 프로젝트 문서는 Python **3.11** 기준인데 실제 검증 환경은 3.13 — **버전 불일치**를 온보딩 문서에 명시하거나 `.python-version`/venv로 고정할 필요.

---

## 5. 우선순위별 조치 목록

### P0 — 협업/외부 노출·파일럿 시작 전 반드시
> (참고: 저장소 공유 자체의 하드 블로커였던 "시크릿 유출"은 점검 결과 무결. 아래는 네트워크 노출·파일럿 전 필수.)

1. **[보안·높음] path traversal 격리검사 추가** — [scribe.py:210](../vigent-core/agents/scribe.py#L210) `_evidence_data_uri` 및 [scribe.py:284](../vigent-core/agents/scribe.py#L284) `cv2.imread` 경로에 `data/evidence` 하위 강제(`is_relative_to`). 임의 파일 읽기 차단.
2. **[보안·높음] 취약 의존성 업그레이드** — pillow→12.3.0, requests→2.33.0, python-dotenv→1.2.2, setuptools→83.0.0, torch(CVE-2025-3000 대응버전 확인). 업그레이드 후 35 tests + 검출 회귀 확인.
3. **[운영·중간] 공유/파일럿 환경 `VIGENT_API_TOKEN` 상시화** — 무인증 로컬모드를 신뢰 못 하는 네트워크에서 기동 금지(규칙으로 문서화).

### P1 — 첫 2주 내 권장
4. **[협업] README + 온보딩 문서 정비** — 본 검토의 [ONBOARDING.md](ONBOARDING.md)를 루트 README에서 링크. Python 버전(3.11 vs 3.13) 불일치 해소, venv/`.python-version` 고정.
5. **[협업] 린터·포매터 도입** — ruff + black + pre-commit 최소 세트. 기존 `# noqa: BLE001` 규율과 정합.
6. **[구조·높음] VLM 호출 관용구 헬퍼화** — `vlm_text()` 1개로 14곳 흡수(§2.2). 저위험·고효과 리팩터.
7. **[구조·높음] main.py 분할 착수** — 최소한 인라인 HTML(`_TBM_NEW_HTML`·`_AUTO_HTML`)을 템플릿 파일로 분리, 라우트를 도메인별(safety/office/sports/tapo) `APIRouter`로 쪼갬.
8. **[보안·낮음] 토큰 비교 `hmac.compare_digest`로 교체** — [main.py:131](../vigent-core/main.py#L131).
9. **[안정성] worker의 `except: pass`에 로깅 추가** — 캡처 실패 은폐 방지(§2.4).
10. **[결정 필요] `rig_monitor.py` 배선 여부 확정** — 파이프라인 연결 or 명시적 "대기 중" 표기.

### P2 — 여유 있을 때
11. **[구조] 위험구역 로딩 3벌 통합**(§2.2), `_load_zone` 동명이인 정리.
12. **[품질] main.py/worker.py 반환 타입 힌트 보강**, mypy 점진 도입.
13. **[품질] worker.py `_loop` 책임 분해**(162줄 → 캡처/트래커/루프 분리).
14. **[테스트] 커버리지 확대** — 최소 `guard.detect`·`analyst`·엔드포인트 스모크 테스트 추가, CI에서 35 tests 자동 실행.
15. **[위생] 워킹트리 정리** — 사본 폴더(`VIGENT USB/` 등)를 리포 밖으로 이동 또는 `.gitignore`, `vigent-core/vigent-core/` 워크트리 잔재 제거, 한국어 식별자 통일.

---

## 부록 — 검토 방법(재현)

```bash
# 테스트 (반드시 의존성 있는 파이썬으로)
/opt/anaconda3/bin/python3 -m unittest discover -s tests      # 35 tests OK

# 의존성 취약점
/opt/anaconda3/bin/python3 -m pip_audit -r requirements.txt

# 시크릿 히스토리 점검(무결 확인됨)
git log --all --oneline -- .env                                # 결과 없음 = 안전
```
