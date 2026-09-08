# Phase 0. 인벤토리 — VIGENT 저장소 전체 구조 (검토일 2026-09-08)

> ## ★기기 역할(고정 — 2026-09-09 대표 정정)
>
> | 역할 | 기기 | 사양(실측 근거) | 이 검토에서의 용도 |
> |---|---|---|---|
> | **개발기** | 이 데스크톱 `DESKTOP-STLQ1LM` | MSI MAG B850M MORTAR · Ryzen 9 9900X 12C/24T · RTX 5070 Ti 16GB · DDR5 64GB · Win11 Home · 저장소는 SATA HDD D: (`Win32_SystemEnclosure` ChassisTypes=3, 2026-09-08) | 코드 검토·테스트·게이트·부하 키트 검증. **현장에 가지 않으며, 여기서 잰 성능은 현장 판정에 쓰지 않는다.** 저장소의 수용량·병목·VRAM 실측(2026-08-18 등)도 이 기계 값이다 |
> | **배포기(현장 설치 대상)** | 현장 노트북 | i7-10750H(6C/12T) · GTX 1650 Ti 4GB · DDR4 16GB · SSD 1TB · **Win10 Pro** · torch cu126 (`md/DEPLOYMENT.md:22`, 2026-08-20 재설치 실증) | 현장 성능 판정의 **유일한 근거는 2026-08-22 램프 실측**(`docs/academy_visit_day.md:718-741`: 한계 6대·권장 4대, N=4 검출 p95 675ms). 4h 소크·실카메라 4대·10항목 판정은 미측정 |
>
> 이 표와 다른 서술이 아래 문서에 남아 있으면 이 표가 우선한다.

> 검토 기준 커밋: `audit/cleanup-20260906` = `b7f49d9`(main `ee4557d` 과 동일 트리 + 이 문서). 추적 파일 1,045개(`git ls-files`),
> 확장자 분포 py 377 · md 263 · txt 127 · json 122 · csv 21 · yaml 19 · html 15. 서빙 코드 `vigent-core/` 88 파일 17,285줄(`find`+`wc`).
> 이 문서는 이후 Phase 1~8 검토의 지도이며, 여기 적힌 "없음"은 grep·ls 로 확인한 것이고 "확인 필요"는 열어 보지 않은 것이다.
> 검토가 도는 기계는 위 표의 **개발기**(데스크톱)이며, 설치 대상은 **배포기**(노트북)다. 개발기 사양은 참고용으로만 적었고 현장 판정에는 쓰지 않는다.

## 1. 언어·프레임워크·의존성·실행

| 항목 | 값 | 근거 |
|---|---|---|
| 언어 | Python **3.11.9** 정본(`.python-version`, `pyproject.toml:7 target-version py311`), 프론트 순수 HTML/JS + CDN(MediaPipe·TF.js) | `pyproject.toml`, `themes/safety/*.html` |
| 웹 | FastAPI 0.137.2 · uvicorn 0.23.2 · websockets 16.0 | `requirements.txt:8-13` |
| 추론 | torch 2.12.0(+cu130 개발기 / CPU 휠 기본) · torchvision 0.27 · **rfdetr 1.8.0**(RF-DETR nano) · supervision 0.29(ByteTrack) · **rtmlib 0.0.15**(RTMPose, onnxruntime 1.27 CPU) · opencv-contrib-python-headless 4.13.0.92(constraints.txt 로 GUI 4종 동버전 고정) · numpy 2.4.6 | `requirements.txt:22-72`, `constraints.txt` |
| 선택 | requirements-agents.txt(LLM·RAG 3종) · requirements-train.txt(ultralytics 등 3종) · requirements-optional.txt(Apple mlx-vlm 등 7종) | 각 파일 |
| 설치 | `py -3.11 -m venv .venv` → `python scripts/setup_env.py --weights`(pip + opencv GUI 제거·검증 + 가중치 13종·go2rtc 조달) | `scripts/setup_env.py`, README:24 |
| 실행 | 개발: `run.ps1`/`run.bat`/`run.sh`/`VIGENT Safety 시작.bat` · 서비스: `deploy/windows/install_service.ps1`(NSSM, `.venv\Scripts\python.exe deploy\windows\service_entry.py --host --port`) · 리눅스: `deploy/systemd/vigent-edge.service` + watchdog timer · 컨테이너: `Dockerfile`(python:3.11-slim, CPU) | 각 파일 |
| 버전 | `VERSION` = 0.2.0 · `md/RELEASES.md` | — |
| 게이트 | ruff 0 · mypy(화이트리스트 19파일) 0 · unittest **662**(2026-09-08) · OpenAPI move-only 체커(`baseline_openapi.json` 99 경로) · 프로파일 드리프트 체커 | `.github/workflows/ci.yml:39-52` |

