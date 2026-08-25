# VIGENT 현장 설치 전 안전 리뷰 리포트 (2026-08-21)

> **기준**: ①미검출(놓치면 사고) 최우선 ②오탐 다발(현장이 시스템을 꺼버림) 차순위.
> **방법**: 코드 전수 열람 + 이 세션의 실측 기록(audit/·benchmarks/) 대조. 추측한 항목은
> "확인 필요"로 표기했다. **코드는 수정하지 않았다** — 수정은 항목별 지시에 따른다.
>
> **전제(코드·문서로 확인된 것)**: VIGENT 는 §8 **보조·감시 계층**이다 — 설비 정지(인터록)
> 책임은 인증 하드웨어(Type4 방호장치·안전 PLC)에 있고, 본 시스템은 **알림 + 보조 사이렌**
> 까지만 출력한다. PLC·Modbus·GPIO 연동 코드는 **존재하지 않는다**(전수 검색 0건).
> 따라서 이 리포트의 "치명"은 "설비가 안 멈춤"이 아니라 **"위험을 못 보거나, 알림이 안
> 나가거나, 죽은 것을 아무도 모르는 상태"**를 뜻한다.
>
> **전제 확정(2026-08-21 사용자 답변)**:
> ①**요구 반응시간 미확정** — 파일럿 단계. 현재 실측(침입 폰 도착 2.7초)이 감당 가능한지
>   학원에서 확인. → 관련 항목(F8) 심각도를 "미확정 기준" 전제로 재조정했다.
> ②**알람 해제 정책 미정** — 현재 자동 해제(쿨다운·타이머) 유지.
> ③**야간·IR 파일럿 범위 밖** — 학원은 주간 실습. → F11 을 🟠→🟡 로 하향.
> ④**카메라 고정**(학원 CCTV). C200 보조 카메라만 이동 가능 → 이동 시 구역 재설정 필요.
>
> **수정 현황(2026-08-21)**: 🔴 F5·F1·F2 **수정 완료**(테스트 17건 동봉) ·
> F6 **확인 완료**(주기 실행 주체 부재 확정 — 조치는 운영 결정) ·
> F4 **방향 결정**(침입·근접(high)에도 릴레이 배선 — 구현은 릴레이 장비 확보 후) ·
> F3 는 방문 후로 이월.

---

## 1. 시스템 구조 요약

```
[RTSP 카메라]
  │ _StreamCapture 캡처 스레드(카메라별)  worker.py:408
  │   grab-드레인→retrieve, 최신 1프레임 슬롯 덮어쓰기
  │   읽기실패 5회→지수 백오프 재연결(상한 5s), generation++
  ▼
[worker._loop]  worker.py:939   검출주기 0.5s(fullset_fps 2)
  │   read_latest() → 슬롯 프레임 / 하트비트 = 슬롯 갱신 시각
  ▼
[guard.detect]  agents/guard.py   전역 DETECT_LOCK 직렬화
  │   RF-DETR 4슬롯(person·ppe·fire_smoke·forklift) imgsz384
  │   → NMS(0.55) → 포함비 억제 → person 병합 → ByteTrack
  │   히스테리시스: ppe 3프레임 / fire 2프레임 (guard.py:259)
  ▼
[worker._derive]  worker.py:145   규칙 판정
  │   zone_intrusion  : 발끝점∈폴리곤 → 시간 디바운스 1.0s → 확정 "전이"에서만 발화
  │   proximity_hazard: 반경3m + 운전자제외(0.65) → 디바운스 0.4s → 전이 발화
  │   ppe_missing / fire_smoke / immobility / rapid_motion / crowd
  ▼
[worker._process_frame]  worker.py:865
  │   규칙별 쿨다운 15s → 증거 프레임(쿨다운 30s, 얼굴 모자이크)
  │   → data_engine.log_event(JSONL+JPEG)  ★기록
  │   → alert_notify.submit()              ★통보(비동기·비블로킹)
  ▼
[alert_gate]  반복억제 300s→백오프×2(상한 3600s)·시간당 6건·등급상승 예외
  ▼
[alert_notify 스레드] → dispatcher.dispatch
  │   → alert_queue 선기록(sqlite) → telegram/email/webhook
  │   → critical 등급만 relay.turn_on() (HTTP 사이렌, 기본 비활성)
  │   실패 시 재시도 스레드(지수 백오프, 최대 10회) → 데드레터
```

**알람 발생/해제 상태 흐름**
```
발생: 구역진입 → 1.0s 체류 → 확정전이 → 기록 → (게이트 통과 시) 폰 알림
      critical 만 릴레이 ON(30s 자동 OFF, 재발화 시 연장)
해제: ★"상황 종료" 이벤트가 없다.
      · 알림은 1회성 — 해제 개념 자체가 없음
      · 사람이 나가면 exit 1.0s 후 상태기계만 해제(외부 통보 없음)
      · 릴레이 OFF 는 타이머 만료뿐 — turn_off() 를 부르는 다른 코드 없음(전수 확인)
```

**감시 계층**: readiness(예열, 503) / hang 워치독(15s) / starvation_guard(3단계) /
health_status(카메라별 ok·stale_detect·stale_frame → 전체 healthy·degraded·unhealthy,
unhealthy=HTTP 503) / alert_queue 재시도(pending≥1 → degraded) / NSSM 자동 재시작(5s).

---

## 2. Fail-safe 매트릭스

