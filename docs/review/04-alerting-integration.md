# Phase 4 검토 — 알람 · 연동 · 현장 액션

> 검토일 2026-09-08 · 브랜치 `audit/cleanup-20260906`(HEAD `d4517fc`) · **코드 수정 0 · 서버 기동 0 · 실제 통보 0**.
> 근거는 전부 `파일:줄` 또는 읽기 전용 명령 출력이다. 읽지 않은 것은 "확인 필요"로 표기했다.
> 심각도: **P0** 안전사고 직결 / **P1** 신뢰성·데이터 유실 / **P2** 경쟁 열위 / **P3** 품질.

---

## 0. 한 줄 결론

통보 파이프라인 자체(게이트 → 비동기 큐 → sqlite 선기록 → 재시도 → 데드레터 → /health)는 **설계·테스트 밀도가 높다**(관련 테스트 88건: `tests/test_alert_wiring.py` 29 · `test_alert_queue.py` 15 · `test_alert_delivery_hardening.py` 10 · `test_relay.py` 10 외). 그러나 **현장에서 사람에게 닿는 채널은 텔레그램 1개뿐**이고, 그 1개가 **지금 이 순간 HTTP 401로 죽어 있다**(오늘 21:22~21:35 발생한 critical/high 26건 전부 dead — `data/alert_queue.db` 실측). 현장 내 가청·가시 경보(사이렌·경광등·관제 PC 소리)는 **기본 비활성 + 실물 미보유**, PLC/설비 정지 연동은 **없음**, 전후 클립·오탐 워크플로우·에스컬레이션·교대 수신자·CSV/PDF 내보내기도 **없음**이다.

---

## 1. 알람 채널 매트릭스

| 채널 | 상태 | 근거 | 실패 시 대체 경로 | 재시도 | 데드레터 | "미설정" 표시 |
|---|---|---|---|---|---|---|
| **텔레그램** | **있음** | `agents/dispatcher.py:157-170` `sendMessage`(텍스트만, 4000자 절단) | 없음 — 이메일·웹훅이 함께 시도되나 **현재 둘 다 미설정**(§1-1) | `alert_queue.py:133-156` 지수 백오프 1→60s·10회 · 4xx는 즉시 dead(`:158-168`) · 429 Retry-After(`dispatcher.py:114-120`) | `alert_queue.py:143-145` + 1h 1회 요약 통보(`:181-207`) | `/health alerts.channels_configured`(`routers/system.py:181`) · `warnings[channels_not_configured]`(`health_status.py:117-118`) |
| **이메일(SMTP)** | **있음(코드)** / 미설정(운영) | `dispatcher.py:172-192` starttls·login | 동일 | 동일 | 동일 | 동일 |
| **웹훅(HTTP POST)** | **있음(코드)** / 미설정(운영) | `dispatcher.py:194-204` JSON `{level,message,meta}` | 동일 | 동일 | 동일 | 동일 + 목적지 화이트리스트(`routers/dispatch.py:25-28`) |
| **현장 경광등/사이렌(릴레이)** | **부분** — HTTP GET/POST 1채널, **기본 비활성**, 실물 미보유(mock만) | `relay.py:7-8, 70-82` · `config/tuning.yaml:281-292` `enabled: false` · `deploy/SITE_CHECKLIST.md:186-187` "실물 릴레이 미보유 → mock 서버로만 검증" | 없음(ON 실패는 로그 + `last_error`) | ON 3회/OFF 8회(`relay.py:105-138`) | 없음(물리 채널은 큐 비대상 — `alert_queue.py:273-284`) | `/health relay.enabled/off_failed`(`system.py:208`) |
| **관제 대시보드(/hub)** | **부분** — 이벤트 표·배지·미전송 배너만, **소리 없음·확인(ack) 버튼 없음** | `themes/safety/index_hub.html:612` `/safety/auto/feed` 폴링 · `:217-229` 미전송/실패 배너 · 오디오 API 사용 0(`grep AudioContext\|new Audio` → 0건, 유일한 `v.play()`는 영상 음소거 재생 `:402`) | — | — | — | 배너는 `pending/dead`만(`:218`), `channels_configured`·`last_config_error`는 **표시 안 함** |
| **자동처리 콘솔(/safety/auto)** | **있음** — 승인·조치확인·📌보존 | `templates/auto.html:47-53, 78-97` | — | — | — | — |
| **브라우저 시연 페이지 비프** | 있음(시연 전용) | `static/realtime_core.js:1770-1773, 1908` `dzBeep` — `/safety`·`/safety-local` 만, 운영 `/hub`에는 없음 | — | — | — | — |
| **모바일 푸시(FCM/APNs)** | **없음** | `grep -riE "fcm|push_notif|apns|webpush"` → 코드 0건(테스트 파일명 2건만 매칭) | — | — | — | — |
| **SMS / 카카오 알림톡** | **없음** | `grep -riE "sms|kakao|카카오|알림톡"` → 코드 0건 | — | — | — | — |
| **Windows 토스트/관제 PC 스피커** | **없음** | `grep -rn "winsound|Beep("` → 0건 · 이벤트 로그 쓰기는 **기동 실패 전용**(`main.py:355-360`) | — | — | — | — |