★**Dockerfile 은 현재 빌드되지 않는다**: `COPY VERSION weights_manifest.json fetch_weights.py ./` 가 루트의 `fetch_weights.py` 를 요구하나 파일은 `scripts/fetch_weights.py` 에만 있다(`ls fetch_weights.py` → 없음). CUDA 도 없다(python:3.11-slim). Phase 6 에서 판정.

## 2. 서비스 구성요소와 흐름

```mermaid
flowchart LR
  subgraph IN[카메라 입력]
    C1[RTSP/파일/웹캠<br/>worker._open_capture<br/>TCP·타임아웃 5s·재연결≤5s·hang 15s]
  end
  subgraph INF[추론 - 단일 프로세스, DETECT_LOCK 직렬화]
    G[agents/guard.py<br/>RF-DETR person·ppe·fire_smoke<br/>(forklift: 학원 프로파일만 YOLO)]
    T[ByteTrack(person)·IoU]
    P[worker 포즈 스레드<br/>rtmlib RTMPose onnxruntime CPU]
  end
  subgraph RULE[규칙·상태]
    R1[proximity.py 근접<br/>zone_geom/zone_debounce 침입<br/>ppe_check·hazard_rules·behavior]
    R2[alert_gate.py 쿨다운·억제]
  end
  subgraph OUT[이벤트·알람]
    Q[alert_notify.py 큐200<br/>반복억제300s·시간당6건]
    DB[(alert_queue.db sqlite<br/>재시도 5s·데드레터)]
    D[agents/dispatcher.py<br/>텔레그램·이메일·웹훅·relay·log]
    RL[relay.py / critical_controls<br/>보조 방호신호]
  end
  subgraph STORE[저장]
    E[data_engine.py<br/>evidence JPEG(YuNet 모자이크)·recognition jsonl·pin]
    L[vlog.py logs/vigent.log·events.jsonl]
    RT[retention.py 스윕 24h<br/>evidence 30일·audit 1095일]
  end
  subgraph UI[UI/API]
    H[/health B2 검출 생존]
    HUB[/hub 관제·/safety 시연<br/>console 자동처리]
    API[routers/* 99 경로<br/>Bearer 토큰·Host 허용목록]
  end
  C1 --> G --> T --> R1 --> R2 --> Q --> DB --> D --> RL
  G --> P --> R1
  R1 --> E --> RT
  R2 --> L
  G --> H
  E --> HUB
  API --> HUB
  D -.실패 시 재시도/데드레터.-> DB
```

