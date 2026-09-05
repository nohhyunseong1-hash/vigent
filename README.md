# VIGENT

**Vision + AI Agent 산업안전 플랫폼.** 스마트 카메라 영상에서 위험(위험구역 침입·보호구 미착용·화재/연기·협착 등)을 실시간 탐지하고, AI 에이전트가 그 결과로 **법령 근거 위험성평가서**를 자동 초안화한다. 1차 완성 테마는 **safety**.

> ⚠️ **안전 경계**: 비전 ML은 확률적이라 인증 안전기능(안전 PLC·Type 4 방호장치)을 **대체하지 않는다.** VIGENT는 **보조·감시 계층**이며 모든 산출물은 "안전관리자 검토용 초안"이다.

---

## 빠른 시작 (로컬)

### 1. 파이썬 — 3.13 고정
이 저장소는 **Python 3.13.9** 기준으로 검증한다(`.python-version`). 모든 테스트·의존성 작업은 이 인터프리터로만 수행한다.
```bash
# ★ 이 환경의 정본 인터프리터(3.13.9):
/opt/anaconda3/bin/python3 --version        # Python 3.13.9
```
> ⚠️ 시스템 기본 `python3`가 다른 버전(예: 3.9)일 수 있다. **아래 명령은 반드시 위 정본 경로로 실행**한다.
> 편의를 위해 셸에서 `PY=/opt/anaconda3/bin/python3` 로 두고 `$PY …` 로 써도 된다.

### 2. 의존성 설치
```bash
/opt/anaconda3/bin/python3 -m pip install -r requirements.txt
# 선택: 평가/학습 도구
# /opt/anaconda3/bin/python3 -m pip install -r requirements-agents.txt   # 에이전트(LLM·RAG)
# /opt/anaconda3/bin/python3 -m pip install -r requirements-train.txt    # 학습·측정(구 requirements-eval)
```
> `torch`/`torchvision`은 플랫폼마다 설치법이 다르다(Jetson/CUDA는 기기용 휠 별도). `requirements.txt` 주석 참조.

### 3. 서버 실행
```bash
./run.sh                    # 로컬 개발: http://127.0.0.1:8010 (무토큰)
# 외부 노출은 토큰 필수:
# VIGENT_HOST=0.0.0.0 VIGENT_API_TOKEN=<비밀> ./run.sh
```
> `run.sh`는 uvicorn/fastapi가 설치된 파이썬을 자동 탐색한다(정본 경로 포함).

기동 확인:
```bash
curl -s http://127.0.0.1:8010/health | /opt/anaconda3/bin/python3 -m json.tool
# status: "ok", rfdetr_slots 3개 LOADED, llm.provider 확인
```
주요 화면: `/home`(허브) · `/safety/incident`(재해 원인분석) · `/health`.

### 4. 테스트
```bash
/opt/anaconda3/bin/python3 -m unittest discover -s tests    # 34 tests 통과가 정상
```

---

## 더 알아보기

| 문서 | 내용 |
|---|---|
| [docs/ONBOARDING.md](docs/ONBOARDING.md) | 신규 개발자용 — 아키텍처·핵심 흐름·엔드포인트 지도 |
| [DEPLOYMENT.md](md/DEPLOYMENT.md) | 표준 기동·확인(/health 3슬롯)·재기동·좀비 방지·환경변수 |
| [docs/CODE_REVIEW.md](docs/CODE_REVIEW.md) | 코드 검토 스냅샷(이슈·우선순위) |
| [benchmarks/FINDINGS.md](benchmarks/FINDINGS.md) | 측정·이관 과정의 리스크와 후속 태스크(F-1~) |
| [CLAUDE.md](CLAUDE.md) | AI 도구(에이전트) 작업 규칙 |

---

## 환경변수 (요약 — 상세는 DEPLOYMENT.md)

| 변수 | 기본 | 의미 |
|---|---|---|
| `VIGENT_HOST` / `VIGENT_PORT` | `127.0.0.1` / `8010` | 바인딩 |
| `VIGENT_API_TOKEN` | (없음) | 설정 시 전 라우트 Bearer 인증. **외부 바인딩엔 필수**(미설정 시 기동 거부). 공유 네트워크·파일럿에선 상시 설정 |
| `VIGENT_LLM_PROVIDER` | `openai` | 텍스트 LLM(`openai`/`anthropic`). 키 없으면 규칙 기반 폴백(기능 유지) |
| `VIGENT_CLOUD_VLM` | off | **1**일 때만 현장 프레임을 클라우드 VLM에 전송(기본 차단, 영상 불유출 원칙) |

---

## 설계 원칙 (핵심 2가지)
1. **절대 저하 없음 = 가산식 + 폴백.** 딥러닝 신호는 규칙 점수에 가산만. 모델/키/네트워크가 없거나 실패하면 휴리스틱·규칙으로 자동 폴백한다(코드의 `except … → 폴백`은 의도된 패턴).
2. **테마 = 코드가 아니라 설정.** 신규 테마는 `themes/<name>/vision.yaml` + 프론트 1개로 추가하고 코어 로직은 건드리지 않는다.
