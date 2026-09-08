# Phase 3. 영상 입력 및 스트림 안정성 — 검토 보고서

> 검토일 2026-09-08 · 브랜치 `audit/cleanup-20260906` (HEAD `d4517fc`) · 검토자: 수석 아키텍트(외부 시점)
> 방식: **코드 정독 + 저장소 내 실측 기록 인용만.** 서버 기동·코드 수정·카메라 접속은 하지 않았다.
> 유일하게 실행한 것은 `.venv` 의 `cv2.getBuildInformation()`(모듈 import, 서버 무관)이다.
> 읽지 않았거나 저장소에 근거가 없는 항목은 **"확인 필요"** 로 표기했다. 비밀값(RTSP 자격증명·IP)은 싣지 않았다.

---

## 0. 한 줄 요약

RTSP 1대 기준의 **입력 경로·재연결·헬스 판정은 코드와 실측이 잘 맞물려 있다**(죽은 IP 5.05s 타임아웃, 전원차단 복구 6~50s, 실카메라 24h 소크 합격).
그러나 **"4대 동시 RTSP" 는 한 번도 실측되지 않았고**, **입력 단절(카메라 사망)이 `/health` 에서 `stale_detect`(추론 사망)로 오분류**되며, **카메라 오프라인을 누구에게도 push 통보하지 않는다**. 카메라 자체 이상(가림·초점·과노출)·ONVIF·H.265 HW 디코드는 없다.

---

## 1. 입력 처리 능력 매트릭스

| 항목 | 현재 상태 | 근거 | 평가 |
|---|---|---|---|
| **RTSP(H.264)** | 지원. FFMPEG 백엔드 + TCP 강제 + `nobuffer/low_delay/max_delay 0.5s` | `vigent-core/worker.py:68-69`, `:85-87` | ✅ 실카메라(Tapo C200, 1080p h264 15fps) 검출 p50 184ms 실측(`docs/academy_visit_day.md:669`) |
| **RTSP(H.265/HEVC)** | 코드상 분기 없음(FFmpeg 가 디코드하면 됨). **현 cv2 4.13 휠(FFmpeg 4.4, avcodec 58.134)에서 미검증** | HEVC **파일** 디코드 통과 기록은 2026-08-19(`audit/site_precheck_2026-08-19.md:30-35`) — 당시 cv2 5.0/FFmpeg 7.1. cv2 는 2026-09-06 에 **4.13.0.92 로 고정**(`md/DEPLOYMENT.md:174-176`, 커밋 `f12182c`) | ⚠ **재검증 필요**. 현장 문서도 "H.265 미검증"(`benchmarks/field_academy_2026-08-27.md:128`) |
| **하드웨어 디코드(NVDEC/D3D11/QSV)** | **없음**. `CAP_PROP_HW_ACCELERATION` 미사용. 소프트웨어 디코드만 | grep `hwaccel|cuvid|nvdec|d3d11|qsv|HW_ACCEL` → 런타임 코드 0건. 의도적 결정: "NVDEC 에 돈 쓰지 말 것"(`docs/INFRA_REQUIREMENTS.md:47`) | 🔸 E1 근거(디코드 0.4~1.2ms/프레임, `benchmarks/e1_bottleneck_report.md:165-172`)는 **파일 소스 2fps 순차 읽기** 측정치다. 실 RTSP 15~30fps 를 캡처 스레드가 **전부 grab(=디코드)** 하는 경로의 CPU 는 별개(§5) |
| **로컬 파일(mp4 등)** | 지원. EOF 시 `POS_FRAMES=0` 되감기(루프 재생). 캡처 스레드 미사용(순차) | `worker.py:1182`, `:1251-1256` | ✅ 24h 소크 통과(§4) |
| **정지 이미지** | 지원(`cv2.imread` 1회, 매 루프 copy) | `worker.py:1181-1183`, `:1223-1224` | ✅ 테스트용 |
| **웹캠/USB(정수 인덱스)** | 지원. 기본 백엔드, 타임아웃 없음. 스트림으로 분류돼 캡처 스레드 경로 | `worker.py:80-81`, `:1184` | 🔸 Windows MSMF 열기 지연·장치 분리 시 동작 **미측정** |
| **HTTP/MJPEG URL** | 코드상 FFMPEG 경로로 흐름(비파일·비정수 문자열 전부) | `worker.py:84-87` | ❓ **확인 필요** — 실측 기록 없음 |
| **ONVIF / 자동 검색** | **없음** | grep `onvif|ws-discovery` → 0건 | ❌ 주소를 사람이 입력(§7) |
| **NVR 경유** | RTSP URL 을 직접 넣으면 가능(코드 분기 없음). 미검증 | `benchmarks/field_academy_2026-08-27.md:128`, `audit/d3_recheck_2026-08-26.md:75` | ❓ 주소 형식·서브스트림 해상도 미확인 |
| **재접속 백오프** | 캡처 스레드: 연속 `read_fail_max`(5)회 실패 → release → 1→2→4→**5s 상한** → 재오픈, `generation+1`. sync 모드도 동일 | `worker.py:55`, `:693-711`, `:1257-1278`; 30→5s 축소 근거 `audit/b3_root_cause_2026-08-16.md` | ✅ 상한 5s 확인. 단 §3-이슈 I-3 참조(실제로는 hang 워치독이 먼저 발화) |
| **열기/읽기 타임아웃** | OpenCV `CAP_PROP_OPEN/READ_TIMEOUT_MSEC` = 5000ms | `worker.py:74`, `:85-87` | ✅ 죽은 IP **123.4s → 5.05s** 실측(`benchmarks/rtsp_capture_probe.py:19-25`, `md/DEPLOYMENT.md:176`). FFmpeg `timeout` 옵션은 4.13 에서 **즉시 실패**라 쓰지 않음(정확한 판단) |
| **디코딩 오류 처리** | `grab/retrieve` 실패 → `dropped+1` → 연속 5회면 재연결. 프레임 단위 예외는 `_process_frame` 에서 격리 | `worker.py:693-714`, `:1134-1138` | ✅ 부분 손상 프레임(회색 블록 등)은 **감지하지 않음**(FFmpeg 가 ok=True 로 넘기면 그대로 추론) |
| **프레임 드롭 정책(최신 우선)** | thread 모드: 캡처 스레드가 `grab()` 을 20ms 간격 판정으로 최대 60회 드레인 후 마지막만 `retrieve` → 슬롯 1장 덮어쓰기. 워커는 2fps 로 슬롯의 최신 1장만 소비 | `worker.py:679-691`, `:717-719`, `:1226` | ✅ 설계 타당. 단 **드레인으로 버린 프레임 수는 어디에도 노출되지 않는다**(`dropped` 는 읽기 실패 수) |
| **캡처 모드 기본값** | 코드 기본 **`sync`**, 서비스·`run.ps1` 은 **`thread`** 주입 | `worker.py:1186`; `deploy/windows/install_service.ps1:160` | 🔸 코드 기본과 운영값이 다르다. 문서 `docs/STABILITY.md:75,100` 도 "기본 sync" 로 서술 |
| **해상도·fps 다운샘플링** | 캡처 측 리사이즈 없음(원본 1080p 유지). 추론은 guard 의 `imgsz`(현장 384)로 축소. 처리 fps 는 워커 루프 2fps(등록값)로 표본화 | `agents/guard.py:402,976`; `deploy/SITE_CHECKLIST.md:199`; `worker.py:1296-1297` | ✅ 증거·스냅샷은 원본 해상도(스냅샷만 640×360 축소, `routers/cameras.py:184`) |
| **캡처 버퍼** | `CAP_PROP_BUFFERSIZE=1` 병용(FFmpeg 는 무시 가능 — 주석에 명시) | `worker.py:59`, `:661` | ✅ 정직한 주석 |

