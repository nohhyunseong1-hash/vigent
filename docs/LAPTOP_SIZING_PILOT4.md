# 파일럿(카메라 4대 + 노트북 1대) 노트북 사양 판정 — 실측 런북·결과 (작성 2026-09-08)

> **판정 원칙(대표 지시)**: 추정하지 않는다. **지금 있는 현장 노트북(i7-10750H / GTX 1650 Ti 4GB / DDR4 16GB / SSD 1TB)** 으로
> 재고, 그 결과로 판단한다. 답이 "지금 것으로 충분"이면 사지 않는다. 기준(§1)은 측정 전에 선언했고 측정 뒤 바꾸지 않는다.
>
> **이 문서의 상태**: §0(부하 목록)·§1(기준)·§2~6 절차·키트는 완성. **§2~§7 의 실측값은 전부 "미측정"** — 이 세션은 개발 PC
> (DESKTOP-STLQ1LM, Ryzen 9 9900X / RTX 5070 Ti)에서 돌았고 현장 노트북에 원격 접근 경로가 없다. 개발 PC 에서 돌린 것은
> **키트 동작 확인(드라이런)뿐**이며 판정에 쓰지 않는다(§8). 노트북에서 §2 명령 한 줄을 돌리면 결과 표(`audit/loadtest_*.md`)가
> 나오고, 그 표로 §7 을 채운다.

## 0. 운영 부하 목록 — 코드로 확정(추측 아님)

파일럿 운영 시 서버 프로세스(`service_entry.py → main.app`) 안팎에서 동시에 도는 것. 근거는 파일:줄.

| # | 항목 | 주기·규모(카메라 4대) | CPU | GPU | 근거 |
|---|---|---|---|---|---|
| 1 | RTSP 캡처(카메라별 스레드, TCP, 타임아웃 5s) | 4 스레드, 실스트림 디코드 | ● (FFmpeg 디코드, [E1] 실측 프레임당 <1ms → 병목 아님) | — | `worker.py:68-87`, `benchmarks/e1_bottleneck_report.md` H1 기각 |
| 2 | 검출 RF-DETR person·ppe·fire_smoke(풀세트 2fps 캡) | 4대 × 2fps = 8회/s, `DETECT_LOCK` 직렬화 | ● 전·후처리(카메라당 1.55 환산코어, [Q10]) | ● 추론 | `tuning.yaml worker.fullset_fps: 2`, `guard.py`, DEPLOYMENT §0 |
| 3 | 지게차 검출 — ★프로파일에 따라 다르다 | safety 기본: forklift 도 RF-DETR(backend 4슬롯 전부 rfdetr, F-7로 검출 목록에선 제외) · **학원 프로파일(`deploy/academy`): YOLO boda_ax** → **모델 2개(RF-DETR + YOLO) 동시** | ● | ● | `themes/safety/vision.yaml:16`, `deploy/academy/profile_intent.yaml:48` |
| 4 | 추적(ByteTrack person, 나머지 IoU) · 파생(근접·급이동·정지) · 규칙 판정 · 히스테리시스 · 구역 | 프레임마다 | ● | — | `agents/guard.py`, `worker.py` |
| 5 | 포즈(rtmlib RTMPose, onnxruntime **CPU 휠** intra_op 4스레드) | 사람 있을 때 카메라당 pose_fps 2 | ● | — | `requirements.txt:72 onnxruntime`(GPU 휠 아님), `tuning.yaml worker.pose_fps`, `ort_tune.py` |
| 6 | 얼굴 모자이크(YuNet `cv2.FaceDetectorYN`) | **저장·전송 이미지에만**(증거 JPEG·스냅샷·연결테스트) — 매 프레임 아님 | ● | — | `privacy.py:17,51`, `tuning.yaml privacy` |
| 7 | ★녹화 `scripts/field_recorder.py` — original.mp4 + overlay.mp4 | **서비스가 아니라 별도 프로세스**(방문 시 장면별 수동 실행). 4대면 프로세스 4개 · `cv2.VideoWriter(mp4v)` **인코더 8개** + 서버 `/cameras/{id}/snapshot` JPEG 인코드 2Hz×4 | ● (인코더 CPU) | — | `scripts/field_recorder.py:115,163-167` |
| 8 | 경보 큐(sqlite) 재시도 스레드 5s · 통보 스레드(텔레그램 HTTP) · 데드레터 요약 1h | 상시 스레드 3 | ○(미미) | — | `alert_queue.py:342`, `alert_notify.py` |
| 9 | 기아 감시(60s 슬롯 회수 / 120s 워커 재시작) · hang 감시 15s | 상시 | ○ | — | `starvation_guard.py:35-36`, `worker.py:44` |
| 10 | retention 스윕 | **24h 주기**, 기동 10분 뒤 첫 실행, data/ 28k 파일 순회 | ● 순간(디스크 I/O) | — | `tuning.yaml retention.sweep_interval_s 86400 / sweep_initial_delay_s 600` |
| 11 | 웹 UI `/hub`: `/health` 2s · 썸네일 1.3s · 스팟 1.2s 폴링(열어 둔 브라우저당) | 브라우저 1개당 초당 ~2.5 요청 | ○ | — | `themes/safety/index_hub.html:636` |
| 12 | go2rtc(확대뷰 WebRTC 변환기) | 스트림 등록된 카메라만, 시청 중일 때 | ● | — | `routers/cameras.py:337` |
| 13 | Windows 자체: Defender 실시간 검사(data/ 에 JPEG 생성마다), Windows Update, 검색 인덱싱 | 불규칙 | ● | — | OS — 키트가 **시스템 CPU 전체**를 따로 재므로 서버 프로세스 코어 수와의 차이가 곧 이 항목이다 |

