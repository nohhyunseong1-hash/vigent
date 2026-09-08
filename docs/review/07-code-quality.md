# Phase 7. 코드 품질·테스트·문서 검토 — VIGENT

- 검토일: 2026-09-08 · 대상 커밋: `b7f49d9` (브랜치 `audit/cleanup-20260906`, 작업트리 clean)
- 방식: 정적 분석·테스트·커버리지·타입검사 **실행** + 코드·문서 정독. **코드 수정 없음 · 서버 기동 없음 · 비밀값 미기재.**
- 실행 환경: `D:\vigent_original`, `PYTHONUTF8=1`, 정본 파이썬 `C:\Users\shgus\AppData\Local\Programs\Python\Python311\python.exe`(3.11.9, torch 2.12.0+cu130). 커버리지는 스크래치 venv(`py -3.11 -m venv --system-site-packages` + `coverage 7.16.0`)로 측정.
- 심각도: P0(안전사고 직결) / P1(보안 침해·데이터 유실·운영 오염) / P2(경쟁 열위·운영 진단 불가) / P3(코드 품질·유지보수성). 읽지 않은 것은 "확인 필요". 판단 유보는 §10 "확인 질문".
- 모든 수치는 이 세션에서 **실제로 실행한 결과**다. 스크래치 원본: `C:\Users\shgus\AppData\Local\Temp\claude\d--vigent-original\7ae58df6-0718-46a6-8582-7374338dc1d7\scratchpad\`(`unittest_phase7.log`·`coverage_report.txt`·`except_table.md`·`test_map.md`·`bisect_writes.log`·`before.json`/`after.json`).

---

## 0. 한 줄 요약

게이트 5종(ruff·mypy·unittest 662·OpenAPI·프로파일 드리프트)은 **모두 통과**하고 커버리지는 **59%**(8,790문 중 3,606 미실행)다. 그러나 **① 테스트 스위트가 운영 `data/` 4파일을 실제로 바꾸고 실 `go2rtc.exe` 를 띄운다**(격리 "변경 0" 주장과 불일치 — 운영 PC 에서 돌리면 라이브 go2rtc 를 죽이고 재기동), **② 안전 판정 핵심 4모듈(hazard_rules·incident·ppe_check·safety_brain)이 커버리지 0%**, **③ 광범위 `except Exception` 223곳 중 54곳은 `pass` 로 삼키고 124곳은 로그 없이 폴백**(통보 채널 실패 3종 포함), **④ 비동기 핸들러 2곳이 블로킹 `urlopen` 으로 이벤트 루프를 최대 13초 정지**, **⑤ CLAUDE.md·RELEASES·README 등 문서 낡음이 2026-09-03 지적 6건 중 4건 그대로** 남아 있다. **P0 0건 · P1 2건 · P2 8건 · P3 14건.**

---

## 1. 실행 결과 표

| # | 명령 | 결과 | 시간 |
|---|---|---|---|
| 1 | `python scripts/tree_hash.py snapshot data logs -o before.json` | 28,474파일 스냅샷 | ~2분 |
| 2 | `python -m unittest discover -s tests` | **`Ran 662 tests in 109.852s` / `OK`**, exit 0, FAIL/ERROR 0, skip 표기 없음 | 116s(벽시계) |
| 3 | `python scripts/tree_hash.py snapshot … -o after.json` + `compare before after` | **불일치 — exit 1**: 전 28,474 / 후 28,473 · 추가 0 · **삭제 1 · 변경 3** — `[removed] data\go2rtc.pid` · `[changed] data\go2rtc.log` · `data\go2rtc.runtime.yaml` · `data\retention\pinned.json`. `logs/` 는 무변경 | ~2분 |
| 4 | `coverage run -m unittest discover -s tests` → `coverage report --omit="*/vendor/*"` | `Ran 662 tests in 110.763s OK` · **TOTAL 8,790 stmts / 3,606 miss / 59%** (부록 C 전체표) | 116s |
| 5 | `python -m ruff check vigent-core tests` (ruff 0.16.1) | **All checks passed!** exit 0 | 0.8s |
| 6 | `python -m mypy` (mypy 2.3.0, pyproject `files` 19개) | **Success: no issues found in 19 source files** | 17.8s |
| 7 | `python scripts/check_openapi_diff.py` | HTTP (path,method) 현재 110 / 기준 110 · WS `['/tapo/ws']` 동일 → **통과** | 0.65s |
| 8 | `python scripts/check_profile_drift.py` | **프로파일 드리프트 없음** → 통과 | 0.16s |
| 9 | `ruff check --isolated --select BLE,S,B --exit-zero vigent-core` (vendor 제외) | **130건**: S110 54 · B008 42 · S112 6 · S603 5 · S607 4 · S310 4 · S101 4 · B904 4 · S108 3 · B007 2 · BLE001 1 · B905 1 | 1s |
| 10 | `grep -rn "except Exception" vigent-core \| wc -l` | **222** (그중 `# noqa: BLE001` 221 · noqa 없음 1 = `vigent-core/legal_whitelist.py:59`) · `except BaseException` 1 (`rfdetr_service.py:186`) · bare `except:` 0 | — |
| 11 | AST 전수 분류(`except_audit.py`, 부록 A) | 광범위 핸들러 **223곳**: **삼킴(pass) 54 · 무로그 폴백 124 · 로그 45** | — |
| 12 | 테스트 모듈별 운영 파일 쓰기 이분 탐색(`bisect_writes.py`, 97모듈 단독 실행) | `data/` 를 바꾸는 모듈 **4개**: `test_alert_queue`(pinned.json) · `test_bypass_paths_gated`·`test_endpoints_smoke`·`test_machine_guard`(go2rtc.log·go2rtc.runtime.yaml) — §2.3 | ~4분 |
| 13 | 스레드/락 grep | `threading.Lock/RLock/Event` 22곳 · `threading.Thread(` 12곳 · `asyncio.` 2파일(main·tapo) · `run_in_threadpool/to_thread` **0** · `DETECT_LOCK` 사용 12파일 — §4 | — |

> ★규칙 11 관점: 표 3 은 "테스트가 운영 데이터를 건드리지 않는다"는 주장의 **반증**이다(§2.3). 게이트 통과와 별개로 기록한다.

---

## 2. 테스트 실체

### 2.1 규모
- 테스트 파일 **97개**(`tests/test_*.py`) + 헬퍼 2(`_isolate.py`·`_source_probe.py`) + fixtures 2장(얼굴 없음: `no_person.jpg`·`person_far.jpg`).
- `def test_` grep **660** / 러너 집계 **662** (차이 2건은 동적 생성 추정 — 확인 필요). 파일당 최다: `test_alert_wiring.py` 29 · `test_zone_edit_guard.py` 23 · `test_safety_review_fixes.py` 17.
- 코어 모듈 84개 중 **44개는 어떤 테스트도 직접 import 하지 않는다**(부록 B). 그중 사용자 지정 핵심 모듈의 매핑은 아래.

### 2.2 핵심 로직 ↔ 테스트 매핑

| 핵심 로직 | 모듈 | 테스트 파일(직접 참조) | 커버리지 | 판정 |
|---|---|---|---|---|
| 협착/근접 판정 | `proximity.py` | `test_proximity_driver.py`(14) · `test_motion_tracker.py` · `test_alert_wiring.py` | **97%** | 있음 |
| 위험구역 기하·타일 | `zone_tile.py` / `zone_geom.py` | `test_zone_tile.py` · `test_worker_zone_tile.py` / **없음**(web_util 재export만) | 98% / 67% | 있음 / 부분 |
| 위험구역 디바운스 | `zone_debounce.py` | `test_zone_debounce.py`(13) · `test_track_scoped_cooldown.py` 외 4 | 98% | 있음 |
| 위험목록 규칙 | `hazard_rules.py` | **없음** | **0%** | **없음** |
| PPE 착용 규칙 | `ppe_check.py` | **없음**(`test_ppe_*` 2개는 `agents/guard.py` 의 PPE 임계·라벨을 검사, `ppe_check` 미참조) | **0%** | **없음** |
| 사고 원인분석 | `incident.py`(462줄) | **없음** | **0%** | **없음** |
| 안전 두뇌(등급·법령) | `safety_brain.py`(467줄) | **없음** | **0%** | **없음** |
| 경보 게이트(쿨다운) | `alert_gate.py` | `test_alert_wiring.py` · `test_bypass_paths_gated.py` · `test_track_scoped_cooldown.py` 외 2 | **100%** | 있음 |
| 경보 통보 스레드 | `alert_notify.py` | `test_alert_queue.py` · `test_alert_delivery_hardening.py` · `test_notify_queue_drop.py` 외 7 | 92% | 있음 |
| 경보 내구 큐 | `alert_queue.py` | `test_alert_queue.py` · `test_dispatch_retry_remote_only.py` 외 8 | 90% | 있음 |
| 통보 채널(텔레그램·메일·웹훅) | `agents/dispatcher.py` | `test_alert_delivery_hardening.py` 외 9(대부분 mock) | 부록 C | 있음(채널 실패 로그 없음 — §3) |
| 거리 계산(픽셀→m, 종횡비) | `proximity.py`·`agents/guard.py` | `test_proximity_driver.py` · `test_constants_config.py` | 97% / 87% | 있음 |
| 스트림 캡처·재접속 | `worker.py:_StreamCapture`(630-760) | **재연결 루프 자체 테스트 없음** — `test_capture_timeouts.py` 는 열기/읽기 타임아웃, `test_starvation_guard.py:112` 는 백오프 상한 상수, `test_health_detect_alive.py:26` 는 상태 필드만 | worker 72% | **부분** |
| 워커 생명주기·hang 감시 | `worker.py:Worker` | `test_worker_lifecycle_guards.py` · `test_health_detect_alive.py`(16) · `test_camera_delete_no_ghost.py` | 72% | 있음 |
| 검출 라우트 | `routers/detect.py` | **없음**(스모크 간접) | **17%** | 부분 |
| 종합 라우터 | `routers/safety_core.py`(827줄·57라우트) | 스모크 간접 | 36% | 부분 |
| RF-DETR 서비스 | `rfdetr_service.py` | `test_vlm_text_helper.py` · `test_worker_zone_tile.py` | 29% | 부분 |
| 인증·WS | `auth_session.py` / `ws_auth.py` | `test_browser_session_auth.py` / `test_ws_auth.py` | 88% / 100% | 있음 |

### 2.3 ★테스트 격리 실패 — 운영 `data/` 변경 + 실 프로세스 기동 (P1-1)

**증거**: 표 1-3 의 4건 변경 mtime 은 `23:16:43`(pinned.json)·`23:17:48`(go2rtc.*) 으로 모두 테스트 창(`23:16:08`~`23:18:34`) 안이고, 실행 후 `tasklist` 에 go2rtc·python 서버 프로세스는 없었다(외부 원인 배제). `data/go2rtc.log` 꼬리에 `INF [api] listen addr=127.0.0.1:1984` · `[webrtc] listen tcp addr=[::]:8555` · `go2rtc … version=1.9.14` 가 테스트 시각으로 남아 **실제 바이너리가 포트를 열었다**. 모듈 단독 실행 이분 탐색(표 1-12):

| 테스트 모듈 | 바뀐 운영 파일 | 경로(파일:줄) | 원인 |
|---|---|---|---|
| `tests/test_alert_queue.py` | `data/retention/pinned.json`(내용에 `"…events_20260908.jsonl": "alert:1"` 추가) | `alert_queue.py:95-128 mark_sent()` → `data_engine.pin_evidence()` → `data_engine.py:31 _PINNED`(운영 경로) | `setUp`(`test_alert_queue.py:38-49`)이 `q._reset_for_test(tmp db)` 로 DB 만 바꾸고 **`_isolate.isolate_alerts()` 를 쓰지 않는다**. `tests/_isolate.py:127` 주석이 바로 이 누수("임시 DB 행 id 로 만든 alert:1 pin 이 운영 pinned.json 에 남았다")를 기록해 두었으나 이 파일에는 적용 안 됨 |
| `tests/test_endpoints_smoke.py:39` · `test_machine_guard.py:64` · `test_bypass_paths_gated.py:58` | `data/go2rtc.runtime.yaml`(템플릿으로 **덮어씀**) · `data/go2rtc.log` · `data/go2rtc.pid`(삭제) | `TestClient(main.app)` → lifespan `_startup()`(`main.py:467`) → `_optional("go2rtc", …)`(`main.py:479-482`) → `routers/cameras.py:337 ensure_go2rtc()` → `:385 subprocess.Popen([bin/go2rtc.exe …])` | `ensure_go2rtc()` 에 **테스트/환경변수 가드가 없다**. `bin/go2rtc.exe` 가 있는 PC(이 PC 포함 — `bin/` 19MB) 에서는 실제로 뜬다. CI 러너(ubuntu, bin 없음)에선 `:362 return False` 로 조용히 건너뛰므로 CI 는 이 문제를 못 본다 |