### 1-1. ★현재 운영 상태 실측(읽기 전용)

- `config/notify.yaml` 비어 있지 않은 키: `telegram_token`·`telegram_chat`·`smtp_port`(기본 587) — **이메일·웹훅은 비어 있음**(값은 출력하지 않음).
- `data/alert_queue.db`(읽기 전용 조회): `dead 76 · sent 37 · pending 0`. 감사(09-06) 시점 dead 50 → **오늘 +26**. 26건 전부 `created 2026-09-08 21:22:59~21:35:35`, `last_error = config_error … telegram status 401`, 이메일 `SMTP 미설정`, 웹훅 `미설정`.
  - 내용: `[파일럿모의1~5] 화재/연기 감지`(critical 9) · `보호구 미착용`(high) · `작업반경 침입`(high) · `장시간 무동작 — 쓰러짐·실신 의심`(high) · **그리고 `[시스템] 경보 전송 실패로 폐기(데드레터)` 요약 통보(id 93)까지 401로 dead**.
  - 발원: `scripts/pilot_load_test.py`(카메라명 `파일럿모의`) 부하 시험 — **실제 사고는 아니다.** 그러나 같은 시각 서버 로그 `logs/vigent*.log` 에 `★통보 설정 오류(telegram HTTP 401) — 재시도하지 않는다` 가 반복된다. 즉 **지금 실카메라를 붙이면 화재 경보가 아무에게도 가지 않는다.**
- 오늘 인식 로그 `data/recognition/events_20260908.jsonl` 297행(증거 JPEG 189장): ppe_missing/high 155 · fire_smoke/critical 64 · rapid_motion/mid 35 · proximity_hazard/high 34 · immobility/high 5 · crowd_density/mid 4. 기록 경로는 정상 동작했다(기록과 통보의 분리 설계 `alert_gate.py:8-10`는 실측으로 확인).

### 1-2. 게이트·큐 동작 확인(코드 근거)

- 게이트: 카메라+규칙 단위 쿨다운 300s → 2배 백오프 → 상한 3600s, 시간당 6건, 등급 상승 예외, edge(센서 전이) 예외, 억제 요약 문구(`alert_gate.py:83-138`). 현장 실측 270 판정 → 폰 19건, 전송 19/19, 중앙값 1.8s(`benchmarks/field_academy_2026-08-27.md §6`).
- 비동기: 워커는 `submit()`만(`worker.py:1125-1128`), 전송은 단일 데몬 스레드(`alert_notify.py:49-72`), 큐 200 초과 시 최고령 폐기 + WARNING + `/health alerts.dropped`(`alert_notify.py:134-149`).
- 선기록 후전송: `dispatcher.dispatch()` → `alert_queue.enqueue` → `_dispatch_now` → `mark_sent/mark_failed`(`dispatcher.py:206-239`). 재시도는 `remote_only=True`로 relay·log 제외(`main.py:524-526`, `dispatcher.py:258-291`).
- 채널 미설정 시 큐 미적재 + `undeliverable_count` 집계(`dispatcher.py:214-222`) — 단 이 카운터는 **프로세스 메모리**(`dispatcher.py:99`) → 재기동 시 0으로 초기화되어 `/health degraded` 근거가 사라진다.
- 발송 성공(sent)한 critical/high는 증거 JPEG·그날 jsonl 자동 pin(`alert_queue.py:103-130`).

---

## 2. 산업 설비 연동 매트릭스