**★녹화(7번)에 대한 결정 필요**: 현재 코드에서 녹화는 서비스 기능이 아니라 방문 시 검증용 스크립트다. 파일럿 운영 중에도 켜 둘 것인지는
대표 결정 사항이다. 켜기로 하면 키트를 `--record` 로 돌려 8개 인코더 부하를 **반드시 포함**해 잰다(§2). 켜지 않으면 `--record` 없이 재되
문서에 "녹화 미포함"으로 남는다. 기본 권고: **두 번 재서 둘 다 표에 남긴다**(4시간 × 2 는 길므로, 미포함 4h + 포함 1h 로 차분만 본다).

**★"GPU 가 아니라 CPU 가 병목" 재확인 포인트**: 개발 PC 실측([E1])은 8대에서 GPU util 16~42%로 놀고 CPU 가 포화했다. 노트북(6코어/12스레드,
GTX 1650 Ti)에서도 같은지 — 키트가 매 샘플 **시스템 CPU%·서버 환산코어·GPU util·GPU 클럭**을 나란히 기록하므로 4대·5대·6대에서 어느 쪽이
먼저 한계(CPU ≥ 70% / GPU util ≥ 90% / VRAM ≥ 3.5GB)에 닿는지 표에서 바로 읽힌다.

## 1. 합격 기준 — ★측정 전 선언(2026-09-08). 측정 뒤 바꾸지 않는다

키트 `scripts/pilot_load_test.py` 머리의 `PASS` 와 동일하며 결과 JSONL 머리에 복사된다.