**왜 P1 인가**: `ensure_go2rtc()` 는 포트가 이미 점유돼 있고 PID 파일이 살아 있으면 **기존 인스턴스를 종료하고 재기동**한다(`cameras.py:342-349 _terminate_pid(old)`; `:363-366` 런타임 yaml 을 템플릿으로 초기화 → 동적 등록 스트림·자격증명 소실). 운영 중인 PC 에서 `python -m unittest` 를 돌리면 **라이브 확대뷰 스트림이 끊기고 등록이 초기화**된다. 또한 `docs/FINAL_SUMMARY.md:57` 과 커밋 `3764280` 메시지("전후 변경 0")의 주장과 **불일치**한다(그때는 `bin/go2rtc.exe` 조달(`b72242d`) 이전이었을 가능성 — 확인 필요).

### 2.4 통합·회귀(골든) 테스트

| 세트 | 실체 | 대상 | CI 포함 |
|---|---|---|---|
| `eval/golden/`(19파일) + `scripts/golden_regression.py`·`golden_score*.py` | 위험성평가 **텍스트 산출물**(Scribe/Copilot) 채점 회귀. `eval/golden/README.md:1-25` — 강사 정답 1건(크레인 89점) 확정 | 에이전트(LLM/RAG) — **비전 아님** | **아니오**(`ci.yml` 5스텝에 없음) |
| `datasets/goldens/T1/`(15 케이스 json + 판정기준 md) | 위험성평가 케이스 정답표 | 에이전트 | 아니오 |
| `scripts/eval_tracking.py` + `tests/test_eval_tracking.py` | 다인 추적 프록시 지표(ID 스위치·단절) — 테스트는 **합성 데이터로 지표 계산만**(`test_eval_tracking.py:1-5`) | 추적 | 지표 계산만 CI |
| `benchmarks/d1c_replay_verify.py` 등 | 특정 변경(D1-C) 재생 검증 **일회성 스크립트**, 실데이터는 저장소 밖(`VIGENT_DATA_DIR`) | 파이프라인 | 아니오 |
| **녹화 영상 → 전체 파이프라인 → 기대 이벤트 검증 세트** | **없음**. `tests/` 에서 `VideoCapture`/`.mp4` 를 쓰는 4파일(`test_alert_wiring`·`test_capture_timeouts`·`test_rfdetr_onnx_parity`·`test_safety_review_fixes`)은 합성 프레임·타임아웃·ONNX 동등성이지 사건 시퀀스 회귀가 아니다 | — | — |

→ **검출기·추적기·임계 변경이 "이 영상에서 이 시각에 이 경보"를 깨뜨렸는지 자동으로 아는 장치가 없다**(P2-2). 규칙 9 사고(2026-08-13 ByteTrack 전환 후 12일 미재측정)를 코드로 막는 장치가 아직 없다.

---

## 3. 린터·타입·예외 처리

### 3.1 린터/타입/포매터
- ruff `E,F,I,W,BLE` 0건. 단 `pyproject.toml:20` 이 `BLE001` 을 **ignore** 하고 있어 blind-except 는 사실상 꺼져 있다(`# noqa: BLE001` 221건은 규율의 흔적일 뿐 강제력 없음). `ruff format` 훅은 `.pre-commit-config.yaml:11` 에서 의도적으로 보류.
- mypy 는 **88개 중 19파일** 화이트리스트만(`pyproject.toml:44-64`). 관대 검사(`routers.*`·`worker`·`main` 은 `disallow_untyped_defs=false`). 나머지 69파일은 타입검사 밖.
- **도구 버전 드리프트**: CI `ci.yml:37-38` 는 `ruff==0.12.0`·`mypy==1.17.1`, `.pre-commit-config.yaml:7` 도 `v0.12.0`; 로컬 정본은 **ruff 0.16.1 · mypy 2.3.0**. 같은 코드가 CI 와 로컬에서 다른 규칙집으로 검사된다(P3-3).
- CI 트리거는 `push/pull_request: branches [main]`(`ci.yml:8-11`) — 현재 작업 브랜치 `audit/cleanup-20260906` 의 커밋은 CI 를 타지 않는다(P3-4). `ci.yml:49` 주석 "경로·메서드 106" 은 실제 110 과 불일치.

### 3.2 정적 스캔(S/B) 상위 예
| 규칙 | 건수 | 대표(파일:줄) | 평가 |
|---|---|---|---|
| S110 try-except-pass | 54 | `agents/dispatcher.py:237` · `agents/guard.py:484,694` · `privacy.py:142,158,210` · `worker.py:967` | §3.3 전수표 |
| B008 함수 기본인자 호출 | 42 | FastAPI `Body()/Query()/File()` 기본값 — 프레임워크 관용구, 오탐 다수(확인 필요) | 무시 가능 |
| S603/S607 subprocess | 5/4 | `main.py:350,358`(eventcreate) · `privacy.py:286,308`(cipher/powershell) · `routers/cameras.py:385`(go2rtc) | 모두 고정 argv 리스트, 사용자 입력 아님 — 실질 위험 낮음 |
| S108 `/tmp` | 3 | `ml/vlm_risk_summary.py:101` · `rfdetr_service.py:224,242` | Windows 배포에서 `/tmp` 는 존재하지 않는 경로 — 해당 분기가 실제 도달하는지 **확인 필요** |
| S101 assert | 4 | `alert_notify.py:50,132` · `pose/rtmpose_adapter.py:55-56` | `python -O` 에서 사라지는 검사 — 런타임 불변식이면 `if … raise` 로 |
| S310 urlopen 스킴 | 4 | `relay.py:75-76` · `routers/tapo.py:117` · `starvation_guard.py:55` | URL 이 설정/고정값이면 무해 — relay 대상 URL 검증 여부 확인 필요 |
| B904 raise-from | 4 | `routers/safety_core.py:808` · `tapo.py:56,120` · `web_util.py:113` | 원인 예외 체인 유실 |
| B905 zip strict | 1 | `safety_brain.py:214` | 길이 불일치 조용히 절단 |
| B007 미사용 루프변수 | 2 | `worker.py:614` | 죽은 값 |

### 3.3 광범위 except 전수 (223곳 — 전체 표는 **부록 A**)
분류 기준(AST): `pass`/문서열만 = **삼킴(pass)** · 핸들러에 log/warn/print/vlog 계열 호출 있음 = **로그** · 그 외 값 반환/상태만 = **무로그**.

| 분류 | 건수 | 파일 상위 |
|---|---|---|
| 삼킴(pass) | **54** | `routers/cameras.py` 7 · `agents/scribe.py` 6 · `privacy.py` 5 · `main.py` 4 · `routers/safety_core.py`·`system.py`·`tapo.py`·`vlog.py` 각 3 |
| 무로그 폴백 | **124** | `agents/guard.py` 9 · `incident.py` 9 · `routers/system.py` 9 · `routers/cameras.py` 8 · `agents/dispatcher.py` 6 · `scene_vlm.py` 6 · `worker.py` 6 |
| 로그 남김 | 45 | — |

**운영 진단을 막는 대표 사례**(P2-3):
- **통보 채널 실패 원인이 어디에도 남지 않는다**: `agents/dispatcher.py:169 _send_telegram` · `:187 _send_email` · `:203 _send_webhook` — `requests.post`/`smtplib` 예외를 잡아 `sent:False` 만 반환(무로그). 큐의 `alert_queue.py:313 try_send` 도 무로그. 재시도는 되지만 **"왜 안 갔는지"는 로그가 없다**(토큰 만료·DNS·TLS 구분 불가).
- `privacy.py:142,158 anonymize_faces` — `import vlog` 실패 시 pass(비식별화 감사 기록 유실) · `:210 _note_failure` — `alert_notify` import 실패 pass(비식별화 실패 통보 유실).
- `incident.py:152,166,174,205,225 analyze` — hazard_rules·scene_vlm·vlm_confirm·behavior·safety_rag **5단계 전부** 무로그 폴백 → 결과가 빈약해져도 사용자는 "정상 출력"으로 본다.
- `worker.py:967 _pose_loop` — 인체공학 트래커 예외 pass(포즈 경보 조용히 중단).
- `starvation_guard.py:111 _tick` — `manager.status()` 예외를 무로그 흡수(§4 의 무락 순회가 터지면 감시 틱이 조용히 빠짐).
- `routers/system.py:48,77,116,133,160,173 health` — `/health` 구성 요소 6곳이 삼킴/무로그 → 헬스 응답이 "부분 누락"으로 정상처럼 보일 수 있음.
- `routers/tapo.py:98 tapo_ws` — WS 중계 예외 전부 pass(연결 실패 원인 미기록).

---

## 4. 동시성 위험 표

| # | 위치(파일:줄) | 패턴 | 위험 | 심각도 |
|---|---|---|---|---|
| C1 | `routers/tapo.py:104-120 async def tapo_webrtc` | **비동기 핸들러에서 블로킹** `_ensure_stream()`(`:43 urlopen timeout=3`) + `:117 urlopen(req, timeout=10)` | go2rtc 가 느리면 **이벤트 루프 최대 13초 정지** → 같은 루프의 `tapo_ws` 중계·모든 요청 디스패치 지연 | **P2** |
| C2 | `routers/tapo.py:60-72 async def tapo_ws` | `:72 _ensure_stream(src)` 블로킹(3초) | 동일 | P2(C1 과 묶음) |
| C3 | 라우터 전부 동기 `def`(cameras 11·detect 4·safety_core 57 … `async def` 0) | Starlette 스레드풀 위임 — 블로킹 자체는 안전 | 단 `DETECT_LOCK`(RLock)을 잡는 라우트(`detect.py:138`·`incident.py:34,73`·`ppe.py:58`·`safety_core.py:439,492`)와 워커·예열(`readiness.py:133`)이 **하나의 락**을 두고 직렬화 → 동시 요청은 스레드풀 스레드를 점유한 채 대기(풀 크기·포화 시 응답 거부 여부 **확인 필요**) | P3 |
| C4 | `worker.py:1383-1385 WorkerManager.status()` | `self._workers.items()` 를 **`_reg_lock` 없이 순회**; `start`(`:1337`)·`remove`(`:1366`)는 락 안에서 dict 를 변경 | `/health`·`starvation_guard._tick`(`:111`) 도중 카메라 추가/삭제 시 `RuntimeError: dictionary changed size during iteration` 가능(드묾). `_tick` 은 무로그로 삼켜 감시 1회 누락 | P3 |
| C5 | `worker.py:844 status()` — `dict(self.state)` 무락 복사; 워커 스레드가 34곳에서 `self.state[k]=` 갱신 | CPython 에서 단일 키 쓰기·dict 복사는 원자적이라 손상은 없으나 **키 간 일관성(찢긴 읽기)** 은 보장 안 됨(`frames` 와 `last_frame_ts` 가 다른 시점) | P3(허용) |
| C6 | `worker.py:1010,1039,1041` 가 `_last_frame`/`_last_dets` 를 참조 교체; `routers/cameras.py:146,175,181` 이 무락 읽기 | 참조 교체는 원자적, 리스트는 교체만 하고 원위치 수정 없음 → 안전. 단 `_last_frame` numpy 를 라우트가 in-place 수정하면 위험(`cameras.py:179` 주석 "원본 수정되지 않는다"로 인지됨) | 없음(관찰) |
| C7 | `_StreamCapture`(`worker.py:640 _lock`) / 포즈 스레드(`:784 _pose_lock`, 사용 `:958,970,1057`) | 슬롯·이벤트 공유는 락으로 보호됨 | 양호 |
| C8 | `app_state.STATE`(`app_state.py:21`) — 전역 dict, 라우터 11파일 29곳 접근 | 기동 시 1회 채우고 이후 읽기 전용에 가까움(`load_theme` 재호출 여부 확인 필요) | P3(전역 상태) |
| C9 | 데몬 스레드 12개(`alert_notify:84`·`alert_queue:347`·`readiness:161`·`retention_scheduler:127`·`rfdetr_service:178`·`cameras:210`·`starvation_guard:150`·`worker:653,819,825,1214`) | 종료 순서는 `main.py:435-438` 에서 stop 호출 확인 | 양호 |
| C10 | `rfdetr_service.py:186 except BaseException` | 호출 스레드로 전파(의도) — VLM 전용 스레드 teardown 크래시(F-14) 회피 설계 | 양호 |

---

## 5. 설정·중복·죽은 코드

