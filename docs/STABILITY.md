# VIGENT 런타임 안정성 (STABILITY)

> 대상: 24시간 상시 가동되는 산업 안전 감시 서버(FastAPI + 헤드리스 워커).
> 범위: **무중단 · 자동복구 · 메모리/리소스 누수 · 프레임 신선도(지연)**.
> 이 문서의 모든 수치·동작은 실제 코드(`vigent-core/worker.py`·`main.py`·`deploy/watchdog.sh`)와
> 소크 리포트(`audit/soak_2026-07-08_*.md`)에 근거한다. **측정하지 못한 것은 "현장 미측정"으로 명시**했다.

관련 커밋: `9398313`(1단계) · `eb67c18`(2단계) · `11a92cd`(3단계) · `241f22a`(4단계) · `bb7b169`(RTSP 캡처 스레드).

---

## 1. 개요 / 목적

외부 기술 감사에서 **안정성이 C**로 지목됐다. 핵심 우려는 "프로세스는 살아 있는데(`/health` 200) 실제 감지는 죽어 있는" **무증상 실패**였다. 산업 안전에서 감지 중단·지연은 치명적이므로, 다음을 코드로 확보하고 실증했다.

- 워커(카메라 처리 루프)가 **죽어도 자동 재시작**(무증상 실패 차단)
- 워커가 **멈춰도(hang) 자동 감지·재기동**
- RTSP **끊김 시 자동 재연결**
- 장시간 가동에도 **메모리·FD 누수 없음**
- RTSP에서 **최신 프레임 처리**(과거 프레임 지연 누적 차단)

---

## 2. 문제 정의 (0단계 실측에서 지목된 갭)

| 갭 | 내용 | 닫은 단계 |
|---|---|---|
| 전역 예외 부재 | 워커 스레드 예외가 조용히 스레드를 죽여도 `/health`는 200 유지 | 1단계 |
| 워치독이 프로세스 레벨만 | `/health` 실패만 감지, **hang(멈춤)은 못 잡음** | 1·2·4단계 |
| RTSP 재연결 없음 | 스트림 끊김 시 `continue`만, 백오프·재연결 없음 | 2단계 |
| 워커별 상태 가시성 부족 | 카메라별 살아있음·마지막 프레임·재시작 횟수 불투명 | 2단계(`/status`) |
| 누수 후보 | `guard._tracks` 전역 공유 등 무한 증가 우려 | 4단계(점검) |
| 프레임 신선도 | 2fps 처리인데 RTSP 25~30fps 유입 → 버퍼에 과거 프레임 누적 | RTSP 캡처 스레드 |

---

## 3. 아키텍처 / 설계

### 3.1 워커 구조 — 감독자 + 프레임 격리 (1단계)

```
Worker.start() ──► _run_supervised (감독자, daemon 스레드)
                     │  while not stop:
                     │    _loop(...)  ← 크래시/hang/종료해도
                     │    └ 예외 → 로그 + 지수 백오프 재시작
                     └  _hang_watch (감시 데몬, 별도)
```

- **`_run_supervised`**: `_loop`이 예외로 빠지거나 조용히 종료돼도 `_stop` 전까지 **지수 백오프(1→2→…→30s 상한)로 재시작**. daemon 스레드가 소리 없이 사라지는 경로를 0으로 만든다.
- **프레임 단위 예외 격리**: `_loop` while 본문을 `try/except`로 감싸 **한 프레임 처리 실패가 루프를 죽이지 않음**(로그 남기고 다음 프레임).
- **하트비트**: `state["last_frame_ts"]`를 프레임마다 갱신. hang 감지의 기반.
- 재시작 시 하트비트를 `now`로 리셋해 **무한 재시작(옛 타임스탬프 재판정) 방지**.

### 3.2 2계층 방어 — 앱 내부(1차) + 워치독(2차)

```
프레임 정지 ──[15s]──► 앱 내부 hang 자동 재기동(1차)  ──[45s]──► 워치독 프로세스 재기동(2차)
                     VIGENT_HANG_TIMEOUT                    VIGENT_HANG_RESTART_S
```