| 장애 상황 | 현재 동작 (코드 확인) | 안전? | 개선 방향 |
|---|---|---|---|
| **카메라 랜선 뽑힘 / RTSP 끊김** | 캡처 재연결(백오프 상한 5s) → 30s 후 `stale_frame` → /health degraded·unhealthy(503). 실측 4/4 자동복구(6~50s) | ✅ 양호 | — (503 폴링하는 외부 감시가 있을 때만 성립 — F9 참조) |
| **프레임 None** | error 기록 후 0.5s 대기·계속. 지속되면 stale → 상동 | ✅ | — |
| **★프리즈(정지화면 계속 송출)** | **감지 없음**(전수 검색 0건). 슬롯 ts 계속 갱신 → hang·stale 전부 통과 → **영구 healthy + 실명** | 🔴 아니오 | 프레임 해시/차분 기반 프리즈 감지 → stale_frame 승격 (F3) |
| **모델 로드 실패(기동 시)** | readiness FAILED → /health unhealthy(503), 워커 미기동 | ✅ | — |
| **슬롯 추론 연속 실패(런타임)** | 3회 후 slot_degraded 표시(guard.py:770) — **그러나 /health 전체 판정·본문에 미반영**(system.py:39 는 rfdetr_slots 만 추출). 다른 슬롯이 detect_ts 갱신 → **healthy 유지** | 🔴 아니오 | slot_degraded → overall degraded/unhealthy 배선 (F1) |
| **GPU OOM / CUDA 예외** | 슬롯 예외와 동일 경로(빈 결과+streak). 전 슬롯 실패여도 detect 자체는 정상 반환 → stale 로 안 잡힐 수 있음 | 🔴 부분 | F1 과 동일 수정으로 해소 |
| **처리 지연(과거 프레임 판정)** | 슬롯은 최신 1프레임만 보관(누적 차단, 실측 신선도 0.3~0.6s). 단 재연결 중엔 **옛 프레임을 최대 15s 재처리**(hang 임계까지) | 🟡 경계 | read_latest 에 슬롯 나이 상한(예: 3s) 추가 검토 (F8 유사) |
| **프로세스 크래시** | NSSM 재시작 5s + 예열 ~30s + 카메라 복귀 ~34s(실측 T2). 재시작 중 감시 공백 ~34s. 릴레이가 켜져 있었다면 자동 OFF 타이머도 함께 죽음 | 🟡 | 재기동 시 릴레이 OFF 1회 송신 (F13) |
| **PC 재부팅(정전 복구)** | 자동 기동 실측 통과 — 단 **부팅 +284s(지연시작) + 예열**, 약 5분 공백. 그 사실을 통보할 채널 없음 | 🟠 | 기동 완료 통보 (F9) |
| **디스크 풀** | log_event 의 mkdir·open 이 try 밖(data_engine.py:48,96) → OSError → _process_frame except → **같은 프레임의 alert_notify.submit 까지 건너뜀 = 기록·통보 동시 사망**. 루프는 유지 | 🔴 아니오 | 기록/통보 예외 격리 + 디스크 잔량 /health 노출 (F2) |
| **알림 채널 두절(인터넷)** | 선기록 큐 → 백오프 재시도(최대 10회) → 데드레터. pending≥1 → degraded. 24h 소크 미전송 0건 실측 | ✅ 양호 | 데드레터 발생 시 별도 통보 검토 |
| **릴레이 통신 두절** | ON 실패: 3회 재시도 후 포기(**사이렌 안 울림 — fail-silent**). OFF 실패: 8회+상태 노출(off_failed→degraded) | 🟡 | ON 최종 실패도 /health 반영 검토. §8 경계상 수용 가능 |
| **시스템 전체 다운(PC 사망)** | **외부에 알릴 방법 없음** — /health 는 pull 전용, push 하트비트 없음. NSSM 도 PC 가 죽으면 무력 | 🟠 | 일일 생존 신고 또는 외부 폴링 감시 (F9) |
| **시간 미동기(NTP)** | Windows 기본 의존. 이벤트 시각은 KST 고정(data_engine.py) | 🟢 | 설치 시 시간 동기 확인 항목화 |

---

## 3. 발견 항목 (심각도순)

### 🔴 치명