### 5.1 설정과 코드 분리
- **있음**: `tuning.py:1-60` 엄격 로더(중복 키 → `TuningConfigError`, M7-1) · `scripts/check_profile_drift.py` 통과 · `runtime_config.py`(100%) · `test_tuning_strict_loader.py`·`test_constants_config.py`.
- **매직 넘버 잔존**: 핵심 6파일(`worker.py`·`agents/guard.py`·`proximity.py`·`hazard_rules.py`·`incident.py`·`routers/cameras.py`)에서 비교 연산에 리터럴을 쓰는 곳 **25곳**, 그중 `tuning`/`cfg` 미참조 **25곳**(전부). 예: `worker.py:681` 드레인 상한 `60` · `:684` `0.020`s · `agents/guard.py:205` IoU `0.45` · `:833` `0.25`/`0.40` · `:154 min_ratio=0.70` · `routers/cameras.py:184,221` JPEG 품질 `70`/`65`·해상도 `640×360`/`480×270`. 대부분 주석으로 근거는 적혀 있으나 현장 조정은 코드 수정이 필요(P3-7).

### 5.2 중복 코드
- `_iou`/`iou`/`containment` 가 **저장소 전체 40곳**에 재정의(`vigent-core/agents/guard.py:104,128` · `proximity.py:41` · `scripts/eval_tracking.py:51` · `benchmarks/*` 30곳 · `tools/*` 4곳). 코어 밖이라 게이트 대상이 아니지만 **측정 스크립트끼리 IoU 정의가 다르면 수치가 어긋난다**(규칙 9 리스크, P3-8).
- 프론트: `themes/safety/` 에 `index.html`(639줄)·`index_local.html`(814)·`index_hub.html`(638)·`index_vigent.html`(557)·`index_boda_ref.html`(241)·`index_rfdetr.html`(208) 6종 — 상호 diff 는 하지 않았다(**확인 필요**).

### 5.3 죽은 코드 표

| 모듈 | 줄 | 코어 import | 테스트 | 커버리지 | 판정 |
|---|---|---|---|---|---|
| `rig_replay.py` | 143 | **0** | `test_rig_replay.py` | 부록 C | **앱에서 도달 불가**(테스트만 살림) |
| `rig_monitor.py` | 186 | `rig_replay.py:24` 만 | `test_rig_monitor.py` | 94% | 위와 같은 섬 — "줄걸이 RIG v2" 기능은 라우트·워커에 배선 없음 |
| `quote.py` | 115 | `routers/safety_core.py:682`(`/safety/quote` HTML) | 없음 | 0% | 라우트로 살아 있으나 미검증 |
| `voice.py` | 85 | `safety_core.py:575`(`/safety/voice`) | 없음 | 0% | 동일 |
| `demo.py` | 177 | `safety_core.py:688-700`(`/safety/demo`) | 없음 | 0% | 동일 |
| `liveguide.py` | 125 | `safety_core.py:467,479`(`/safety/guide`) | 없음 | 0% | 동일 |
| `setup_console.py` | 218 | `safety_core.py:725-745`(`/safety/setup`) | 없음 | 0% | 동일 |
| `dashboard.py` | 332 | `safety_core.py:714`(`/dashboard`) | 없음 | 0% | 동일 |
| `evaluator.py` | 200 | `safety_core.py:417,423`(`/safety/eval`) | 없음 | 0% | 동일 |
| `detectors/yolo_adapter.py` | — | (ultralytics 는 배포 requirements 밖, RELEASES v1.0 축) | 없음 | 0% | 라이선스 축 이관 뒤 잔존 어댑터 — 제거/격리 대상 후보 |
| `behavior.py`·`critical_controls.py`·`scene_vlm.py`·`vlm_confirm.py`·`safety_rag.py`·`llm_provider.py` | 49~184 | `incident.py`·`safety_manager.py` 경유 | 없음 | 0~26% | 선택 기능(VLM/LLM) — 키 없으면 폴백 경로만 실행 |
| `_archive/` | 29파일 | ruff 제외(`pyproject.toml:14`) | — | — | 격리 보관(README 명시) — 양호 |
| `UNIMPLEMENTED_SERVER_PATHS` | `static/realtime_core.js:1836-1842` | 9경로 | `test_frontend_unimplemented.py` 가 "목록에만 있고 fetch 없음 + 서버에 라우트 없음" 양방향 고정 | — | 양호(계약 테스트) |

- `vigent-core/static/realtime_core.js` **4,335줄 / 257KB 단일 파일**(프론트 총 9,146줄의 47%) — 모듈 분리 없음(P3-9).
- `print(` 34곳(vendor 제외) — `vlog` 로거와 혼용(P3-10).

---

## 6. 문서 현황 매트릭스

| 문서 항목 | 상태 | 근거 |
|---|---|---|
| 설치 가이드 | **있음** | `md/DEPLOYMENT.md`(610줄, Windows 기준 §0~§9) · `README.md`(81줄) · `docs/ONBOARDING.md`(241줄) · `scripts/setup_env.py` |
| 설치 가이드 결함 | 부분 | `README.md:37` 에 **리터럴 CR 문자**가 박혀 `.\run.ps1` 이 `.^Mun.ps1` 로 표시됨(`cat -A` 확인) · `README.md:20` "CI 는 아직 3.13" — `ci.yml:22-27` 은 이미 `.python-version` 을 읽음(낡음) · `docs/ONBOARDING.md:30` `cd ~/Desktop/VIGENT` · `:194` `/opt/anaconda3/bin/python3 … 55 tests`(맥 잔재) |
| 운영 매뉴얼 | **있음** | `md/DEPLOYMENT.md` §8 운영(서비스 제어·로그 위치·상태 감시) · §9 문제 해결 5가지 · `docs/STABILITY.md` §5 `/health` vs `/status` · `docs/SOAK_24H_CHECKLIST.md` |
| 카메라 설치 가이드 | **부분** | `docs/camera_requirements.md`(80줄): 설치각 조항(직하방·고각 금지, 정성) · 근접 화각 · 카메라 지연 실측법(시계 촬영, ~1.4s). **높이(m)·하향각(°)·거리(m) 정량 권장 없음** — `:76-78` 스스로 "각도 임계값은 측정하지 않았다" |
| 장애 대응 runbook | **부분** | `docs/STABILITY.md` §8(시작/중지·장애 시 확인 순서·롤백) · `md/DEPLOYMENT.md` §9 · `deploy/windows/README.md`(21줄: 설치/상태/제거 3스크립트·종료코드). ★`deploy/windows/README.md:21` "DEPLOYMENT.md 는 아직 맥 기준" — `md/DEPLOYMENT.md:1,4` 는 2026-08-17 Windows 로 전면 재작성됨(낡음). 증상별(카메라 stale·go2rtc 포트 충돌·디스크 풀·토큰 만료) 통합 runbook 은 없음 |
| API 문서 | **부분** | `baseline_openapi.json` 99 경로/110 오퍼레이션(체커용 스냅샷). `main.py:98 FastAPI(...)` 에 `docs_url` 미지정 → 기본 `/docs`·`/openapi.json` 노출; `_AUTH_EXEMPT`(`main.py:205`)에 없어 토큰 설정 시 인증 뒤, 무토큰 로컬 모드에선 공개. 사람이 읽는 API 설명서(엔드포인트별 의미·에러 코드)는 없음 |
| 변경 이력 | **없음/불일치** | `md/RELEASES.md` **12줄**, 항목은 `v1.0-copyleft-zero`·`v1.0.1-server-verified` 2건뿐. `git tag` 는 `audit-before-cleanup`·`v-audit-2026-09`·`weights-v1` 3개 — **RELEASES 가 말하는 v1.0 태그가 저장소에 없다**(커밋 `c1863d5`·`3725eb1` 은 존재). `VERSION`=`0.2.0` 은 RELEASES·README 어디에도 없음. 최신 커밋 `b7f49d9`(2026-09-08) 까지의 변경은 이력 문서에 없음 |
| 온보딩(코드 흐름) | 있음 | `docs/ONBOARDING.md` §3 흐름 A/B, §3.5 라우터 규칙 |
| 테스트 문서 | 부분 | `docs/ONBOARDING.md:73-77`(명령, "600+") · `CLAUDE.md:104` "**55 tests**"(실측 662) |
| 2026-09-03 문서불일치(`docs/review/05_문서불일치.md`) 6건 재검증 | **4건 미해소** | #1 `CLAUDE.md:104` "55 tests" **그대로**(662) · #2 `CLAUDE.md:87` "302줄" **그대로**(`wc -l` 621) · #3 README 3.13 → **정정됨**(`README.md:14-15`), CI 도 정정(`ci.yml:22-27`) — 단 `README.md:20` 이 새로 낡음 · #4 `CLAUDE.md:83,93` `~/Desktop/…` **그대로** · #5 `SAFETY_REVIEW_REPORT.md:222` F6 "미조치" **그대로**(`main.py:435,510` 에 `retention_scheduler` 기동·정지 있음) · #6 `CLAUDE.md:104` `python3` **그대로** |
| 게이트 기술 | 불일치 | `CLAUDE.md:105` "106 == baseline" — 실제 110. `ci.yml:49` 주석도 106 |

---

## 7. 저장소 위생

| 항목 | 실측 | 평가 |
|---|---|---|
| 추적 파일 | `git ls-files` **1,045** · `.git/objects/pack` **47.66 MiB**(in-pack 6,700) | — |
| 루트 | 추적 26파일: md 6개(`CODE_REVIEW.md` 106KB · `SAFETY_REVIEW_REPORT.md` 44KB · `AUDIT_REPORT.md` 35KB · `CLEANUP_PLAN.md` 21KB · `CLAUDE.md` · `README.md`) + 런처 4(`run.bat/ps1/sh` · `VIGENT Safety 시작.bat`) + 설정 | 리뷰 보고서 4종이 루트에 상주 — `docs/` 로 이동 대상(P3-11) |
| 이력 내 민감 미디어 | `git rev-list --objects --all` 기준 **110 객체**(영상 21) — `docs/NEXT_SESSIONS.md:12-20` 세션 1 과 일치, 원격 ref 7개에 push 됨 | **P1-2**(반복 지적, 미착수) |
| `.gitignore` 함정 | `.gitignore:65 pilot_*.md` + `core.ignorecase=true` → **`docs/PILOT_DECISIONS.md` 가 무시됨**(`git check-ignore -v` 확인, `git status --ignored` 에 `!!`), 반면 `docs/PILOT_PROPOSAL.md` 는 추적 중 | 대표 결정 기록이 커밋되지 않고 있음(P2-6) |
| 무시 규칙과 추적 파일 충돌 | `data/` 무시인데 `data/field_eval` 116 · `data/legal` 2 · `data/datasets` 1 추적 · `business_assets/` 무시인데 svg 3 추적 | 강제 추가(`-f`) 이력 — 규칙과 실체가 다름(확인 필요) |
| 작업트리 비추적 대용량 | `footage/` 10MB · `bin/` 19MB · `benchmarks/` 54MB(results 무시) · `runs/` 5.5MB | 로컬 관리(양호) |
| 혼재 디렉터리 | `_archive`(29파일, 격리 README 있음) · `cloud`(6) · `colab`(1) · `reports`(4+3) · `attribution`(1) · `audit`(72) | 제품 코드와 감사 산출물이 같은 레벨 — 구조 정리 대상(P3-11) |
| 한글 파일명 추적 | `"docs/…` 51 · `"runs/…` 22 등 | 크로스플랫폼 도구(일부 CI 액션)에서 인코딩 이슈 가능 — 확인 필요 |

---

## 8. 이슈 목록