- **1차(앱 내부, `_hang_watch`)**: `last_frame_ts`가 `HANG_TIMEOUT`(기본 15s) 이상 무진전이면 hang 판정 → `cap.release()`로 블로킹 언블록 + `_restart_req` → `_loop` 탈출 → 감독자 재시작.
- **2차(워치독, `deploy/watchdog.sh`)**: 프로세스는 살아있고 `/health`도 200이지만 `/status`의 `any_hang` + `slot/last_frame` 지연이 `HANG_RESTART_S`(기본 45s) 이상 지속되면 **프로세스 재기동**.
- **임계값 근거**: 1차(15s)가 2차(45s)의 1/3로 충분히 짧아, 워치독이 프로세스를 통째로 내리기 전에 앱이 먼저 스스로 복구한다. 프로세스 재기동은 **최후 수단**(다운타임 최소화). fps 2.0(=0.5s 간격) 기준 15s는 오탐 없이 진짜 멈춤만 잡는 여유값이다.

### 3.3 RTSP 캡처 스레드 (`_StreamCapture`) — 프레임 신선도

```
[캡처 스레드] ──continuously read──► [최신 1프레임 슬롯] ◄──read_latest── worker._loop (2fps 처리)
                                        (락 보호, 덮어쓰기)
```

- 배경: `CAP_PROP_BUFFERSIZE=1`은 **FFmpeg 백엔드(RTSP 기본)가 대부분 무시**한다(V4L2 웹캠 등 일부만 존중). BUFFERSIZE만으로는 현장 RTSP에서 여전히 과거 프레임을 처리할 위험이 있다.
- 해결: 백그라운드 캡처 스레드가 스트림을 계속 읽어 **최신 1프레임만 슬롯에 덮어쓰기**로 보관. 워커는 그 최신 프레임을 가져가 처리 → 백엔드와 무관하게 항상 최신.
- **BUFFERSIZE=1도 병용**(비용 0, 일부 백엔드 보조 효과). FFmpeg/RTSP에서는 무시될 수 있음을 코드 주석에 명시.
- **토글**: `VIGENT_CAPTURE_MODE=thread|sync`(**기본 sync** = 기존 동기 경로, 즉시 롤백 가능).
- **재연결**: 지수 백오프를 캡처 스레드 내부에 내장(`READ_FAIL_MAX` 연속 실패 → `cap.release()` → 백오프 → 재생성, 상한 `RECONNECT_MAX`).
- **감시 편입**: thread 모드에선 `last_frame_ts`를 **슬롯 갱신 시각** 기준으로 둔다 → 캡처 스레드가 멈추면 슬롯이 정지 → `last_frame_ts` 정지 → `_hang_watch`가 캡처 스레드 정지를 잡아 재시작. 캡처 스레드 사망 시 `_loop`이 종료돼 감독자가 재시작.
- **파일 소스는 이 구조를 쓰지 않음**(기존 동기 순차 처리·되감기 유지). 소스 타입 분기: 이미지 / 파일 비디오(순차·되감기) / 스트림(RTSP·웹캠·HTTP).
- **슬롯 스레드세이프**: `threading.Lock`으로 쓰기(캡처)/읽기(워커) 보호. 워커가 읽을 때 아직 첫 프레임이 없으면 **0.05s 대기 후 재시도**(직전 프레임 재사용 아님).

### 3.4 전역 예외 안전망 (1단계, `main.py`)

- `@app.exception_handler(Exception)`: 미처리 **요청** 예외 → 500 크래시 대신 구조화 로그 + 안전 응답.
- `threading.excepthook`: **daemon 워커 스레드**의 미처리 예외 포착(핵심 — 무증상 스레드 소멸 로깅).
- `sys.excepthook`(메인) + asyncio 예외 핸들러.
- `@app.on_event("shutdown")`: graceful shutdown(SIGTERM/SIGINT 시 `manager.stop_all()`로 워커 정리).

---

## 4. 설정 값 레퍼런스

로드 우선순위: **환경변수 → `config/tuning.yaml`[stability] → 코드 기본값** (`tuning.val`).