| 항목 | 기준 | 측정 방법 |
|---|---|---|
| 검출 주기 | 4대 모두, 10분 창마다 `last_detect_age_s` **p95 ≤ 1.0s**(2fps 주기 0.5s 의 2배 이내) **그리고** age ≤ 0.55s 비율 **≥ 90%**(허용 편차 10%) | 창마다 30초 동안 2초 간격 `/health` 폭주 샘플 |
| 경보 지연 | 큐 적재(created_at) → 텔레그램 전송 완료(sent_at) **p95 ≤ 5s**; 침입 프레임 → 적재 ≤ 1s(검출 주기 0.5s + 판정) → **합계 ≤ 6s**. 채널 미설정이면 "미측정" | `data/alert_queue.db` 창 내 행. 현장 시험 실측(2026-08-27) 중앙값 1.8s·최대 3.7s 가 참고선 |
| CPU 상한 | 10분 창 평균 **시스템 CPU ≤ 70%** · 서버 프로세스 **≤ 8.0 환산코어**(12스레드의 2/3) | typeperf `\Processor(_Total)\% Processor Time` 5초 평균 · 프로세스 CPU 시간 차분 |
| 메모리 상한 | 서버 RSS **≤ 6GB** · 시스템 가용 **≥ 2GB** · 소크 동안 RSS 기울기 **≤ 100MB/h**(누수) | WorkingSet64 · Win32_OperatingSystem |
| degraded | **카메라 사유 0건**. 경보 적체(pending/dead_1h) 사유는 따로 세고 판정에서 제외(채널 문제) | `/health` cameras[*].status ≠ ok, slot_degraded |
| 프레임 유실 | 창마다 카메라별 dropped_frames 증가 ≤ 창 예상 프레임(2fps×600s=1,200)의 **1%** · 파일 카메라 재연결 **0** | `/health` dropped_frames·reconnects 차분 |
| 발열(스로틀링) | 3시간 이후 창의 CPU `% Processor Performance` 와 GPU SM 클럭이 **첫 30분 평균의 80% 이상** · GPU 온도 **< 87°C** | typeperf `\Processor Information(_Total)\% Processor Performance`, nvidia-smi clocks.sm/temperature |
| VRAM | 사용 **≤ 3.5GB**(4GB 의 87%) | nvidia-smi memory.used |
| 지속 시간 | 소크 **≥ 4h**(8h 권장). 4h 미만은 결과 파일을 남기되 **무효** 표시 | 키트가 자동 표기 |
| 과부하(4단계) | 판정 항목 아님 — 5·6대에서 드롭/밀림/사망, 경보 지연 증가폭, degraded 표시 여부를 **기록**. 알림 없이 조용히 느려지면 **결함으로 등재** | 같은 샘플러 |

## 2. 노트북에서 돌리는 명령(2~5단계를 한 번에)

전제: 노트북에 이 브랜치(`main`, 태그 v-audit-2026-09 이후)가 있고 서비스가 떠 있다(`deploy\windows\service_status.ps1` exit 0),
학원 프로파일이면 `deploy\academy` 적용 상태(README_academy), `.env` 에 토큰, 모의 영상 `VIGENT_DATA_DIR\runs\rfdetr\accident\*.mp4` 9개
(개발 PC `D:\vigent_private_data\runs\rfdetr\accident` 에서 복사 — 저장소에 없다).

```powershell
cd D:\vigent_original          # 노트북의 저장소 경로
# 2·3단계: 4대 · 4시간(8시간이면 --hours 8) · 10분 간격 · 4단계: 5대·6대 각 20분 → 정리 → 보고서
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --tag laptop_4cam
# 녹화 포함 차분(대표가 "운영 중 녹화"를 켜기로 한 경우): 1시간
python scripts\pilot_load_test.py --cams 4 --hours 1 --interval 600 --overload-cams 0 --record --tag laptop_4cam_record
# 실카메라 4대가 있으면(6단계 네트워크 포함): rtsp 주소 4줄을 cams.txt 에(자격증명 포함, 파일은 저장소 밖에 둘 것)
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --rtsp-list D:\vigent_field\cams.txt --tag laptop_4cam_rtsp
# 중단됐을 때
python scripts\pilot_load_test.py --phase cleanup
```

키트가 스스로 하는 검증(1차 프로브 무효 사유 재발 방지): 등록은 `enabled: true` 고정 → `/health` running 대수를 세어 N 과 다르면
**무효 기록 후 중단** · 유령 카메라(등록에 없는데 `/health` 에 남음)·age 비정상 카메라가 있으면 **중단** · 정지 카메라는 집계에서 제외
(`--exclude`) · degraded 를 카메라/경보 사유로 분리 · GPU·CPU 를 매 샘플 함께 기록 · 결과 파일에 기준·호스트·CPU·GPU·소스 종류·녹화 여부 기록.

결과: `audit\loadtest_<시각>_<tag>.jsonl`(원시) + `.md`(표·판정). 두 파일을 저장소에 커밋한다(비밀값 없음 — rtsp 자격증명은 마스킹).

## 3. 지속 부하(3단계) — 표를 읽는 법

