# 5단계 5-1 깨끗한 환경 검증 — 새 클론 `D:\vigent_verify` (2026-09-06)

> 방법: `git clone --branch audit/cleanup-20260906 D:\vigent_original D:\vigent_verify`(★브랜치가 원격에 아직 없어 **로컬 저장소에서 클론** — 추적 파일만 체크아웃되므로 "저장소에 없는 것" 검출 목적은 동일). `py -3.11 -m venv .venv` → `requirements.txt` 만 설치(agents/train 미설치). 이 PC 의 기존 작업 폴더·가중치·설정은 쓰지 않았다.

## 1. 결과 요약

| 단계 | 결과 | 실측 |
|---|---|---|
| 클론 | 추적 파일 1,064 · `data/`(field_eval 라벨 116·legal 2·datasets 1)·`vigent-core/weights/MANIFEST.md` 만 존재. `.env`·`config/notify.yaml`·`config/site.yaml`·`data/cameras.json` 없음(설계대로) | — |
| venv + pip | Python 3.11.9 · `pip install -r requirements.txt` **exit 0 · 142초** · 패키지 76개 · `pip check` 이상 없음 · venv 1,410MB · 빌드(소스 컴파일) 필요 패키지 **0**(전부 휠) | 로그 verify_pip_install |
| ★opencv 그림자 | requirements 만으로는 `cv2 == 5.0.0`(GUI `opencv-python`·`opencv-contrib-python` 5.0.0.93 이 `supervision`·`rtmlib`·`rfdetr` 전이의존으로 딸려와 headless 4.13.0.92 를 가림). DEPLOYMENT §3-1 수동 절차(GUI 제거 + headless 강제 재설치) 적용 후 `cv2 == 4.13.0` | 개발 PC 도 5.0.0 이었음 → 모듈 5 RTSP 실측은 5.0.0 기준 |
| 가중치 | `fetch_weights.py --all` **13/13 OK · 938MB · 117초**(GitHub 릴리스 자산 API + Google Storage + OpenMMLab). `--check --all` 누락 0. required 6종(RF-DETR 4 + rtmlib 2) | 토큰은 GCM(`git credential fill`)에서 자동 |
| 기동(카메라 0대·채널 미설정) | `run.ps1` → **/health 200 · 17.2초**(503 starting 2회 후) · `status=healthy` · `phase=ready` · `warnings=[channels_not_configured]` · `alerts.channels_configured=false` · cameras 0 · **degraded 아님**. 서버가 cameras.json·notify.yaml 을 만들지 않음(생성물: `data/alert_queue.db`·`data/config/machine_zone.json`·`data/retention/pinned.json`) | verify_health.json |
| unittest (cv2 5.0.0) | 638 중 **2 실패** — `test_alert_queue.TestQueueEligibilityFollowsWiring` 2건: `_queue_enabled` 가 [M4] 이후 채널 설정을 요구하는데 테스트가 개발 PC 의 `config/notify.yaml` 에 기대고 있었다 → 테스트가 채널 존재를 고정하도록 수정 | 저장소 밖 의존 1건 발견·수정 |
| unittest (headless 4.13, 수정 후) | **638 OK (skipped 1)** — skip = `test_rfdetr_onnx_parity`(`ppe_rfdetr_v1.onnx` 매니페스트 미포함, 문서화된 skip) | 90초 |

## 2. "저장소에 없어서 실패·주의" 목록

| 파일·항목 | 원인 | 조치 |
|---|---|---|
| `config/notify.yaml` | 개발 PC 에만 있음 → 큐 자격 테스트 2건이 이에 의존 | ✅ 테스트 수정(채널 존재 고정) — 5단계 커밋 |
| GUI opencv 그림자(`cv2` 5.0.0) | 전이의존이 requirements 핀을 덮음 | 수동 절차 유지(DEPLOYMENT §3-1) + 이번 실측 기록. 자동화(설치 스크립트) 는 다음 단계 후보 |
| `vigent-core/weights/*` 13파일(938MB) | gitignore | ✅ `fetch_weights.py`(rtmlib 2종은 M7-2b 에서 편입) |
| `ppe_rfdetr_v1.onnx`(onnx-cpu 백엔드 패리티 테스트) | 매니페스트에 없음(export 산출물) | 문서: export 절차·선택 항목. 테스트는 skip(정상) |
| `bin/go2rtc.exe` | 저장소·개발 PC 모두 없음(`ensure_go2rtc` 는 미설치 시 경고 후 스냅샷 폴백) | 수동 절차: go2rtc 릴리스에서 받아 `bin/go2rtc.exe` 에 둠(DEPLOYMENT 에 기재) — 확대뷰 WebRTC 만 영향 |
| `vigent-core/static/vendor/`(MediaPipe·TF.js 로컬 번들, `/safety-local` 폐쇄망용) | gitignore(144MB) · 개발 PC 에도 없음 · `bin/download-vendor.sh` 는 bash 스크립트 | 수동 절차(인터넷 있는 곳에서 1회). 시연 화면 전용이라 관제(`/hub`)에는 영향 없음 |
| `.env` · `config/site.yaml` · `data/cameras.json` | 현장 입력값 | 없어도 기동·테스트 OK(설계대로). `.env.example`·`site.example.yaml` 로 안내 |
| `node`(JS 구문 검사 테스트) | 선택 도구 | 없으면 skip(테스트가 명시) |
| 런처 콘솔 한글 | `run.ps1` 의 Write-Host 한글이 리다이렉트 시 깨짐(코드페이지) — 앱 로그(UTF-8)는 정상 | 낮음: `[Console]::OutputEncoding` 설정 후보(다음 단계) |

