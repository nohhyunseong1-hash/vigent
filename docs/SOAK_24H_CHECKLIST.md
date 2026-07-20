# VIGENT 24시간 소크 테스트 체크리스트 (실카메라)

> 목적: GPU 장비 + 실 RTSP 카메라가 확보되면 **이 문서만 따라 24시간 무인 안정성**을 실증한다.
> 도구: `tools/soak_monitor.py`(외부 관측) + `tools/stress_concurrent.py`(완만 부하). 둘 다 **소스 무수정·외부 관측만**.
> 합성 스트림 단축 소크로 도구 자체는 검증됨(2026-07-20). 실카메라 24h 는 아래 절차로.

---

## 0. 사전 조건

- [ ] **GPU 장비** (프로덕션은 Linux/CUDA 권장. Apple MPS 는 개발용 — F-14 이력·RSS 노이즈 참고).
- [ ] **실 RTSP 카메라 URL** 1개 이상 (예: `rtsp://user:pass@ip:554/stream`).
- [ ] `weights/` 커스텀 가중치 존재 확인 → `/health` 의 `rfdetr_slots` 가 **LOADED** 여야 함(COCO 폴백 아님, F-8).
- [ ] **단일 프로세스 원칙(F-14)**: 이 머신에서 VIGENT 서버는 **하나만** 띄운다. 개발 머신엔 launchd 에이전트
      `~/Library/LaunchAgents/com.vigent.dev8010.plist`(KeepAlive)가 8010 을 상주시키므로, 소크 대상 서버와
      **동시에 MPS 를 쓰지 않게** 한다(둘 중 하나만). 필요시 `launchctl bootout gui/$(id -u)/com.vigent.dev8010` 로
      잠시 내리고 끝나면 `launchctl bootstrap gui/$(id -u) <plist>` 로 복원.
- [ ] psutil 설치 확인(`python3 -c "import psutil"`) — 프로세스·시스템 메모리 관측에 필요.

## 1. 서버 기동

```bash
cd ~/Desktop/VIGENT/vigent-core
# 외부노출이면 토큰 필수(미설정 시 기동거부)
VIGENT_HOST=0.0.0.0 VIGENT_API_TOKEN=<비밀> \
  /opt/anaconda3/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port 8010
```
- [ ] `curl -s http://127.0.0.1:8010/health` → `"loaded":true` 이고 `rfdetr_slots` 전부 `LOADED`.
- [ ] 서버 **PID 확인**: `SRVPID=$(pgrep -f 'uvicorn main:app.*8010' | head -1); echo $SRVPID`

## 2. 카메라 워커 시작

```bash
# 카메라 1대(여러 대면 id 바꿔 반복). fps 는 현장 카메라에 맞춰.
curl -s -X POST http://127.0.0.1:8010/worker/start -H 'Content-Type: application/json' \
  -d '{"id":"cam1","source":"rtsp://user:pass@IP:554/stream","name":"현장1","fps":5}'
```
- [ ] `curl -s http://127.0.0.1:8010/workers` → 해당 카메라 `running:true`, `frames` 가 시간에 따라 증가.
- [ ] (선택) 위험구역을 UI(`/safety-pro`)에서 그려 두면 zone_intrusion 경보가 기록된다.

## 3. 24시간 소크 모니터 실행

```bash
cd ~/Desktop/VIGENT
SRVPID=$(pgrep -f 'uvicorn main:app.*8010' | head -1)
python3 tools/soak_monitor.py \
  --url http://127.0.0.1:8010 --pid "$SRVPID" \
  --duration 24h --interval 60 --warmup 600 \
  --load --load-concurrency 2 --load-delay 2.0 \
  --tag prod24h
```
- `--load` 는 UI 동시사용을 흉내내는 **완만한 HTTP 부하**(delay 로 스로틀 — 워커 락기아 방지). 순수 카메라만 볼 거면 `--load` 뺀다.
- `--warmup 600`: 초기 10분(모델 콜드로드·Metal 컴파일)은 누수·에러 판정에서 제외.
- 백그라운드로 돌리려면 `nohup ... &` 또는 `tmux`/`screen`. 종료(24h) 시 리포트 자동 생성.