| ID | 심각도 | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|---|
| P1-1 | **P1** | 테스트 스위트가 운영 `data/` 를 변경하고 실 `go2rtc.exe` 를 기동·재기동한다 | §2.3: `tree_hash compare` 삭제1·변경3 · `bisect_writes.log` · `alert_queue.py:95-128` · `main.py:479-482` · `cameras.py:337-393,342-349` | 운영 PC 에서 테스트 실행 시 라이브 go2rtc 종료·설정 초기화·pin 목록 오염. "격리 완료" 문서 주장 무효 | ① `test_alert_queue` 에 `isolate_alerts()` 적용 ② `ensure_go2rtc()` 에 `VIGENT_TEST=1`/`VIGENT_GO2RTC_AUTOSTART=0` 가드 + `_isolate` 에서 강제 ③ CI 에 `tree_hash compare` 를 게이트로 추가(bin/go2rtc 있는 러너에서) | S |
| P1-2 | **P1** | git 이력 내 얼굴·사고 영상 110 객체 잔존(원격 포함) | §7 · `docs/NEXT_SESSIONS.md` 세션 1 · `docs/public_release_checklist.md:13-31` | 저장소 공유·공개 시 즉시 노출 | 세션 1 절차 실행(백업 번들 → filter-repo → force-push) | M |
| P2-1 | P2 | 안전 판정 핵심 4모듈 커버리지 0%: `hazard_rules.py`·`ppe_check.py`·`incident.py`·`safety_brain.py` | 부록 C · §2.2 | PPE 규칙·위험목록·사고분석 회귀를 아무 게이트도 못 잡음 | 규칙별 표 기반 단위테스트(입력 검출 → 기대 규칙/등급) 최소 1파일씩 | M |
| P2-2 | P2 | 녹화 영상 기반 파이프라인 회귀 세트 없음(골든은 텍스트 에이전트 전용, CI 밖) | §2.4 | 검출기·추적기·임계 변경 시 경보 회귀를 사람이 눈으로만 확인(규칙 9 재발 구조) | `benchmarks/d1c_replay_verify.py` 의 가상시계 재생 방식을 일반화해 "영상+기대 이벤트 jsonl" 회귀 러너 작성, 표본은 `VIGENT_DATA_DIR` 에서 선택적 실행 | L |
| P2-3 | P2 | 통보 채널 실패·비식별화 실패·사고분석 폴백이 로그 없이 삼켜짐 | §3.3: `dispatcher.py:169,187,203` · `alert_queue.py:313` · `privacy.py:142,158,210` · `incident.py:152-225` · `worker.py:967` | 현장 장애 원인 추적 불가("안 왔다"만 남음) | 삼킴 54곳 전수 검토: 최소 `_WLOG.debug/warning` 1줄 + 실패 카운터를 `/health.warnings` 로 | M |
| P2-4 | P2 | 비동기 핸들러에서 블로킹 `urlopen`(최대 13초) | §4 C1/C2: `routers/tapo.py:72,104-120,43` | 확대뷰 WS 중계·전 요청 디스패치 정지 | `httpx.AsyncClient` 또는 `starlette.concurrency.run_in_threadpool` 로 감싸기 | S |
| P2-5 | P2 | 변경 이력 부재·버전 불일치(RELEASES 12줄, v1.0 태그 없음, VERSION 0.2.0 미기재) | §6 | 고객·심사에 "무엇이 언제 바뀌었는지" 답할 근거 없음(규칙 9) | `VERSION` 을 단일 소스로 태그·RELEASES 를 커밋 시점에 함께 갱신, `scripts/check_release_sync.py` 같은 확인 코드 | S |
| P2-6 | P2 | `.gitignore:65 pilot_*.md` 가 대소문자 무시로 `docs/PILOT_DECISIONS.md` 를 삼킴 | §7 | 대표 결정 기록이 git 에 없음(PC 분실 시 유실) | 패턴을 `/pilot_*.md`(루트 한정) 또는 `business_assets/pilot_*.md` 로 좁히고 파일 `git add` | S |
| P2-7 | P2 | 카메라 설치 가이드에 정량 권장(높이·각도·거리) 없음 | `docs/camera_requirements.md:76-78` | 현장 설치 편차 → 검출 성능 편차를 사후에야 앎 | 다음 현장에서 각도별 표본 수집 후 정량 기준 추가(측정 전엔 "미측정" 유지가 옳음) | M |
| P2-8 | P2 | 2026-09-03 문서불일치 6건 중 4건 미정정 + 신규 낡음 3건 | §6 재검증 행 · `README.md:20,37` · `deploy/windows/README.md:21` | 첫 화면·규칙서가 틀린 수치를 안내 | 한 커밋으로 일괄 정정, `tests/test_baseline_freshness.py` 류로 "CLAUDE.md 수치 = 실측" 자동 검사 | S |
| P3-1 | P3 | `BLE001` ignore 로 blind-except 규율이 강제되지 않음 | `pyproject.toml:20` · 삼킴 54 | 새 삼킴이 게이트를 통과 | ignore 해제 + 기존 221 `noqa` 는 사유 주석 의무화 | M |
| P3-2 | P3 | mypy 화이트리스트 19/88 파일 | `pyproject.toml:44-64` | 69파일 타입 회귀 무감지 | `alert_*`·`retention*`·`privacy` 부터 편입 | M |
| P3-3 | P3 | 도구 버전 드리프트(ruff 0.12.0/0.16.1 · mypy 1.17.1/2.3.0) | `ci.yml:37-38` · `.pre-commit-config.yaml:7` · 로컬 `--version` | CI 와 로컬 판정 상이 | `requirements-dev.txt` 로 단일 핀 | S |
| P3-4 | P3 | CI 가 `main` 브랜치만 감시 | `ci.yml:8-11` | 작업 브랜치 커밋이 게이트를 안 탐 | `branches: ["**"]` 또는 PR 필수화 | S |
| P3-5 | P3 | `WorkerManager.status()` 무락 순회 | `worker.py:1383-1385` vs `:1337,1366` | 드문 `RuntimeError` → `/health` 실패·감시 틱 누락 | `with self._reg_lock: items = list(self._workers.items())` | S |
| P3-6 | P3 | 죽은 섬 코드(`rig_monitor`·`rig_replay` 앱 미배선) + 0% HTML 부속 모듈 7종 | §5.3 | 유지보수 면적 증가, "기능 있음" 착시 | `_archive/` 격리 또는 라우트 배선 결정 | S |
| P3-7 | P3 | 매직 넘버 25곳(핵심 6파일) | §5.1 | 현장 튜닝 시 코드 수정 필요 | `tuning.yaml` 키로 승격(기본값 동일 유지 = 저하 없음) | M |
| P3-8 | P3 | IoU/containment 정의 40곳 중복(측정 스크립트) | §5.2 | 측정 수치 간 정의 불일치 위험 | `vigent-core/geom.py` 한 곳으로 통일 | M |
| P3-9 | P3 | `realtime_core.js` 4,335줄 단일 파일 | §5.3 | 프론트 변경 위험·리뷰 불가 | 기능 단위 분할(ES 모듈, 빌드 없이 `<script type=module>`) | L |
| P3-10 | P3 | `print(` 34곳이 로거와 혼용 | grep | 서비스(NSSM) 환경에서 stdout 로테이션 외 기록 없음 | `vlog` 로 통일 | S |
| P3-11 | P3 | 루트에 리뷰 보고서 4종·감사/사업 디렉터리 혼재 | §7 | 신규 개발자 진입 혼란 | `docs/audit/`·`docs/reviews/` 로 이동, README 링크 | S |
| P3-12 | P3 | S108 `/tmp` 경로 3곳(Windows 부적합), S101 assert 4곳 | §3.2 | 특정 분기에서 파일 쓰기 실패/검사 소실 | `tempfile.gettempdir()`, `if…raise` | S |
| P3-13 | P3 | 스트림 재연결 루프 자체의 단위테스트 없음 | §2.2 | 재연결 백오프·세대 증가 회귀 무감지 | `cap` 을 가짜 객체로 주입해 `_READ_FAIL_MAX` 초과 → `reconnects+1`·`generation+1` 검증 | S |
| P3-14 | P3 | API 사람용 문서 없음(/docs 자동 생성만) | §6 | 통합 파트너에 스키마만 제공 | 라우트 docstring 정비 → `/docs` 설명 자동 반영, 에러 코드 표 1장 | M |

**P0 0 · P1 2 · P2 8 · P3 14.**

---

## 9. 좋은 점(근거)
- 게이트 5종 전부 통과, 662건 110초 — 빠르고 결정적(2회 연속 동일 결과).
- `alert_gate` 100% · `zone_debounce` 98% · `proximity` 97% · `alert_queue` 90% — **경보 상태 머신은 실제로 촘촘히 검증**된다.
- 사고 기반 테스트 문화: `tests/_isolate.py` 헤더, `test_frontend_unimplemented.py`, `_source_probe.py` 모두 "실측 → 재발방지 테스트" 서사가 파일 안에 있다.
- `tuning.py` 엄격 로더·프로파일 드리프트 체커·OpenAPI move-only 체커 — "확인하는 코드"가 존재한다(규칙 11).
- `test_frontend_unimplemented.py:32-40` 이 서버·프론트 양쪽을 고정해 "미구현 경로" 계약이 깨지면 즉시 드러난다.

---

## 10. 확인 질문

1. **격리 주장 시점**: `3764280`·`FINAL_SUMMARY.md:57` 의 "변경 0" 측정 때 `bin/go2rtc.exe` 가 있었는가? 없었다면 그 측정은 현 구성과 불일치(규칙 9) — 재측정 기록으로 대체할 것인가?
2. **go2rtc 자동기동 가드**: 테스트·CI 에서 `ensure_go2rtc()` 를 끄는 공식 환경변수를 둘 것인가, 아니면 `_isolate` 가 monkeypatch 로 막을 것인가? (전자는 운영 코드 변경, 후자는 테스트만 변경)
3. **`rig_monitor`/`rig_replay`**: 줄걸이 RIG v2 는 로드맵에 있는 기능인가(배선 예정) — 아니면 `_archive/` 로 격리해도 되는가?
4. **HTML 부속 모듈 7종**(`/safety/quote·voice·demo·guide·setup·eval`, `/dashboard`): 현재 제품(산업안전 CCTV)에서 고객에게 노출되는 화면인가? 아니면 시연 잔재인가?
5. **`data/field_eval` 116파일 추적**: `.gitignore` 의 `data/` 와 충돌한다. 의도된 강제 추가(라벨·좌표 텍스트만)인가? 이미지가 섞였는지 `git ls-files data | grep -iE 'jpg|png'`(이번 검토에서 0건 확인) 유지 규칙을 문서화할 것인가?
6. **스레드풀 크기**: `DETECT_LOCK` 대기 중인 동기 라우트가 Starlette 기본 스레드풀(anyio 기본 40)을 다 채우면 나머지 요청이 어떻게 되는지 부하 실측이 있는가? (`scripts/pilot_load_test.py` 가 이를 재는지 확인 필요)
7. **VERSION 0.2.0 의 의미**: RELEASES 의 v1.0/v1.0.1 축과 어떤 관계인가? 어느 쪽을 대외 버전으로 쓸 것인가?
8. **테스트 662 vs `def test_` 660**: 2건 차이의 출처(동적 생성·subTest)가 무엇인지 확인해 둘 것인가?

---

## 부록 A. 광범위 except 전수 표 (223곳, AST 분류)

> 열 설명: **처리** = 삼킴(pass) / 무로그(폴백값/상태만) / 로그 / 재발생. **감싸는 첫 문장** = try 블록 첫 줄(무엇을 보호하는지). 생성 스크립트: 스크래치 `except_audit.py`.