| 연동 | 상태 | 근거 | 비고 |
|---|---|---|---|
| **PLC — Modbus TCP** | **없음** | `grep -riE "modbus|pymodbus"` → `relay.py:7` 주석("HTTP 또는 Modbus TCP")과 `SITE_CHECKLIST.md:171`에만 등장, **구현 0** · `requirements*.txt`·`constraints.txt`에 modbus/opcua/snap7/cpppo/mqtt 라이브러리 **0** | 문서가 "Modbus TCP 지원"처럼 읽힐 수 있음(§5 P3-4) |
| **PLC — OPC-UA** | **없음** | 동일 grep 0건 | |
| **PLC — EtherNet/IP** | **없음** | 동일 grep 0건 | |
| **MQTT / 산업 IoT 브로커** | **없음** | `paho|mqtt` 0건 | 센서는 HTTP POST 수신만(`routers/safety_core.py:508-559`) |
| **릴레이 출력(GPIO/IO 모듈)** | **부분** — 네트워크 HTTP 릴레이 1채널만. GPIO·시리얼 **의도적으로 미구현** | `relay.py:7-8` "GPIO·시리얼은 만들지 않는다" · `_http()` `urllib.request.urlopen(GET/POST)`(`relay.py:70-82`) | 다채널·펄스·인증 헤더 없음 |
| **설비 정지 인터록** | **없음(의도적)** | `dispatcher.py:10-11, 292-302` `safety_relay_signal`은 "보조 신호"; `press_zone.py:3-5` "E-stop을 대신하지 않는다" | §8.1 경계 — 아래 2-2 |
| **fail-safe 기본 상태** | **부분** | ON 후 `on_duration_s`(30s) 자동 OFF 타이머(`relay.py:153-158`) · OFF는 ON보다 강하게 재시도(8회/8s vs 3회/5s, `:130-138`) · OFF 최종 실패 `off_failed` → `/health degraded`(`system.py:193-194`) | **기동·종료 시 OFF 송신 없음**(`grep relay vigent-core/main.py` → import·호출 0, `_shutdown()` `main.py:419-442`에 relay 없음) — 이미 알려진 부채 **F13**(`docs/onboarding/05_알려진_부채_전량.md:16` "미해결") |
| **릴레이 상태 조회(read-back)** | **없음** | `relay.status()`는 메모리 `_state`만 반환(`relay.py:161-175`) — 하드웨어에 상태를 묻는 경로 0 | 실제 접점이 ON인지 알 수 없다 |
| **워치독/하트비트(장비 측)** | **없음** | 릴레이에 주기 신호 0 — VIGENT가 죽어도 장비는 모른다 | |

### 2-1. 실물 릴레이 프로토콜 — 답
**HTTP GET/POST 뿐이다**(`relay.py:70-82`, URL에 `?state=on|off` 부착 또는 `on_url/off_url`). GPIO 없음, Modbus 없음, 시리얼 없음. 실물은 없고 `scripts/mock_relay.py`로 10 시나리오만 통과(`SITE_CHECKLIST.md:186-187`).

### 2-2. 인터록으로 쓰일 때의 경계 문구(§8.1) — 있음
- API 응답에 고정 삽입: `routers/dispatch.py:40-41` `is_primary_safety: False`, `boundary: "§8.1 — 비전은 보조·감시 계층. 1차 정지는 인증 하드웨어 책임."`
- 코드 주석·docstring: `dispatcher.py:10-11, 309-310` · `relay.py:16-17` · `press_zone.py:3-5` · `rig_monitor.py:28`
- UI: `hub.py:70` 푸터 · `templates/auto.html:31-32` · `index_vigent.html:134`(단, 이 파일은 어느 라우트도 서빙하지 않음 — §5 P3-3)
- 문서: `docs/PRIVACY_POLICY_DRAFT.md:14, 21` · `SITE_CHECKLIST.md:183`
- 평가: 경계 문구는 **충분히 일관**된다. 대신 그 결과로 **"정지시킬 수 있는 것이 아무것도 없다"**가 제품 사실이다 — 경쟁 대비 격차로 명시(§6).

---

## 3. 알람 이력 · 보고 기능 매트릭스

