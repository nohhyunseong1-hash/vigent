# VIGENT 눈으로 하는 코드 리뷰 — A~Z 체크리스트

> **용도**: 개발자가 직접 코드를 읽으며 훑는 순서표. 위에서 아래로 **데이터가 흐르는 순서**
> (카메라 → 검출 → 판정 → 통보 → 저장 → 운영)로 배열했다. 각 항목은 독립적으로 볼 수 있다.
>
> **표기**
> - 🔴🟠🟡 = 2026-08-21 안전 리뷰([SAFETY_REVIEW_REPORT.md](../SAFETY_REVIEW_REPORT.md))에서
>   **이미 발견된 결함**이 그 항목에 있다는 뜻. 리뷰 때 그 부분을 특히 볼 것.
> - ✅ = 그 결함은 수정 완료. **수정이 제대로 됐는지** 보는 것이 리뷰 포인트.
> - ⏱ = 대략적인 소요 시간(코드를 읽는 시간 기준, **추정치다**).
>
> **총 26항목 · 코어 약 9,900줄 + 라우터 2,100줄 + 에이전트 2,800줄.**
> 한 번에 다 보지 말고 **묶음 단위**로 끊는 것을 권한다(부록 2 참조).

---

## 1부. 기동과 입력 (A~G) — "영상이 들어오기까지"

### A. 진입점·기동 순서
**파일**: [vigent-core/main.py](../vigent-core/main.py) (464줄) · [app_state.py](../vigent-core/app_state.py)

- [ ] `main.py` 가 **인프라만** 담당하는가 — 앱 생성·라우터 등록·미들웨어·startup·`/` 루트
- [ ] startup 에서 **무엇이 어떤 순서로** 뜨는가: 테마 로드 → 모델 예열 → 워커 자동시작 →
      디스패처 배선 → `alert_notify.start()` → `retention_scheduler.start()`
- [ ] ★**순서 의존성**이 있는가 — 예: 디스패처 배선 전에 경보가 발생하면 어디로 가는가
- [ ] 라우터가 `main` 을 import 하지 않는가(순환 금지 — CLAUDE.md 라우터 규칙)
- [ ] startup 중 예외가 나면 앱이 죽는가, **조용히 반쪽으로 뜨는가**

**핵심 질문**: *기동 도중 실패했을 때, 실패한 채로 "정상"처럼 보이는 경로가 있는가?*  ⏱ 30분

---

### B. 설정 로딩과 프로파일
**파일**: [config/tuning.yaml](../config/tuning.yaml) · [vigent-core/tuning.py](../vigent-core/tuning.py) ·
[themes/safety/vision.yaml](../themes/safety/vision.yaml) ·
[deploy/academy/tuning.academy.yaml](../deploy/academy/tuning.academy.yaml)

- [ ] `tuning.val(section, key, default)` 의 **폴백 규칙** — 키가 없으면? 파일이 없으면?
- [ ] 설정을 **언제 읽는가** — 기동 시 1회인가, 매번인가. 바꾸면 재시작이 필요한 것은 무엇인가
- [ ] 🔴 **학원 프로파일이 파일 전체를 덮는 구조**(2026-08-24 발견).
      기본값에 키가 추가되면 학원 프로파일은 조용히 뒤처진다. 실제로 6개 키가 누락돼
      F5·F6 수정이 무효화될 뻔했다. **드리프트 검사 테스트가 붙었는지 확인할 것.**
- [ ] 환경변수 오버라이드(`env=`)가 있는 키는 무엇이고, `.env` 와 충돌하면 누가 이기는가

**핵심 질문**: *설정 하나를 바꿨을 때, 그게 실제로 반영됐는지 어떻게 확인하는가?*  ⏱ 40분

---

### C. 카메라 등록과 소스 해석
**파일**: [camera_registry.py](../vigent-core/camera_registry.py) (123줄) ·
[routers/cameras.py](../vigent-core/routers/cameras.py) (297줄) · [routers/tapo.py](../vigent-core/routers/tapo.py)

- [ ] 카메라 소스 종류(RTSP·파일·웹캠 인덱스)를 **어떻게 구분**하는가
- [ ] ★RTSP **자격증명이 URL 에 들어가는가** — 로그·`/health`·에러 메시지로 새어 나오는가
- [ ] 카메라 추가·삭제가 **실행 중인 워커**에 어떻게 반영되는가(재시작? 즉시?)
- [ ] 같은 카메라를 두 번 등록하면 어떻게 되는가