---

## 2. 카메라 헬스 감지 매트릭스

| 감지 항목 | 감지 여부 | 판정 위치·임계 | 알림 경로 | 평가 |
|---|---|---|---|---|
| **워커 정지(stopped)** | ✅ | `health_status.py:54-55` | `/health` cameras · 허브 배지 `off` | — |
| **프레임 정지(stale_frame)** | ✅(단 §3 I-1 오분류) | `frame_age > 30s` (`health_status.py:38, 75-77`; `config/tuning.yaml:211`) | `/health`(전 카메라 정지 시 **503**, 일부면 200+degraded, `routers/system.py:237`) · 허브 배지 `D` "입력 끊김"(`themes/safety/index_hub.html:206,260`) | ⚠ hang 재기동이 `last_frame_ts` 를 리셋해 **입력 단절이 stale_detect 로 보인다**(I-1) |
| **검출 정지(stale_detect)** | ✅ | `detect_age > 30s && frame_age ≤ 30s` (`health_status.py:70-73`) | 위와 동일 + 기아 감시 3단계(`starvation_guard.py:105-131`) | ✅ P0 지문 설계는 우수(2026-08-16 실증) |
| **hang(루프 무진전)** | ✅ | 15s, 기동 90s 유예 (`worker.py:44,48`, `:873-902`) | 로그 ERROR + `state.hangs` | ✅ |
| **재연결 횟수·세대** | ✅ | `reconnects`, `session_generation`, `dropped_frames` | `/health` | ⚠ 워커 재기동 시 **0 으로 리셋**돼 오독(`docs/academy_visit_day.md:401-408` 자체 인정) |
| **온라인 플래그(`/cameras.online`)** | 🔸 | `online = bool(running)` (`routers/cameras.py:77`) | 허브 타일 | ⚠ "워커가 돌고 있음"이지 "카메라가 살아 있음"이 아니다 |
| **화면 가림(tamper)** | ❌ 없음 | grep `tamper|가림` → 런타임 코드 0건 | — | ❌ 경쟁 열위(§7) |
| **초점 이탈(defocus/blur)** | ❌ 없음(오프라인 도구만: `benchmarks/blur_check.py` 라플라시안 분산) | — | — | ❌ |
| **과노출/저조도** | ❌ 없음 | grep `overexpos|과노출|brightness` → 0건 | — | ❌ 야간·역광 자체가 "미측정"(`docs/onboarding/04_지금_성능.md:59`) |
| **카메라 이동(팬/틸트)** | 🔸 부분: 급격동작 오발화 억제용 `camera_motion` 플래그만 | `worker.py:516-520`, `:604-613`, `:1088-1090` | `state.camera_motion_frames` (알림 없음) | 🔸 "카메라가 돌아갔다"를 운영자에게 알리진 않음 |
| **텔레그램/푸시 통보(카메라 이상)** | ❌ 없음 | `alert_notify`·`dispatcher`·`routers/dispatch.py` 에 `stale_*`/`unhealthy` 참조 0건. 기동 실패만 통보(`main.py` `_notify_startup_failure`) | — | ❌ **무인 운영에서 카메라 단절을 아무도 모른다**(I-2) |
| **외부 워치독** | 🔸 | `deploy/windows/service_status.ps1` 종료코드 0/1/2/3 | 사람이 실행해야 함 | 🔸 자동 통보 배선 없음 |

---

## 3. 이슈 목록

형식: **[심각도] 제목** — 근거 / 영향 / 권장 / 공수(S·M·L)