| 기능 | 상태 | 근거 |
|---|---|---|
| 스냅샷(증거 JPEG 1장) | **있음** | `data_engine.py:52-72` `data/evidence/<날짜>/ev_*.jpg` · 워커는 규칙별 증거 쿨다운(`worker.py:1113-1116`) · 얼굴 모자이크 적용(`privacy.py:1-20`, 실패 시 `privacy_failed` 꼬리표 `data_engine.py:172-173`) |
| 브라우저 오버레이 분리 저장 | 있음 | `data_engine.py:134-149` `*_overlay.png` |
| **이벤트 전후 클립(pre/post-roll)** | **없음** | `grep -riE "pre_roll|preroll|post_roll|VideoWriter"` → 제품 코드 0 · `scripts/rtsp_recorder.py`는 **수동 원본 녹화 도구**(`:1-16`, 10분 단위 상시 녹화, 이벤트 연동 없음) |
| 메타데이터 | **부분** | 레코드 `{ts,date,time,rule,level,score,site,note,evidence,privacy_failed?,source?}`(`data_engine.py:166-175`) — **id 없음·camera 필드 없음(site에 카메라명 대입 `worker.py:1117`)·track id 없음·bbox 없음·확인자/상태 없음** |
| 목록 조회 | 부분 | `GET /recognition/log?limit&hours`(`routers/recognition.py:46-49`) — 규칙·등급·카메라·기간(from/to) 필터 **없음** · 매 호출 전 jsonl 파일 전량 파싱(`data_engine.py:191-211`) |
| 검색 | 부분 | `/evidence/search`(`safety_core.py:95`) — 본문 미확인, **확인 필요** |
| **내보내기 CSV** | **없음** | `routers/recognition.py:7` docstring은 "CSV"라 쓰지만 구현은 **JSONL**(`:51-56`, `application/x-ndjson`) |
| 내보내기 Excel/PDF | **없음** | `openpyxl|reportlab|weasyprint` 제품 코드 0건(`scripts/build_*`·`rig_replay.py`는 벤치 도구) |
| 사고 기록(incident) | **다름** | `routers/incident.py`·`incident.py`는 **사고 사진 사후 원인분석(VLM)** 이지 실시간 경보의 사고 기록부가 아니다(`incident.py:1-9`) — "사고 케이스 파일" 개념 없음 |
| 확인(ack) | **부분** | `POST /safety/auto/approve action=acknowledge` → `audit_store.record`(`safety_core.py:267-297`, `audit_store.py:21-40`) · 콘솔 버튼 "조치 확인"(`auto.html:50`) · **매칭 키가 (ts, rule)만**(`audit_store.py:62-64`) → 같은 초·같은 규칙·다른 카메라 이벤트를 **한꺼번에 승인 처리**(§5 P1-4) · 승인자 자유 입력(기본 "안전관리자") |
| 📌 보존 pin | **있음** | `routers/recognition.py:63-89` 경로 검증 · `data_engine.py:121-131` · 자동 pin은 **sent된 critical/high만**(`alert_queue.py:106-128`) |
| 보존 기간 | 있음 | 증거·인식로그 30일, 감사·TBM·평가서 3년(`config/tuning.yaml:159-163`) · 서버 내 자동 스윕(`retention_scheduler.py`) · 큐 sent/dead 30일 prune(`retention.py:347`) |
| 감사추적 | 있음 | `data/audit/audit_*.jsonl` · `/safety/auto/audit`(`safety_core.py:299-319`) |
| 관리자 통계 | **부분** | `dashboard.py:39-83` 총계·당월/전월·규칙별·현장별(site)·등급별·14일 추이 · TBM/평가서/승인 수 · **시간대별 없음(`grep hour|시간대` 0)·카메라별 없음·보호구 착용률 없음(분모 없음, ppe_missing 건수만)·기간 선택 없음·내보내기 없음** |
| 자동 보고서(일보·주간) | **없음** | `grep -iE "daily|weekly|schedule"` scribe/safety_manager/analyst 0건 — 위험성평가서는 **사람이 버튼**으로 생성(`/report/safety`, `/safety/auto/approve risk_assessment`) · LLM은 opt-in이고 결정적 폴백 있음(`agents/scribe.py:353-392`, `llm_provider.py:1-15`) |
| TBM | 있음 | `routers/tbm.py:30-113` 6 라우트, `tbm_store.py` — 알람과의 연결은 없음(**확인 필요**: TBM 작성 시 당일 경보 자동 인용 여부는 미확인) |
| **오탐 표시 → 통계 → 재학습 축적** | **없음** | `grep -riE "false_positive|오탐 표시|verdict|feedback"` → 제품 코드에서 `vlm_confirm.py`(VLM 자동 억제 verdict)·`analyst.py`만, **사용자 오탐 표시 UI/API 0** · `vigent-core/ml/merge_retrain_data.py`는 Roboflow 데이터셋 병합(`:1-7`)이지 현장 피드백 축적 경로가 아님 · 인식 로그에 상태 필드 없어 오탐률 산출 불가 |
| 에스컬레이션(미확인 시 상위 통보) | **없음** | `grep -riE "escalat|에스컬레이션"` → `starvation_guard.py`(검출 기아 대응)·`alert_gate.py`(등급 상승)만 — 사람 미확인 → 상위자 통보 경로 0 |
| 교대·시간대별 수신자 | **없음** | `grep -riE "shift|교대|근무|recipient|수신자"` config·setup_console 0건 · `notify_cfg()`는 단일 chat/단일 email_to(`dispatcher.py:53-62`) · `notify.example.yaml:5-8`의 `sites:` 현장별 chat_id 구조는 **dispatcher가 읽지 않는 스키마**(§5 P2-1) |

---

## 4. 브라우저 이중 통보(M8-1)·미구현 경로(M8-2) 확인

- M8-1: `/zone/intrusion`은 `cam` 필수 + 워커 소유 카메라면 기록만·통보 위임(`routers/zone.py:116-130`, `gate="worker_owned"`) — CODE_REVIEW 8-4 `51b188d` 반영 확인.
- M8-2: `UNIMPLEMENTED_SERVER_PATHS` 9경로 호출 차단(`realtime_core.js:1836-1844`) · `/zone/state` "E-stop 보조정지" 문구 제거 확인. 남은 스텁: `GET /alerts/status`가 항상 `{"ok":true,"alerts":[]}`(`safety_core.py:785-787`) — 호출부 grep 0이나 OpenAPI에 남아 있어 외부 연동자가 오해할 수 있음(P3).