| # | 파일:줄 | 함수 | 잡는 타입 | 처리 | 감싸는 첫 문장 |
|---|---|---|---|---|---|
| 1 | `vigent-core/agents/__init__.py:34` | `_optional` | Exception | 로그 | `mod = __import__(f'{__name__}.{modname}', fromlist=[clsname])` |
| 2 | `vigent-core/agents/analyst.py:145` | `integrate` | Exception | 삼킴(pass) | `f['citations'] = copilot.cite(f['rule']).get('citations', [])` |
| 3 | `vigent-core/agents/copilot.py:110` | `enrich_vlm` | Exception | 삼킴(pass) | `import legal_whitelist` |
| 4 | `vigent-core/agents/dispatcher.py:42` | `notify_cfg` | Exception | 무로그(폴백값/상태만) | `import yaml` |
| 5 | `vigent-core/agents/dispatcher.py:169` | `_send_telegram` | Exception | 무로그(폴백값/상태만) | `r = requests.post(f"https://api.telegram.org/bot{c['telegram_token']}/` |
| 6 | `vigent-core/agents/dispatcher.py:187` | `_send_email` | Exception | 무로그(폴백값/상태만) | `import smtplib` |
| 7 | `vigent-core/agents/dispatcher.py:203` | `_send_webhook` | Exception | 무로그(폴백값/상태만) | `r = requests.post(c['webhook_url'], json=payload, timeout=6)` |
| 8 | `vigent-core/agents/dispatcher.py:227` | `dispatch` | Exception | 무로그(폴백값/상태만) | `import alert_queue` |
| 9 | `vigent-core/agents/dispatcher.py:237` | `dispatch` | Exception | 삼킴(pass) | `import alert_queue` |
| 10 | `vigent-core/agents/dispatcher.py:303` | `_dispatch_now` | Exception | 무로그(폴백값/상태만) | `import relay` |
| 11 | `vigent-core/agents/guard.py:44` | `_sha16` | Exception | 무로그(폴백값/상태만) | `h = hashlib.sha256()` |
| 12 | `vigent-core/agents/guard.py:80` | `_guard_logger` | Exception | 로그 | `_ensure_core_on_path()` |
| 13 | `vigent-core/agents/guard.py:377` | `__init__` | Exception | 무로그(폴백값/상태만) | `import tuning as _tun` |
| 14 | `vigent-core/agents/guard.py:387` | `__init__` | Exception | 무로그(폴백값/상태만) | `conf_cfg = _tun.section('detect').get('conf') or {}` |
| 15 | `vigent-core/agents/guard.py:394` | `__init__` | Exception | 무로그(폴백값/상태만) | `self.PPE_PER_CLASS = {LABEL_NORMALIZE.get(str(k), str(k)): float(v) fo` |
| 16 | `vigent-core/agents/guard.py:400` | `__init__` | Exception | 무로그(폴백값/상태만) | `self.FIRE_SMOKE_PER_CLASS = {LABEL_NORMALIZE.get(str(k), str(k)): floa` |
| 17 | `vigent-core/agents/guard.py:428` | `__init__` | Exception | 무로그(폴백값/상태만) | `_req = _tun.section('ppe').get('required')` |
| 18 | `vigent-core/agents/guard.py:484` | `__init__` | Exception | 삼킴(pass) | `self._backend = dict((getattr(config, 'raw', {}) or {}).get('perceptio` |
| 19 | `vigent-core/agents/guard.py:493` | `__init__` | Exception | 무로그(폴백값/상태만) | `_raw_rfw = dict((getattr(config, 'raw', {}) or {}).get('perception', {` |
| 20 | `vigent-core/agents/guard.py:508` | `_tuning_value` | Exception | 무로그(폴백값/상태만) | `return cast(tuning.val(sec, key, default))` |
| 21 | `vigent-core/agents/guard.py:694` | `_dbg_write` | Exception | 삼킴(pass) | `import json as _json` |
| 22 | `vigent-core/agents/guard.py:765` | `_track_bytetrack` | Exception | 로그 | `bt.update(sv.Detections.empty())` |
| 23 | `vigent-core/agents/guard.py:902` | `_get_model` | Exception | 무로그(폴백값/상태만) | `if backend == 'rfdetr':` |
| 24 | `vigent-core/agents/guard.py:977` | `detect` | Exception | 로그 | `boxes = model.detect(image_bgr, conf=run_conf, imgsz=imgsz or self.IMG` |
| 25 | `vigent-core/agents/safety_manager.py:57` | `_grade` | Exception | 삼킴(pass) | `import safety_brain as sb` |
| 26 | `vigent-core/agents/safety_manager.py:128` | `ask` | Exception | 무로그(폴백값/상태만) | `import safety_rag` |
| 27 | `vigent-core/agents/safety_manager.py:137` | `ask` | Exception | 무로그(폴백값/상태만) | `import safety_brain as sb` |
| 28 | `vigent-core/agents/safety_manager.py:142` | `ask` | Exception | 무로그(폴백값/상태만) | `import data_engine` |
| 29 | `vigent-core/agents/safety_manager.py:157` | `ask` | Exception | 무로그(폴백값/상태만) | `import safety_brain as sb` |
| 30 | `vigent-core/agents/scribe.py:218` | `_safe_evidence_path` | Exception | 삼킴(pass) | `import logging` |
| 31 | `vigent-core/agents/scribe.py:281` | `build_assessment` | Exception | 삼킴(pass) | `import legal_whitelist` |
| 32 | `vigent-core/agents/scribe.py:307` | `build_assessment` | Exception | 삼킴(pass) | `import cv2` |
| 33 | `vigent-core/agents/scribe.py:388` | `_narrative` | Exception | 무로그(폴백값/상태만) | `import llm_provider` |
| 34 | `vigent-core/agents/scribe.py:421` | `_cite_line` | Exception | 삼킴(pass) | `import legal_whitelist as _L` |
| 35 | `vigent-core/agents/scribe.py:572` | `_checklist_detected_row` | Exception | 삼킴(pass) | `import legal_whitelist` |
| 36 | `vigent-core/agents/scribe.py:683` | `_cite` | Exception | 삼킴(pass) | `import legal_whitelist as _L` |
| 37 | `vigent-core/alert_notify.py:69` | `_loop` | Exception | 로그 | `if _sender is None:` |
| 38 | `vigent-core/alert_notify.py:152` | `submit` | Exception | 로그 | `if not alert_gate.enabled():` |
| 39 | `vigent-core/alert_queue.py:129` | `_auto_pin_sent` | Exception | 로그 | `if not bool(tuning.val('retention', 'auto_pin_sent_alerts', True)):` |
| 40 | `vigent-core/alert_queue.py:206` | `_on_dead` | Exception | 로그 | `db = _db()` |
| 41 | `vigent-core/alert_queue.py:313` | `try_send` | Exception | 무로그(폴백값/상태만) | `res = _sender(row['level'], row['message'], row['meta'])` |
| 42 | `vigent-core/alert_queue.py:338` | `_loop` | Exception | 로그 | `r = drain()` |
| 43 | `vigent-core/alert_queue.py:382` | `_reset_for_test` | Exception | 삼킴(pass) | `_conn.close()` |
| 44 | `vigent-core/behavior.py:76` | `_parse_json_behaviors` | Exception | 무로그(폴백값/상태만) | `data = json.loads(m.group(0))` |
| 45 | `vigent-core/behavior.py:156` | `analyze` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 46 | `vigent-core/camera_registry.py:42` | `_load` | Exception | 무로그(폴백값/상태만) | `return json.loads(path.read_text(encoding='utf-8'))` |
| 47 | `vigent-core/critical_controls.py:28` | `_load` | Exception | 무로그(폴백값/상태만) | `import yaml` |
| 48 | `vigent-core/detectors/rfdetr_adapter.py:65` | `_preload_supervision` | Exception | 로그 | `__import__(_mod)` |
| 49 | `vigent-core/detectors/rfdetr_adapter.py:116` | `__init__` | Exception | 무로그(폴백값/상태만) | `import ort_tune` |
| 50 | `vigent-core/detectors/rfdetr_adapter.py:206` | `__init__` | Exception | 로그 | `self.model = _OnnxRfdetrModel(onnx_path, res_req or 384)` |
| 51 | `vigent-core/detectors/rfdetr_adapter.py:224` | `__init__` | Exception | 삼킴(pass) | `self.model.optimize_for_inference()` |
| 52 | `vigent-core/device.py:37` | `pick_device` | Exception | 삼킴(pass) | `import torch` |
| 53 | `vigent-core/ergonomics.py:133` | `load_ergonomics` | Exception | 무로그(폴백값/상태만) | `import vision_loader` |
| 54 | `vigent-core/hazard_rules.py:28` | `_rule_kb` | Exception | 무로그(폴백값/상태만) | `from agents.scribe import RULE_KB` |
| 55 | `vigent-core/incident.py:37` | `_parse_accident` | Exception | 무로그(폴백값/상태만) | `obj = json.loads(m.group(0))` |
| 56 | `vigent-core/incident.py:44` | `_parse_accident` | Exception | 무로그(폴백값/상태만) | `obj = json.loads(m.group(0))` |
| 57 | `vigent-core/incident.py:61` | `_openai_accident` | Exception | 무로그(폴백값/상태만) | `import llm_provider` |
| 58 | `vigent-core/incident.py:71` | `_vlm_accident` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 59 | `vigent-core/incident.py:138` | `infer_cause` | Exception | 삼킴(pass) | `import json` |
| 60 | `vigent-core/incident.py:152` | `analyze` | Exception | 무로그(폴백값/상태만) | `import hazard_rules` |
| 61 | `vigent-core/incident.py:166` | `analyze` | Exception | 무로그(폴백값/상태만) | `import scene_vlm` |
| 62 | `vigent-core/incident.py:174` | `analyze` | Exception | 무로그(폴백값/상태만) | `import vlm_confirm` |
| 63 | `vigent-core/incident.py:205` | `analyze` | Exception | 무로그(폴백값/상태만) | `import behavior as _bhv` |
| 64 | `vigent-core/incident.py:225` | `analyze` | Exception | 무로그(폴백값/상태만) | `import safety_rag` |
| 65 | `vigent-core/legal_whitelist.py:59` | `load_whitelist` | Exception | 무로그(폴백값/상태만) | `import yaml` |
| 66 | `vigent-core/legal_whitelist.py:66` | `load_whitelist` | Exception | 무로그(폴백값/상태만) | `with open(_STATUTES, 'r', encoding='utf-8') as f:` |
| 67 | `vigent-core/legal_whitelist.py:108` | `_log_blocked` | Exception | 삼킴(pass) | `_BLOCKED_LOG.parent.mkdir(parents=True, exist_ok=True)` |
| 68 | `vigent-core/legal_whitelist.py:172` | `frequency_report` | Exception | 무로그(폴백값/상태만) | `r = json.loads(line)` |
| 69 | `vigent-core/liveguide.py:37` | `build_guidance` | Exception | 삼킴(pass) | `import ppe_check` |
| 70 | `vigent-core/llm_provider.py:82` | `_anthropic_reason` | Exception | 무로그(폴백값/상태만) | `import anthropic` |
| 71 | `vigent-core/llm_provider.py:103` | `_openai_reason` | Exception | 무로그(폴백값/상태만) | `from openai import OpenAI` |
| 72 | `vigent-core/llm_provider.py:143` | `reason_vision` | Exception | 무로그(폴백값/상태만) | `import base64` |
| 73 | `vigent-core/main.py:324` | `_install_safety_nets` | Exception | 삼킴(pass) | `loop = asyncio.get_event_loop()` |
| 74 | `vigent-core/main.py:354` | `_write_windows_event` | Exception | 삼킴(pass) | `r = subprocess.run(['eventcreate', '/T', 'ERROR', '/ID', '1000', '/L',` |
| 75 | `vigent-core/main.py:362` | `_write_windows_event` | Exception | 무로그(폴백값/상태만) | `safe = text.replace("'", "''")` |
| 76 | `vigent-core/main.py:379` | `_send_startup_alert` | Exception | 무로그(폴백값/상태만) | `from agents.dispatcher import DispatcherAgent` |
| 77 | `vigent-core/main.py:393` | `_notify_startup_failure` | Exception | 삼킴(pass) | `st.update(json.loads(_STARTUP_FAIL_STATE.read_text(encoding='utf-8')))` |
| 78 | `vigent-core/main.py:415` | `_notify_startup_failure` | Exception | 삼킴(pass) | `_STARTUP_FAIL_STATE.parent.mkdir(parents=True, exist_ok=True)` |
| 79 | `vigent-core/main.py:425` | `_shutdown` | Exception | 로그 | `import worker as _w` |
| 80 | `vigent-core/main.py:429` | `_shutdown` | Exception | 로그 | `_cameras_router.stop_go2rtc()` |
| 81 | `vigent-core/main.py:441` | `_shutdown` | Exception | 로그 | `fn()` |
| 82 | `vigent-core/main.py:450` | `_required` | Exception | 로그 | `fn()` |
| 83 | `vigent-core/main.py:460` | `_optional` | Exception | 로그 | `fn()` |
| 84 | `vigent-core/main.py:473` | `_startup` | Exception | 로그 | `bundle = _load_theme(DEFAULT_THEME)` |
| 85 | `vigent-core/main.py:496` | `_start_workers_after_warmup` | Exception | 로그 | `_restore = _cameras_router.autostart_enabled()` |
| 86 | `vigent-core/main.py:504` | `_start_workers_after_warmup` | Exception | 로그 | `import worker as _w` |
| 87 | `vigent-core/ml/calibrate_angles.py:55` | `measure_folder` | Exception | 무로그(폴백값/상태만) | `res = lm.detect(mp.Image.create_from_file(str(fp)))` |
| 88 | `vigent-core/ml/eval_ergonomics.py:85` | `eval_pose_detection` | Exception | 무로그(폴백값/상태만) | `import mediapipe as mp` |
| 89 | `vigent-core/ml/vlm_risk_summary.py:43` | `_load_vlm_config` | Exception | 삼킴(pass) | `import yaml` |
| 90 | `vigent-core/ml/vlm_risk_summary.py:58` | `prompt_for_theme` | Exception | 무로그(폴백값/상태만) | `import yaml` |
| 91 | `vigent-core/ml/vlm_risk_summary.py:69` | `_enrich_with_law` | Exception | 무로그(폴백값/상태만) | `import sys` |
| 92 | `vigent-core/ml/vlm_risk_summary.py:184` | `_ask_openai` | Exception | 무로그(폴백값/상태만) | `import sys` |
| 93 | `vigent-core/ml/vlm_risk_summary.py:209` | `quick` | Exception | 무로그(폴백값/상태만) | `self._ensure_loaded()` |
| 94 | `vigent-core/ml/vlm_risk_summary.py:246` | `summarize` | Exception | 무로그(폴백값/상태만) | `safe = _safe_image(img_path)` |
| 95 | `vigent-core/ort_tune.py:43` | `intra_threads` | Exception | 무로그(폴백값/상태만) | `return max(1, int(tuning.val('onnxruntime', 'intra_op_threads', 4)))` |
| 96 | `vigent-core/ort_tune.py:58` | `session_options` | Exception | 무로그(폴백값/상태만) | `import onnxruntime as ort` |
| 97 | `vigent-core/ort_tune.py:86` | `_find_tools` | Exception | 무로그(폴백값/상태만) | `v = getattr(obj, name)` |
| 98 | `vigent-core/ort_tune.py:104` | `retune` | Exception | 무로그(폴백값/상태만) | `import onnxruntime as ort` |
| 99 | `vigent-core/ort_tune.py:112` | `retune` | Exception | 로그 | `t.session = ort.InferenceSession(path_or_bytes=t.onnx_model, sess_opti` |
| 100 | `vigent-core/pose/rtmpose_adapter.py:36` | `__init__` | Exception | 삼킴(pass) | `import sys` |
| 101 | `vigent-core/ppe_check.py:62` | `get_rules` | Exception | 삼킴(pass) | `import yaml` |
| 102 | `vigent-core/ppe_check.py:75` | `save_rules` | Exception | 삼킴(pass) | `import yaml` |
| 103 | `vigent-core/ppe_check.py:100` | `_vlm_status_batch` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 104 | `vigent-core/privacy.py:72` | `_get_cascade` | Exception | 무로그(폴백값/상태만) | `from pathlib import Path` |
| 105 | `vigent-core/privacy.py:109` | `anonymize_faces` | Exception | 무로그(폴백값/상태만) | `x1, y1, x2, y2 = (float(v) for v in list(b)[:4])` |
| 106 | `vigent-core/privacy.py:134` | `anonymize_faces` | Exception | 로그 | `with _lock:` |
| 107 | `vigent-core/privacy.py:142` | `anonymize_faces` | Exception | 삼킴(pass) | `import vlog` |
| 108 | `vigent-core/privacy.py:150` | `anonymize_faces` | Exception | 로그 | `out = frame.copy()` |
| 109 | `vigent-core/privacy.py:158` | `anonymize_faces` | Exception | 삼킴(pass) | `import vlog` |
| 110 | `vigent-core/privacy.py:210` | `_note_failure` | Exception | 삼킴(pass) | `import alert_notify` |
| 111 | `vigent-core/privacy.py:273` | `_protected_dirs` | Exception | 삼킴(pass) | `import data_paths` |
| 112 | `vigent-core/privacy.py:288` | `_efs_encrypted` | Exception | 무로그(폴백값/상태만) | `out = subprocess.run(['cipher', '/c', str(path)], capture_output=True,` |
| 113 | `vigent-core/privacy.py:317` | `_bitlocker_status` | Exception | 삼킴(pass) | `r = subprocess.run(['powershell', '-NoProfile', '-Command', f"(Get-Bit` |
| 114 | `vigent-core/readiness.py:83` | `required_weights_missing` | Exception | 무로그(폴백값/상태만) | `man = json.loads(man_path.read_text(encoding='utf-8'))` |
| 115 | `vigent-core/readiness.py:121` | `warmup` | Exception | 로그 | `import worker as _w` |
| 116 | `vigent-core/readiness.py:141` | `warmup` | Exception | 로그 | `for slot in dets:` |
| 117 | `vigent-core/readiness.py:158` | `_run` | Exception | 로그 | `on_ready()` |
| 118 | `vigent-core/relay.py:81` | `_http` | Exception | 무로그(폴백값/상태만) | `req = urllib.request.Request(url, method=str(_cfg('method', 'GET')).up` |
| 119 | `vigent-core/retention.py:212` | `_pinned_paths` | Exception | 무로그(폴백값/상태만) | `import data_engine` |
| 120 | `vigent-core/retention.py:349` | `sweep` | Exception | 로그 | `import alert_queue` |
| 121 | `vigent-core/retention.py:375` | `sweep` | Exception | 삼킴(pass) | `import vlog` |
| 122 | `vigent-core/retention_scheduler.py:57` | `overdue` | Exception | 무로그(폴백값/상태만) | `import retention` |
| 123 | `vigent-core/retention_scheduler.py:104` | `_loop` | Exception | 로그 | `_run_once()` |
| 124 | `vigent-core/rfdetr_service.py:73` | `_ensure` | Exception | 삼킴(pass) | `self._model.optimize_for_inference()` |
| 125 | `vigent-core/rfdetr_service.py:102` | `detect` | Exception | 삼킴(pass) | `tracked = self._tracker.update(det)` |
| 126 | `vigent-core/rfdetr_service.py:186` | `_loop` | BaseException | 무로그(폴백값/상태만) | `box[0] = fn(*args, **kw)` |
| 127 | `vigent-core/rfdetr_service.py:270` | `vlm_text` | Exception | 무로그(폴백값/상태만) | `data = vlm.summarize_bgr(image_bgr, prompt=prompt, **kwargs)` |
| 128 | `vigent-core/routers/cameras.py:37` | `_g2_register` | Exception | 삼킴(pass) | `import urllib.parse` |
| 129 | `vigent-core/routers/cameras.py:48` | `_g2_unregister` | Exception | 삼킴(pass) | `import urllib.parse` |
| 130 | `vigent-core/routers/cameras.py:263` | `_lan_ip` | Exception | 무로그(폴백값/상태만) | `s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)` |
| 131 | `vigent-core/routers/cameras.py:288` | `_close_logf` | Exception | 삼킴(pass) | `if _G2_LOGF is not None:` |
| 132 | `vigent-core/routers/cameras.py:302` | `_g2_port_busy` | Exception | 무로그(폴백값/상태만) | `with socket.create_connection(('127.0.0.1', _G2_PORT), timeout=0.5):` |
| 133 | `vigent-core/routers/cameras.py:313` | `_pid_alive` | Exception | 무로그(폴백값/상태만) | `import psutil` |
| 134 | `vigent-core/routers/cameras.py:326` | `_terminate_pid` | Exception | 무로그(폴백값/상태만) | `import psutil` |
| 135 | `vigent-core/routers/cameras.py:333` | `_read_pidfile` | Exception | 무로그(폴백값/상태만) | `return int(_g2_pidfile().read_text(encoding='utf-8').strip())` |
| 136 | `vigent-core/routers/cameras.py:369` | `ensure_go2rtc` | Exception | 무로그(폴백값/상태만) | `runtime.parent.mkdir(parents=True, exist_ok=True)` |
| 137 | `vigent-core/routers/cameras.py:380` | `ensure_go2rtc` | Exception | 삼킴(pass) | `import tuning` |
| 138 | `vigent-core/routers/cameras.py:390` | `ensure_go2rtc` | Exception | 삼킴(pass) | `_g2_pidfile().write_text(str(proc.pid), encoding='utf-8')` |
| 139 | `vigent-core/routers/cameras.py:394` | `ensure_go2rtc` | Exception | 무로그(폴백값/상태만) | `import subprocess` |
| 140 | `vigent-core/routers/cameras.py:409` | `stop_go2rtc` | Exception | 삼킴(pass) | `if p.poll() is None:` |
| 141 | `vigent-core/routers/cameras.py:419` | `stop_go2rtc` | Exception | 삼킴(pass) | `_g2_pidfile().unlink(missing_ok=True)` |
| 142 | `vigent-core/routers/cameras.py:435` | `autostart_enabled` | Exception | 무로그(폴백값/상태만) | `_start(c['id'])` |
| 143 | `vigent-core/routers/detect.py:39` | `_multi_pose` | Exception | 무로그(폴백값/상태만) | `from pathlib import Path` |
| 144 | `vigent-core/routers/detect.py:56` | `_multi_pose` | Exception | 무로그(폴백값/상태만) | `res = _POSE_MODEL.predict(img, verbose=False, device='cpu', imgsz=imgs` |
| 145 | `vigent-core/routers/incident.py:39` | `safety_incident_frame` | Exception | 무로그(폴백값/상태만) | `with _DETECT_LOCK:` |
| 146 | `vigent-core/routers/incident.py:82` | `safety_incident_analyze` | Exception | 무로그(폴백값/상태만) | `with _DETECT_LOCK:` |
| 147 | `vigent-core/routers/ppe.py:63` | `safety_ppe_check` | Exception | 무로그(폴백값/상태만) | `with _DETECT_LOCK:` |
| 148 | `vigent-core/routers/recognition.py:26` | `allowed_rules` | Exception | 무로그(폴백값/상태만) | `from agents.scribe import RULE_KB` |
| 149 | `vigent-core/routers/safety_core.py:141` | `safety_live_analyze` | Exception | 무로그(폴백값/상태만) | `obj = _json.loads(m.group(0))` |
| 150 | `vigent-core/routers/safety_core.py:143` | `safety_live_analyze` | Exception | 무로그(폴백값/상태만) | `import llm_provider` |
| 151 | `vigent-core/routers/safety_core.py:156` | `safety_live_analyze` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 152 | `vigent-core/routers/safety_core.py:448` | `safety_eval_run` | Exception | 무로그(폴백값/상태만) | `with _DETECT_LOCK:` |
| 153 | `vigent-core/routers/safety_core.py:500` | `safety_voice_scene` | Exception | 무로그(폴백값/상태만) | `with _DETECT_LOCK:` |
| 154 | `vigent-core/routers/safety_core.py:545` | `safety_sensor` | Exception | 삼킴(pass) | `data_engine.log_event(rule, level='critical', score=value, site=site, ` |
| 155 | `vigent-core/routers/safety_core.py:556` | `safety_sensor` | Exception | 삼킴(pass) | `import alert_notify` |
| 156 | `vigent-core/routers/safety_core.py:674` | `safety_brain_inspect` | Exception | 삼킴(pass) | `import alert_notify` |
| 157 | `vigent-core/routers/system.py:15` | `_startup_warnings` | Exception | 무로그(폴백값/상태만) | `import app_state as _as` |
| 158 | `vigent-core/routers/system.py:48` | `health` | Exception | 삼킴(pass) | `man = json.loads((_ROOT / 'weights_manifest.json').read_text(encoding=` |
| 159 | `vigent-core/routers/system.py:77` | `health` | Exception | 삼킴(pass) | `_gs = _g.status()` |
| 160 | `vigent-core/routers/system.py:84` | `health` | Exception | 무로그(폴백값/상태만) | `import retention_scheduler as _rs` |
| 161 | `vigent-core/routers/system.py:92` | `health` | Exception | 무로그(폴백값/상태만) | `import llm_provider as _llm` |
| 162 | `vigent-core/routers/system.py:116` | `health` | Exception | 삼킴(pass) | `import tuning as _tuning` |
| 163 | `vigent-core/routers/system.py:133` | `health` | Exception | 무로그(폴백값/상태만) | `import privacy as _pv` |
| 164 | `vigent-core/routers/system.py:141` | `health` | Exception | 무로그(폴백값/상태만) | `import relay as _rl` |
| 165 | `vigent-core/routers/system.py:160` | `health` | Exception | 무로그(폴백값/상태만) | `import alert_queue` |
| 166 | `vigent-core/routers/system.py:167` | `health` | Exception | 무로그(폴백값/상태만) | `_disp = bundle['agents'].get('Dispatcher') if bundle else None` |
| 167 | `vigent-core/routers/system.py:173` | `health` | Exception | 무로그(폴백값/상태만) | `import alert_notify` |
| 168 | `vigent-core/routers/system.py:195` | `health` | Exception | 무로그(폴백값/상태만) | `import health_status` |
| 169 | `vigent-core/routers/tapo.py:24` | `_resolve_src` | Exception | 삼킴(pass) | `import camera_registry as _reg` |
| 170 | `vigent-core/routers/tapo.py:44` | `_ensure_stream` | Exception | 삼킴(pass) | `import urllib.parse` |
| 171 | `vigent-core/routers/tapo.py:55` | `tapo_videortc_js` | Exception | 로그 | `with urllib.request.urlopen('http://127.0.0.1:1984/video-rtc.js', time` |
| 172 | `vigent-core/routers/tapo.py:98` | `tapo_ws` | Exception | 삼킴(pass) | `async with websockets.connect(up_url) as up:` |
| 173 | `vigent-core/routers/tapo.py:119` | `tapo_webrtc` | Exception | 로그 | `with urllib.request.urlopen(req, timeout=10) as r:` |
| 174 | `vigent-core/routers/zone.py:52` | `_go2rtc_fixed_source` | Exception | 무로그(폴백값/상태만) | `import yaml` |
| 175 | `vigent-core/routers/zone.py:63` | `_worker_owns` | Exception | 무로그(폴백값/상태만) | `import worker as _w` |
| 176 | `vigent-core/routers/zone.py:74` | `_worker_owns` | Exception | 무로그(폴백값/상태만) | `import camera_registry as _reg` |
| 177 | `vigent-core/safety_brain.py:26` | `_kb` | Exception | 무로그(폴백값/상태만) | `_KB_CACHE = json.loads(_KB_PATH.read_text(encoding='utf-8'))` |
| 178 | `vigent-core/safety_brain.py:145` | `_cases` | Exception | 무로그(폴백값/상태만) | `p = _ROOT / 'config' / 'corpus' / 'accident_cases.json'` |
| 179 | `vigent-core/safety_brain.py:265` | `assess` | Exception | 무로그(폴백값/상태만) | `import safety_rag` |
| 180 | `vigent-core/safety_rag.py:27` | `_load` | Exception | 무로그(폴백값/상태만) | `return json.loads((_CORPUS_DIR / name).read_text(encoding='utf-8'))` |
| 181 | `vigent-core/safety_rag.py:171` | `search` | Exception | 무로그(폴백값/상태만) | `if self.model is None:` |
| 182 | `vigent-core/scene_vlm.py:46` | `_vlm_understand` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 183 | `vigent-core/scene_vlm.py:56` | `_vlm_understand` | Exception | 무로그(폴백값/상태만) | `data = json.loads(m.group(0))` |
| 184 | `vigent-core/scene_vlm.py:84` | `understand` | Exception | 무로그(폴백값/상태만) | `from ml.vlm_risk_summary import format_facts` |
| 185 | `vigent-core/scene_vlm.py:113` | `answer_questions` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 186 | `vigent-core/scene_vlm.py:126` | `answer_questions` | Exception | 무로그(폴백값/상태만) | `arr = json.loads(m.group(0))` |
| 187 | `vigent-core/scene_vlm.py:133` | `answer_questions` | Exception | 무로그(폴백값/상태만) | `idx = int(item.get('n', 0)) - 1` |
| 188 | `vigent-core/setup_console.py:22` | `_yaml_load` | Exception | 무로그(폴백값/상태만) | `import yaml` |
| 189 | `vigent-core/starvation_guard.py:59` | `_release_go2rtc_slot` | Exception | 로그 | `req = urllib.request.Request(f'http://127.0.0.1:1984/api/streams?name=` |
| 190 | `vigent-core/starvation_guard.py:87` | `_restart_worker` | Exception | 로그 | `import camera_registry as _reg` |
| 191 | `vigent-core/starvation_guard.py:101` | `_escalate` | Exception | 로그 | `subprocess.Popen(_RESTART_CMD, shell=True)` |
| 192 | `vigent-core/starvation_guard.py:111` | `_tick` | Exception | 무로그(폴백값/상태만) | `ws = _w.manager.status()` |
| 193 | `vigent-core/starvation_guard.py:141` | `_loop` | Exception | 로그 | `_tick()` |
| 194 | `vigent-core/tuning.py:90` | `val` | Exception | 무로그(폴백값/상태만) | `return type(default)(os.environ[env])` |
| 195 | `vigent-core/vlm_confirm.py:100` | `confirm` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 196 | `vigent-core/vlm_confirm.py:104` | `confirm` | Exception | 무로그(폴백값/상태만) | `data = rfdetr_service.vlm.summarize_bgr(image_bgr, prompt=build_prompt` |
| 197 | `vigent-core/vlm_confirm.py:131` | `describe_scene` | Exception | 무로그(폴백값/상태만) | `import rfdetr_service` |
| 198 | `vigent-core/vlog.py:32` | `setup` | Exception | 삼킴(pass) | `_LOG_DIR.mkdir(parents=True, exist_ok=True)` |
| 199 | `vigent-core/vlog.py:46` | `setup` | Exception | 삼킴(pass) | `fh = logging.handlers.RotatingFileHandler(_LOG_DIR / 'vigent.log', max` |
| 200 | `vigent-core/vlog.py:71` | `_events` | Exception | 무로그(폴백값/상태만) | `_LOG_DIR.mkdir(parents=True, exist_ok=True)` |
| 201 | `vigent-core/vlog.py:83` | `log_event` | Exception | 삼킴(pass) | `lg.info(json.dumps(event, ensure_ascii=False, default=str))` |
| 202 | `vigent-core/web_util.py:60` | `decode_data_url` | Exception | 무로그(폴백값/상태만) | `buf = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)` |
| 203 | `vigent-core/web_util.py:133` | `_load_allowed_webhook_hosts` | Exception | 무로그(폴백값/상태만) | `f = _ROOT / 'config' / 'security.json'` |
| 204 | `vigent-core/web_util.py:175` | `product_version` | Exception | 무로그(폴백값/상태만) | `return (_ROOT / 'VERSION').read_text(encoding='utf-8').strip()` |
| 205 | `vigent-core/worker.py:385` | `persons` | Exception | 무로그(폴백값/상태만) | `import sys` |
| 206 | `vigent-core/worker.py:399` | `persons` | Exception | 무로그(폴백값/상태만) | `ppl = self._m.persons(frame, bboxes=list(boxes))` |
| 207 | `vigent-core/worker.py:428` | `__init__` | Exception | 무로그(폴백값/상태만) | `self._hold_sec = float(cfg.get('hold_sec', 3)) if isinstance(cfg, dict` |
| 208 | `vigent-core/worker.py:445` | `update` | Exception | 무로그(폴백값/상태만) | `persons = _posemodel.persons(frame, boxes)` |
| 209 | `vigent-core/worker.py:457` | `update` | Exception | 무로그(폴백값/상태만) | `a = self._erg.assess(xy, cf, self._joints)` |
| 210 | `vigent-core/worker.py:662` | `_open` | Exception | 로그 | `cap.set(cv2.CAP_PROP_BUFFERSIZE, _CAP_BUFFERSIZE)` |
| 211 | `vigent-core/worker.py:702` | `_run` | Exception | 로그 | `cap.release()` |
| 212 | `vigent-core/worker.py:722` | `_run` | Exception | 로그 | `cap.release()` |
| 213 | `vigent-core/worker.py:901` | `_hang_watch` | Exception | 로그 | `if self._cap is not None:` |
| 214 | `vigent-core/worker.py:919` | `_run_supervised` | Exception | 로그 | `self.state['running'] = True` |
| 215 | `vigent-core/worker.py:967` | `_pose_loop` | Exception | 삼킴(pass) | `fired += self._pose_etrack.update(frame, t0, person_boxes)` |
| 216 | `vigent-core/worker.py:992` | `_process_frame` | Exception | 로그 | `ctx.dataset_dir.mkdir(parents=True, exist_ok=True)` |
| 217 | `vigent-core/worker.py:1082` | `_process_frame` | Exception | 로그 | `import rfdetr_service as _rfs` |
| 218 | `vigent-core/worker.py:1134` | `_process_frame` | Exception | 로그 | `if ctx.collect_on and t0 - ctx.last_collect >= ctx.collect_every:` |
| 219 | `vigent-core/worker.py:1200` | `_setup_run` | Exception | 로그 | `cap.set(cv2.CAP_PROP_BUFFERSIZE, _CAP_BUFFERSIZE)` |
| 220 | `vigent-core/worker.py:1265` | `_loop` | Exception | 로그 | `cap.release()` |
| 221 | `vigent-core/worker.py:1274` | `_loop` | Exception | 로그 | `cap.set(cv2.CAP_PROP_BUFFERSIZE, _CAP_BUFFERSIZE)` |
| 222 | `vigent-core/worker.py:1298` | `_loop` | Exception | 로그 | `while not self._stop.is_set() and (not self._restart_req.is_set()):` |
| 223 | `vigent-core/worker.py:1322` | `load_site_config` | Exception | 무로그(폴백값/상태만) | `import yaml` |