### I-1 [P1] 입력 단절(카메라 사망)이 `/health` 에서 `stale_detect`(추론 사망)로 오분류된다
- **근거(코드)**: `worker.py:917` `_run_supervised` 가 `_loop` 재진입 때마다 `last_frame_ts = time.time()` 로 리셋. thread 모드에서 카메라가 죽으면 슬롯이 안 채워져 `last_frame_ts` 가 멈추고(`worker.py:1229-1234` 는 갱신 없이 `continue`), 15s 뒤 `_hang_watch`(`:892-897`) 가 재기동 → `:917` 이 다시 now 로 리셋. 따라서 `frame_age` 는 **최대 ~17s 를 넘지 못한다**. 반면 `last_detect_ts` 는 `_process_frame` 에서만 갱신(`:1049`)되므로 30s 를 넘고, `health_status.py:70-73` 의 분기 `detect_age>30 && frame_age≤30` 이 **STALE_DETECT** 를 낸다.
- **근거(실측)**: ① `audit/soak_after_fixes_2026-08-26.md` "네트워크에서 빠진 cam_c200 … `/health.cameras: cam_c200 stale_detect` … `[기아 2단계] 워커 'cam_c200' 재시작`" — 죽은 주소가 stale_detect 로 잡혀 기아 감시(추론 사망 대응)가 발동했다. ② `audit/reconnect_test_2026-08-16.md` 3회차 "`stale_frame` ↔ `stale_detect` 전환이 반복 … `hangs` 17→20". ③ `docs/academy_visit_day.md:401-408` "전원 20초 차단 … HANG 워치독 6회 재기동 … `reconnects` 0".
- **영향**: 운영자 화면 배지가 **"검출 정지(영상만 수신)"**(`index_hub.html:260`)로 찍혀 "영상은 오는데 추론이 죽었다"고 오독한다(실제는 케이블·전원·IP 문제). 기아 감시가 **불필요하게 go2rtc 슬롯을 회수하고 워커를 재시작**한다(`starvation_guard.py:121-131`). 진단 시간이 늘고, 문서(`md/DEPLOYMENT.md:596` "stale_detect 면 검출만 죽은 것")가 틀린 안내가 된다.
- **권장**: (a) hang 재기동 시 `last_frame_ts` 를 리셋하지 말고 **별도 `loop_alive_ts`(하트비트)** 로 hang 판정을 분리, `frame_age` 는 실제 마지막 프레임 시각을 유지. (b) 또는 `_StreamCapture.generation/dropped` 와 `capture_alive` 를 `camera_status` 입력에 넣어 "캡처가 프레임을 못 받는 중" 을 우선 판정. (c) `tests/test_health_detect_alive.py` 에 "hang 재기동 반복 + 카메라 사망" 시나리오 추가.
- **공수**: **M** (worker 하트비트 분리 + health_status 분기 + 테스트)

### I-2 [P1] 카메라 오프라인·검출 정지를 push(텔레그램 등)로 통보하는 경로가 없다
- **근거**: `alert_notify.py`·`dispatcher`·`routers/dispatch.py`·`starvation_guard.py` 어디에도 `stale_frame|stale_detect|unhealthy` 를 통보로 보내는 코드가 없다(grep 0건). `/health` 는 폴링 전제(`routers/system.py:237` 503 반환). `deploy/windows/service_status.ps1` 는 사람이 실행하는 스크립트.
- **영향**: 4대 중 1대가 야간에 죽으면 `/health` 는 **200 + degraded**(`health_status.py:150-154`)이고, 아무도 통보받지 못한 채 그 구역은 무감시가 된다. 제품이 "무인 24시간 감시" 를 표방하는 이상 **감시 공백을 알리지 않는 것 자체가 신뢰성 결함**이다. (단일 카메라 현장이나 무인 야간 운영이면 P0 로 봐야 한다 — 확인 질문 Q1.)
- **권장**: `starvation_guard._tick` 또는 별도 `camera_health_notifier` 스레드에서 상태 전이(ok→stale_*/stopped, 회복)를 **1회 통보 + 반복 억제(예: 10분)** 로 `alert_notify.submit(rule="camera_offline", level="high")` 에 태운다. 기존 W1 배선·M4 대기열을 그대로 쓰므로 새 채널 불필요.
- **공수**: **S~M**

### I-3 [P1] "4대 동시 RTSP" 의 대역폭·디코드 CPU·재연결 실측이 없다
- **근거**: 수용량 실측(`benchmarks/capacity_report.md:38-41`)은 **실카메라 1대 + 파일 모의 N−1대**. E1 의 디코드 0.4~1.2ms(`e1_bottleneck_report.md:165-172`)는 파일 소스 `cap.read()` 2fps 측정. 저해상 대조군(`:127-142`)도 "실카메라(1080p RTSP)는 그대로" 1대. 4대 실측 계획서 `docs/LAPTOP_SIZING_PILOT4.md:105-120` 은 대역폭·재연결·검출주기 전 항목 **"미측정"**. 저장소 전체에 `Mbps` 수치 인용은 노트북 WiFi 링크속도 1건뿐(`audit/d3_recheck_2026-08-26.md:10`). 현장 시험 2026-08-27 문서(`benchmarks/field_academy_2026-08-27.md`, `reports/현장테스트_보고서_20260827.md`)에 **재연결·단절 시험 기록 없음**(grep `재연결|단절|reconnect` 0건; 재연결 실측은 8-16/8-22 실험실 1대 기록뿐).
- **추가 우려(추측/미검증)**: thread 모드 캡처 스레드는 스트림의 **모든 프레임을 `grab()`** 한다(`worker.py:679-687`). 주석(`:672-677`)은 "grab() 은 디코드 없이 큐에서 꺼낸다" 고 전제하지만, OpenCV FFmpeg 백엔드의 `grabFrame` 은 패킷 디코드까지 수행하고 `retrieve` 는 색공간 변환만 한다고 알고 있다 — 이 저장소에서 **측정한 바 없다**. 맞다면 카메라당 디코드 CPU 는 15~30fps × 1080p 소프트웨어 디코드가 상시 붙고, E1 의 "디코드 1ms 미만" 은 실 RTSP 4대에 그대로 적용되지 않는다.
- **영향**: 권장 5대·한계 7대 라는 판매 수치가 4대 실 RTSP 에서 성립하는지 근거가 없다. WiFi 현장에서 4대 동시 TCP 재전송이 겹칠 때의 거동도 미지.
- **권장**: PILOT4 §6 계획을 실행하고(카메라 4대 `--rtsp-list`, `net_rx_mbps`, 캡처 스레드 CPU 를 `psutil.Process.threads()` 로 스레드별 분리), 1대 전원 차단 재연결을 **4대 운전 중** 에 재현. 주석 `:672-677` 의 전제도 같은 실험에서 `grab` 단독 vs `read` CPU 로 검증.
- **공수**: **M** (측정) / 코드 변경 없음