---

## 5. 이슈 목록

| # | 심각도 | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|---|
| **P0-1** | **P0** | **사람에게 닿는 채널이 텔레그램 1개뿐이고, 그 채널이 지금 401로 죽어 있다 — 데드레터 요약 통보까지 같은 채널로 죽는다** | `data/alert_queue.db` 오늘 dead 26/26 `telegram 401`(id 88~113, 요약 통보 id 93 포함) · `notify.yaml` 이메일·웹훅 비어 있음 · `alert_queue.py:181-187` 요약 통보가 `alert_notify.submit` → 같은 dispatcher · 기동 시 채널 자가시험 없음(`main.py` 에 `getMe`/시험 발송 0) · `/hub` 배너는 `channels_configured`·`last_config_error`를 그리지 않음(`index_hub.html:217-229`) | 실카메라 운용 시 **화재·쓰러짐 경보가 아무에게도 가지 않는다.** 운영자는 `/health` JSON을 직접 열어야만 안다 | ① 즉시: 토큰 재발급·`/alerts/test`로 검증 후 이메일 또는 웹훅을 **2번째 채널로 반드시 설정**(현장 체크리스트 필수 항목화) ② 기동 시 텔레그램 `getMe`(토큰 검증, 메시지 미발송) + 실패 시 STARTUP_WARNINGS·Windows 이벤트 로그(이미 `_write_windows_event` 존재 `main.py:355`) ③ 데드레터 요약은 **원격 채널이 아닌 로컬 채널**(관제 PC 이벤트 로그·화면 배너·비프)로도 ④ `/hub`에 `channels_configured=false`·`last_config_error` 붉은 배너 | S(①②④) / M(③) |
| **P1-1** | P1 | **크래시 시 사이렌이 켜진 채 고정(F13) — 기동·종료 시 OFF 송신 없음, 하드웨어 상태 read-back 없음** | `relay.py:153-158` 자동 OFF가 프로세스 내 `threading.Timer` · `main.py:419-442 _shutdown()` relay 없음 · `grep relay main.py` 호출 0 · `relay.status()` 메모리만(`relay.py:161-175`) · `docs/onboarding/05_알려진_부채_전량.md:16` "미해결" | 사이렌 무한 ON → 소음 민원·**경보 무시 학습**(알람 피로) — 다음 진짜 경보가 무시된다 | 기동 직후·`_shutdown()`에서 `relay.enabled`면 무조건 OFF 1회 + 결과를 `/health relay.startup_off` 에 기록. 장비가 자체 타이머(펄스 모드)를 지원하는지 조달 사양에 명시(확인 질문 Q3) | S |
| **P1-2** | P1 | **릴레이 재시도가 통보 스레드를 최대 ~87초 정지시킨다** | `relay.turn_off()`는 `_lock` 을 잡은 채 8회×8s 타임아웃 + 백오프 sleep(1+2+4+4+4+4+4)=**≈87s**(`relay.py:130-138, 85-95`) · `turn_on()`도 같은 락(`:105-127`, ≈18s) · `turn_on`은 `_dispatch_now` 안에서 **동기 호출**(`dispatcher.py:296-299`) → 단일 통보 스레드(`alert_notify.py:49-72`)가 그 시간 동안 텔레그램을 못 보낸다 | 릴레이 장애 시 다음 critical 통보가 1분 이상 지연 — M4-6(채널 3개 순차 20s)보다 큰 정지 | relay 호출을 별도 스레드/큐로 분리하거나 `_lock` 을 HTTP 호출 밖으로. 최소한 `off_attempts×off_timeout` 합을 통보 SLA 이하로 제한 | M |
| **P1-3** | P1 | **critical 증거가 30일 뒤 지워질 수 있다 — 자동 pin은 "발송 성공"한 건만** | `alert_queue._auto_pin_sent` 는 `mark_sent` 에서만(`alert_queue.py:95-128`) · 채널 미설정/401(현재 상태)이면 sent 없음 → pin 0 · high/critical 이라도 게이트 억제분·mid 등급(rapid_motion·crowd)은 대상 아님 · 증거·인식로그 30일(`tuning.yaml:159-160`) | 사고 후 30일 넘어 조사·소송 시 **증거 없음**. 산안법 기록 보존(3년, `tuning.yaml:161` 근거로 자체 명시)과 불일치 | 자동 pin 기준을 "발송"이 아니라 **등급(critical/high) 발생**으로 · 사람이 `acknowledge` 한 이벤트는 자동 pin · 인식 로그(jsonl)는 증거와 분리해 3년 보존 검토 | S |
| **P1-4** | P1 | **확인(ack) 키가 (ts, rule)뿐 — 같은 초에 다른 카메라에서 난 같은 규칙이 한꺼번에 "승인됨"** | `audit_store.event_key()` `audit_store.py:62-64` · 피드 매칭 `safety_core.py:247` · 이벤트에 id 없음(`data_engine.py:166-171`) · 오늘 로그에서 `파일럿모의3` 21:23:14/15 처럼 1초 내 다카메라 발화 실측 | 감사추적("누가 무엇을 승인했나")의 **증명력 붕괴** — 실제로는 확인 안 한 카메라의 위험이 "조치 확인"으로 표시 | 이벤트에 `id`(uuid 또는 `ts|site|rule|seq`) 부여, ack·pin·평가서 모두 id 참조. 기존 로그는 site 포함 복합키로 이행 | S |
| **P1-5** | P1 | **현장 안에서 들리는·보이는 경보가 실질적으로 없다** | 릴레이 `enabled:false` 기본 + 실물 없음(§2) · `/hub` 무음(§1) · 관제 PC 로컬 알림 0(`winsound|Beep` 0) · 비프는 시연 페이지에만(`realtime_core.js:1770`) | 위험구역에 들어간 **작업자 본인**과 관제석 담당자가 폰을 안 보면 아무것도 모른다. "현장 액션" 관점에서 폰 통보는 2차 수단 | ① `/hub` 에 critical/high 신규 이벤트 시 오디오 경보(브라우저 자동재생 정책 → 첫 클릭 후 활성) + 화면 점멸 + 미확인 카운터 ② 릴레이 실물 조달·현장 시험을 파일럿 필수 항목으로 격상(SITE_CHECKLIST N-3은 "쓰는 현장만") | S(①) / M(②) |
| P2-1 | P2 | `config/notify.example.yaml` 스키마가 dispatcher와 다르다 | 예시는 `telegram: {bot_token, default, sites:{…}}`(`notify.example.yaml:2-8`) · dispatcher는 평면 키 `telegram_token/telegram_chat`(`dispatcher.py:53-62`) · 설정 콘솔도 평면 키(`setup_console.py:65-75`) | 예시를 복사한 현장은 **채널 미설정** 상태로 기동(경고만, 통보 0) — 현장별 수신자(`sites`)라는 **약속된 기능이 없음** | 예시를 평면 키로 교체하거나, 현장별·교대별 수신자 구조를 실제 구현 | S |
| P2-2 | P2 | 모바일 푸시·SMS·카카오 알림톡 없음 | §1 grep 0 | 국내 현장 관리자 수신 관행(카카오/문자)과 불일치 · 텔레그램은 설치·가입 장벽 | 웹훅을 이용해 알림톡 게이트웨이(예: 상용 API) 연동 어댑터 1개 추가, 또는 이메일→SMS 게이트웨이 | M |
| P2-3 | P2 | PLC/설비 연동(Modbus TCP·OPC-UA·EtherNet/IP) 전무 | §2 | 프레스·컨베이어 현장의 "감지→감속/정지 요청" 요구를 못 받는다. 경계(§8.1)를 지키면서도 **보조 신호를 PLC 입력 접점으로 주는 것**은 가능 | `pymodbus` 클라이언트로 코일 1개 쓰기(보조 신호) 어댑터 + 동일 fail-safe 규칙(기동/종료 OFF·read-back 코일 확인). §8.1 문구 유지 | M |
| P2-4 | P2 | 이벤트 전후 클립 없음 | §3 | 경쟁 제품은 대개 pre/post-roll 클립을 알람에 첨부 — 조사·교육·오탐 판정에 필수 | go2rtc 이미 있음 → 워커 프레임 링버퍼(예: 10s) + 발화 시 mp4 저장(별도 스레드, DETECT_LOCK 밖) | M |
| P2-5 | P2 | 오탐 표시 → 통계 → 재학습 축적 경로 없음 | §3 | 규칙 7·9의 재현율 재측정을 **현장 데이터로 못 한다** · 안전관리자가 오탐을 걸러 줄 수단 0 | 이벤트 id + `POST /recognition/verdict {id, verdict: tp|fp, note}` + 대시보드 오탐률 + `data/feedback/`로 증거·라벨 복사(재학습 큐) | M |
| P2-6 | P2 | 에스컬레이션·교대 수신자 없음 | §3 | 야간·주말 미확인 경보가 영원히 미확인 | 이벤트 미확인 N분 → 2차 수신자 · 시간표 기반 수신자 그룹(`notify.yaml` `schedules:`) | M |
| P2-7 | P2 | 알람 이력 필터·CSV/Excel/PDF 내보내기 없음, docstring은 "CSV" | `routers/recognition.py:7 vs :51-56` · `dashboard.py` 기간 선택·내보내기 0 | 안전관리자 월간 보고를 손으로 재가공 | `?rule=&level=&site=&from=&to=` + CSV(표준 라이브러리로 가능) · PDF는 기존 위험성평가 HTML 인쇄 경로 재사용 | S |
| P2-8 | P2 | 관리자 지표 부족 — 시간대별·카메라별·보호구 착용률·기간 비교 없음 | `dashboard.py:39-83` | 경쟁 제품의 기본 KPI(착용률·구역별 침입 추이) 미제공 | 워커가 "검출 인원 수"를 주기 집계에 남기면 착용률 분모 확보(`worker.py` 상태에 person_count 있음 — **확인 필요**) | M |
| P2-9 | P2 | 텔레그램 통보에 증거 사진 미첨부 | `dispatcher.py:157-170` `sendMessage`만, `sendPhoto|MIMEImage` 0 · 워커 meta에 `evidence` 경로는 실림(`worker.py:1128`) | 수신자가 사진 없이 판단 → 오탐 확인 위해 관제로 돌아와야 함 | `sendPhoto`(모자이크 적용본) 옵션, 실패 시 텍스트 폴백 | S |
| P2-10 | P2 | 승인자 신원이 자유 입력, 인증은 단일 공유 토큰 | `safety_core.py:274` `approver = payload.get("approver") or "안전관리자"` · `main.py:178-250` Bearer 단일 토큰 | 감사추적 "누가"가 법적 증명력 없음 | 최소: 로그인 사용자명(쿠키/토큰별 이름) 강제 · 향후 사용자 계정 | M |
| P2-11 | P2 | `undeliverable_count`·`_SENSOR_DANGER`가 프로세스 메모리 | `dispatcher.py:99` · `safety_core.py:505` | 재기동 후 `/health` degraded 근거 소실 · 센서 전이 상태 초기화 → 재기동 직후 같은 임계에서 중복 통보(상한으로 억제됨) | 카운터를 `alert_queue.db` 별도 테이블에 · 센서 상태 파일 저장 | S |
| P2-12 | P2 | relay `off_failed`는 통보되지 않는다(M4-10) | `relay.py:145-149` 로그+상태만 · `alert_queue` 요약에 미포함 | 사이렌 안 꺼짐을 폰으로 모른다 | 요약 통보에 `relay.off_failed` 포함(원격 채널 살아 있을 때) | S |
| P3-1 | P3 | `/hub` 미전송 배너가 **누적 dead**(76)를 그려 영구 붉은 배너 | `index_hub.html:218` `a.dead` · `/health alerts.dead`는 누적(`alert_queue.counts()`) | 알람 피로 — 배너를 아무도 안 본다 | `dead_1h` 사용(이미 `/health`에 있음) | S |
| P3-2 | P3 | `GET /alerts/status` 스텁이 항상 빈 목록 | `safety_core.py:785-787` | 외부 연동자 오해 | 제거하거나 `alert_notify.stats()+alert_queue.counts()` 반환(OpenAPI 게이트 확인) | S |
| P3-3 | P3 | 서빙되지 않는 `themes/safety/index_vigent.html`이 `/dispatch/relay` 를 호출 | `index_vigent.html:409` · 서빙 라우트 grep 0(`safety_core.py:706-818`은 index_local/rfdetr/hub/index만) | M8-9 "호출부 0" 결론이 파일 기준으로는 부정확 · 정리 대상 | 삭제 또는 `docs/`로 이동 | S |
| P3-4 | P3 | `relay.py:7`·`SITE_CHECKLIST.md:171` "HTTP 또는 Modbus TCP" — Modbus는 미구현 | §2 | 조달 담당이 Modbus 릴레이를 사 오면 동작 안 함 | 문구를 "HTTP만"으로 정정 | S |
| P3-5 | P3 | `docs/PRIVACY_POLICY_DRAFT.md` §3·§6·§9 가 "얼굴 비식별화·보관기간 파기 미구현"이라 서술 — 코드는 구현됨 | `privacy.py:1-20` 모자이크 · `retention_scheduler.py` 자동 스윕 · `data_engine.py:172-173` | 대외 문서 신뢰 저하(규칙 7 역방향: 있는 것을 없다고 씀) | 문서 갱신(측정일·구성 병기) | S |
| P3-6 | P3 | 인식 로그 조회가 매 호출 전 파일 파싱, 대시보드는 20만 건 로드 | `data_engine.py:191-211` · `dashboard.py:40` | 30일×수천 건에서 대시보드·피드 지연(미측정) | 일자 인덱스 또는 sqlite 이관 | M |
| P3-7 | P3 | 센서 임계에 히스테리시스 없음 | `safety_core.py:519-545` 단일 임계 비교 | 임계 부근 진동 시 전이 반복(시간당 상한 6으로 억제) | 해제 임계 별도(예: O2 18.0 진입 / 18.5 해제) | S |