## 4. 판정 기준 (soak_monitor 가 자동 판정 — 임계는 CLI 로 조정)

| # | 기준 | 기본 임계 | 불합격 조건 |
|---|---|---|---|
| 1 | **크래시 0** (필수) | — | 구간 중 프로세스 사망 또는 종료후 `/health` 실패 |
| 2 | **메모리 누수 없음** | `--rss-max-mb-per-hour 10` | median(앞1/4)↔median(뒤1/4) 증가율 초과 |
| 3 | **워커 생존율** | `--running-miss-max 0.05` | running<등록 샘플 비율 초과(워밍업 이후) |
| 4 | **재연결 복구율 100%** | — | RTSP 끊김 후 frames 재증가 실패 |
| 5 | **처리율 안정** | `--fps-degrade-floor 0.8` | 후반 fps < 전반 × 0.8 |
| 6 | **에러율 상한** | `--err-rate-max 0.01` | (probe실패+새 에러이벤트)/샘플 초과(워밍업 이후) |
| 7 | **hang 미복구 0** | — | hang 감지 후 워치독 복구 실패 |

- 메모리 판정은 **median 앞/뒤 창 비교**(MLX/Metal RSS 스윙에 강건). 24h 처럼 긴 창일수록 신뢰도↑.

## 5. 종료 후

- [ ] `audit/soakmon_YYYY-MM-DD_prod24h.md` — 합격/불합격 + 7기준 표 + 메모리/처리율/경보 요약.
- [ ] `audit/soakmon_YYYY-MM-DD_prod24h.csv` — 60초 간격 원자료(그래프·정밀분석용).
- [ ] `--load` 썼으면 `audit/soak_load_*.log`(부하 stress_concurrent 로그)도 확인.
- [ ] 종료코드: 합격 0 · 불합격 1.

## 6. 불합격 시 진단 가이드

| 실패 기준 | 먼저 볼 것 |
|---|---|
| 1 크래시 | 서버 로그의 `Fatal Python error`(F-14 회귀? → VLM 고정스레드·단일프로세스 확인) · watchdog 재기동 흔적 |
| 2 메모리 | CSV 의 `proc_rss_mb` 시계열 — 진짜 우상향인지 노이즈인지. 우상향이면 tracemalloc(soak_test.py `--tracemalloc`) |
| 3 워커생존 | CSV `workers_running` 급감 시점 ↔ `reconnects`/`hangs`/`new_errors` 상관 |
| 4 재연결 | 카메라 네트워크 안정성 · RTSP 재연결 백오프. `restarts`/`reconnects` 폭증이면 소스 불안정 |
| 5 처리율 | `--load` 가 워커를 굶겼는지(부하 concurrency↓·delay↑) · GPU 포화 |
| 6 에러율 | CSV `new_errors` 발생 시점의 서버 로그 예외 |
| 7 hang | `hangs_cum` 증가 시점 — 추론 지연(모델·GPU)인지 소스 정지인지 |

## 7. 주의 (규칙7 — 실측만)

- 합성 스트림에는 **RTSP 재연결이 없어 기준4는 N/A**로 나온다. 재연결 복구는 **실카메라에서만** 실측된다.
- Apple MPS 개발 머신은 RSS 가 노이지(통합메모리)하고 F-14 이력이 있다 — **24h 신뢰 판정은 프로덕션 GPU(Linux/CUDA) 권장**.
- 이 도구는 서버를 **관측만** 한다(소스 무수정). 판정은 관측 지표 기반이며, 현장 정확도(오탐/미탐)는 별도 검증 대상이다.