`.md` 의 "소크 샘플" 표에서 시간축으로 본다: `CPU perf%`(클럭 성능, 100 = 정격)와 `GPU clk` 가 초반 대비 떨어지면 스로틀링,
`RSS` 가 우상향이면 누수, `경보 p95s` 가 뒤로 갈수록 커지면 적체다. 키트는 첫 30분 평균 vs 3시간 이후 평균을 자동 비교한다.
`CPU°C` 는 `\Thermal Zone Information` 카운터가 있는 기종에서만 값이 찍힌다(없으면 빈칸 = 미측정, 추정치로 채우지 않는다).

## 4. 과부하(4단계) — 기록할 것

5대·6대 구간 표: `age p95`(밀림) · `dropped`(버림) · `overall`(degraded 로 표시되는가) · `경보 p95s`(늦어지는가, 몇 초까지) · 서버 프로세스
생존(`RSS` 빈칸이면 죽은 것). **`overall` 이 healthy 인데 `age p95` 가 1s 를 넘거나 경보 p95 가 늘어나면 "조용히 뒤처짐" = 결함** →
CODE_REVIEW 후속 등재(현재 `/health` 의 카메라 상태는 `detect_stale_s` 임계로만 판정한다 — `health_status.py`).

## 5. 저장 용량(5단계)

- 실측 입력: 키트 `.md` 하단 "저장 용량" — 소크 동안 `data/`+`logs/` 증가량 → **MB/일/카메라**. 4대 × 보존일 = 필요 용량.
- 보존일(코드 확정, `config/tuning.yaml retention.groups`): evidence 30일 · recognition 30일 · audit/tbm/risk_assessments 1,095일 · field_eval 365일(저장소 밖) ·
  운영 로그(go2rtc·legal) 상한 50MB 회전 · alert_queue_days 미설정(주석) · 스윕 24h 주기·기동 10분 뒤 첫 실행.
- 계산식: `1TB 지속일 = (1,000,000MB − OS·앱·가중치 점유) ÷ (4 × MB/일/카메라)` — 증거(30일)만 순환하므로 30일 이후엔 audit 류(작음)만 누적.
  **숫자는 노트북 실측값이 나온 뒤 채운다(미측정).**
- ★retention 이 실제로 도는지: `data/retention/status.json`(`last_run`) 과 `/health disk_retention.pending_count` 를 소크 뒤 확인. 과거에 스윕이 아예 안 돌던
  사고가 있어 [F6] 자동 스윕 + [M7-8] 지연 보정이 들어갔다 — 소크 4h 로는 24h 주기가 한 번도 안 올 수 있으니 `sweep_initial_delay_s 600` 뒤 첫 실행이
  status 에 남는지를 본다.

## 6. 네트워크(6단계) — 실카메라 전용

키트는 `net_rx_mbps`(어댑터 수신 합) 를 창마다 기록한다(파일 소스면 0 근처 = 의미 없음). 실카메라 4대 `--rtsp-list` 실행에서:
4대 동시 수신 대역폭 · 재연결 횟수(`reconnects`) · WiFi 에서 age p95 가 유선보다 얼마나 나쁜지. 재접속 시험은 소크 중 카메라 1대 전원을 30초 끊었다
붙여 `reconnects` +1 과 `status` 복귀(ok)까지의 시간을 표에 적는다(키트는 상태만 기록, 전원 조작은 사람). 유선 판단 근거 = WiFi 에서 기준(검출 주기·재연결 0)
미달이면 유선. **미측정.**

## 7. 판정·구매 사양 — §2~§6 결과가 나온 뒤에 채운다

| 항목 | 노트북 실측 | 기준 | 통과/미달 |
|---|---|---|---|
| 검출 주기(4대) | 미측정 | age p95 ≤ 1.0s · ok ≥ 90% | — |
| 경보 지연 | 미측정 | 큐→전송 p95 ≤ 5s | — |
| CPU | 미측정 | 시스템 ≤ 70% · 서버 ≤ 8코어 | — |
| 메모리 | 미측정 | RSS ≤ 6GB · 가용 ≥ 2GB · ≤ 100MB/h | — |
| degraded(카메라) | 미측정 | 0 | — |
| 프레임 유실 | 미측정 | ≤ 1% · 재연결 0 | — |
| 발열 | 미측정 | 3h 후 ≥ 초기 80% · GPU < 87°C | — |
| VRAM | 미측정 | ≤ 3.5GB | — |
| 저장(1TB 지속일) | 미측정 | §5 계산 | — |
| 네트워크(WiFi 4대) | 미측정 | 재연결 0 · 주기 기준 | — |