---

## 6. 경쟁 상용 제품 대비 격차

> 아래 "통상 제공"은 산업안전 비전·VMS 계열 상용 제품의 **일반적 기능 범주**에 대한 검토자 경험 기반 서술이며, 개별 제품의 실제 스펙은 **미검증**(제품별 확인 필요).

| 영역 | 상용 제품 통상 제공 | VIGENT 현재 | 격차 |
|---|---|---|---|
| 현장 경보 출력 | 경광등·사이렌·방송 연동, 다채널 IO, 릴레이 상태 감시 | HTTP 릴레이 1채널, 기본 off, 실물 미검증, read-back 없음 | **큼** |
| PLC/설비 연동 | Modbus/OPC-UA/EtherNet-IP 입출력, 감속·정지 요청 신호 | 없음 | **큼** |
| 수신 채널 | 앱 푸시·SMS·카카오·이메일·VMS 이벤트 | 텔레그램·이메일·웹훅(실운영 텔레그램 1개) | 중 |
| 알람 클립 | pre/post-roll 영상 첨부 | 스냅샷 1장, 텍스트 통보 | **큼** |
| 확인·에스컬레이션 | ack·담당자 배정·미확인 상향·교대표 | ack(키 결함) | **큼** |
| 오탐 관리 | 오탐 표시·오탐률 대시보드·재학습 파이프라인 | 없음(VLM 자동 억제만) | **큼** |
| 이력·보고 | 필터·검색·CSV/PDF·정기 리포트 자동 발송 | JSONL 다운로드, 수동 평가서 | 중 |
| KPI | 착용률·구역별·시간대별·카메라별 | 규칙·현장·등급·14일 추이 | 중 |
| 통보 신뢰성 내부 장치 | 큐·재시도·데드레터 | **있음(우수)** — 게이트·백오프·선기록·config_error 분류·/health 연동 | 우위 |
| 근거 인용·서류 자동화 | 드묾 | 법령 인용·위험성평가·TBM 자동 생성 | 우위 |