### I-4 [P2] 캡처 스레드의 "재연결" 경로가 실 장애에서는 거의 발화하지 않고 hang 워치독이 대신 잡는다
- **근거**: `worker.py:56` `read_fail_max=5` × `:74` READ 타임아웃 5s = 조용한 정지(카메라 프리즈, TCP 유지)에서 **최대 25s** 뒤에야 재연결. `:44` hang 15s 가 먼저 발화 → `_loop` 전체 재시작(트래커·디바운서 상태 소실, `_StreamCapture` 재생성). 주석 `:73` "hang 15s 보다 먼저 잡힘" 은 **1회 실패 기준**일 때만 참. 실측 정합: `docs/academy_visit_day.md:669` "HANG 6회 재기동으로 복구 · reconnects 0", `audit/soak_realcam_2026-08-17_report.md` 부록 A "재연결 #1 → 16s 뒤 HANG".
- **영향**: 복구는 되지만 경로가 무겁고(워커 전체 재시작), `reconnects/generation` 지표가 실 장애를 반영하지 않으며, hang 재시작마다 `hangs` 가 늘어 "불안정" 으로 오독된다.
- **권장**: READ 타임아웃 뒤 첫 실패에서 즉시 재연결(`read_fail_max` 를 타임아웃 경로에선 1로) 또는 `read_fail_max × timeout < hang_timeout` 을 **기동 시 assert/경고**. 실 프리즈에서 `grab()` 이 5s 블로킹인지 즉시 False 인지 **측정 필요**(Q3).
- **공수**: **S**

### I-5 [P2] 실행 중 카메라의 `source`/`fps` 변경이 조용히 무시된다
- **근거**: `routers/cameras.py:95` `_start(cid)` → `worker.py:1339-1340` "이미 실행 중" 이면 `{"ok": False}` 를 **내부 필드로만** 돌려주고 라우트는 `{"ok": True, ...}` 를 반환(`cameras.py:96`). 등록부(`cameras.json`)만 바뀌고 워커는 옛 주소로 계속 돈다. 구역만 재시작 경로가 있다(`cameras.py:246-250`).
- **영향**: 카메라 IP 를 바꾸거나 stream2 로 내리는 현장 조치가 "저장됐다" 고 보이지만 적용되지 않는다(재시작·disable/enable 전까지). 고정 IP 실패 사고(`deploy/SITE_CHECKLIST.md:19`)의 복구 절차에서 실제 혼란을 만든다.
- **권장**: `cameras_add` 에서 `source`/`fps` 가 바뀌고 워커가 running 이면 `manager.stop` → `_start` 재시작(구역 경로와 동일) 후 `restarted: true` 반환; UI 는 `worker.ok` 를 검사.
- **공수**: **S**

### I-6 [P2] H.265(HEVC) 가 현재 배포 cv2 4.13(FFmpeg 4.4) 빌드에서 재검증되지 않았다
- **근거**: HEVC 통과 기록(`audit/site_precheck_2026-08-19.md:30-35`)은 cv2 5.0/FFmpeg 7.1 시절. 2026-09-06 에 cv2 를 4.13.0.92 로 고정(`md/DEPLOYMENT.md:174`, `constraints.txt`). 이번 import 확인: `cv2 4.13.0 · avcodec 58.134.100 · avformat 58.76.100`(FFmpeg 4.4 계열). 학원 문서(`docs/academy_cctv_survey.md:12`)는 "H.265 도 문제없음" 이라 단언.
- **영향**: NVR 이 H.265 인 현장에서 기동 실패 또는 무프레임. 대체안(서브스트림 H.264)은 해상도 저하로 검출 요건(사람 크기) 미달 가능.
- **권장**: 4.13 환경에서 HEVC 파일 + go2rtc 재송출 RTSP 로 재검증하고 문서 갱신. 실패 시 go2rtc `#video=h264` 트랜스코딩 경로(CPU 비용 측정) 또는 opencv 휠 교체 결정.
- **공수**: **S** (측정)

### I-7 [P2] 카메라 자체 이상(가림·초점·과노출·이동) 감지가 전무하다
- **근거**: §2 표. 런타임 코드에 tamper/blur/exposure 판정 없음. 오프라인 `benchmarks/blur_check.py` 만 존재.
- **영향**: 렌즈에 비닐이 덮이거나 스프레이가 묻어도, 조명이 꺼져 전부 검게 나와도 `/health` 는 **ok**(프레임은 오고 추론도 돈다). 사람이 0명으로 검출되므로 침입·PPE 경보가 "정상적으로" 사라진다 — 감시 공백이 정상으로 위장되는 최악 형태.
- **권장**: 캡처 스레드 슬롯에서 1분에 1회 정도 ① 평균 휘도·히스토그램(암전·과노출) ② 라플라시안 분산(초점/가림) ③ 기준 프레임 대비 구조 유사도(이동/가림) 를 계산해 `state.camera_quality` 로 노출하고 임계 초과 시 `camera_tamper` 규칙으로 I-2 경로에 통보. 학습 없이 수십 줄이면 된다. 임계는 현장별 캘리브레이션 필요.
- **공수**: **M**