| 설정 | 환경변수 | tuning.yaml 키 | 기본값 | 의미 |
|---|---|---|---|---|
| hang 판정 임계 | `VIGENT_HANG_TIMEOUT` | `stability.hang_timeout_s` | **15.0s** | 프레임 무진전 이 시간 초과 → 앱 내부 hang 재기동(1차) |
| 재연결 백오프 상한 | `VIGENT_RECONNECT_MAX` | `stability.reconnect_max_s` | **30.0s** | 스트림 재연결 지수 백오프 최대 간격 |
| read 실패 임계 | `VIGENT_READ_FAIL_MAX` | `stability.read_fail_max` | **5** | 연속 read 실패 이 횟수 → 재연결 시도 |
| 캡처 버퍼 크기 | `VIGENT_CAP_BUFFERSIZE` | `stability.cap_buffersize` | **1** | 스트림 `CAP_PROP_BUFFERSIZE`(FFmpeg는 무시 가능) |
| 캡처 방식 | `VIGENT_CAPTURE_MODE` | — | **sync** | `thread`=캡처 스레드(최신 프레임) / `sync`=동기(롤백) |
| 기아 1단계(슬롯 회수) | `VIGENT_STARVE_GRAB_S` | `stability.starve_grab_s` | **60s** | `stale_detect` 지속 시 go2rtc 스트림 해제 → 카메라 슬롯 회수 |
| 기아 2단계(워커 재시작) | `VIGENT_HANG_RESTART_S` | `stability.starve_restart_s` | **120s** | 그래도 지속 → 해당 카메라 워커만 재시작 |
| 기아 3단계 승격 임계 | `VIGENT_HEALTH_FAILS` | `stability.starve_max_fails` | **3** | 이 횟수 실패 → 프로세스 재기동 승격 |
| 재기동 명령 | `VIGENT_RESTART_CMD` | `stability.restart_cmd` | (없음) | 3단계 재기동 커맨드. 미설정 시 경고만(Windows 서비스는 `deploy/windows/install_service.ps1` 이 설정) |

> ★[B3, 2026-08-16] 위 3종은 이전까지 **이 문서에만 있고 코드에 소비처가 없었다**(감사
> `audit/site_readiness_2026-08-16.md` §7 문서-실물 불일치). 이제 `vigent-core/starvation_guard.py`
> 가 실제로 읽어 단계별 승격을 수행한다. 근거·기전은 `audit/b3_root_cause_2026-08-16.md`.

> 소크 하네스 전용(운영 무관): `VIGENT_HANG_TIMEOUT`을 소크에서 짧게 주입해 hang을 빠르게 테스트.

---

## 5. 모니터링 — `/health` vs `/status`

- **`/health`**: 프로세스 생존용(200/비200). 워치독 1차 판정.
- **`/status`**: **워커 단위 세부 상태**(2단계 신설). 프로세스는 살아도 워커가 hang/정지인지 여기서 판단.

### `/status` 필드 (실측)

**요약**: `worker_count` · `running_count` · `any_hang`(하나라도 hang) · `uptime_s`.

**카메라별**(`cameras[cam_id]`):

| 필드 | 의미 | 현장 판단 |
|---|---|---|
| `running` | 워커 가동 여부 | false면 감독자 재시작 중/실패 |
| `last_frame_secs_ago` | 마지막 프레임 처리 후 경과(초) | `HANG_TIMEOUT` 근접 시 hang 임박 |
| `hang` | 멈춤 판정 | true면 1차 재기동 대상 |
| `frames` | 누적 처리 프레임 | 증가 정지 = 멈춤 |
| `restarts` | 감독자 재시작 횟수 | 급증 = 불안정 소스 |
| `reconnects` | 스트림 재연결 횟수 | 급증 = 네트워크/카메라 문제 |
| `hangs` | hang 감지 횟수 | >0 = 멈춤 이력 |
| `error` | 마지막 에러 | 원인 진단 |
| `capture_mode` | `thread`(캡처 스레드) 시 노출 | 신선도 모드 확인 |
| `slot_age_s` | 슬롯 나이=현재-슬롯시각(초) | **작을수록 신선**, 크면 캡처 지연 |
| `read_ms` | 프레임 read 소요(ms) | 신선도 프록시 |
| `capture_alive` | 캡처 스레드 생존 | false면 캡처 스레드 사망 |

---

## 6. 소크 테스트 방법론 (`tools/soak_test.py`)

**소스 무수정, 관찰·구동 전용** 하네스. worker를 그대로 import해 인프로세스로 N개 구동.