| 단계 | 파일 | 비고 |
|---|---|---|
| 캡처 | `vigent-core/worker.py:68-90`(`_FFMPEG_CAPTURE_OPTIONS`, `_open_capture`), 캡처 스레드 모드 `VIGENT_CAPTURE_MODE=thread` | Tapo 특화 `routers/tapo.py`, go2rtc(확대뷰) `routers/cameras.py:337` |
| 추론 | `agents/guard.py`, `detectors/rfdetr_adapter.py`·`yolo_adapter.py`, `rfdetr_service.py`, `vision_loader.py`, `device.py`, `ort_tune.py` | 슬롯·임계 `themes/safety/vision.yaml`, 예열 `readiness.py` |
| 규칙 | `proximity.py`, `zone_geom.py`, `zone_debounce.py`, `ppe_check.py`, `hazard_rules.py`, `behavior.py`, `ergonomics.py`, `press_zone.py`, `critical_controls.py` | 임계 정본 `config/tuning.yaml`(strict loader `tuning.py`), 카메라별 override `camera_registry.py` |
| 알람 | `alert_gate.py`, `alert_notify.py`, `alert_queue.py`, `agents/dispatcher.py`, `relay.py`, `routers/dispatch.py` | 채널 설정 `config/notify.yaml`(gitignore) |
| 저장 | `data_engine.py`, `privacy.py`, `audit_store.py`, `tbm_store.py`, `incident.py`, `retention.py`, `retention_scheduler.py`, `data_paths.py`(`VIGENT_DATA_DIR`) | `data/`(gitignore) |
| UI/API | `main.py`(앱 골격·lifespan·보안 게이트), `routers/`(cameras·zone·system·detect·incident·tbm·ppe·recognition·dispatch·safety_core·tapo), `hub.py`, `dashboard.py`, `themes/safety/*.html`, `static/realtime_core.js`(브라우저 검출 경로) | OpenAPI 기준선 `baseline_openapi.json` |
| 에이전트(LLM) | `agents/analyst.py·scribe.py·copilot.py·safety_manager.py`, `safety_rag.py`, `llm_provider.py`, `ml/vlm_risk_summary.py`(mlx 전용), `vlm_confirm.py` | 코어와 분리(requirements-agents), 없어도 기동 |

## 3. 위치 지도