### I-8 [P2] 프레임 타임스탬프가 캡처 시각이 아니라 처리 시각이며, 카메라 자체 지연이 이벤트 시각에 반영되지 않는다
- **근거**: thread 모드 슬롯 시각 `_ts = time.time()`(`worker.py:719`, 캡처 완료 시각, RTSP PTS 아님). `_loop` 는 `t0 = time.time()`(`:1222`, 슬롯에서 꺼낸 시각)을 `_process_frame` 에 넘기고, `_last_det_ts = t0`(`:1044`), `last_detect_ts = now`(`:1049`, 추론 완료), 이벤트 `ts = datetime.now(KST)`(`data_engine.py:164-167`, 기록 시각). 카메라 내부 지연 실측 **~1.4s**(`docs/camera_requirements.md` 카메라 자체 지연 조항) 은 어디에도 더해지지 않는다. `slot_age_s` 는 별도 지표로만 노출(`:1236`).
- **영향**: 증거 이미지·이벤트 시각이 실제 상황보다 **1.4s + 슬롯 나이 + 추론 시간** 만큼 늦게 찍힌다. NVR 녹화와 대조하는 사고 조사에서 초 단위 불일치가 생기고, 다카메라 간 시각 정렬도 불가.
- **권장**: 이벤트 레코드에 `frame_ts`(슬롯 시각) 와 `detect_ts` 를 분리 기록하고, 등록부에 카메라별 `latency_offset_s`(시계 촬영법으로 측정한 값)를 두어 `frame_ts - offset` 을 `scene_ts` 로 함께 남긴다. 판정 로직은 불변.
- **공수**: **S**

### I-9 [P2] 기아 감시 3단계(프로세스 재기동) 는 설계상 도달 불가능해 보인다 — 확인 필요
- **근거**: `starvation_guard.py:124-131` 2단계 `_restart_worker` → 새 `Worker`(`worker.py:1341`, `started_at` 갱신) → 다음 tick 에서 `uptime ≤ 90s` 라 `STARTING`(`health_status.py:60-62`) → `_tick` 이 `_state.pop`(`starvation_guard.py:116-117`) → `restarts` 카운터 소실. 즉 `restarts ≥ 3` 은 `_restart_worker` 자체가 예외로 실패할 때만 성립. 실환경 발동 실적 없음(`audit/reconnect_test_2026-08-16.md` "2차 방어 미실시").
- **영향**: 문서(`docs/STABILITY.md:§4`)가 약속한 "3회 실패 → 프로세스 재기동" 이 실제로는 안 일어난다. (역으로, 죽은 카메라 1대가 프로세스 전체를 재기동시키지 않는 안전 효과도 있다 — I-1 오분류와 결합하면 오히려 다행이다.)
- **권장**: 회복 판정을 "STARTING 도 아니고 OK 로 N초 유지" 로 바꾸거나, `restarts` 를 `STARTING` 중엔 보존. I-1 을 먼저 고쳐야 한다(안 고치면 죽은 카메라가 3단계를 밟아 **정상 카메라 3대까지 재기동**된다).
- **공수**: **S** + 단위 테스트 갱신

### I-10 [P2] sync 캡처 모드에서 감시 스레드가 다른 스레드의 `VideoCapture.release()` 를 호출한다(스레드 안전성 미보장)
- **근거**: `worker.py:899-900` `_hang_watch` 가 `self._cap.release()`; 같은 시각 `_loop` 는 `cap.read()`(`:1239`) 안에 있을 수 있다. cv2 `VideoCapture` 는 스레드 안전을 보장하지 않는다(추측/미검증 — 이 저장소에 크래시 기록은 없다). thread 모드에선 `_cap=None`(`:1188`, `:1202` 미설정)이라 무해.
- **영향**: sync 모드로 롤백(`docs/STABILITY.md:216` 권장 절차)했을 때 프로세스 전체(4대) 세그폴트 가능성.
- **권장**: READ 타임아웃(5s)이 생긴 지금은 강제 release 없이 `_restart_req` 만 세워도 5s 내 `read()` 가 돌아온다. release 호출 제거 또는 `_loop` 스레드에서만 release.
- **공수**: **S**

### I-11 [P3] `go2rtc.log` 는 기동 시에만 회전되고 세션 중엔 무제한 증가한다
- **근거**: `routers/cameras.py:375-383` `rotate_if_large(…, 50MB)` 는 `ensure_go2rtc` 안에서만 호출; 파일 핸들이 Popen 수명 동안 열려 있다(주석도 "세션 중 회전 불가" 인정). 현재 `data/go2rtc.log` 4.9MB · 35,537줄 중 **EOF 경고 35,304줄(99.3%)**. `audit/b3_root_cause_2026-08-16.md` "EOF 경고 초당 ~10회" → 카메라 장기 단절 시 하루 수십 MB(추정).
- **영향**: 수주 단절이면 디스크 경고선(`retention.py` 5GB) 에 영향. go2rtc 는 확대뷰 전용이라 검출엔 무관.
- **권장**: go2rtc 를 `-config` 에 `log: {level: error}` 로 낮추거나, 스트림이 죽었을 때 `_g2_unregister` 로 등록을 내려 재시도 스팸을 끊는다(기아 감시 1단계와 동일 API).
- **공수**: **S**

### I-12 [P3] 실카메라 24h 소크 기록에 스레드·핸들 수가 없다(누수 판정 근거 부족)
- **근거**: `scripts/soak_realcam.py:135-146` 기록 필드 = 상태·카메라 age·RSS·GPU. 파일 소스 소크(`audit/soakmon_2026-08-11_s3edge24h.csv`)에는 `proc_threads` 108→111 이 있으나 실카메라 24h(`audit/soak_realcam_2026-08-17_0237.jsonl`)에는 없다. 재연결·hang 재기동이 **스레드를 만들고 지우는 경로**(§4 표)인데 그 누수 여부를 24h 로 증명하지 못한다.
- **권장**: `psutil.Process(pid).num_threads()`·`num_handles()`(Windows) 를 소크 레코드에 추가.
- **공수**: **S**