## 부록 B. 코어 모듈 ↔ 테스트 파일 매핑 (84모듈 / 97테스트 파일)

> 참조 판정 = 테스트 파일이 해당 모듈을 `import`/`from … import`/`mock.patch("모듈.…")` 로 직접 가리키는 경우. "**없음**" = 직접 참조 테스트 0(스모크·간접 실행은 제외). 두 번째 표는 파일별 `TestCase` 직접 상속 클래스의 test 메서드 수(AST, 간접 상속은 미집계 → 합 619 < 662).

| 코어 모듈 | 참조 테스트 파일(수) | 파일 |
|---|---|---|
| `agents.analyst` | 1 | test_analyst.py |
| `agents.base` | 0 | **없음** |
| `agents.copilot` | 0 | **없음** |
| `agents.dispatcher` | 7 | test_alert_delivery_hardening.py, test_alert_queue.py, test_bypass_paths_gated.py, test_dispatch_retry_remote_only.py, test_machine_guard.py, test_redact_secrets.py, test_scribe_copilot_dispatcher.py |
| `agents.guard` | 16 | test_adaptive_ema.py, test_bytetrack_empty_frame_update.py, test_cross_validate_ppe.py, test_guard_logger_syspath.py, test_guard_tuning_partial_failure.py, test_hysteresis.py, test_isolated_detect.py, test_passthrough_grid_key.py, test_person_ensemble.py, test_ppe_missing_labels.py, test_ppe_required_config.py, test_rfdetr_onnx_parity.py, test_slot_degraded.py, test_slot_load_failure.py, test_track_key_isolation.py, test_track_key_ttl_sweep.py |
| `agents.safety_manager` | 0 | **없음** |
| `agents.scribe` | 1 | test_scribe_path_traversal.py |
| `alert_gate` | 5 | test_alert_wiring.py, test_browser_intrusion_ownership.py, test_bypass_paths_gated.py, test_notify_queue_drop.py, test_track_scoped_cooldown.py |
| `alert_notify` | 6 | test_alert_wiring.py, test_browser_intrusion_ownership.py, test_bypass_paths_gated.py, test_notify_queue_drop.py, test_privacy_failure_policy.py, test_startup_services.py |
| `alert_queue` | 6 | test_alert_delivery_hardening.py, test_alert_queue.py, test_dispatch_retry_remote_only.py, test_pin_routes_and_auto_pin.py, test_retention_queue_logs.py, test_startup_services.py |
| `app_state` | 2 | test_startup_services.py, test_warmup_holds_detect_lock.py |
| `audit_store` | 0 | **없음** |
| `auth_session` | 2 | test_browser_session_auth.py, test_ws_auth.py |
| `behavior` | 0 | **없음** |
| `camera_registry` | 3 | test_browser_intrusion_ownership.py, test_constants_config.py, test_worker_credential_masking.py |
| `critical_controls` | 0 | **없음** |
| `dashboard` | 0 | **없음** |
| `data_engine` | 12 | test_browser_event_hygiene.py, test_browser_intrusion_ownership.py, test_bypass_paths_gated.py, test_console_pin.py, test_data_engine_report.py, test_pin_routes_and_auto_pin.py, test_privacy_failure_policy.py, test_retention.py, test_retention_pin_hardening.py, test_safety_review_fixes.py, test_worker_process_frame.py, test_worker_zone_tile.py |
| `data_paths` | 1 | test_field_eval_group.py |
| `demo` | 0 | **없음** |
| `detectors.base` | 0 | **없음** |
| `detectors.rfdetr_adapter` | 1 | test_rfdetr_onnx_parity.py |
| `detectors.yolo_adapter` | 0 | **없음** |
| `device` | 0 | **없음** |
| `ergonomics` | 0 | **없음** |
| `evaluator` | 0 | **없음** |
| `hazard_rules` | 0 | **없음** |
| `health_status` | 7 | test_alert_delivery_hardening.py, test_alert_queue.py, test_health_detect_alive.py, test_notify_queue_drop.py, test_safety_review_fixes.py, test_slot_load_failure.py, test_starvation_guard.py |
| `hub` | 0 | **없음** |
| `incident` | 0 | **없음** |
| `isolated_detect` | 1 | test_isolated_detect.py |
| `labels` | 0 | **없음** |
| `legal_whitelist` | 0 | **없음** |
| `liveguide` | 0 | **없음** |
| `llm_provider` | 0 | **없음** |
| `main` | 15 | test_browser_event_hygiene.py, test_browser_intrusion_ownership.py, test_browser_session_auth.py, test_bypass_paths_gated.py, test_capture_timeouts.py, test_console_pin.py, test_endpoints_smoke.py, test_frontend_unimplemented.py, test_machine_guard.py, test_pin_routes_and_auto_pin.py, test_retention_scheduler.py, test_security_gate.py, test_startup_failure_notify.py, test_startup_services.py, test_ws_auth.py |
| `ml.calibrate_angles` | 0 | **없음** |
| `ml.eval_ergonomics` | 0 | **없음** |
| `ml.merge_retrain_data` | 0 | **없음** |
| `ml.train_retrain` | 0 | **없음** |
| `ml.vlm_risk_summary` | 0 | **없음** |
| `ort_tune` | 1 | test_ort_tune.py |
| `pose.rtmpose_adapter` | 0 | **없음** |
| `ppe_check` | 0 | **없음** |
| `press_zone` | 1 | test_press_zone.py |
| `privacy` | 3 | test_field_eval_group.py, test_privacy_anonymize.py, test_privacy_failure_policy.py |
| `proximity` | 2 | test_constants_config.py, test_proximity_driver.py |
| `quote` | 0 | **없음** |
| `readiness` | 5 | test_detector_visibility.py, test_launcher_env_parity.py, test_readiness_warmup.py, test_startup_services.py, test_warmup_holds_detect_lock.py |
| `relay` | 2 | test_dispatch_retry_remote_only.py, test_relay.py |
| `retention` | 8 | test_field_eval_group.py, test_pin_routes_and_auto_pin.py, test_retention.py, test_retention_execute.py, test_retention_overdue.py, test_retention_pin_hardening.py, test_retention_queue_logs.py, test_tuning_strict_loader.py |
| `retention_scheduler` | 3 | test_retention_overdue.py, test_retention_scheduler.py, test_startup_services.py |
| `rfdetr_service` | 2 | test_vlm_text_helper.py, test_worker_zone_tile.py |
| `rig_monitor` | 1 | test_rig_monitor.py |
| `rig_replay` | 1 | test_rig_replay.py |
| `routers.cameras` | 3 | test_capture_timeouts.py, test_constants_config.py, test_go2rtc_lifecycle.py |
| `routers.detect` | 0 | **없음** |
| `routers.dispatch` | 0 | **없음** |
| `routers.incident` | 0 | **없음** |
| `routers.ppe` | 0 | **없음** |
| `routers.recognition` | 0 | **없음** |
| `routers.safety_core` | 2 | test_bypass_paths_gated.py, test_console_pin.py |
| `routers.system` | 2 | test_detector_visibility.py, test_slot_load_failure.py |
| `routers.tapo` | 0 | **없음** |
| `routers.tbm` | 0 | **없음** |
| `routers.zone` | 2 | test_browser_event_hygiene.py, test_browser_intrusion_ownership.py |
| `runtime_config` | 1 | test_runtime_config.py |
| `safety_brain` | 0 | **없음** |
| `safety_rag` | 0 | **없음** |
| `scene_vlm` | 0 | **없음** |
| `setup_console` | 0 | **없음** |
| `starvation_guard` | 2 | test_startup_services.py, test_starvation_guard.py |
| `tbm_store` | 0 | **없음** |
| `tuning` | 8 | test_baseline_freshness.py, test_constants_config.py, test_detector_visibility.py, test_guard_tuning_partial_failure.py, test_motion_tracker.py, test_ppe_required_config.py, test_retention_overdue.py, test_tuning_strict_loader.py |
| `vision_loader` | 9 | test_analyst.py, test_data_engine_report.py, test_ergonomic_level_low.py, test_guard_tuning_partial_failure.py, test_machine_guard.py, test_passthrough_grid_key.py, test_ppe_required_config.py, test_scribe_copilot_dispatcher.py, test_vision_loader_theme.py |
| `vlm_confirm` | 0 | **없음** |
| `vlog` | 1 | test_isolate_logs.py |
| `voice` | 0 | **없음** |
| `web_util` | 2 | test_json_charset.py, test_web_util_upload_limit.py |
| `worker` | 25 | test_alert_wiring.py, test_browser_intrusion_ownership.py, test_camera_delete_no_ghost.py, test_camera_motion.py, test_capture_timeouts.py, test_constants_config.py, test_cooldown_key_pruning.py, test_detector_visibility.py, test_ergonomic_level_low.py, test_motion_tracker.py, test_passthrough_grid_key.py, test_ppe_missing_labels.py, test_privacy_anonymize.py, test_privacy_failure_policy.py, test_readiness_warmup.py, test_safety_review_fixes.py, test_startup_services.py, test_starvation_guard.py, test_track_scoped_cooldown.py, test_worker_credential_masking.py, test_worker_lifecycle_guards.py, test_worker_process_frame.py, test_worker_zone_tile.py, test_zone_debounce.py, test_zone_subject_pruning.py |
| `ws_auth` | 0 | **없음** |
| `zone_debounce` | 5 | test_alert_wiring.py, test_passthrough_grid_key.py, test_track_scoped_cooldown.py, test_zone_debounce.py, test_zone_subject_pruning.py |
| `zone_geom` | 0 | **없음** |
| `zone_tile` | 1 | test_zone_tile.py |