판정 규칙: A 전부 통과 → **사지 않는다**. B 통과지만 CPU 60~70% / 발열 80~90% / VRAM 3~3.5GB 처럼 여유 10% 미만 → 부족 항목 지목.
C 미달 → 병목 항목(CPU 코어·클럭·메모리·디스크·발열) 특정 후 **그 병목만 넘기는 최소 사양**.

**하드 제약(사양서에 반드시)**: Windows **Pro**(BitLocker N-2 + 서비스 계정 — Home 불가, 값싼 노트북은 대부분 Home) · 하루 종일 가동이므로 발열 설계
(얇은 기기 주의, 3h 후 클럭 유지가 §1 기준) · **VRAM 4GB 로 충분한지는 §7 VRAM 행 실측으로 재확인**(개발 PC 실측 1.4GB 이므로 맞으면 비싼 GPU 를 넣지 않는다) ·
저장 용량은 §5 계산값.

## 8. 무효·참고 측정(지우지 않는다)

| 회차 | 무엇 | 왜 판정에 못 쓰나 |
|---|---|---|
| 2026-08-18 capacity_probe(한계 7대/권장 5대) | 개발 PC Ryzen 9 9900X / RTX 5070 Ti | 다른 기계. 병목 구조(CPU) 규명에만 유효 |
| 2026-09-08 키트 드라이런 | 개발 PC, 4대 모의, 7분 소크 + 5대 2분 | 다른 기계 + 4h 미만. **키트가 끝까지 돌고 표를 만드는지 확인한 것뿐**(§8-1) |

### 8-1. 드라이런 기록(개발 PC) — 아래는 키트 동작 확인 결과이며 사양 판정 근거가 아니다

- 실행: 2026-09-08 21:22~21:35, 개발 PC(Ryzen 9 9900X / RTX 5070 Ti), 모의 4대(파일) 7분 소크(60s 간격) + 5대 2분, `--exclude test`(오프라인 실카메라 1대는 집계 제외·상태만 기록), 녹화 미포함.
- 결과 파일: `audit/loadtest_20260908_2122_devpc_dryrun.{jsonl,md}` — 키트 종료코드 1(**무효**: 소크 0.1h < 4h · VRAM 4,008MB > 3.5GB 기준은 16GB 카드가 넉넉히 잡은 값이라 노트북과 무관).
- 키트가 확인한 것: 등록 4/4 running 확인 → 예열 → 창마다 CPU·CPU perf%·GPU util/VRAM/온도/클럭·RSS·카메라별 age p95·검출 ms·drop·degraded(카메라 0 / 경보 적체 15 — 이 PC 텔레그램 config_error 로 인한 데드레터, 판정 제외)·경보 행·data+logs 크기 기록 → 5대 과부하 2샘플 → 정리 5/5 제거·`/health` 잔존 0 → 표·판정 생성. `CPU°C` 는 이 PC 에 열 카운터가 없어 빈칸(미측정) — 노트북에서 채워지는지 확인 대상.
- 참고 관찰(판정 아님): 4대에서 시스템 CPU 31→57%, 서버 6.3→7.5코어, GPU util 1→89%(3분 시점에 VRAM 2.5→4.0GB 로 뛰며 검출 ms 가 2배 — 어떤 모델이 뒤늦게 올라온 것인지 미확인) · 5대에서 서버 9.3코어·시스템 69%.
- **잔재(개발 PC 운영 data/, 지우지 않음)**: 경보 큐 행 id 88~113(26건, 전부 dead/config_error — 실제 텔레그램 발송 0) · `data/evidence/20260908` JPEG 175장 · `data/recognition/events_20260908.jsonl` 297행 — 카메라명 `파일럿모의N`/`pilotNN` 으로 식별되는 시험 잔재. retention 30일이 지운다.
- 드라이런에서 고친 키트 결함: 출력 버퍼링(줄 단위 flush) · 결과 파일 접두 `pilot_`→`loadtest_`(.gitignore 의 사업문서 규칙 `pilot_*.md` 에 걸림) · 경보 pending 최대값 기록.