**핵심 질문**: *비밀번호가 들어간 RTSP URL 이 어디까지 흘러가는가?*  ⏱ 30분

---

### D. 캡처 스레드 — 프레임을 가져오는 곳
**파일**: [worker.py:437-551](../vigent-core/worker.py#L437) `_StreamCapture`

- [ ] `_run()` 의 **grab-드레인 → retrieve** 패턴 — 왜 이렇게 하는가(누적 지연 방지)
- [ ] `read_latest()`([:537](../vigent-core/worker.py#L537))가 **최신 1프레임 슬롯**만 주는가.
      큐가 쌓이는 경로는 없는가
- [ ] 재연결: 읽기 실패 5회 → 지수 백오프(상한 5초) → `generation++`.
      **`generation` 이 하는 일**을 따라가 볼 것
- [ ] 🔴 **F3 미수정** — 프리즈(정지화면 계속 송출) 감지가 **없다**. `read()` 가 계속
      성공하므로 슬롯 ts 가 갱신되고 hang·stale 를 전부 통과한다.
      **NVR 채널 프리즈 시 영구 healthy 인데 실제로는 실명 상태.**
- [ ] 🟡 재연결 중 **옛 프레임을 최대 15초 재처리**할 수 있다(hang 임계까지) — 슬롯 나이 상한이 없다

**핵심 질문**: *카메라가 "거짓말"할 때(같은 화면 반복) 알아챌 방법이 있는가?* → 없다(F3)  ⏱ 1시간

---

### E. 워커 수명주기
**파일**: [worker.py:573](../vigent-core/worker.py#L573) `Worker` ·
[worker.py:1112](../vigent-core/worker.py#L1112) `WorkerManager`

- [ ] `start`([:609](../vigent-core/worker.py#L609)) → `_run_supervised`([:713](../vigent-core/worker.py#L713))
      → `_setup_run`([:929](../vigent-core/worker.py#L929)) → `_loop`([:991](../vigent-core/worker.py#L991))
      흐름을 한 번 따라갈 것
- [ ] `_run_supervised` 가 **무엇을 감독**하는가 — 루프가 죽으면 되살리는가
- [ ] `stop()` 이 **실제로 스레드를 정리**하는가. 좀비 스레드가 남는 경로는?
- [ ] `WorkerManager.autostart`([:1172](../vigent-core/worker.py#L1172))가 기동 시 무엇을 어떤 순서로 띄우는가
- [ ] ✅ **F5 확인** — `_setup_run` 의 `zone_source` 분기가 보이는가.
      구역 미설정이면 `zone=[]` + 경고 로그 + `zone_source="none"` 이어야 한다.
      **전역 폴백은 `zone.global_fallback: true` 일 때만.**

**핵심 질문**: *워커가 죽었을 때 되살아나는가, 조용히 사라지는가?*  ⏱ 1.5시간

---

### F. 행 워치독·기아 방지
**파일**: [worker.py:682](../vigent-core/worker.py#L682) `_hang_watch` ·
[starvation_guard.py](../vigent-core/starvation_guard.py) (152줄)

- [ ] hang 임계 15초의 **근거**가 무엇인가. 검출 주기(0.5초) 대비 30배다
- [ ] 워치독이 hang 을 감지하면 **무엇을 하는가** — 로그만? 재시작? 상태 표시?
- [ ] `starvation_guard` 3단계가 각각 무엇을 하고, **어떤 조건**에서 올라가는가
- [ ] ★워치독 자신이 죽으면? 워치독을 감시하는 것은 무엇인가

**핵심 질문**: *멈춘 것을 감지하는 코드가 멈추면 누가 아는가?*  ⏱ 40분

---

### G. 예열(readiness) 게이트
**파일**: [readiness.py](../vigent-core/readiness.py) (154줄)

- [ ] `starting` → `ready` 전이 조건이 정확히 무엇인가
- [ ] 예열 실패(`FAILED`) 시 `/health` 가 **503** 을 주고 워커가 안 뜨는가 — 실제로 그런가
- [ ] ★필수 가중치 누락 판정(`required_weights_missing`)이 어디서 걸리는가.
      **이 판정 때문에 개발 PC 재시작이 막혔던 실제 사례가 있다**(rf-detr-nano.pth 누락)
- [ ] 예열 시간(실측 ~30초)이 NSSM 재시작 정책(5초)과 어긋나지 않는가

**핵심 질문**: *"아직 준비 안 됨"과 "고장남"을 구분해서 보여주는가?*  ⏱ 30분

---

## 2부. 검출 (H~L) — "무엇이 보이는가"

### H. 모델 로딩과 가중치 해석
**파일**: [agents/guard.py:413](../vigent-core/agents/guard.py#L413) `_resolve_rfdetr_weights` ·
[:476](../vigent-core/agents/guard.py#L476) `_require_rfdetr_pretrain` ·
[:721](../vigent-core/agents/guard.py#L721) `_get_model` ·
[detectors/rfdetr_adapter.py](../vigent-core/detectors/rfdetr_adapter.py) (243줄)

- [ ] 4개 슬롯(person·ppe·fire_smoke·forklift)의 **지연 로딩(lazy)** 구조 — 언제 올라오는가
- [ ] ★**폴백 경로**: 가중치가 없거나 손상되면 무엇으로 떨어지는가.
      **COCO 폴백으로 조용히 떨어진 사고가 실제로 있었다**(2026-07-07 F-8, 워크트리 weights 누락)
- [ ] `_sha16`([:35](../vigent-core/agents/guard.py#L35)) 해시 검증이 **실제로 로딩을 막는가**, 로그만 남기는가
- [ ] ONNX 백엔드와 torch 백엔드 중 **무엇이 언제 선택**되는가
- [ ] 🔍 **F30 미확인** — `test_rfdetr_onnx_parity` 가 전체 스위트에서 1회 ERROR.
      **원인 미확인.** torch+ONNX 동시 적재라 GPU 메모리 압박을 **의심하나 확인 안 됨**

**핵심 질문**: *모델이 "다른 것"으로 바뀌어 로딩됐을 때 알아챌 수 있는가?*  ⏱ 1.5시간

---

### I. 추론과 직렬화
**파일**: [agents/guard.py:756](../vigent-core/agents/guard.py#L756) `detect` · `DETECT_LOCK`([app_state.py](../vigent-core/app_state.py))

- [ ] 전역 `DETECT_LOCK` 이 **모든 추론을 직렬화**한다 — 카메라가 늘면 어떻게 되는가
- [ ] 락을 잡는 **범위**가 어디부터 어디까지인가(전처리 포함? 후처리 포함?)
- [ ] 슬롯 하나가 예외를 던지면 **나머지 슬롯**은 어떻게 되는가
- [ ] ✅ **F1 수정 확인** — 슬롯 연속 3회 실패 시 `slot_degraded` 를 세우는 코드([:770](../vigent-core/agents/guard.py#L770)).
      이제 `/health` 에 배선됐다. **person 슬롯 저하 = unhealthy(503)** 인지 확인
- [ ] imgsz 384 고정 — 원본 해상도와의 관계, **작은 물체 검출**에 미치는 영향

**핵심 질문**: *한 슬롯이 죽었을 때, 나머지가 살아 있어서 "정상"으로 보이지 않는가?* → F1 이 그 결함이었다  ⏱ 1.5시간

---

### J. 후처리 — 중복 억제  ★가장 촘촘히 볼 곳
**파일**: [guard.py:106](../vigent-core/agents/guard.py#L106) `_containment_suppress` ·
[:132](../vigent-core/agents/guard.py#L132) `_cross_validate_ppe` ·
[:156](../vigent-core/agents/guard.py#L156) `_nms` ·
[:170](../vigent-core/agents/guard.py#L170) `_suppress_vehicle_dupes` ·
[:186](../vigent-core/agents/guard.py#L186) `_merge_cross_source_person` ·
[:208](../vigent-core/agents/guard.py#L208) `_drop_ppe_origin_person`

- [ ] ★**적용 순서**를 확인할 것 — 억제 함수가 6개다. 순서가 바뀌면 결과가 달라진다
- [ ] NMS IoU 0.55 / 포함비 0.70 의 **근거**가 있는가, 경험값인가
- [ ] ★**억제가 과한 경우** — 사람 둘이 겹쳐 서 있으면 하나로 합쳐지는가?
      **이것이 미검출로 직결된다**(2인 작업 중 1인만 검출)
- [ ] `_merge_cross_source_person` — person 슬롯과 ppe 슬롯이 같은 사람을 각각 잡을 때의 병합 규칙
- [ ] `_drop_ppe_origin_person` — PPE 모델이 만든 person 을 왜 버리는가

**핵심 질문**: *겹친 사람을 하나로 지워버리는 경로가 있는가?*  ⏱ 2시간

---

### K. 추적(ByteTrack)
**파일**: [guard.py:523](../vigent-core/agents/guard.py#L523) `_track` ·
[:583](../vigent-core/agents/guard.py#L583) `_track_bytetrack` · [:631](../vigent-core/agents/guard.py#L631) `_track_iou` ·
[:536](../vigent-core/agents/guard.py#L536) `_maybe_sweep_stale_keys` · [:563](../vigent-core/agents/guard.py#L563) `reset_tracks`

- [ ] `track_key` 가 **카메라별로 분리**되는가 — 섞이면 ID 가 카메라를 넘나든다
- [ ] ByteTrack 실패 시 `_track_iou` 폴백 — 언제 떨어지는가
- [ ] ★**ID 스위치**가 나면 무엇이 깨지는가 — 디바운스? 히스테리시스? 쿨다운?
- [ ] `_maybe_sweep_stale_keys` — 오래된 트랙 정리 주기. **메모리 누수 경로**인가
- [ ] 카메라 재연결(`generation++`) 시 트랙이 리셋되는가

**핵심 질문**: *사람이 잠깐 가려졌다 나타나면 같은 사람으로 보는가, 새 사람으로 보는가?*  ⏱ 1.5시간

---

### L. 히스테리시스
**파일**: [guard.py:879](../vigent-core/agents/guard.py#L879) `_hysteresis` · [:259](../vigent-core/agents/guard.py#L259)

- [ ] ppe 3프레임 / fire 2프레임 — **왜 다른가**. 근거가 코드나 문서에 있는가
- [ ] ★**person·zone 에는 히스테리시스가 없다** — 왜인가(디바운스로 대체?). 의도된 설계인가
- [ ] 히스테리시스 상태가 **트랙 단위**인가 프레임 단위인가. ID 스위치 시 어떻게 되는가
- [ ] 켜지는 조건과 **꺼지는 조건**이 대칭인가(같은 프레임 수인가)

**핵심 질문**: *깜빡이는 검출을 안정화하려다 진짜 위험을 늦추지는 않는가?*  ⏱ 40분

---

## 3부. 판정 (M~P) — "위험인가"

### M. 구역 판정
**파일**: [worker.py:172](../vigent-core/worker.py#L172) `_derive` ·
[:74](../vigent-core/worker.py#L74) `_point_in_poly` · [:140](../vigent-core/worker.py#L140) `_load_zone` ·
[press_zone.py](../vigent-core/press_zone.py) · [config/zones.json](../config/zones.json)

- [ ] ★**발끝점(foot point)** 기준 판정 — 박스 하단 중앙인가. 사람이 기울면?
- [ ] `_point_in_poly` 구현 — **경계선 위의 점**은 안인가 밖인가
- [ ] 좌표계: **정규화(0~1)인가 픽셀인가.** 해상도가 바뀌면 구역이 따라가는가
- [ ] ✅ **F5 수정 확인** — 카메라별 구역이 없을 때 **전역 구역으로 폴백하지 않는가**.
      `zone_source` 가 `camera`/`global`/`none` 중 무엇으로 나오는지 `/health` 로 확인
- [ ] 🟠 `/safety-pro` 의 좌표 미러링 — CSS 미러를 `fx = 1 - fx` 로 되돌린다.
      **저장은 비활성화(B안)** 됐는지 확인

**핵심 질문**: *구역을 안 그린 카메라가 남의 구역으로 판정하지 않는가?* → F5 가 그 결함이었다  ⏱ 1.5시간

---

### N. 디바운스
**파일**: [zone_debounce.py](../vigent-core/zone_debounce.py) (112줄) ·
[proximity.py](../vigent-core/proximity.py) (107줄) ·
[worker.py:163](../vigent-core/worker.py#L163) `_make_prox_debouncer`

- [ ] **시간 기반**(프레임 수가 아니라) 디바운스인가 — FPS 가 흔들려도 일관적인가
- [ ] zone enter 1.0초 / proximity enter 0.4초 · exit 1.0초. **비대칭인 이유**가 있는가
      (근거로 든 계산: 3m ÷ 2.78m/s ≈ 1.08초 — 사람이 3m 를 지나는 시간)
- [ ] ★**"확정 전이"에서만 발화**하는 구조 — 계속 안에 있으면 재발화하지 않는가.
      그게 맞는 설계인가(**오래 머무는 사람을 잊지 않는가**)
- [ ] `_make_prox_debouncer` 가 `enter_s <= 0` 이면 `None` 을 준다(롤백 경로) — 그때 동작은?

**핵심 질문**: *디바운스가 위험을 얼마나 늦추는가. 그 지연이 허용 범위인가?*  ⏱ 1시간

---

### O. 나머지 규칙
**파일**: [hazard_rules.py](../vigent-core/hazard_rules.py) · [ppe_check.py](../vigent-core/ppe_check.py) (263줄) ·
[behavior.py](../vigent-core/behavior.py) · [ergonomics.py](../vigent-core/ergonomics.py) ·
[worker.py:381](../vigent-core/worker.py#L381) `MotionTracker` · [:295](../vigent-core/worker.py#L295) `ErgonomicsTracker`

- [ ] 규칙 목록: `ppe_missing` · `fire_smoke` · `immobility` · `rapid_motion` · `crowd`
- [ ] 각 규칙의 **임계값이 어디서 오는가**(tuning.yaml? 하드코딩?)
- [ ] ★`immobility`(쓰러짐 의심) — **오탐이 가장 많이 나는 규칙**이다. 조건을 정확히 볼 것
- [ ] PPE 판정: 안전모·조끼 각각의 규칙과 **"사람이 아닌데 PPE 로 잡히는"** 경로
- [ ] 규칙 간 **우선순위·중복**이 있는가(하나의 상황이 여러 규칙을 동시에 때리는가)

**핵심 질문**: *현장에서 가장 자주 틀릴 규칙은 무엇이고, 그걸 끌 수 있는가?*  ⏱ 2시간

---

### P. 이벤트 발화와 쿨다운
**파일**: [worker.py:786](../vigent-core/worker.py#L786) `_process_frame`

- [ ] 규칙별 쿨다운 15초 / 증거 프레임 쿨다운 30초 — **왜 다른가**
- [ ] ★쿨다운이 **규칙 단위**인가 카메라 단위인가 트랙 단위인가.
      **다른 사람이 들어와도 쿨다운에 막히는가?**
- [ ] ✅ **F2 수정 확인** — `log_event()` 가 실패해도 `alert_notify.submit()` 이 실행되는가.
      (수정 전: 기록 실패 → 예외 → 통보까지 건너뜀 = 기록·통보 동시 사망)
- [ ] 프레임 단위 `except` 가 **무엇을 삼키는가** — 조용히 넘어가는 예외가 있는가

**핵심 질문**: *한 사람 때문에 걸린 쿨다운이 다른 사람의 위험을 가리지 않는가?*  ⏱ 1시간

---

## 4부. 통보 (Q~U) — "누가 아는가"

### Q. 경보 게이트(폭주 방지)
**파일**: [alert_gate.py](../vigent-core/alert_gate.py) (153줄) · `config/tuning.yaml` 의 `alerts:` 절

- [ ] 적응형 백오프: 300초 → ×2 → 상한 3600초. **조용해지면 리셋**(quiet_reset_s 1800)
- [ ] 시간당 상한 6건 · **등급 상승 시 예외**(억제 중이어도 뚫고 나감)
- [ ] ★`annotate()` 가 "직전 통보 이후 N건 억제됨"을 붙이는가 — **억제된 사실이 보이는가**
- [ ] ★**억제가 과한 시나리오**를 상상해 볼 것: 진짜 사고가 백오프 상한(1시간) 중에 나면?
- [ ] 실측 근거: M3 재집계에서 221건 → 24건 통보, 진짜 경보 4/4 보존
      ([benchmarks/m3_alert_rate_2026-08-20.md](../benchmarks/m3_alert_rate_2026-08-20.md))

**핵심 질문**: *폭주를 막는 장치가 진짜 사고를 막지는 않는가?*  ⏱ 1시간

---

### R. 비동기 통보
**파일**: [alert_notify.py](../vigent-core/alert_notify.py) (158줄)

- [ ] ★`submit()` 이 **절대 블로킹하지 않고 예외도 던지지 않는** 구조인가.
      (채널 타임아웃이 검출 루프를 멈추면 안 된다 — 그게 이 모듈의 존재 이유)
- [ ] 큐가 가득 차면 **오래된 것을 버린다** — 그게 맞는가(최신 경보가 더 중요하다는 전제)
- [ ] 전송 스레드가 죽으면? 되살아나는가, 조용히 사라지는가
- [ ] `set_sender()` 배선 시점 — **그 전에 발생한 경보는 어디로 가는가**(A 항목과 연결)

**핵심 질문**: *통보 채널이 느려질 때 검출이 같이 느려지지 않는가?*  ⏱ 40분

---

### S. 디스패처와 채널
**파일**: [agents/dispatcher.py](../vigent-core/agents/dispatcher.py) (240줄) ·
[config/notify.yaml](../config/notify.yaml) · [docs/telegram_setup.md](telegram_setup.md)

- [ ] 등급(`critical`/`high`/`mid`/`low`)별로 **어떤 채널**이 붙는가(`on_severity`)
- [ ] ★`notify_cfg()` 가 **`config/notify.yaml` 을 환경변수보다 먼저** 읽는다.
      이 때문에 **테스트가 실제 텔레그램을 쏜 사고가 있었다.** 테스트 격리가 됐는지 확인
- [ ] 🟡 자격증명이 `notify.yaml` 에 평문인가, `.env` 참조인가
- [ ] 메시지 본문에 **개인정보·내부 IP·경로**가 들어가는가
- [ ] `guard_bypass_text` 가 tuning 에서 오는가(하드코딩 "프레스/전단기" 문구는 일반화됨)

**핵심 질문**: *알림 문구에 밖에 나가면 안 되는 것이 섞여 있지 않은가?*  ⏱ 1시간

---

### T. 전송 큐·재시도·데드레터
**파일**: [alert_queue.py](../vigent-core/alert_queue.py) (241줄)

- [ ] **선기록(write-ahead)** 구조 — sqlite 에 먼저 쓰고 보낸다. 프로세스가 죽어도 남는가
- [ ] 지수 백오프 재시도 최대 10회 → 데드레터. **데드레터가 되면 누가 아는가**
- [ ] ✅ `_attempted_remote()` — **원격 채널을 시도조차 안 한 경우**(log-only 등급)는
      재시도하지 않고 즉시 sent 처리. (수정 전: mid 등급이 영원히 재시도하다 데드레터)
- [ ] `pending ≥ 1` → `/health` degraded 배선이 실제로 되는가
- [ ] sqlite 파일이 **어디에 있고 얼마나 커지는가**. 정리되는가

**핵심 질문**: *못 보낸 경보가 조용히 사라지는 경로가 있는가?*  ⏱ 1시간

---

### U. 릴레이(물리 출력)
**파일**: [relay.py](../vigent-core/relay.py) (183줄) · [scripts/mock_relay.py](../scripts/mock_relay.py)

- [ ] ★**ON 실패는 3회 후 포기**(fail-silent — 사이렌이 안 울린다).
      **OFF 실패는 8회 + 상태 노출**(off_failed→degraded). 비대칭이 의도된 것인가
      (의도: 안 꺼지는 사이렌이 최악이므로 OFF 를 더 끈질기게)
- [ ] 자동 OFF 타이머 30초 — **프로세스가 죽으면 타이머도 죽는다.** 사이렌이 켜진 채 남는가
- [ ] 🟠 **F4 미구현** — 현재 `critical` 등급만 릴레이가 붙는다.
      **침입·근접(high)에는 물리 출력이 없다.** 배선 방향은 결정됐고 장비 확보 후 구현
- [ ] 🟡 **F13 미착수** — 재기동 시 릴레이 OFF 1회 송신이 필요한데 없다
- [ ] ✅ **F29 수정 확인** — mock 서버가 `ThreadingHTTPServer` 이고 `start()` 가 기동을 기다리는가

**핵심 질문**: *사이렌이 안 울린 것을 우리가 아는가? 켜진 채 남는 경로는?*  ⏱ 1시간

---

## 5부. 저장과 운영 (V~Z)

### V. 기록과 증거
**파일**: [data_engine.py](../vigent-core/data_engine.py) (173줄) · [incident.py](../vigent-core/incident.py) (462줄)

- [ ] JSONL 이벤트 + JPEG 증거. **건당 용량**(~230KB)과 하루 예상 증가량
- [ ] ✅ **F2 수정 확인** — `_save_frame` 의 `mkdir`, `log_event` 의 `mkdir`+`open` 이
      **try 안에** 있는가. 실패 시 `record["logged"]=False` 로 표시하고 **record 를 정상 반환**하는가
- [ ] 실패가 **반드시 ERROR 로그로 드러나는가**(`_elog()`) — 조용한 실패가 없는가
- [ ] 시각이 KST 고정인가. NTP 미동기 시 이벤트 순서가 꼬이는가
- [ ] 동시 쓰기(여러 카메라) 시 JSONL 이 깨지지 않는가 — 락이 있는가

**핵심 질문**: *디스크가 찼을 때 무엇이 죽고 무엇이 사는가?*  ⏱ 1시간

---

### W. 개인정보 — 얼굴 모자이크
**파일**: [privacy.py](../vigent-core/privacy.py) (270줄) ·
[worker.py:152](../vigent-core/worker.py#L152) `_frame_to_dataurl`

- [ ] person 박스 상단 + YuNet 얼굴 검출 **2단 구조** — 하나가 실패하면?
- [ ] ★YuNet 모델 접근에 **락이 있는가**(스레드 안전).
      **락 없이 돌다 4,144건 실패한 실제 사고가 있었다** → 수정됨
- [ ] 모자이크가 **실패했을 때 원본이 저장되는가**, 저장을 포기하는가.
      ★어느 쪽이 맞는 설계인지 판단할 것(개인정보 보호 vs 증거 보전)
- [ ] 모자이크 강도가 **되돌릴 수 없을 만큼** 충분한가
- [ ] 라이브 스트림(`/safety-hub` 화면)에도 적용되는가, 저장본에만인가

**핵심 질문**: *모자이크가 조용히 실패하면 원본 얼굴이 디스크에 남는가?*  ⏱ 1시간

---

### X. 보존과 파기  ★가장 조심할 곳
**파일**: [retention.py](../vigent-core/retention.py) (332줄) ·
[retention_scheduler.py](../vigent-core/retention_scheduler.py) (140줄)

- [ ] 보존 기간 그룹(30일 / 1095일) — **무엇이 어느 그룹**인가. 법적 근거가 있는가
- [ ] ★**경로 화이트리스트** — 삭제 대상 경로를 어떻게 제한하는가.
      **여기가 뚫리면 엉뚱한 파일을 지운다.** 이 저장소에서 가장 위험한 코드다
- [ ] **첫 주기 보류**(P1b) — 처음 실행 때는 지우지 않고 보고만. 그 안전장치가 살아 있는가
- [ ] ✅ **F6 수정 확인** — `retention_scheduler` 가 `sweep()` 을 **execute 인자 없이** 부르는가
      (인자를 넘기면 첫 주기 보류가 우회된다)
- [ ] 스레드가 **예외로 죽지 않는가**(주기마다 try) — 한 번 죽으면 영영 안 돈다
- [ ] ★스윕이 **검출을 방해하지 않는가** — `DETECT_LOCK`·GPU 를 안 건드리는가
      (테스트가 AST 로 강제한다: [tests/test_retention_scheduler.py:107](../tests/test_retention_scheduler.py#L107))

**핵심 질문**: *이 코드가 지우면 안 되는 것을 지울 경로가 있는가?*  ⏱ 1.5시간

---

### Y. 헬스와 관측
**파일**: [health_status.py](../vigent-core/health_status.py) (153줄) ·
[routers/system.py](../vigent-core/routers/system.py) (191줄) · [rig_monitor.py](../vigent-core/rig_monitor.py)

- [ ] 3상태(healthy/degraded/unhealthy) **판정 규칙 전체**를 한 번에 볼 것
- [ ] `stale_detect`(검출이 안 돎) vs `stale_frame`(프레임이 안 옴) 구분 — 30초 임계
- [ ] ✅ **F1 수정 확인** — `slot_degraded` 가 판정에 들어가는가.
      `CRITICAL_SLOTS=("person",)` 저하 = **unhealthy(503)**, 나머지 슬롯 = degraded
- [ ] ✅ **F5 확인** — `zone_source`·`zone_points` 가 카메라별로 노출되는가
- [ ] ✅ **F6 확인** — `retention_sweep`(runs·failures·next_run_in_s)이 보이는가
- [ ] 🟠 **F9 미수정** — `/health` 는 **pull 전용**이다. PC 가 죽으면 밖에서 알 방법이 없다.
      push 하트비트·생존 신고가 없다
- [ ] ★**"정상"의 정의가 너무 관대하지 않은가** — 무엇이 고장 나도 healthy 인가

**핵심 질문**: *healthy 가 진짜 "다 잘 돌고 있다"는 뜻인가?* → F1·F3 이 그 반례였다  ⏱ 1.5시간

---

### Z. 인증·권한·비밀
**파일**: [auth_session.py](../vigent-core/auth_session.py) · [ws_auth.py](../vigent-core/ws_auth.py) ·
[routers/safety_core.py](../vigent-core/routers/safety_core.py) (786줄 — 가장 큰 라우터) ·
`.env` · [config/security.json](../config/security.json)

- [ ] ★세션이 **프로세스 메모리에만** 있다 — 재시작하면 로그인이 풀린다. 의도된 것인가
- [ ] `VIGENT_API_TOKEN` 검사가 **어떤 경로에 걸리고 어디가 열려 있는가**.
      ★**인증 없이 부를 수 있는 엔드포인트 목록을 직접 뽑아볼 것**
- [ ] WebSocket 인증(`ws_auth`)이 HTTP 와 **같은 수준**인가
- [ ] `.env` 가 `.gitignore` 에 있는가. **커밋 이력에 들어간 적은 없는가**
- [ ] 로그·에러 응답에 **토큰·비밀번호가 찍히는가**
- [ ] 🔴 **운영 주의**: `config/tuning.yaml` 은 git 추적 파일이다.
      **학원 프로파일을 덮어쓴 상태로 커밋하면 학원 설정이 저장소 기본값이 된다**

**핵심 질문**: *인증 없이 부를 수 있는 엔드포인트가 무엇인가?*  ⏱ 1.5시간

---

## 부록 1. 품질 게이트 (리뷰와 별개로 항상 통과해야 함)

```powershell
ruff check vigent-core tests                      # → 0
python -m mypy                                    # → 화이트리스트 0 에러
python -m unittest discover -s tests              # → 412 tests OK
python scripts\check_openapi_diff.py              # → 108 == baseline
```

- [ ] 테스트 **52개 파일 / 412건**. 어떤 영역에 **테스트가 없는지** 확인할 것
- [ ] ★게이트가 초록인데 결함이 있었던 사례가 이번에 여럿 나왔다(F1·F2·F5·F6).
      **게이트는 회귀를 막지, 설계 결함을 잡지 못한다** — 그래서 이 눈 리뷰가 필요하다

---

## 부록 2. 진행 방법 (권장)

**한 번에 다 보지 말 것.** 26항목 합계 ⏱ **약 30시간**(추정)이다. 묶어서 나누는 편이 낫다.

| 묶음 | 항목 | 왜 함께 보는가 | ⏱ |
|---|---|---|---|
| **1. 미검출 경로** | D · H · I · J · K | 🔴 **놓치면 사고**. 최우선 | ~8h |
| **2. 판정 정확도** | L · M · N · O | 오탐/미탐의 균형이 정해지는 곳 | ~5h |
| **3. 통보 사슬** | P · Q · R · S · T · U | 검출돼도 사람에게 안 닿으면 무의미 | ~6h |
| **4. 운영·관측** | A · E · F · G · Y | "죽은 걸 아는가" | ~5h |
| **5. 데이터·법규** | V · W · X · Z | 개인정보·파기·권한 | ~5h |
| **6. 설정·배포** | B · C | 현장에서 틀어지는 곳 | ~1h |

**읽을 때 권하는 습관**

1. ★**"실패하면 어떻게 되는가"를 매 함수마다 물을 것.** 이번 안전 리뷰의 🔴 4건이
   전부 "실패했는데 아무도 모르는" 유형이었다.
2. 주석이 **코드와 맞는지** 확인할 것. docstring 에 "예외로 죽지 않음"이라 적혀 있지만
   실제로는 죽던 것이 F2 였다.
3. 이상하면 **테스트를 찾아볼 것** — 없으면 그 자체가 발견이다.
4. 발견은 [SAFETY_REVIEW_REPORT.md](../SAFETY_REVIEW_REPORT.md) 형식(위치·내용·현장
   시나리오·수정 제안)으로 적으면 바로 이어붙일 수 있다.

---

## 부록 3. 이미 알려진 미해결 결함 (리뷰 중 마주치면 중복 보고 불필요)

| 번호 | 항목 | 내용 | 상태 |
|---|---|---|---|
| **F3** | D | 프리즈 스트림 감지 없음 | 🔴 방문 후 |
| **F4** | U | high 등급에 물리 출력 미배선 | 🟠 방향 결정·장비 대기 |
| **F9** | Y | 시스템 다운을 외부에 알릴 방법 없음 | 🟠 미착수 |
| **F13** | U | 재기동 시 릴레이 OFF 미송신 | 🟡 미착수 |
| **F30** | H | onnx_parity 간헐 ERROR | 🔍 원인 미확인 |
| **—** | B | 학원 프로파일 드리프트(전체 덮어쓰기 구조) | 🔴 임시 조치·근본 해법 대기 |

전체 30건과 수정 내역은 [SAFETY_REVIEW_REPORT.md](../SAFETY_REVIEW_REPORT.md) 참조.