### I-13 [P3] 드레인으로 버린 프레임 수·캡처 스레드 CPU 가 노출되지 않는다
- **근거**: `worker.py:681-687` `_drained` 는 지역변수로 소멸. `/health` 의 `dropped_frames` 는 읽기 실패(`:695`). "프레임 유실 ≤1%" 기준(`docs/LAPTOP_SIZING_PILOT4.md:117`)을 잴 지표가 없다.
- **권장**: `self.drained += _drained`, `self.frames_in += 1` 누적 → `/health` 노출.
- **공수**: **S**

### I-14 [P3] 문서-코드 불일치(안정성 문서)
- `docs/STABILITY.md:§4 표` 재연결 상한 **30.0s** ↔ 코드 **5.0s**(`worker.py:55`, `tuning.yaml:216`); 같은 문서 `:75,100` "기본 sync" ↔ 서비스 thread; `§7` "real 24h 진행 중" ↔ 실카메라 24h 는 2026-08-17 완료. `md/DEPLOYMENT.md:596` "stale_detect 면 검출만 죽은 것" ↔ I-1.
- **공수**: **S**

### I-15 [P3] 자격증명 저장이 평문 JSON 이며 go2rtc 런타임 설정·API 에도 복제된다
- **근거**: `camera_registry.py:46-48` `_save` 평문, `:115` secrets 기록; `routers/cameras.py:35` go2rtc API 로 원본 URL 전달, `:368` 런타임 yaml 에 기록. 완화: `data/` gitignore, 마스킹 일관(`:25-36`, 테스트 `tests/test_worker_credential_masking.py`), 저장 폴더 암호화 검사(`privacy.py:278-304`, 노트북 BitLocker on 확인 `docs/academy_visit_day.md` 0-E). go2rtc API 는 127.0.0.1 무인증(`config/go2rtc.yaml:19-20`).
- **영향**: 같은 PC 의 임의 로컬 프로세스가 `GET 127.0.0.1:1984/api/streams` 로 자격증명을 읽을 수 있다(추정 — go2rtc 응답 형식 미확인). Phase 3 범위 밖(보안 Phase)이라 P3 로만 둔다.
- **공수**: **M** (DPAPI 암호화 + go2rtc 스트림명 토큰화)

---

## 4. 누수 위험 지점 표 (24h × 수일 연속)

| 지점 | 생성 경로 | 해제 경로 | 판정 | 근거 |
|---|---|---|---|---|
| `cv2.VideoCapture` (캡처 스레드) | `_StreamCapture._open` (`worker.py:656-664`), 재연결마다 재생성(`:708`) | 재연결 전 `release`(`:701`), 스레드 종료 시(`:721`) | ✅ 누락 없음 | 코드 정독 |
| `cv2.VideoCapture` (sync) | `_setup_run`(`:1196`), 재연결(`:1271`) | `finally: cap.release()`(`:1304-1305`), 재연결 전(`:1264`) | ✅ | — |
| `cv2.VideoCapture` (`/cameras/{id}/test`) | 요청마다 데몬 스레드(`cameras.py:203-210`) | `finally: cap.release()`(`:209`) · 타임아웃 후에도 스레드는 5s 내 자연 종료 | ✅ 유한 | — |
| **캡처 스레드** | `_loop` 마다 1개(`:1191-1192`) — hang 재기동·감독자 재시작마다 새로 생성 | `finally: streamcap.stop()` join **3s**(`:1306-1307`, `:734-737`). 스레드가 `_open_capture`(OPEN 5s) 안이면 join 이 먼저 끝나지만 5s 내 `_stop` 을 보고 종료 | ✅ 유한(짧은 중복 가능) | 죽은 카메라에서 15~17s 마다 반복 생성되나 누적은 안 됨 |
| hang 감시·포즈 스레드 | Worker 당 1개씩(`:825-827`, `:1213-1215`) | `_stop` 이벤트로 종료. `WorkerManager.start` 는 **새 Worker 를 만들어 dict 를 교체**(`:1341-1342`) — 옛 Worker 는 `stop()` 후 GC | ✅ | 구역 저장 재시작(`cameras.py:248-249`)·기아 2단계도 같은 경로 |
| `_pose_input` / `_last_frame` | 프레임 1장 참조 | 다음 프레임이 덮어씀 | ✅ 상수 | — |
| 위험구역 주체 키·쿨다운 키 | 트랙별 | 퇴장 확정 후 정리(`:300-312`, M2-1), 만료 정리(`:1093-1097`, M3-4) | ✅ 2026-09-06 수정됨 | 수정 전엔 무한 누적이었다(코드 주석) |
| `MotionTracker.hist` / `ErgonomicsTracker._tracks` | 프레임마다 | `hist_s` 60s·`expire_s` 3s 만료(`:594-595`, `:496`) | ✅ | — |
| 통보 대기열 | `alert_notify.submit` | 가득 차면 최고령 폐기(`dropped`, `health_status.py:121-122`) | ✅ 유계 | — |
| `go2rtc.log` | 세션 내내 append | 기동 시 50MB 회전만(`cameras.py:379`) | ⚠ **세션 중 무제한**(I-11) | 현재 4.9MB, 99% EOF 스팸 |
| `VIGENT_COLLECT=1` 수집 JPEG | 30s 마다 디스크(`:985-993`) | 없음 | ⚠ 기본 off — 켜면 무제한 | 운영 미사용 확인 필요 |
| `state.hangs/restarts` 카운터 | — | — | ✅ int, 무해 | — |

### 소크 실측 근거(RSS 추이)