| 테스트 파일 | 테스트 수 |
|---|---|
| test_adaptive_ema.py | 3 |
| test_alert_delivery_hardening.py | 10 |
| test_alert_queue.py | 3 |
| test_alert_wiring.py | 29 |
| test_analyst.py | 6 |
| test_baseline_freshness.py | 4 |
| test_browser_event_hygiene.py | 5 |
| test_browser_intrusion_ownership.py | 7 |
| test_browser_session_auth.py | 8 |
| test_bypass_paths_gated.py | 0 |
| test_bytetrack_empty_frame_update.py | 4 |
| test_camera_delete_no_ghost.py | 5 |
| test_camera_motion.py | 5 |
| test_capture_timeouts.py | 6 |
| test_console_pin.py | 2 |
| test_constants_config.py | 8 |
| test_cooldown_key_pruning.py | 3 |
| test_cross_validate_ppe.py | 3 |
| test_data_engine_report.py | 6 |
| test_detector_visibility.py | 12 |
| test_dispatch_retry_remote_only.py | 3 |
| test_endpoints_smoke.py | 8 |
| test_ergonomic_level_low.py | 2 |
| test_eval_tracking.py | 9 |
| test_field_eval_group.py | 7 |
| test_frontend_privacy.py | 2 |
| test_frontend_unimplemented.py | 3 |
| test_go2rtc_lifecycle.py | 5 |
| test_go2rtc_manifest.py | 3 |
| test_guard_logger_syspath.py | 4 |
| test_guard_tuning_partial_failure.py | 2 |
| test_health_detect_alive.py | 16 |
| test_hysteresis.py | 3 |
| test_install_constraints.py | 3 |
| test_isolate_logs.py | 3 |
| test_isolated_detect.py | 2 |
| test_json_charset.py | 5 |
| test_launcher_env_parity.py | 7 |
| test_machine_guard.py | 8 |
| test_measurement_hygiene.py | 6 |
| test_motion_tracker.py | 13 |
| test_notify_queue_drop.py | 2 |
| test_ort_tune.py | 9 |
| test_passthrough_grid_key.py | 9 |
| test_person_ensemble.py | 4 |
| test_pin_routes_and_auto_pin.py | 6 |
| test_ppe_missing_labels.py | 3 |
| test_ppe_required_config.py | 13 |
| test_press_zone.py | 7 |
| test_privacy_anonymize.py | 16 |
| test_privacy_failure_policy.py | 9 |
| test_profile_drift.py | 5 |
| test_proximity_driver.py | 14 |
| test_readiness_warmup.py | 11 |
| test_redact_secrets.py | 6 |
| test_relay.py | 0 |
| test_retention.py | 11 |
| test_retention_execute.py | 0 |
| test_retention_overdue.py | 5 |
| test_retention_pin_hardening.py | 5 |
| test_retention_queue_logs.py | 5 |
| test_retention_scheduler.py | 13 |
| test_rfdetr_onnx_parity.py | 1 |
| test_rig_monitor.py | 5 |
| test_rig_replay.py | 6 |
| test_runtime_config.py | 5 |
| test_safety_review_fixes.py | 17 |
| test_scribe_copilot_dispatcher.py | 7 |
| test_scribe_path_traversal.py | 4 |
| test_security_gate.py | 6 |
| test_service_entry.py | 5 |
| test_slot_degraded.py | 5 |
| test_slot_load_failure.py | 11 |
| test_soak_report.py | 5 |
| test_startup_failure_notify.py | 5 |
| test_startup_services.py | 7 |
| test_starvation_guard.py | 9 |
| test_track_debug_covers_person.py | 4 |
| test_track_key_isolation.py | 2 |
| test_track_key_ttl_sweep.py | 2 |
| test_track_scoped_cooldown.py | 8 |
| test_tuning_strict_loader.py | 8 |
| test_verify_service_script.py | 9 |
| test_vision_loader_theme.py | 4 |
| test_vlm_format_facts.py | 3 |
| test_vlm_text_helper.py | 7 |
| test_warmup_holds_detect_lock.py | 2 |
| test_web_util_upload_limit.py | 4 |
| test_worker_credential_masking.py | 5 |
| test_worker_lifecycle_guards.py | 6 |
| test_worker_process_frame.py | 4 |
| test_worker_zone_tile.py | 3 |
| test_ws_auth.py | 6 |
| test_zone_debounce.py | 13 |
| test_zone_edit_guard.py | 23 |
| test_zone_subject_pruning.py | 5 |
| test_zone_tile.py | 7 |