---

## 7. 확인 질문

1. **Q1 (P0-1)** 오늘 21:22~21:35 부하 시험 때 텔레그램 토큰이 401이 난 것을 인지하고 있었는가? 토큰이 회수/재발급된 것인가, 아니면 `notify.yaml`이 시험용 값인가? (값은 묻지 않는다 — 상태만.)
2. **Q2** 파일럿 현장에서 **2번째 원격 채널**(이메일 또는 웹훅→문자 게이트웨이)을 둘 계획이 있는가, 아니면 텔레그램 단일 채널이 확정 정책인가?
3. **Q3 (P1-1)** 조달 예정 릴레이가 **자체 펄스/타임아웃 모드**(호스트 무응답 시 자동 OFF)를 지원하는가? 지원하면 F13 위험이 하드웨어에서 상쇄된다. 모델이 정해졌는가?
4. **Q4** 현장 작업자 본인에게 알리는 수단(현장 방송·경광등)이 계약 범위에 있는가, 아니면 관리자 폰 통보만이 범위인가? (P1-5 판단이 갈린다.)
5. **Q5 (P1-3)** 증거 30일·인식 로그 30일 보존이 고객사 개인정보 정책에서 온 값인가? 사고 조사·산안법 기록(3년) 요구와 어떻게 조화할 계획인가?
6. **Q6** `/evidence/search`(`safety_core.py:95`)의 실제 검색 조건 — 본 검토에서 본문을 읽지 않았다(확인 필요).
7. **Q7** TBM 작성 시 당일 경보 이력이 자동 인용되는가(`tbm_store.py` 본문 미확인).
8. **Q8** 워커 상태의 인원 수(`person_count`)가 주기 집계로 남는가 — 보호구 착용률 분모로 쓸 수 있는지(P2-8).
9. **Q9** `notify.example.yaml`의 `sites:` 현장별 chat_id 구조는 **과거 구현의 잔재**인가, **예정 기능**인가?
10. **Q10** 고객이 요구하는 PLC 프로토콜이 확인된 것이 있는가(Modbus TCP가 가장 흔하나 미확인)?

---

## 8. 검토 범위 밖 / 읽지 않은 것

- `routers/safety_core.py` 전체 827줄 중 피드·승인·센서·통보 시험·알림 설정·대시보드 라우트만 읽음(`/evidence/search`·`/safety/live/analyze`·brain 계열은 미독).
- `tbm_store.py`·`routers/tbm.py` 본문(라우트 목록만), `agents/scribe.py`·`safety_manager.py`·`analyst.py`는 LLM 의존·폴백 부분만 grep.
- `incident.py` 60줄 이후(VLM 프롬프트·렌더).
- 테스트는 파일·건수만 세었고 실행하지 않았다(서버 기동·통보 금지 조건과 무관하지만 본 검토 범위 밖).

---

**파일**: `D:\vigent_original\docs\review\04-alerting-integration.md` · **P0 1건 · P1 5건**(P2 12 · P3 7)