| 날짜 | 소스 종류 | 길이 | RSS | 판정 | 파일 |
|---|---|---|---|---|---|
| 2026-08-10~11 | **파일 루프 1대**(`multi_scene.mp4`) | 24h | 3,430 → 476MB(초기 급락 후 **412~505MB 안정**), median 기울기 **+0.46MB/h**, 스레드 108→111 | ✅ 누수 없음 | `audit/soakmon_2026-08-11_s3edge24h.md`, `.csv` 1,440샘플 |
| 2026-08-17~18 | **실카메라 RTSP 1대**(Tapo C200, thread 모드, NSSM 서비스) | 24h | 0~9.7h **+1.23MB/h**, 이후 외부 GPU 부하로 계단 낙차 2회(−782/−1,856MB), 11.2~24h **−4.17MB/h**; hang 2·재연결 1·unhealthy 0 | ✅ 합격(스크립트 FAIL 은 계단 때문, R4 로 정정) | `audit/soak_realcam_2026-08-17_report.md`, `.jsonl` 1,437샘플 |
| 2026-08-26 | **파일 카메라 2대**(현장 노트북) | 3h | 2,542 → 2,386MB(**−52.3MB/h**) | ✅ | `audit/soak_after_fixes_2026-08-26.md` |
| — | **실 RTSP 2대 이상** | — | **기록 없음** | ❓ | `capacity_report.md:100` "장시간 다중 카메라 안정성 미검증" |

→ 결론: **1대 조건에서는 24h 누수 징후 없음**이 실측으로 뒷받침된다. 4대·재연결 반복 조건은 근거가 없다(I-3·I-12).

---

## 5. 4대 동시 RTSP 부하·재연결 근거 (요청 항목 5)

| 질문 | 답 | 근거 |
|---|---|---|
| 4대 대역폭 | **없음**. 1080p H.264 15fps 카메라 4대면 통상 8~20Mbps 급이나 이는 일반 지식(추측)이지 이 저장소의 측정이 아니다 | `docs/LAPTOP_SIZING_PILOT4.md:105-108` "미측정" |
| 4대 디코드 CPU | 파일 모의 N−1 + 실 1대 기준 카메라당 1.55 환산코어(추론 지배). 실 RTSP 4대의 캡처 스레드 디코드분은 분리 측정 없음 | `e1_bottleneck_report.md:56-63`, `capacity_report.md:38-41` |
| 네트워크 단절·재접속 시험 | 실험실 1대: 전원차단 3회+슬롯경쟁 1회 **6.0/8.1/49.6/8.2s 복구**(2026-08-16), 20s 차단 **~30s 복구**(2026-08-22) | `audit/reconnect_test_2026-08-16.md`, `docs/academy_visit_day.md:669` |
| 2026-08-27 현장 시험에 재연결 실측이 있는가 | **없다** | `benchmarks/field_academy_2026-08-27.md`, `reports/현장테스트_보고서_20260827.md` grep 0건 |
| 다중 카메라 동시 차단 | 미실시 | `audit/reconnect_test_2026-08-16.md` 잔여 표 |
| IP 변동 시 | 자동복구 성립 안 함(고정 IP 필수) — 정직하게 문서화됨 | `deploy/SITE_CHECKLIST.md:9-22` |

---

## 6. 카메라 추가·삭제·변경(요청 항목 4)

| 동작 | API | UI | 영구 저장 | 런타임 반영 | 평가 |
|---|---|---|---|---|---|
| 추가/수정 | `POST /cameras`(`cameras.py:82-96`) | 허브 addModal(`index_hub.html:630-634`), 설정 콘솔(`setup_console.py:115`) | `data/cameras.json`(마스킹) + `data/camera_secrets.json`(원본) (`camera_registry.py:17-18, 114-117`) | enabled 면 즉시 워커 시작 + go2rtc 등록. **실행 중이면 source/fps 미반영(I-5)** | 🔸 |
| 활성/비활성 | `POST /cameras/{id}/enable|disable`(`:99-112`) | — | `enabled` | 즉시 | ✅ |
| 삭제 | `DELETE /cameras/{id}`(`:115-131`) | — | 등록부 먼저 삭제(경합 봉쇄, 2026-08-26 사고 반영) | 즉시 + 2중 회수 | ✅ 테스트 `tests/test_worker_lifecycle_guards.py` |
| 구역 변경 | `POST /cameras/{id}/zone`(`:235-251`) | 허브 편집 | `zone` | **워커 재시작**으로 반영 | ✅ |
| 카메라별 override | `overrides.motion.immobile_s` 1키(`camera_registry.py:66-86`) | — | ✓ | 워커 시작 시 | 🔸 확장은 다음 단계(주석) |
| 연결 테스트 | `POST /cameras/{id}/test`(`:188-222`) | 추가 직후 자동 호출 | — | 타임아웃 11s 내 응답(테스트 `test_capture_timeouts.py:98-112`) | ✅ |
| 기동 시 복원 | `autostart_enabled`(`:426-437`), 예열 후 실행(`main.py` `_start_workers_after_warmup`) | — | — | — | ✅ B4 콜드로드 사고 반영 |
| site.yaml(엣지) | `manager.autostart`(`worker.py:1387-1400`) `VIGENT_EDGE=1` | — | `config/site.yaml` | — | 🔸 등록부와 **두 경로 병존**(site.yaml 카메라는 등록부에 없어 기아 감시가 "유령"으로 회수할 수 있다 — `starvation_guard.py:77-81` 확인 질문 Q5) |

→ **코드 수정 없이 추가·삭제·설정 변경 가능**(I-5 예외). 자격증명 분리·마스킹은 잘 돼 있다.

---

## 7. 경쟁 상용 제품 대비 격차