## 부록 C. 커버리지 전체 표 (`coverage report --omit="*/vendor/*" --sort=cover`, 2026-09-08)

```
Name                                      Stmts   Miss  Cover
-------------------------------------------------------------
vigent-core\behavior.py                      64     64     0%
vigent-core\critical_controls.py             29     29     0%
vigent-core\dashboard.py                    114    114     0%
vigent-core\demo.py                          55     55     0%
vigent-core\detectors\yolo_adapter.py        28     28     0%
vigent-core\evaluator.py                     51     51     0%
vigent-core\hazard_rules.py                  46     46     0%
vigent-core\incident.py                     162    162     0%
vigent-core\labels.py                         8      8     0%
vigent-core\liveguide.py                     38     38     0%
vigent-core\pose\rtmpose_adapter.py          31     31     0%
vigent-core\ppe_check.py                     96     96     0%
vigent-core\quote.py                          4      4     0%
vigent-core\safety_brain.py                 180    180     0%
vigent-core\safety_rag.py                    96     96     0%
vigent-core\scene_vlm.py                     92     92     0%
vigent-core\setup_console.py                 56     56     0%
vigent-core\vlm_confirm.py                   71     71     0%
vigent-core\voice.py                          4      4     0%
vigent-core\routers\detect.py               154    128    17%
vigent-core\agents\safety_manager.py         90     74    18%
vigent-core\tbm_store.py                    106     85    20%
vigent-core\routers\incident.py              63     49    22%
vigent-core\llm_provider.py                  70     52    26%
vigent-core\rfdetr_service.py               173    122    29%
vigent-core\routers\tbm.py                   67     46    31%
vigent-core\ml\vlm_risk_summary.py          178    120    33%
vigent-core\routers\safety_core.py          541    345    36%
vigent-core\routers\tapo.py                  85     54    36%
vigent-core\ergonomics.py                    74     47    36%
vigent-core\agents\copilot.py                70     38    46%
vigent-core\legal_whitelist.py              139     75    46%
vigent-core\routers\ppe.py                   47     25    47%
vigent-core\routers\cameras.py              301    131    56%
vigent-core\audit_store.py                   38     16    58%
vigent-core\starvation_guard.py             102     42    59%
vigent-core\device.py                        16      6    62%
vigent-core\rig_replay.py                    85     31    64%
vigent-core\web_util.py                     130     44    66%
vigent-core\zone_geom.py                      3      1    67%
vigent-core\agents\analyst.py                77     23    70%
vigent-core\agents\scribe.py                346     98    72%
vigent-core\worker.py                       906    250    72%
vigent-core\main.py                         330     81    75%
vigent-core\camera_registry.py              101     22    78%
vigent-core\routers\system.py               141     30    79%
vigent-core\vision_loader.py                 81     16    80%
vigent-core\routers\zone.py                  87     17    80%
vigent-core\agents\dispatcher.py            180     35    81%
vigent-core\agents\base.py                   11      2    82%
vigent-core\detectors\base.py                11      2    82%
vigent-core\detectors\rfdetr_adapter.py     149     24    84%
vigent-core\vlog.py                          57      9    84%
vigent-core\data_paths.py                    42      6    86%
vigent-core\ort_tune.py                      63      9    86%
vigent-core\privacy.py                      197     28    86%
vigent-core\retention.py                    238     32    87%
vigent-core\agents\guard.py                 544     73    87%
vigent-core\routers\recognition.py           46      6    87%
vigent-core\auth_session.py                  51      6    88%
vigent-core\data_engine.py                  142     15    89%
vigent-core\alert_queue.py                  224     23    90%
vigent-core\agents\__init__.py               31      3    90%
vigent-core\alert_notify.py                 107      9    92%
vigent-core\tuning.py                        54      4    93%
vigent-core\readiness.py                     88      6    93%
vigent-core\rig_monitor.py                  107      6    94%
vigent-core\relay.py                        103      5    95%
vigent-core\routers\dispatch.py              22      1    95%
vigent-core\press_zone.py                    54      2    96%
vigent-core\proximity.py                     59      2    97%
vigent-core\health_status.py                 73      2    97%
vigent-core\zone_tile.py                     43      1    98%
vigent-core\zone_debounce.py                 51      1    98%
vigent-core\retention_scheduler.py           92      1    99%
vigent-core\alert_gate.py                    64      0   100%
vigent-core\app_state.py                     17      0   100%
vigent-core\detectors\__init__.py             0      0   100%
vigent-core\hub.py                           12      0   100%
vigent-core\isolated_detect.py                9      0   100%
vigent-core\pose\__init__.py                  0      0   100%
vigent-core\routers\__init__.py               0      0   100%
vigent-core\runtime_config.py                 7      0   100%
vigent-core\ws_auth.py                       16      0   100%
-------------------------------------------------------------
TOTAL                                      8790   3606    59%
```