**F1. person 슬롯이 죽어도 /health 가 healthy — 실명 상태 미노출** — ✅ **수정 완료(2026-08-21)**
- 위치: [agents/guard.py:770](vigent-core/agents/guard.py#L770)(감지) vs [routers/system.py:39](vigent-core/routers/system.py#L39)(미배선)
- 내용: 슬롯 추론이 연속 3회 실패하면 `slot_degraded` 를 세우고 로그에 "★/health 에서
  확인할 것"이라 적지만, `/health` 는 `guard.status()` 에서 **`rfdetr_slots` 만** 꺼낸다.
  `slot_degraded`·`predict_fail_streak` 는 응답 본문에도, 전체 판정(healthy/degraded)에도
  들어가지 않는다. person 슬롯만 죽으면(가중치 파일 손상, GPU 부분 고장, 어댑터 예외)
  다른 슬롯이 `last_detect_ts` 를 계속 갱신해 stale_detect 도 안 걸린다.
- 현장 시나리오: 설치 몇 주 후 person 가중치가 디스크 오류로 손상 → 사람 검출 0건이
  되지만 화재·PPE 슬롯이 돌아가므로 모든 지표 정상 → **위험구역에 사람이 들어가도
  아무 일도 안 일어나고, 아무도 모른다.** 미검출 중 최악의 형태.
- ✅ **적용된 수정**: `health_status.overall/build` 에 `slot_degraded` 인자 추가 —
  `CRITICAL_SLOTS=("person",)` 저하는 **unhealthy(503)**, 비핵심 슬롯(ppe·fire_smoke·
  forklift)은 degraded. `routers/system.py` 가 guard 에서 꺼내 판정에 넘기고 **본문에도
  `slot_degraded` 노출**. 인자 미지정 시 기존 판정 유지(하위호환).
  테스트 6건(`tests/test_safety_review_fixes.py::TestSlotDegradedSurfaces`).

**F2. 디스크 풀이면 기록과 통보가 함께 죽는다** — ✅ **수정 완료(2026-08-21)**
- 위치: [data_engine.py:48-50](vigent-core/data_engine.py#L48)(`folder.mkdir` try 밖),
  [data_engine.py:96-99](vigent-core/data_engine.py#L96)(`_RECOG.mkdir`+`open` try 밖),
  [worker.py:876-886](vigent-core/worker.py#L876)(log_event 예외 → submit 미도달)
- 내용: docstring 은 "항상 결과를 반환(예외로 죽지 않음)"이지만 mkdir·open 은 예외를
  던질 수 있다. `_process_frame` 에서 `log_event()` 가 던지면 프레임 단위 except 로
  빠져 **그 뒤의 `alert_notify.submit()` 이 실행되지 않는다.** 즉 디스크가 차면
  증거·이벤트 기록 실패가 **알림 실패로 전이**된다.
- 현장 시나리오: retention 미가동(F6) 상태로 수 주 무인 운영 → 증거 JPEG(건당 ~230KB)
  로 디스크 풀 → 이후 발생하는 모든 위험이 기록도 통보도 안 됨. 검출 루프는 살아 있어
  /health 는 healthy(큐에 못 들어가니 pending 도 안 쌓임).
- ✅ **적용된 수정**: `_save_frame` 의 `folder.mkdir` 을 try 안으로 옮기고
  `log_event` 의 `_RECOG.mkdir`+`open` 을 try 로 감쌌다. 기록 실패 시 예외를 올리지 않고
  `record["logged"]=False` 로 표시한 뒤 **record 를 정상 반환**해 호출부의
  `alert_notify.submit()` 이 이어지게 했다. 증거 저장 실패는 `evidence=None` 으로 흡수.
  실패는 ERROR 로그로 반드시 드러난다(`_elog()`).
  테스트 5건(`TestRecordFailureDoesNotBlockAlert`) — 통합 테스트로 "기록 실패 시에도
  워커가 통보를 호출한다"까지 고정.
- ⏸ **미적용(별도 결정)**: 디스크 잔량 /health 노출은 이번 범위에서 제외 — F6 조치와
  함께 다루는 것이 자연스럽다.

**F31. 슬롯 '로드 실패'는 초록불 — [F1] 이 절반만 덮었다** — ✅ **수정 완료(2026-08-24)**
- 위치: [agents/guard.py:781](vigent-core/agents/guard.py#L781) `if model is None: continue`
- 내용: [F1] 은 슬롯 **추론 실패**(로드는 됐는데 매 프레임 예외)만 덮었다. `_get_model()` 이
  None 을 돌려주는 **로드 실패** 경로(가중치 손상·GPU OOM·라이브러리 오류)는 스트릭도
  `slot_degraded` 도 세우지 않고 조용히 `continue` 했다. person 이 이 경로로 죽으면
  **침입 경보가 통째로 무력화되는데 `/health` 는 healthy** 였다.
  person 은 3중으로 안 보였다 — ①`rfdetr_slots` 에 없음(커스텀 가중치가 없어 그 맵에 미포함)
  ②`slot_degraded` 미발동 ③`load_errors` 에 원인이 있는데 `/health` 가 안 꺼냄.
- **실측 재현**(주입 시험, 2026-08-24): person 로드 실패 10프레임 →
  `detections 0건 · slot_degraded {} · predict_fail_streak {} · /health healthy`.
  같은 "사람 못 봄" 상태인데 추론 실패는 unhealthy, 로드 실패는 healthy 로 **정반대**였다.
- 현장 시나리오: 가중치 파일이 디스크 오류로 손상 → 기동 시 **존재 검사만** 하므로 통과 →
  첫 추론에서 로드 실패 → 이후 영구 실명. **[F1] 을 만든 근거가 바로 이 시나리오였는데
  정작 그 시나리오가 이 구멍으로 빠졌다.**
- ✅ **적용된 수정(최소안 — 2026-08-24 사용자 결정)**:
  ① `model is None` 을 추론 실패와 **같은 등급**으로 취급(스트릭·DEGRADED·ERROR 로그) →
     기존 F1 배선을 그대로 타 person 저하 시 unhealthy(503).
  ② ★**로그 폭주 방지**: 로드 실패는 재시도가 없어 매 프레임 영구 발생한다(2fps면 하루
     17만 줄). 그대로 두면 이 수정이 디스크를 채워 **[F2] 를 되살린다** — 임계까지는 매번,
     이후 `LOAD_FAIL_LOG_EVERY`(1200프레임 ≈ 10분) 주기로만 남긴다.
  ③ `/health` 에 `slot_errors` 노출 — ★`/health` 는 **무인증 허용**이라 `_strip_paths()` 로
     **경로를 파일명으로 축약**한다(백로그 B-expose 의 경로 노출 우려와 같은 취지).
  테스트 11건(`tests/test_slot_load_failure.py`) — 수정 전 코드로 돌리면 **5건이 실패**함을
  확인했다(테스트가 실제로 결함을 잡는지 검증).
- ⏸ **미적용(백로그 이월)**: 재시도(B-slotretry) — **로드 실패는 자동 복구되지 않고 재시작이
  필요하다**. 예열 단계 검사(B-warmslot) — 예열은 ready 인데 ~1.5초 뒤 빨간불이 되는 동작은
  `docs/academy_visit_day.md` 문제해결 절에 명시했다.

**F3. 프리즈(정지 화면) 스트림 감지 없음**
- 위치: [worker.py:408-527](vigent-core/worker.py#L408) `_StreamCapture` /
  [health_status.py](vigent-core/health_status.py) — 프레임 내용 검사 코드 0건(전수 검색)
- 내용: 카메라·NVR 가 마지막 화면을 정지 상태로 계속 송출하는 고장(현장에서 실제 흔함)
  은 `read()` 가 계속 성공하므로 슬롯 ts 가 갱신되고, hang 워치독(15s)·stale_frame(30s)
  을 전부 통과한다. "같은 프레임 반복" 케이스에 대한 방어가 없다.
- 현장 시나리오: NVR 채널 프리즈 → 화면은 어제 오후 장면 고정 → 시스템은 영구히
  healthy → 그 카메라 구역은 **감시가 죽었는데 죽은 줄 모른다.**
- 수정 제안: 캡처 스레드에서 N초 간격 프레임 해시(또는 다운샘플 절대차) 비교 —
  장시간(예: 10분) 완전 동일(diff=0)이면 `frozen` 상태로 stale_frame 승격.
  야간 정지 장면은 센서 노이즈로 diff>0 이므로 오판 위험 낮음(검증 필요).

**F4. 주요 위험(high)에는 물리 출력이 배선돼 있지 않다** — 📌 **방향 결정됨(구현 보류)**
- 위치: [agents/dispatcher.py:70](vigent-core/agents/dispatcher.py#L70)·[dispatcher.py:173](vigent-core/agents/dispatcher.py#L173)
  (`safety_relay_signal` 은 critical 전용), [themes/safety/vision.yaml:105](themes/safety/vision.yaml#L105)
- 내용: `zone_intrusion`·`proximity_hazard` 는 **high** 로 발화한다(worker.py:180·199).
  릴레이(사이렌·경광등)는 **critical**(fire_smoke·guard_bypass)에서만 켜진다. 즉 현장에서
  릴레이를 연결·활성화해도 **사람이 위험구역에 들어가거나 지게차에 접근할 때 사이렌이
  울리지 않는다.** 폰 알림(2.7s)만 간다.
- 현장 시나리오: 시연에서 화재 시험으로 "사이렌 됩니다" 확인 후 설치 → 실제 침입에서
  사이렌 침묵 → 현장은 시스템 고장으로 인식. 담당자가 폰을 못 보는 동안 현장 경고
  수단이 전무.
- 수정 제안: `on_severity.high` 에 `safety_relay_signal` 추가를 **현장별 설정**으로
  (vision.yaml 이 이미 그 자리). 침입 오경보 시 사이렌 오작동 트레이드오프를 현장과
  합의 후 결정. §8 경계 문구 유지.
- ✅ **결정(2026-08-21, 사용자)**: **침입·근접(high)에도 릴레이를 배선한다.** 사람이
  위험구역에 들어갔는데 사이렌이 안 울리면 현장에서 납득되지 않는다.
  **구현은 릴레이 장비 확보 후** — 실물 없이 배선만 바꾸면 검증 없이 배포하는 셈이다.
  구현 시 함께 처리할 것: F13(크래시 시 OFF 송신) · 오경보 시 사이렌 오작동 대비
  (억제 게이트가 릴레이에도 적용되는지 확인 필요).

### 🟠 높음

**F5. 전역 구역 폴백 — 카메라별 구역을 안 그리면 개발 때 좌표가 조용히 적용된다** — ✅ **수정 완료(2026-08-21, 최우선 처리)**
- 위치: [worker.py:917](vigent-core/worker.py#L917)(`zone or _load_zone()`),
  [config/danger_zone.json](config/danger_zone.json)(개발 중 만든 3점 폴리곤 실존:
  {0.115,0.233}{0.409,0.244}{0.212,0.746})
- 현장 시나리오: 설치 당일 카메라 등록만 하고 구역을 아직 안 그림 → 전역 파일의 개발
  좌표가 즉시 적용 → 그 자리를 지나는 사람마다 침입 경보("설치하자마자 오경보").
  반대로 운영자는 "구역 안 그렸으니 침입 감지 없음"으로 오인(실제로는 엉뚱한 곳 감시 중).
- ✅ **적용된 수정**(worker.py `_setup_run`): **전역 폴백을 기본 차단**했다.
  카메라별 구역이 없으면 `zone=[]` → **침입 판정을 하지 않는다**(PPE·화재·근접은
  구역과 무관하게 그대로 동작). 상태를 `zone_source`(camera|global|none)·`zone_points`
  로 남겨 **/health 의 `cameras[].zone_source` 에 노출**한다 — 운영자가 "미설정"과
  "전역 좌표 적용"을 구분할 수 있다. 미설정 시 WARNING 로그로도 드러낸다.
  롤백: `zone.global_fallback: true`(tuning.yaml, 기본 false).
  테스트 6건(`TestZoneFallbackBlocked`).
- 📌 **config/danger_zone.json 실물 — 처리 방향 제안(미실행)**: 코드 수정으로 이 파일은
  **기본 경로에서 더 이상 읽히지 않아** 무해해졌다. 그래도 남겨둘지는 선택이다.
  · **(권장) 내용만 비우기** `{"points": []}` — 시드 파일 구조는 유지하고 개발 좌표만 제거.
    폴백을 나중에 켜더라도 사고가 안 난다. git 이력으로 복구 가능.
  · (대안) 파일 삭제 — `_load_zone()` 이 없으면 빈 목록을 반환하므로 동작상 동일.
  · (비권장) 그대로 두기 — 폴백을 켜는 순간 다시 지뢰가 된다.
  **파괴적 변경이라 실행하지 않았다 — 지시 주시면 처리한다.**

**F6. retention(자동 파기) 주기 실행 주체가 서버 안에 없다 — 디스크 풀은 시간문제** — 🔍 **확인 완료(미조치)**
- 위치: [retention.py:1](vigent-core/retention.py#L1)("scripts/retention_sweep.py 가 호출"),
  main.py 에 주기 스레드 등록 없음(전수 확인). /health last_run = 2026-08-18(3일 전).
- 현장 시나리오: 설치 후 스케줄러 등록 누락 → 증거 JPEG 무한 누적 → 수 주 후 디스크
  풀 → **F2 로 전이**(기록·통보 동시 사망).
- 수정 제안: ①서버 내 일일 스윕 스레드 또는 ②작업 스케줄러 등록을 설치 필수 항목화
  + last_run 이 N일 초과면 /health degraded.
- 🔍 **전수 확인 결과(2026-08-21)**: `main.py` 에 retention 주기 스레드 **없음** ·
  `deploy/windows/*.ps1` 에 `schtasks`/`Register-ScheduledTask` **0건** ·
  `scripts/retention_sweep.py` 는 존재하나 **부르는 주체가 어디에도 없다.**
  라이브 `/health` 의 `disk_retention.last_run` = 2026-08-18(3일 전, 수동 실행 추정).
  → **"자동 파기가 구현돼 있다"는 현재 사실이 아니다** — 스윕을 돌리는 것은 사람이다.
- ⚠**F2 와 결합 시나리오**(사용자 지적 그대로): 스케줄러 미등록 → 증거 무한 누적 →
  디스크 풀 → (F2 수정 전이라면) 기록·통보 동시 사망. **F2 를 고쳐 두 번째 고리는
  끊었으나, 첫 번째 고리(디스크가 차는 것 자체)는 그대로다.**
- 조치 선택지: ①서버 내 일일 스윕 스레드 추가(코드) ②작업 스케줄러 등록(운영) —
  ②는 아래 명령 한 줄이면 된다. **운영 결정 사항이라 실행하지 않았다.**

**F7. 정지 물체 person 오검출 → 상시 침입·무동작 경보 (실측 근거)**
- 위치: 모델 특성. [benchmarks/m2_night_person.md](benchmarks/m2_night_person.md)
  (사람 없음 조건 검출회차 86.4% person 오검출, conf 0.36~0.67 — 운용임계 0.40 초과),
  [benchmarks/m3_alert_rate_2026-08-20.md](benchmarks/m3_alert_rate_2026-08-20.md)(무동작 221건/24h)
- 현장 시나리오: 구역 안에 검은 장비·자재가 놓이면(현장은 물건이 수시로 이동) 상시
  침입 + 무동작 경보 → 억제가 묶어도 시간당 1건 영구 발신 → **현장이 알림을 무시하기
  시작 = 시스템 사망.** 오탐 관점 1순위.
- 수정 제안: 단기 — 설치 시 "사람 없이 잡히는 자리" 확인 후 구역 배치(절차서 반영됨).
  중기 — 장시간 고정 person 박스 자가진단(동일 위치 N시간 → 오검출 의심 통보).

**F8. 빠르게 통과하는 사람을 놓칠 수 있다 (디바운스×검출주기)**
- 위치: [config/tuning.yaml](config/tuning.yaml) zone.enter_s=1.0 + worker.fullset_fps=2
- 내용: 침입 확정에 1.0s 연속 구역 내 검출 = 2fps 에서 **3연속 검출**. 구역을 1.5초
  미만에 통과(뛰는 사람: 구역 폭 3m 를 2m/s)하면 확정 전에 이탈 → 무경보. 실측(m1)의
  "경계 스침 무발화"는 설계 의도지만 **구역이 좁으면 정상 통과도 스침이 된다.**
- 현장 시나리오: 지게차 동선을 가로질러 뛰어가는 작업자 — 가장 위험한 행동이 가장
  안 잡힌다.
- 수정 제안: 구역 폭을 통과시간 ≥2s 로 그리는 지침 명문화 + 설치 당일 "빠른 통과"
  실보행 시험. enter_s 하향은 오검출 트레이드오프(F7)와 함께 결정.

**F9. 시스템 다운을 외부에 알릴 수단이 없다 (무인 운영 전제와 충돌)**
- 위치: push 하트비트 코드 0건. /health 는 pull 전용.
- 현장 시나리오: PC 전원 사망·네트워크 단선 → "알림이 안 오는 것"과 "위험이 없는 것"
  을 담당자가 구분 못 함. 몇 주 뒤에야 발견.
- 수정 제안: ①일일 생존 신고 텔레그램("정상 가동, 카메라 N대 ok") ②기동/재기동 통보
  ③관제 있으면 /health 503 폴링. 최소 ①은 소규모.

**F10. GPU 폴백·성능 저하가 조용하다**
- 위치: guard._pick_device(기동 시 1회) + 지연 임계 경보 없음(stale 30s 만 존재)
- 현장 시나리오: 드라이버 업데이트 후 CUDA 실패 → CPU 폴백 → 검출 수백 ms 로 급증,
  그러나 30s 미만이면 healthy. 반응시간이 몇 배로 늘었는데 아무도 모름.
- 수정 제안: /health 에 추론 device 노출(확인 필요: 현재 미노출로 보임) + detect p95
  임계(예: 400ms) 초과 지속 시 degraded.

**F11. 야간·IR 성능 미측정** — 🟡 **하향(학원 파일럿 범위 밖 — 주간 실습)**
- 위치: [benchmarks/m2_night_person.md](benchmarks/m2_night_person.md) — 유인 야간·소등
  구간 미측정. IR 흑백 전환 시 person 재현율 데이터 0.
- 수정 제안: 현장 카메라가 IR 전환형이면 설치 첫 밤 실보행 시험 필수. 결과 전까지
  야간 무인 감시를 신뢰 대상으로 제시하지 않는다(규칙7).

**F12. PPE 미착용 놓침 — NO-Hardhat 재현율 36.1% (실측)**
- 위치: 모델 성능. [benchmarks/field_eval_results.md](benchmarks/field_eval_results.md).
  구조상 "판정 불가" 개념 없음 — NO-Hardhat 미검출이면 무경보(미검출 방향으로 실패).
- 현장 시나리오: 안전모 미착용 3명 중 2명 통과. 직하방 화각이면 물리적으로 더 악화.
- 수정 제안: 화각 요건 준수 + PPE 경보의 신뢰 등급을 침입·근접과 구분해 고지.
  재학습은 기존 로드맵 항목.

**F13. 크래시 시 릴레이가 켜진 채 고정될 수 있다**
- 위치: [relay.py:154-159](vigent-core/relay.py#L154) — 자동 OFF 는 프로세스 내
  threading.Timer. 프로세스가 죽으면 타이머도 죽는다. 재기동 경로에 OFF 송신 없음
  (main.py 예열 배선 전수 확인).
- 현장 시나리오: 사이렌 ON 직후 크래시 → NSSM 재시작 후에도 사이렌 계속 —
  "안 꺼지는 것이 최악"이라는 모듈 자신의 설계 원칙 위반.
- 수정 제안: 기동 시(main 예열) relay enabled 면 무조건 OFF 1회 송신.

### 🟡 중간

**F14. bypass(통보 끔) 이력이 안 남는다** — `alerts.notify:false`/`VIGENT_ALERT_NOTIFY=0`
는 파일·환경변수 수정이라 누가 언제 껐는지 기록 없음, 자동 복귀 없음. 상태를 /health
노출 + 기동 로그 명시 권장.
**F15. 등급 표기 불일치 "mid" vs "medium"** — worker 발화([worker.py:207](vigent-core/worker.py#L207)·398)
는 `mid`, 배선(vision.yaml·dispatcher 기본)은 `medium`. 현재 둘 다 log 전용이라 무해하나
향후 medium 에 원격을 배선해도 mid 이벤트는 안 나가는 지뢰. 통일 권장.
**F16. 데모 이벤트 주입 API 잔존** — `POST /safety/demo/seed`([safety_core.py:654](vigent-core/routers/safety_core.py#L654)).
토큰 뒤지만 현장 이벤트 로그에 가짜 사고를 섞을 수 있다. 운영 빌드 비활성 권장.
**F17. 학습용 수집이 원본(비식별화 없는) 프레임 저장** — [worker.py:769](vigent-core/worker.py#L769)
`VIGENT_COLLECT=1` 시 frame 그대로 imwrite. 기본 off 지만 켜는 순간 개인영상 원본 누적.
수집 경로에도 모자이크 적용 또는 명시 경고 필요.
**F18. 두 번째 사람 진입은 새 이벤트가 아니다** — 구역 상태기계가 카메라 단위
([worker.py:160](vigent-core/worker.py#L160)). A 확정 상태에서 B 진입 시 전이 없음 →
추가 경보·기록 없음. 인원수 변화 기록 검토.
**F19. 이벤트↔알림 연결 키 부재** — 이벤트(recognition JSONL)와 전송 결과
(alert_queue.db)에 상호 참조 ID 없음. 사고 조사 시 "이 이벤트가 통보됐는가"를 시각
대조로만 추적. event_id 전파 권장.
**F20. /health 무인증 공개 범위** — 내부 절대경로(rfdetr_slots.weights)·모델 구성·
카메라명 LAN 무인증 노출(백로그 B-expose 등재됨). 파일럿 수용, 상용 전 축소.
**F21. 증거 비암호화** — 개발 PC Home 한계 확인(T1). 현장 장비 **Pro 필수 + 설치 시
암호화 적용**(요건 문서화됨) — 체크리스트 포함.
**F22. 재시작 시 재로그인(세션 메모리 보관)** — 화면이 안내 없이 빈다(실측). 절차서
반영됨. 401 시 프론트 "재로그인 필요" 배너 권장.
**F23. 부팅 후 감시 공백 ~5분** — Delayed Auto(+284s)+예열. 설계지만 현장 고지 필요
(F9 기동 통보로 완화).
**F24. `fault_stop_detect` 결함 주입 코드 상존** — [worker.py:758](vigent-core/worker.py#L758)
B2 시험용(추론 스킵). 기본 false·API 전용이지만 운영 빌드 제거 또는 이중 안전 검토.

**F29. `test_relay` 가 전체 스위트에서 간헐 실패 — 게이트 신뢰도 훼손** — ✅ **수정 완료(2026-08-21)**
- 위치: [tests/test_relay.py](tests/test_relay.py) + [scripts/mock_relay.py:69](scripts/mock_relay.py#L69)
- 내용: 단독 실행은 **5/5 통과**인데 전체 스위트(378건)에서는 **4회 중 2회 실패**한다
  (`test_auto_off_after_duration` · `test_off_failure_sets_flag_and_surfaces` — 회차마다 다른 케이스).
  mock 릴레이가 **단일 스레드 `HTTPServer`**(`ThreadingHTTPServer` 아님)라 스위트 부하에서
  연결 처리가 밀리고, `down=True` 의 "응답 없이 끊기" 와 타이밍이 겹치면 판정이 흔들린다.
  `relay.py` 자체의 락·상태 관리에서는 경합을 찾지 못했다(코드 확인) — **제품 결함이 아니라
  테스트 인프라 문제로 판단**하나, `relay.py` 실물 검증이 없는 상태라 단정하지 않는다.
- 현장 시나리오: 직접적 현장 영향은 없다. 다만 **"4대 게이트 통과 후 커밋" 규칙이
  무의미해진다** — 실패가 절반 확률로 나오면 진짜 회귀와 flake 를 구분할 수 없고,
  결국 "또 그거겠지" 하고 넘기게 된다. 안전 제품에서 가장 위험한 습관이다.
- ✅ **적용된 수정**(원인이 둘이라 둘 다 고쳤다):
  ① `scripts/mock_relay.py` 를 **`ThreadingHTTPServer`** 로 교체(+`daemon_threads`). relay 는
     OFF 를 8회까지 재시도하는데 단일 스레드 서버가 그 연속 요청을 직렬 처리하며 밀렸다.
  ② `MockRelay.start()` 가 **실제 응답을 확인할 때까지 대기**한다(`/log` 폴링, 상한 3초).
     `serve_forever` 는 스레드 시작 직후 곧바로 수락 가능한 상태가 아니라 첫 요청이
     연결 거부로 실패할 수 있었다.
  ③ `test_auto_off_after_duration` 의 고정 `sleep(1.0)` 을 **조건 폴링(상한 5초)** 으로 바꿨다.
     '언제까지 되는가' 가 아니라 '되는가' 를 보는 테스트라 폴링이 맞다.
  검증: relay 단독 3회 + **전체 스위트(412건) 3회 연속 통과** — 수정 전에는 전체 실행
  4회 중 2회 실패했다.

**F30. `test_rfdetr_onnx_parity` 가 전체 스위트에서 1회 ERROR — 🔍 미확인, 재발 시 조사** 🟡 *(2026-08-21 추가)*
- 위치: [tests/test_rfdetr_onnx_parity.py](tests/test_rfdetr_onnx_parity.py)
- **관측된 사실만**(추측과 구분해 적는다):
  · 2026-08-21 전체 스위트 **6회 실행 중 1회** `ERROR` 발생
    (`test_torch_onnx_detection_parity`). 실패 유형은 FAIL 이 아니라 **예외**였다.
  · 같은 테스트 **단독 실행은 통과**(11.0초). 이후 전체 스위트 **3회 연속 전건 통과**.
  · 발생한 1회는 relay 반복 실행 등으로 **연속 전체 실행을 여러 번 한 뒤**였다.
  · ★**예외 본문을 확보하지 못했다** — 재현을 시도했으나 실패해 원인을 특정할 수 없다.
  · **2026-08-24 추가 관측**: 다시 1회 재발(누적 8회 중 2회). 재발한 실행은 **같은 셸에서
    GuardAgent 를 3회 적재해 RF-DETR 모델을 반복 로드한 직후**였다. 직후 2회 실행은 통과.
    이 정황은 GPU/메모리 압박 가설과 **어긋나지 않으나 여전히 증명은 아니다** —
    이번에도 traceback 확보에 실패했다(전체 출력을 파일로 남기며 반복 실행했으나 미재현).
  · **2026-08-25 3번째 재발**: 트래커 실험(GuardAgent 를 20회 이상 적재)한 직후 발생.
    **3회 재발이 모두 GPU 대량 사용 직후**라는 정황이 누적됐다(누적 15회 중 3회).
    직후 재실행은 또 통과해 이번에도 traceback 미확보 — **원인은 여전히 미확인**이나,
    재현 조건이 '무거운 GPU 작업 직후'로 좁혀졌다. 다음 재발 시 그 직후에 즉시
    `nvidia-smi` 와 함께 단독 실행하면 잡을 가능성이 높다.
- 🔍 **원인 미확인**: 이 테스트는 torch 와 ONNX 모델을 **동시에 올려** 출력을 대조한다.
  연속 실행 시 GPU 메모리가 제때 반환되지 않아 생긴 압박을 **의심**하나,
  **확인하지 못했다**(규칙7 — 그럴듯한 원인을 사실처럼 적지 않는다).
- 현장 시나리오: 직접적 현장 영향은 없다(측정·검증 전용 테스트). 다만 **F29 와 같은
  종류의 함정**이다 — 간헐 실패를 "flake 니까 괜찮다"로 넘기기 시작하면 게이트가
  경고 기능을 잃는다. F29 를 고친 직후이므로 같은 판단 실수를 반복하지 않기 위해 남긴다.
- 재발 시 조사 순서: ①예외 traceback 확보(전체 실행 로그 보존) ②`nvidia-smi` 로 실행 중
  VRAM 추이 관측 ③단독/전체 실행 간 차이가 메모리인지 순서인지 분리(테스트 격리 실행)
  ④메모리로 확인되면 테스트 tearDown 에서 모델 해제·`torch.cuda.empty_cache()` 검토.

### 🟢 낮음 (정리 권장)

**F25. ml/ 실험 스크립트 26개** — 서빙 참조는 `vlm_risk_summary` 1개뿐. `train_yoga.py`
는 [Z-3] 삭제된 sports 테마 잔재. 배포 패키지 제외 권장.
**F26. `except Exception: pass` 3건** — 전부 ml/(미사용 경로). 코어는 로그 동반 스타일.
TODO/FIXME 0건 · cv2.imshow/waitKey 0건(headless 안전) · print 잔재 없음 — 양호.
**F27. safety-pro 전역 구역 저장 API 잔존** — UI 는 비활성(W3-B), `POST /zone/danger`
API 는 열려 있음. F5 수정과 함께 재검토.
**F28. go2rtc 주소 `127.0.0.1:1984` 2곳 중복** — starvation_guard.py:54 ·
routers/cameras.py:27. 동일 호스트 고정이라 무해하나 상수화 권장.

---

## 4. 하드코딩 전체 표

> 원칙 확인: RTSP 계정·구역 좌표·임계값은 **코드 밖**(config/tuning.yaml·서버 저장·
> secrets 파일)에 있다. 아래는 코드에 남은 값 전부.

| 값 | 위치 | 종류 | 현장 튜닝 | 판정 |
|---|---|---|---|---|
| `HYSTERESIS_FRAMES {ppe:3, fire:2}` | agents/guard.py:259 | 발화 민감도 | **예** | 🔶 **config 분리 권장** — 유일한 실질 잔여 |
| `PREDICT_FAIL_DEGRADE_THRESHOLD=3` | agents/guard.py:249 | 장애 판정 | 아니오 | 상수 가능 |
| `DETECTOR_CONF {person:.35 …}` | agents/guard.py:225 | 임계 폴백 기본값 | 예 | ✅ tuning.yaml `detect.conf` 가 우선 — 유지 가능 |
| `_nms(iou_thr=0.55)` · `CONTAIN_RATIO=0.70` | agents/guard.py:156·244 | 후처리 | 드묾 | 상수 가능(실측 근거 주석) |
| ByteTrack activation | agents/guard.py:301 | 추적 | 예 | ✅ `track.bytetrack_activation` tuning 연동 |
| 쿨다운15s·증거30s·hang15s·재연결5s·읽기실패5회·버퍼1 | worker.py:44-67 | 안정성 | 예 | ✅ 전부 tuning/env 연동 확인 |
| 침입1.0s·근접0.4s·반경3m·운전자0.65·억제300s 등 | config/tuning.yaml | 안전 판정 | **예** | ✅ config — 무코드 변경(★재시작 필요) |
| 구역 폴리곤 | 서버 저장(카메라별) + config/danger_zone.json 폴백 | 구역 | **예** | ✅ /safety-hub UI 로 무코드 변경. ⚠폴백 파일은 F5 |
| RTSP 계정 | data/camera_secrets.json (`data/` gitignore 확인) | 자격증명 | 예 | ✅ 코드 밖. 평문은 F21 로 보완 |
| 알림 토큰 | config/notify.yaml (gitignore 확인) | 자격증명 | 예 | ✅ 코드 밖 + **무재시작 반영** |
| 릴레이 주소·시간 | config/tuning.yaml `relay.*` | 출력 | 예 | ✅ config(기본 비활성) |
| 모델 경로·클래스 | themes/safety/vision.yaml + 모델 내장 names | 모델 | 예 | ✅ 설정 주입(클래스 하드코딩 없음 — yolo 는 model.names, rfdetr 은 체크포인트 메타) |
| go2rtc `127.0.0.1:1984` | starvation_guard.py:54 · cameras.py:27 | 내부 포트 | 아니오 | 상수화 권장(F28) |
| 앱 포트 8010 | deploy/windows/install_service.ps1 | 배포 | 드묾 | 배포 스크립트 변수 — 유지 |
| 로그 회전 10MB×5/×10 | vlog.py:43·67 | 로그 | 아니오 | 상수 가능 |
| `D:/vigent_tmp` 등 절대경로 | benchmarks/·scripts/ 한정 | 개발 전용 | — | 서빙 경로 절대경로 0건 확인 — 무해 |

**요약**: 현장 튜닝 대상은 전부 무코드 변경 가능. 단 **tuning.yaml 은 재시작 필요 /
notify.yaml 은 즉시 반영**이라는 비대칭이 현장 혼동 포인트(절차서에 명시됨).

---

## 5. 테스트/디버그 잔재 점검

| 항목 | 결과 |
|---|---|
| 알람 출력 임시 차단(SEND_ALARM=False 류) | **없음** — `alerts.notify` 기본 true, NSSM 환경변수에 차단값 없음(실환경 확인) |
| 판정 강제 무시 | 없음. 단 `fault_stop_detect` 시험용 주입 코드 상존(F24, 기본 off) |
| cv2.imshow/waitKey | 0건 |
| 테스트 영상 파일 카메라 | 기능(파일 소스 지원). 연습 카메라 삭제 확인 — 설치 당일 실카메라만 있는지 확인 항목화 |
| print/TODO/FIXME | 0건(코어), vlog 일원화 |
| 데모 시드 API | 잔존(F16) |
| 미사용 실험 스크립트 | ml/ 26개(F25) |

## 6. 성능·지연 (실측)

| 구간 | 값 |
|---|---|
| 위험 발생 → 증거·기록 | 침입 **1.31s** / 근접 0.81s (중앙, 최악 1.57/1.07) |
| → 담당자 폰 도착 | 침입 **2.72s** / 근접 2.22s (텔레그램 왕복 1.42s 포함) |
| 프레임 신선도 | p50 0.3s / p95 0.6s — 최신 슬롯 방식으로 큐 밀림 구조 차단 |
| 카메라 수용 | 한계 7대·권장 5대(GPU 1대 기준), 병목=CPU |
| 이벤트 저장 | 인코딩 55ms — 캐던스(500ms) 내. 통보는 비동기(느린 채널 무영향, 테스트 고정) |
| ⚠요구 반응시간 | **미정의** — 확인 필요① |

## 7. 증적

**남는 것**: 시각(KST)·카메라·규칙·등급·비고·증거경로(JSONL, 10MB 회전) / 전송 시각·
상태·재시도(alert_queue.db) / 기동·재시작·hang·재연결(vigent.log) / 얼굴 모자이크
(P1a 경합 결함 수정, 라이브 실패 0건 확인) / 보존정책(30일/3년, 구현 완료·첫 삭제 승인 대기).
**빠지는 것**: 알람 해제 시각(해제 개념 부재) · bypass 이력(F14) · 이벤트↔알림 키(F19) ·
검출 스코어의 이벤트 단위 기록.

---

## 8. 현장 설치 당일 체크리스트

### A. 설치 전(사무실)
1. [ ] **프로파일 적용** — 현장용 tuning/vision 덮어쓰기 → 재시작 → `/health` `backend`
   로 슬롯 구성 확인(학원이면 `forklift: yolo`) — 빠뜨리면 지게차 미검출+화재 오탐(실측)
2. [ ] `config/danger_zone.json` **비우기**(F5 — 개발 좌표 잔존 금지)
3. [ ] retention 스케줄 등록 + 수동 1회 실행 확인(F6)
4. [ ] 디스크 잔량 확인(증거 하루 예상량 × 보존 30일 + 여유)
5. [ ] Windows **Pro** 확인 → 증거 폴더 암호화(F21)
6. [ ] 시간 동기(NTP) — 관제·NVR 와 일치
7. [ ] 노트북 리허설 표(academy_visit_day 부록 D) 전 항목 재작성

### B. 현장 연결
8. [ ] 카메라 등록 → `/health` ok · frame_age < 2s
9. [ ] `/cameras` 에 **실카메라만**(시험용 파일 카메라 잔존 금지)
10. [ ] 화각: 감시 지점 사람 박스 높이 ≥ 화면 10%
11. [ ] ★**사람 없이 5분 관찰** — person 오검출 자리 확인(F7), 그 자리 피해 구역 설계
12. [ ] 구역 그리기(/safety-hub 카메라별) → `GET /cameras/{id}/zone` count ≥ 3
13. [ ] 구역 폭 = 예상 동선 통과시간 ≥ 2초(F8)
14. [ ] 알림 설정 → 테스트 발송 → 폰 도달

### C. ★실동작 시험 (전부 실제로 — 이것이 설치 완료의 정의)
15. [ ] **걸어 들어가기**: 밖→안 2초 체류 → 폰 알림 ≤3초
16. [ ] **빠른 통과**: 뛰어서 통과 → 잡히는지 확인(13번 충족 검증)
17. [ ] **연속 진입 억제**: 5분 내 재진입 → 억제 + 다음 알림 "N건 억제됨" 확인
18. [ ] **랜선 뽑기**: 30s 내 /health 상태 변화(503) → 재연결 → 자동 복구
19. [ ] **강제 재시작**: 자동 기동 → 재로그인 → 카메라·구역 유지 확인
20. [ ] 릴레이 현장: critical 시험으로 ON/자동 OFF + **침입(high)은 사이렌이 안 울림을
   현장에 명시 고지**(F4 결정 전까지)
21. [ ] 야간 운영 현장: 첫 밤 실보행 시험 예약(F11)
22. [ ] ⚠**한계 고지**: 프리즈(F3)·person 슬롯 단독 사망(F1)은 현재 감지 불가 —
   수정 전까지 주 1회 육안 스냅샷 대조를 운영 절차로

### D. 철수 전
23. [ ] 당일 로그·증거 백업, 시험 이벤트와 실이벤트 구분 기록
24. [ ] 계정·토큰 보관 상태 점검(평문 파일 위치 고지)
25. [ ] 인수인계 3가지: 재시작→재로그인 / tuning 변경→재시작 필요 / 알림 안 올 때
   /health 확인 순서

---

## 결론

**설치 전 수정 권고(🔴 4건)**: F1(슬롯 사망 미노출) · F2(디스크 풀=통보 사망) ·
F3(프리즈 미감지) · F4(주요 위험 물리출력 — 정책 결정). 공통점은 **"조용히 실패"** —
이 시스템이 지금까지 잘 잡아온 실패 모드(카메라 끊김·모델 미로드·경보 유실·워커 hang)
의 사각지대에 정확히 남아 있는 것들이다.

**오탐 관점 1순위**: F7(정지 물체 오검출) — 기술 수정 전까지는 구역 설계 규율
(체크리스트 11번)이 유일한 방어.

수정 지시 시 항목별 진행: F1·F2·F13·F14 소규모 / F3·F9 중규모(임계 튜닝 동반) /
F4 는 코드보다 정책 결정.