| 기능 | 상용 VMS/AI-NVR(일반적 기대치) | VIGENT 현재 | 격차 | 심각도 |
|---|---|---|---|---|
| ONVIF 자동 검색·프로파일 협상 | 표준(WS-Discovery → Profile S 로 RTSP URL 자동 획득) | 없음. 사람이 `rtsp://` 를 타이핑 | 설치 인력 숙련도 의존, 주소 오타·스트림 경로 오류가 흔함(`docs/academy_visit_day.md:155` 자체 인정) | P2 |
| H.265 + HW 디코드 | NVDEC/QSV 로 16~32ch | SW 디코드, H.265 미재검증 | 4대 이하 pilot 엔 치명적이지 않으나 8ch 이상 확장 시 CPU 벽(E1 의 CPU 병목과 합산) | P2 |
| 카메라 tamper(가림·이동·초점·암전) | 대부분 카메라 펌웨어 또는 VMS 기본 이벤트 | 없음 | **감시 공백이 정상으로 위장** | P2(현장 조건에 따라 P1) |
| 카메라 오프라인 통보 | 이메일/푸시 기본 | `/health` 폴링뿐 | 무인 운영 불가 수준 | P1 |
| NVR 연동(재생·북마크) | 이벤트 시각으로 NVR 구간 점프 | 없음. 이벤트 시각도 처리 시각(I-8) | 사고 조사 시 수작업 | P3 |
| 다중 스트림(메인/서브) 자동 선택 | 분석은 서브, 표시는 메인 | 단일 URL. 분석·확대뷰 모두 카메라 직결(세션 2개 소모 → B3 슬롯 경쟁의 근본 원인) | go2rtc 를 **단일 수신자**로 두고 워커가 go2rtc 에서 받으면 카메라 세션 1개로 줄어든다 — 설계 대안으로 검토 가치 있음 | P2 |
| 대역폭·fps 통계 | 채널별 kbps/fps/드롭 | `read_ms`·`slot_age_s`·`dropped`(읽기실패) 만 | 드레인 수·수신 fps 없음(I-13) | P3 |

---

## 8. 잘 된 점(유지할 것)

- **타임아웃을 실측으로 잡았다**: FFmpeg `timeout` 옵션이 cv2 4.13 에서 즉시 실패한다는 발견(`rtsp_capture_probe.py:21-24`)과 OpenCV 속성 채택은 정확한 판단이다.
- **stale_detect 3단계 판정**(`health_status.py`)은 "영상은 살고 검출만 죽는" 최악 모드를 실제로 잡아냈다(2026-08-16 실증). 이 설계 자체는 경쟁 제품에도 드문 강점이다 — I-1 만 고치면 된다.
- **캡처 스레드 최신 프레임 슬롯 + grab 드레인**은 지연 누적을 구조적으로 막는 올바른 패턴이다.
- **자격증명 마스킹**이 state·로그·예외 메시지까지 일관되고 테스트로 잠겨 있다.
- 삭제 경합·유령 워커 사고를 **코드+테스트+문서** 로 닫았다(`cameras.py:118-125`, `starvation_guard.py:67-81`).
- 소크·재연결 기록이 **합격 기준 사전 선언·원자료 보존·오판 정정 이력** 까지 남긴다(규칙 7 준수의 모범).

---

## 9. 확인 질문 (판단 유보)

- **Q1.** 파일럿 현장의 운영 형태는? 야간 무인·단일 카메라 구역이 있으면 I-2 는 P0 로 올려야 한다.
- **Q2.** 4대 실 RTSP 동시 운전을 한 번이라도 해봤는가(기록이 저장소에 없을 뿐인지)? PILOT4 §6 의 미측정 항목을 이번 검토 후 첫 과제로 잡을 수 있는가.
- **Q3.** 실카메라를 **전원은 켜둔 채 네트워크만** 끊었을 때(TCP 유지·프레임 정지) `grab()` 이 5s 블로킹인지 즉시 False 인지 측정한 적이 있는가(I-4 판정 근거).
- **Q4.** thread 모드에서 캡처 스레드 단독 CPU(디코드분)를 측정한 적이 있는가. 없다면 `worker.py:672-677` 주석의 "grab 은 디코드 없음" 전제를 어디서 가져왔는가.
- **Q5.** `VIGENT_EDGE=1` + `config/site.yaml` 경로를 실제 배포에서 쓰는가? 쓴다면 site.yaml 카메라는 등록부에 없어 `starvation_guard._restart_worker`(`:77-81`) 가 "유령" 으로 제거한다 — 의도인가.
- **Q6.** 배포 대상 현장의 카메라 코덱·NVR 여부(학원 질문지 4번 답)는 확정됐는가. H.265 면 I-6 재검증이 선행 조건이다.
- **Q7.** 대시보드 확대뷰(go2rtc)와 워커가 카메라 세션을 각각 1개씩 쓰는 현 구조를 유지할 것인가, 아니면 go2rtc 단일 수신 → 워커가 go2rtc 에서 받는 구조(세션 1개)로 갈 것인가. B3 슬롯 경쟁의 근본 해법이지만 go2rtc 를 검출 경로의 단일 장애점으로 만든다.
- **Q8.** `/cameras/{id}/test` 가 실행 중 카메라에 대해 호출되면 카메라 세션을 1개 더 소모한다(한도 2). 운영자가 확대뷰를 연 채 "연결 테스트" 를 누르면 워커가 밀려날 수 있다 — 실측한 적 있는가.

---

## 10. 권장 우선순위(공수 순)

1. **I-1**(M) 하트비트 분리 → stale_frame/stale_detect 정확화 — 다른 모든 자동복구 판단의 전제.
2. **I-2**(S~M) 카메라 상태 전이 통보 — 기존 통보 대기열 재사용.
3. **I-3**(M, 측정) 4대 실 RTSP 소크 + 재연결 + 캡처 CPU 분리.
4. **I-5·I-4·I-10**(각 S) 코드 소폭 수정.
5. **I-6**(S, 측정) HEVC 재검증 → 문서 정정.
6. **I-7**(M) tamper/노출/초점 최소 감지 — 경쟁 격차 중 가장 싸게 메울 수 있는 항목.

---

**산출물**: `D:\vigent_original\docs\review\03-video-input.md` · **P0 0건 · P1 3건**(I-1 오분류 · I-2 무통보 · I-3 4대 미실측) · P2 8건 · P3 4건