### 사용법
```bash
# 15분 스모크
python3 tools/soak_test.py --duration 15m --workers 3 --interval 30 --inject
# 1시간 (mock: 파이프라인 / real: 추론모델 포함)
python3 tools/soak_test.py --duration 1h --workers 2 --guard real --inject --tracemalloc
# 24시간 확증 (real 권장)
python3 tools/soak_test.py --duration 24h --workers 2 --guard real --inject \
  --inject-every 90 --hang-timeout 30 --fps 2 --warmup 120 --tracemalloc --tag real24h
```

| 파라미터 | 의미 |
|---|---|
| `--duration` | 15m·1h·24h·초 |
| `--workers N` | 합성 워커 수(다중 카메라 흉내) |
| `--interval` | 샘플 주기(초) |
| `--inject` / `--inject-every` | hang/kill 순환 주입 |
| `--guard mock\|real` | mock=합성 detect(cv2·tracker·rule 실행, 추론 제외) / real=실제 Guard(추론 포함) |
| `--tracemalloc` / `--trace-top` | 상위 할당 Top-N 추적 |
| `--warmup` | 초기 로딩 스파이크를 누수 회귀에서 제외 |
| `--url` | 외부 서버 `/health`·`/status` 병행 관찰 |

### mock vs real
- **mock**: 워커 루프·감독자·hang감시·재시작·tracker·rule·cv2 파이프라인의 누수 검증(경량, 장시간 반복 복구).
- **real**: RF-DETR·rtmpose **추론모델 상주 메모리의 시간 거동**까지 검증. RSS 기준선은 mock보다 높은 게 정상(모델 상주) — **판정은 절대값이 아니라 시간 기울기(우상향 여부)**.

### 단계적 실행 이유
`15분 → 1h → 24h`로 올린다. 15분에서 이미 RSS 우상향이 보이면 24h를 기다릴 필요 없이 원인을 잡는다. 리포트는 `audit/soak_YYYY-MM-DD[_tag].md`(+`.csv`).

---

## 7. 실증 결과 요약

| 소크 | RSS 기울기 | 크래시 | FD | 복구율 | tracemalloc |
|---|---|---|---|---|---|
| **mock 15분** | -2.73 MB/분 | 0 (3/3) | 4→4 | 14/14 = 100% | — |
| **mock 1h** | -0.03 MB/분 | 0 (3/3) | 4→4 | 39/39 = 100% | — |
| **real 1h** | -2.33 MB/분 | 0 (2/2) | 13→13 | 39/39 = 100% | +2.35MB(앱 누수 0) |
| **real 24h** | (진행 중 — §9) | | | | |

- **누수 판정**: 모든 소크에서 RSS 기울기가 0 이하(우상향 없음), FD·스레드 고정. real은 모델 상주로 RSS 기준선이 높지만(129~919MB 초기 스파이크 포함) 워밍업 이후 기울기 음수.
- **tracemalloc(real 1h)**: 1시간 total +2.35MB. 증가 지점이 전부 **테스트 하네스(`soak_test.py` 샘플 누적)와 torchvision/PIL 추론 프레임워크 상주** — **앱 코드(`vigent-core`) 라인은 Top에 없음** = 앱 누수 없음.
- **정적 점검(트래커)**: `guard._tracks`는 이중 만료(`misses>STALE_MAX_MISSES` + TTL), MotionTracker/ErgonomicsTracker는 hist 윈도우 만료 + 트랙 시간 만료(FallTracker는 2026-08 기능 제거로 더 이상 존재하지 않음, `docs/P3_BACKLOG.md` PF). **무한 증가 없음 → 만료 로직 추가 불필요**. `data_engine.log_event`는 디스크 jsonl append(메모리 누수 아님).

### RTSP 캡처 스레드 검증 (합성)
| 항목 | 결과 |
|---|---|
| A. `_StreamCapture` 단위(비디오 파일) | 슬롯 최신 갱신·alive·stop ✓ |
| B. thread 모드 통합 + 캡처 스레드 정지 주입 | 캡처 hang을 감시가 잡아 재시작·복구 ✓ |
| C. sync 롤백(미설정) | 기존 동기 경로 동작 ✓ |
| D. 파일 소스 무손상 | 순차 처리·되감기 유지 ✓ |
| E. 기존 테스트 24개 | 무손상 ✓ |