## 3-1. 5-2 1차 실행 결과(대표, 19:53) — ❌ 실패 → 원인 확정·수정(2026-09-06 20:1x)

- 관찰: 재설치·파라미터(60s/180s·env 7·이벤트 소스)는 성공, 서비스 시작 직후 **Paused** → /health code=0 → 검증 3·4 False, 원복 정상.
- **원인(확정)**: `logs/vigent.err.log` 마지막 기록 = `[VIGENT 보안 오류] VIGENT_REQUIRE_TOKEN 설정됨 — 무인증 기동을 금지합니다`. 서비스 env `VIGENT_REQUIRE_TOKEN=1` 인데 검증 절차가 `.env`(토큰 출처)를 통째로 중화 → `main.py` 보안 게이트가 **import 시점** `SystemExit(1)` → `_startup` 이전이라 M4-5 흔적(이벤트 1000·startup_failure.json) 0 → NSSM 60s 재시작 대기(Paused) 반복. 의심 1(시스템 Python311 등록)은 이 PC 에 `.venv` 가 없어 그렇게 등록된 것이고 패키지 부재는 아니었다(같은 인터프리터로 638 테스트 통과).
- 수정 4건: ① `install_service.ps1` — `.venv\Scripts\python.exe` 만(없으면 명시적 오류로 중단, 시스템 python 폴백 금지) + Application 을 얇은 런처 `deploy\windows\service_entry.py` 로 ② 런처가 import·인터프리터 단계 실패를 이벤트 **ID 1001**·`startup_failure.json`(stage=import·stderr 꼬리)에 기록하고 종료코드 반환 — 실측: 토큰 빈값 실험 exit 1, json 기록, 이벤트 1001 기록(비관리자 Write-EventLog 폴백) ③ `service_status.ps1` 이 무응답 시 err 로그 마지막 20줄 + startup_failure.json 출력 ④ 검증 스크립트: nssm stderr 흡수(NativeCommandError 제거), 서비스 Running 선확인(아니면 즉시 사유+err 꼬리), `.env` 는 키 값만 비운 임시본(토큰은 무작위 임시값) 사용, Application/.venv/런처 등록 검증(검증 2) 추가.
- 이 PC 에 `.venv` 생성(py -3.11, requirements + opencv headless 정리; torch 는 CPU 휠 — GPU 서비스 운용 시 DEPLOYMENT §3 cu130 휠 교체 필요).

## 3-2. 5-2 서비스 재설치 검증 절차(관리자 재실행)

이 세션의 PowerShell 은 관리자가 아니다(`IsInRole(Administrator) = False` 실측). NSSM 설치·이벤트 소스 등록·서비스 기동은 관리자 권한이 필요하므로 **전 절차를 자동화한 스크립트를 만들어 두었다**:

```powershell
# 관리자 PowerShell 에서
cd D:\vigent_original\deploy\windows
.\verify_service_reinstall.ps1        # 결과: audit\service_reinstall_<시각>.md · 종료코드 0 = 통과
```

스크립트가 하는 일: 기존 상태·NSSM 설정 백업 → 중화(cameras·secrets·notify·.env → `*.audit_hold`, sha256) → `install_service.ps1` 재설치(py -3.11 · 60s/180s · 이벤트 소스 · env 7개) → /health 200(warnings=channels_not_configured, degraded 아님) → **의도적 기동 실패**(RF_HOME 오지정) → `startup_failure.json` count 증가·이벤트 ID 1000·연속 실패 간격 ≥ 60s 확인 → env 원복 → /health 200 → `service_status.ps1` 종료코드 0 → **finally**: Stopped+Disabled 원복 · 파일 원복(sha256 대조) · 보고서. 기동 실패 유도 중 통보는 나가지 않는다(채널 중화, `notified_count` 로 확인).

현재 서비스 상태(실측): `Stopped / Disabled`. `install_service.ps1` 은 5단계에서 `py -3.11` 전용으로 바뀌었다(M7-6).