| 무엇 | 위치 |
|---|---|
| 모델 가중치 | `vigent-core/weights/`(gitignore) — `weights_manifest.json` 13종(RF-DETR 4 required, rtmlib 2 required, YOLO 폴백 5, YuNet, go2rtc.exe), 조달 `scripts/fetch_weights.py`(sha256 검증) |
| 학습 코드 | `training/`(rfdetr_train.py, train_ppe/fire/forklift/merged, build_*_ds.py, prelabel.py), `colab/`, `vigent-core/ml/`(train_retrain.py, merge_retrain_data.py) |
| 데이터셋·정답지 | `datasets/goldens`, `eval/golden`, `data/field_eval/labels`(추적), 평가 이미지·현장 미디어는 저장소 밖 `D:\vigent_private_data\`(VIGENT_DATA_DIR)·`D:\vigent_field\` |
| 설정 | `config/tuning.yaml`(임계 정본), `themes/safety/vision.yaml`(슬롯), `config/zones.json·danger_zone.json·machine_zone.json`, `config/ppe_rules.yaml`, `config/critical_controls.yaml`, `config/security.json`, `config/go2rtc.yaml`, `config/notify.yaml`(gitignore, `.example` 있음), `config/site.example.yaml`, 현장 프로파일 `deploy/academy/` |
| 배포 | `Dockerfile`, `deploy/windows/`(install·uninstall·status·verify·service_entry·nssm.exe 동봉), `deploy/systemd/`, `deploy/watchdog.sh`, `deploy/SITE_CHECKLIST.md`, `md/DEPLOYMENT.md`, `docs/TLS_DEPLOYMENT.md`, `docs/edge_network_hardening.md` |
| 테스트·CI | `tests/` 97파일 662건(카메라·GPU 없이, `tests/_isolate.py` 로 data/·logs/ 무접촉 실측), `.github/workflows/ci.yml`(ubuntu) |
| 측정·감사 | `benchmarks/` 67 md + 스크립트, `audit/`(스모크·소크·서비스 검증·부하 키트 결과), `scripts/`(37: capacity_probe, pilot_load_test, soak_*, tree_hash, check_*), `tools/`(10) |
| 문서 | 루트 `README.md·CLAUDE.md·CODE_REVIEW.md·AUDIT_REPORT.md·CLEANUP_PLAN.md·SAFETY_REVIEW_REPORT.md`, `md/`(DEPLOYMENT·RELEASES·META_PROMPT·사업계획), `docs/`(40여 개: ONBOARDING·STABILITY·PRIVACY_POLICY_DRAFT·disk_retention_policy·camera_requirements·detection_limits·FINAL_SUMMARY·NEXT_SESSIONS·LAPTOP_SIZING_PILOT4 …), 이전 검토 `docs/review/01_현황.md~07_기록표.md`(2026-09-03, 미추적) |
| 잔재·비추적 | `_archive/`(office/sports·macOS 런처), `business_assets/`·`footage/`·`reports/`·`cloud/`·`runs/`(gitignore 대부분), git 이력의 민감 미디어 110객체(재작성 미완 — `docs/NEXT_SESSIONS.md` 세션 1) |

## 4. 테스트·CI·문서 상태(실측)

| 항목 | 상태 | 근거 |
|---|---|---|
| 단위 테스트 | 662 OK(skip 1), 약 2분. ★"data/+logs/ 전후 해시 변경 0"은 고아 go2rtc 가 포트를 점유한 상태에서 잰 값 — Phase 7 재측정에서는 `data/` 삭제 1·변경 3(go2rtc 기동·pin) 발견 | 2026-09-08 게이트 로그, `scripts/tree_hash.py`, `07-code-quality.md` §2.3 |
| 회귀(영상→기대 이벤트) | `eval/golden`·`datasets/goldens` 존재 — CI 미포함, 실행 절차는 Phase 7 확인 | `ls eval datasets` |
| CI | push/PR 시 ruff·mypy·unittest·OpenAPI·드리프트 5스텝, ubuntu, PowerShell 실행 테스트는 skip | `.github/workflows/ci.yml` |
| 서비스 재설치 검증 | 2026-09-06 4차 통과(검증 2~5, 원복 일치) | `audit/service_reinstall_20260906_224451.md` |
| 새 클론 검증 | 2026-09-06 재실행: setup_env 322s·cv2 4.13 headless·/health 200 19.4s·662 OK | `audit/verify_clean_clone_2026-09-06.md` §1-2 |
| 문서 | 설치(DEPLOYMENT·ONBOARDING·README), 안정성(STABILITY), 보안(TLS·edge_network_hardening), 개인정보 초안, 보존 정책, 카메라 요건, 검출 한계, 현장 체크리스트 — 운영 runbook·API 문서·변경 이력의 충실도는 Phase 7 |

## 5. "한다"고 적혀 있지만 코드에는 없거나 다른 것(1차, Phase 별로 확정)

| # | 문서·주석의 주장 | 코드 실측 | 판정 |
|---|---|---|---|
| 1 | `Dockerfile` 이 서비스를 컨테이너로 띄운다 | `COPY … fetch_weights.py ./` 대상 파일이 루트에 없어 **빌드 실패**, CUDA 없음, docker compose 없음 | 거짓(낡음) — Phase 6 |
| 2 | `themes/safety/vision.yaml:65-70` "rtmpose 는 미설치·미사용, 포즈는 yolov8n-pose 하드코딩" | `worker.py:362,437,947` 이 rtmlib RTMPose(onnxruntime CPU)를 실제 로드·실행, 매니페스트에 rtmlib 2종 required | 주석 낡음 — Phase 2 |
| 3 | `vision.yaml:71` "ByteTrack 미구현·미사용" | person 슬롯 ByteTrack 사용(`agents/guard.py` `_track_bytetrack`, `benchmarks/track_ab_bytetrack.md`) | 주석 낡음 — Phase 2 |
| 4 | `CLAUDE.md:101` 테스트 게이트 "55 tests" | 662 | 낡음(`docs/review/05_문서불일치.md` #1 이후 계속 갱신 안 됨) |
| 5 | `md/VIGENT_META_PROMPT.md` 의 3테마(office/sports) 서술 | Z-3 로 영구 삭제, `_archive/` | CLAUDE.md 가 무효 선언함 |
| 6 | `docs/TLS_DEPLOYMENT.md` — TLS 적용 | 코드에 uvicorn ssl 옵션·리버스 프록시 구성 없음(문서만) — 확인 필요 | Phase 5 |
| 7 | 알람 채널 "SMS/카카오/문자/모바일 푸시" | dispatcher 채널은 텔레그램·이메일·웹훅·relay·log 뿐(`agents/dispatcher.py`) — 확인 필요 | Phase 4 |
| 8 | PLC/Modbus/OPC-UA 연동 | grep `modbus|opcua|pymodbus` 0건(확인 필요: relay.py 가 어떤 실물 출력을 쓰는지) | Phase 4 |
| 9 | 사용자·역할(RBAC) | 단일 Bearer 토큰 + `auth_session.py` 로그인 잠금 — 역할 구분 없음(확인 필요) | Phase 5 |
| 10 | 이벤트 전후 클립(pre/post-roll) 저장 | evidence 는 JPEG 스틸(`data_engine.py`), 영상 클립 저장 코드 grep `VideoWriter` 는 scripts/field_recorder.py 뿐 | Phase 4 |
| 11 | 중앙 관제(다중 현장) | `hub.py`/`index_hub.html` 은 단일 서버 UI — 확인 필요 | Phase 6 |
| 12 | 캘리브레이션(픽셀→미터) | `proximity.py` 는 박스 비율 기반(`vehicle_size_limits`), 호모그래피 코드 없음(확인 필요) | Phase 2 |

## 6. Phase 별 지시(어떤 파일을 보라)

- Phase 1 아키텍처: main.py(lifespan·`_required`/`_optional`·`_notify_startup_failure`), worker.py, starvation_guard.py, health_status.py, routers/system.py, alert_gate·alert_notify·alert_queue, retention*, deploy/windows/*, service_entry.py, zone_debounce·proximity·tuning·camera_registry(overrides).
- Phase 2 모델: vision.yaml, weights_manifest.json, guard.py, detectors/*, device.py, worker.py 포즈, benchmarks(v1_field_baseline, field_academy_2026-08-27, forklift_duel, capacity_report, e1_bottleneck, v1_slot_config, v2_onnx), training/, docs/detection_limits.md, audit/loadtest_20260908_2122_devpc_dryrun.md.
- Phase 3 입력: worker.py 캡처·재연결·hang, routers/cameras.py, camera_registry.py, health_status.py, benchmarks/rtsp_capture_probe.py, audit/soakmon_*, scripts/soak_*.
- Phase 4 알람: dispatcher.py, alert_*.py, relay.py, critical_controls, routers/dispatch·incident·recognition·safety_core, dashboard.py, data_engine.py, audit_store.py, hub/console UI.
- Phase 5 보안: main.py 게이트, auth_session.py, ws_auth.py, security.json, privacy.py, retention, audit_store, git 이력 비밀 검색, pip-audit.
- Phase 6 운영: Dockerfile, deploy/*, service_entry.py, vlog.py, retention, /health 필드, docs/ops_disk_sizing·edgebox_purchase_guide·LAPTOP_SIZING_PILOT4, 데스크톱 현황 명령.
- Phase 7 품질: tests/ 매핑, ruff/mypy/coverage 실행, except 전수, 동시성, 죽은 코드, 문서 매트릭스.
- Phase 8 규제·경쟁: audit_store 무결성, incident 조치 이력, scribe 보고서, §8.1 경계 문구, PRIVACY_POLICY_DRAFT, 웹 검색 출처.