---

## 8. 운영 가이드

### 시작 / 중지
- 서버: `cd vigent-core && python3 -m uvicorn main:app --port 8010` (엣지 자동시작: `VIGENT_EDGE=1` → `config/site.yaml` 카메라로 워커 자동 기동).
- 캡처 스레드 모드로 RTSP 운영: `VIGENT_CAPTURE_MODE=thread` 로 기동.

### 장애 시 확인 순서
1. **`/status` 먼저 확인** → 어떤 워커가 이상인지.
2. 지표 해석:
   - `hang: true` / `last_frame_secs_ago` 큼 → 멈춤. 1차 재기동이 곧 동작(15s), 안 되면 워치독(45s).
   - `slot_age_s` 큼(thread 모드) → 캡처 지연/카메라 문제. `capture_alive` 확인.
   - `reconnects` 급증 → 네트워크·카메라. `restarts` 급증 → 소스 불안정.
3. 로그(`vigent.worker`)에서 hang 감지·재시작·재연결 이력 확인.

### 롤백 (thread → sync)
캡처 스레드에 문제 시: `VIGENT_CAPTURE_MODE` 미설정(또는 `sync`)으로 재기동 → 즉시 기존 동기 경로. 코드 변경 불필요.

---

## 9. 합격 기준 / 현재 상태 / 남은 것

### 완료 정의와 충족
| 기준 | 상태 |
|---|---|
| 워커 죽음(스레드 소멸) 자동 재시작 | ✅ 실증(1단계) |
| 워커 멈춤(hang) 감지·재기동 | ✅ 실증(2단계) |
| RTSP 끊김 재연결(지수 백오프) | ✅ 단위 실증(2단계) |
| 워커별 상태 가시성(`/status`) | ✅ |
| 장시간 메모리/FD 누수 없음(추론 포함) | ✅ real 1h 실증, tracemalloc 앱 누수 0 |
| RTSP 최신 프레임 처리 | ✅ 구조 실증(캡처 스레드 A~E) |
| 기존 기능·테스트 24개 무손상 | ✅ |

### ⚠️ 현장 미측정으로 남은 것 (정직한 명시)
- **실제 RTSP 지연(`slot_age_s`) 실측**: 이 개발 환경에 RTSP 서버·웹캠 권한이 없어 실지연을 측정하지 못했다. **계측 훅(`slot_age_s`·`read_ms`)은 `/status`에 심어두었으므로 현장 RTSP에서 즉시 확인 가능.** (수치를 지어내지 않았다.)
- **24h real 소크 확증**: 실행 중 / 결과 대기(명령은 §6). 1h real이 깨끗했으므로 확증 성격.
- **real 소크의 hang 주입**: `SoakGuard`(mock)에만 hang 주입 훅이 있어, real 소크는 kill 주입 위주. real의 hang 복구는 별도 단위 검증(2단계·캡처 스레드 B)으로 실증됨.

---

## 부록 — 감사 등급 근거 (안정성 C → 목표 B+)

| 감사 지적(C) | 대응 | 실증 근거 |
|---|---|---|
| 무증상 실패(스레드 소멸) | 감독자 + threading.excepthook | 예외 주입 A/B, "죽는 경로 0" |
| hang 감지 없음 | `_hang_watch` 1차 + 워치독 2차 | hang 주입 → 재기동·복구 |
| RTSP 재연결 없음 | 지수 백오프(워커/캡처 스레드) | 끊김 주입 → 재연결 |
| 상태 불투명 | `/status` 워커별 지표 | 필드 실측 |
| 누수 우려 | 정적 점검(만료 존재) + real 1h 소크 | RSS 기울기 ≤0, FD 고정, tracemalloc 앱 누수 0 |
| 프레임 지연 | 캡처 스레드(최신 프레임) | 구조 검증 A~E |

**남은 상향 근거(현장에서 채울 것)**: 실제 RTSP 지연 실측 + 24h real 확증. 이 둘이 채워지면 "코드 실증 + 현장 실측"이 모두 갖춰진다.

---

*작성 근거: 커밋 `9398313`·`eb67c18`·`11a92cd`·`241f22a`·`bb7b169`, 리포트 `audit/soak_2026-07-08_smoke15m.md`·`soak1h.md`·`real1h.md`.*
