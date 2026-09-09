# Phase 6 — 운영·배포·관측성 + 하드웨어 평가 검토

> 작성 2026-09-08 · 대상 커밋 `d4517fc`(branch `audit/cleanup-20260906`) · 검토 방식: **읽기 전용**(코드 수정 0 · 서비스 조작 0 · 실행한 명령은 `Get-*`·`nssm get`·`powercfg /query`·`nvidia-smi --query` 등 조회뿐).
> 규칙 7·11 준수: 모든 지적은 `파일:줄` 또는 "명령 → 출력"으로 근거를 단다. 읽지 않은 것·실행하지 못한 것은 **"확인 필요"** 로 남긴다. 수치는 실측(이 PC·저장소 안 리포트)만 쓰고, 추정은 "추정"이라 적는다.
> 심각도: **P0** 현장에서 시스템이 죽을 수 있음 · **P1** 신뢰성·데이터(경보) 유실 · **P2** 경쟁 열위 · **P3** 품질.

---

## 0. 요약

| 구분 | 결론 |
|---|---|
| 배포 | Windows(NSSM) 경로는 2026-09-06 재설치 검증 4차 통과(`audit/service_reinstall_20260906_224451.md`)로 **실제로 동작하는 유일한 경로**다. Docker 는 **빌드 자체가 불가**(constraints.txt 미복사·루트 `fetch_weights.py` 부재), systemd 는 **존재하지 않는 런처**를 가리킨다. 폐쇄망 설치는 가중치·go2rtc 까지는 매니페스트로 닫혔으나 **pip 휠·NSSM·vendor JS 는 절차가 없다**. |
| 프로세스 관리 | 크래시 재시작·지연 자동 기동·LocalSystem 무로그인 기동·기동 실패 통보(이벤트 1000/1001)·sqlite 경보 이월까지 **코드로 추적됨**. 그러나 **정전→전원 복구 시 "기기가 다시 켜지는 것" 과 "노트북 덮개·절전" 은 코드 밖이며 문서·체크리스트에 0건**이다(P0 2건). |
| OTA | 없음. 업데이트 = `git pull` + `Restart-Service`(수동), 실패 시 롤백 절차 없음. 설정은 git 추적(tuning.yaml)이나 현장 프로파일은 파일 덮어쓰기 방식. |
| 로깅 | 구조화(events.jsonl)·회전(10MB×5 / 10MB×10)·자격증명 마스킹(실측 308건 전부 마스킹) 양호. NSSM 회전본 개수 무제한(retention 이 50개 유지)·앱 로그 stderr 이중 기록. |
| 관측성 | `/health` 자체 구현이 넓다(카메라별 stale·슬롯 저하·경보 큐·보존·프라이버시·릴레이). **없는 것**: 디스크 여유(24h 1회 캐시), GPU 온도/클럭, CPU 온도/성능, 추론 장치(cuda/cpu), 시계열·대시보드, 외부 폴링 알림. |
| 저장소 | 용량 산정·보존 스윕·pin 보호는 있음. **백업·복구 절차 0건**, 레지스트리(`cameras.json` 등) **비원자적 쓰기**. |
| 하드웨어 | ★역할(2026-09-09 정정): **배포기 = 현장 노트북**(i7-10750H / GTX 1650 Ti 4GB / 16GB / 1TB / Win10 Pro), **개발기 = 이 데스크톱**(현장에 가지 않음, §2 는 개발기 현황). 노트북의 4대 성능 근거는 2026-08-22 램프 1회(한계 6·권장 4, N=4 p95 675ms)뿐이고 4h 소크·10항목은 미측정. VRAM 4GB 는 충분(서버 몫 1.2~1.4GB 확정). 진짜 위험은 **절전·덮개·정전 복구·발열·Windows Update·물리 보안**이며 전부 코드 밖 항목이다(§9). |

**이슈 합계: P0 2 · P1 5 · P2 8 · P3 5** (§13).

---

## 1. 검토 범위·방법

### 1-1. 읽은 파일(줄 인용 대상)
`Dockerfile` · `.dockerignore` · `deploy/windows/{install_service.ps1, service_entry.py, service_status.ps1, uninstall_service.ps1, verify_service_reinstall.ps1(1~200줄), README.md}` · `deploy/systemd/*` · `deploy/watchdog.sh` · `run.ps1`·`run.bat`·`run.sh`·`VIGENT Safety 시작.bat` · `scripts/setup_env.py` · `constraints.txt` · `requirements.txt` · `scripts/fetch_weights.py` · `weights_manifest.json` · `deploy/SITE_CHECKLIST.md` · `deploy/DEPLOYMENT.md` · `md/DEPLOYMENT.md` · `deploy/academy/{README_academy.md, profile_intent.yaml}` · `scripts/check_profile_drift.py`(머리) · `docs/{INFRA_REQUIREMENTS, edgebox_purchase_guide(1~250), STABILITY(1~200), SOAK_24H_CHECKLIST, disk_retention_policy, ops_disk_sizing, LAPTOP_SIZING_PILOT4, public_release_checklist(머리), NEXT_SESSIONS(머리), ops_capacity_sizing(머리), TLS_DEPLOYMENT(머리)}.md` · `vigent-core/{vlog, retention, retention_scheduler, health_status, starvation_guard, alert_queue, data_paths, readiness(1~60), runtime_config, hub}.py` · `vigent-core/routers/system.py` · `vigent-core/main.py`(300~600줄) · `config/tuning.yaml`(retention·alerts 절) · `config/{site.example.yaml, security.json, go2rtc.yaml, notify.example.yaml(키만)}` · `md/RELEASES.md` · `VERSION` · `audit/{loadtest_20260908_2122_devpc_dryrun.md, service_reinstall_20260906_224451.md, verify_clean_clone_2026-09-06.md}` · `benchmarks/{capacity_report, e1_bottleneck_report(1~120)}.md` · `CLAUDE.md`. 그 외는 grep 으로 특정 줄만 확인(`worker.py`·`camera_registry.py`·`data_engine.py`·`device.py`·`alert_notify.py`·`agents/dispatcher.py`·`privacy.py`·`setup_console.py`).

### 1-2. 실행한 명령(전부 조회)
`Get-CimInstance Win32_{ComputerSystem,OperatingSystem,Processor,VideoController,Battery,PhysicalMemory,Service}` · `Get-Service VIGENT` · `nssm get VIGENT <Start|AppExit Default|AppRestartDelay|AppThrottle|AppRotate*|AppStopMethod*|AppKillProcessTree|ObjectName|Application|AppDirectory|AppStdout|AppStderr|AppEnvironmentExtra(키 이름만)>` · `powercfg /getactivescheme` · `powercfg /query SCHEME_CURRENT <SUB_SLEEP|SUB_BUTTONS|SUB_VIDEO|USB|PCIe|SUB_DISK|SUB_PROCESSOR>` · `powercfg /a` · `powercfg /lastwake` · `Get-PhysicalDisk`·`Get-Disk`·`Get-Partition`·`Get-Volume` · `Get-StorageReliabilityCounter`(**권한 거부**) · `Get-BitLockerVolume`(**권한 거부**) · `Get-MpPreference`(**권한 거부**) · `Get-NetAdapter`·`Get-NetAdapterPowerManagement` · `Get-ItemProperty HKLM:\...\WindowsUpdate\UX\Settings` · `Get-ItemProperty ...\Session Manager\Power HiberbootEnabled` · `Get-WinEvent Application/VIGENT, nssm` · `nvidia-smi --query-gpu` · `typeperf -qx "\Thermal Zone Information"` · `Get-Process python, go2rtc` · `Get-NetTCPConnection -LocalPort 8010` · `git ls-files bin deploy` · `git log -1 -- <파일>` · `du/ls` 로 `data/`·`logs/` 크기.

### 1-3. 읽지 않았거나 실행하지 못한 것(확인 필요)
- `data/go2rtc.log` 내용(자격증명 평문 여부 — `docs/SOAK_24H_CHECKLIST.md:30-34` 가 우려 표기) — 열지 않았다.
- `verify_service_reinstall.ps1` 200줄 이후, `worker.py` 전체, `agents/dispatcher.py` 전체, `docs/ONBOARDING.md` 본문, `docs/edge_network_hardening.md` 본문.
- SSD S.M.A.R.T.(`Get-StorageReliabilityCounter`)·BitLocker·Defender 제외 — **관리자 권한 필요**로 이 세션에서 조회 불가.
- 노트북 관련 모든 실측 — 이 기계는 데스크톱이다(§2). 노트북 명령은 §9-3 에 남긴다.

---

## 2. 개발 기기 현황(2026-09-08 실측)

★대표가 "개발용 노트북"이라 부르는 기계는 **데스크톱**이다(`Win32_ComputerSystem.PCSystemType = 1`(Desktop) · `Win32_Battery` **없음** · MSI MS-7E61 메인보드).

| 항목 | 명령 | 출력(요약) |
|---|---|---|
| 호스트 | `Get-CimInstance Win32_ComputerSystem` | DESKTOP-STLQ1LM · Micro-Star MS-7E61 · RAM 65,905,455,104B(≈61.4GiB) · PCSystemType 1 |
| OS | `Win32_OperatingSystem` | Windows 11 **Home** 10.0.26200 · 마지막 부팅 2026-09-08 12:34 · 업타임 10h42m |
| CPU | `Win32_Processor` | AMD Ryzen 9 9900X 12C/24T 4.4GHz |
| GPU | `Win32_VideoController` · `nvidia-smi` | RTX 5070 Ti · 드라이버 610.74 · 16,303MiB · **온도 35°C · 사용 1,589MiB · 26.4W/300W**(유휴) + Radeon iGPU |
| RAM | `Win32_PhysicalMemory` | 32GB×2 DDR5-4800(DIMMA2/B2) |
| 디스크 | `Get-PhysicalDisk`·`Get-Partition` | Disk0 **CT240BX500SSD1**(Crucial BX500 240GB, SATA SSD) = **C:** 221GB/여유 35.3GB · Disk1 **WDC WD10EZEX**(1TB **HDD**, SATA) = **D:** 931GB/여유 429GB — ★**저장소·data/·logs/ 가 HDD(D:) 위에 있다** |
| SSD 수명·온도 | `Get-StorageReliabilityCounter` | **권한 거부**(관리자 필요) → 확인 필요 |
| 배터리 | `Win32_Battery` | 없음(데스크톱) |
| 전원 구성 | `powercfg /getactivescheme` | 균형 조정(SCHEME_BALANCED) |
| 절전 | `powercfg /query SUB_SLEEP` | 절전 진입 **AC 0(안 함)** / DC 600s · 하이브리드 절전 **켜짐** · 최대 절전 AC 0 |
| 화면 | `SUB_VIDEO` | 끄기 AC **0(안 함)** / DC 180s |
| 전원 단추 | `SUB_BUTTONS` | 시작메뉴 전원 단추=절전(덮개 항목 없음 — 데스크톱) |
| USB 선택적 절전 | `2a737441…/48e6b7a6…` | **AC/DC 모두 사용(1)** |
| PCIe ASPM | `501a4d13…/ee12f906…` | AC 보통 절전(1) / DC 최대 절전(2) |
| 디스크 끄기 | `SUB_DISK` | **AC 1,200s(20분)** / DC 600s — HDD D: 가 20분 유휴면 스핀다운 |
| 프로세서 | `SUB_PROCESSOR` | 최소 AC 0% / 최대 100% |
| 절전 가능 상태 | `powercfg /a` | S3 만 가능 · **최대 절전 해제됨** · 빠른 시작 불가(HiberbootEnabled=1 이지만 hibernate 꺼져 무효) |
| 마지막 깨움 | `powercfg /lastwake` | 전원 단추 |
| 온도 카운터 | `typeperf -qx` · `MSAcpi_ThermalZoneTemperature` | Thermal Zone 카운터 **존재**(4종) · WMI 는 "지원하지 않음" — 키트 드라이런에서 CPU°C 값은 None(`audit/loadtest_…dryrun.md:23-32`) |
| NIC | `Get-NetAdapter` | 이더넷 2(Realtek) **Up 100Mbps** · Wi-Fi 7 어댑터 3개 Disconnected · `Get-NetAdapterPowerManagement` 출력 없음(권한/드라이버 — 확인 필요) |
| Windows Update | `HKLM:\...\WindowsUpdate\UX\Settings` | 활성 시간 **8~2시**(18h) · `Policies\...\WindowsUpdate\AU` **없음**(Home — 정책 미설정) · UsoSvc Running · 재부팅 대기 플래그 없음 |
| 서비스 | `Get-Service VIGENT` · `Win32_Service` | **Stopped / Disabled** · StartName **LocalSystem** · PathName `deploy\windows\nssm.exe` · DelayedAutoStart False(현재 SERVICE_DISABLED 상태라) |
| NSSM 파라미터 | `nssm get VIGENT …` | Start=SERVICE_DISABLED · AppExit Default=**Restart** · AppRestartDelay=**60000** · AppThrottle=**180000** · AppRotateFiles=1 · AppRotateOnline=1 · AppRotateBytes=268,435,456 · AppRotateSeconds=0 · AppStopMethodConsole/Window/Threads=**1500/1500/1500** · AppKillProcessTree=1 · Application=`.venv\Scripts\python.exe` · AppDirectory=`vigent-core` · AppStdout/AppStderr=`logs\vigent.{out,err}.log` · AppEnvironmentExtra 키 7개(VIGENT_REQUIRE_TOKEN·VIGENT_CAPTURE_MODE·VIGENT_HOST·PYTHONUTF8·RF_HOME·TORCH_HOME·VIGENT_RESTART_CMD) |
| nssm.exe | `Get-Item` | 368,640B · 2017-04-26(= NSSM 2.24 계열, 확인 필요) · **gitignore**(`.gitignore` "deploy/windows/nssm.exe") |
| 이벤트 로그 | `Get-WinEvent Application/VIGENT` | 최근 5건: ID 1000 ×3(09-06 22:48~22:50 검증 유도) · 1001 ×2(09-06 20:13, 21:03) — M4-5 경로가 실제로 남긴다 |
| 실행 중 프로세스 | `Get-Process python` · `Get-NetTCPConnection 8010` | python PID 30036(23:16 시작, WS **4.9GB**) 존재하나 **8010 LISTEN 없음** · go2rtc 프로세스 없음 → 어떤 프로세스인지 **확인 질문** §15 |
| 데이터 크기 | `du` | `data/evidence` **968MB / 14,175장 / 평균 69,326B** · `data/recognition` 6.6MB · `logs/` 23MB · `alert_queue.db` 72KB · `logs/events.jsonl` 405줄/325KB(2026-08-05~) |
| 보존 스윕 | `data/retention_status.json` | last_run 2026-09-08 21:19 · enabled·dry_run=false·executed_delete=true · 삭제 74건/61,180B(268B 짜리 비정상 소량 파일) · 디스크 여유 460.8GB · 경고 0 |

---

## 3. 배포 매트릭스

| 항목 | 상태 | 근거 |
|---|---|---|
| Windows 서비스(NSSM) 설치 자동화 | **있음** | `install_service.ps1:59-69`(.venv 전용·3.11 검증) `:124-142`(런처·지연 시작·60s/180s) `:144-151`(로그 회전) `:158-187`(env 7개) `:111-119`(이벤트 소스). 4차 검증 통과 `audit/service_reinstall_20260906_224451.md:1,16,24,27,33` |
| 컨테이너 빌드 | **없음(빌드 불가)** | `Dockerfile:24` 는 `requirements.txt` 만 COPY 하는데 `requirements.txt:7` 이 `-c constraints.txt` 를 요구 → `pip install` 단계 실패. `Dockerfile:38` `COPY … fetch_weights.py ./` — 루트에 파일 없음(`ls fetch_weights.py` → No such file; 정본은 `scripts/fetch_weights.py`). `docker-compose*` 없음(`ls` 확인). CUDA 베이스 아님(`Dockerfile:14` python:3.11-slim) → CPU torch. 마지막 수정 2026-08-10(`git log`) 이후 constraints 도입(09-06)과 어긋남 |
| 컨테이너 헬스체크 | 부분 | `Dockerfile:53-54` curl /health, start-period 60s — CPU 예열 실측 23s(`md/DEPLOYMENT.md` §9-②)·19.4s(`audit/verify_clean_clone…` §1-2)라 충분. 단 빌드가 안 되므로 미검증 |
| Linux systemd | **없음(경로 부재)** | `deploy/systemd/vigent-edge.service:24` `ExecStart=/bin/bash __INSTALL_DIR__/bin/vigent-edge.command` — `git ls-files bin` = `build-package.sh, download-vendor.sh, vigent-serve.sh` 뿐. 2026-07-05 이후 미수정. `docs/INFRA_REQUIREMENTS.md:34` 스스로 "Linux 이식 미검증" 표기 |
| 워치독(외부) | Linux/mac 용만 | `deploy/watchdog.sh:87-96` 은 `python3` + `/status.any_hang` 의존. Windows 는 앱 내부(`starvation_guard.py`) + `service_status.ps1`(수동 실행) |
| 재현 가능한 빌드(핀·해시) | **부분** | 버전 핀 `requirements.txt`·`constraints.txt`(opencv 4종 4.13.0.92) · 가중치 sha256 13종+go2rtc(`weights_manifest.json`) · **pip 해시(`--require-hashes`) 없음** · torch CUDA 휠은 requirements 밖 수동(`requirements.txt:37-41`, `md/DEPLOYMENT.md:114-135`) · `setup_env.py` 가 cv2 를 새 프로세스에서 검증(`scripts/setup_env.py:46-59`) |
| 환경별 설정 분리(dev/staging/현장) | **부분** | 시드/런타임 분리 `runtime_config.py:1-31`(config/ 읽기전용, data/config/ 쓰기) · 비밀 `.env`·`notify.yaml`·`camera_secrets.json` gitignore · 현장 프로파일은 **파일 덮어쓰기**(`deploy/academy/README_academy.md:23-25`) + 드리프트 게이트(`profile_intent.yaml`, `check_profile_drift.py`) · `site.yaml` 은 `VIGENT_EDGE=1` 에서만 소비(`main.py:498-506`)인데 **서비스 env 에 VIGENT_EDGE 없음**(env 7개) → 서비스는 `data/cameras.json` 복원 경로만 탄다(`routers/cameras.py:426`). 카메라 정의 소스가 2개(site.yaml vs cameras.json)라 혼동 여지 |
| 폐쇄망: 가중치 | **있음** | `fetch_weights.py --all` 13종 + go2rtc(`weights_manifest.json`), `RF_HOME`·`TORCH_HOME` 고정(`install_service.ps1:177,184`), 첫 사람 검출까지 확인 절차(`SITE_CHECKLIST.md` N-5) |
| 폐쇄망: pip 휠 | **없음** | N-5 "pip 캐시/휠을 먼저 준비" 한 줄뿐(`deploy/SITE_CHECKLIST.md:226`). `pip download` 번들 스크립트·검증 없음(`scripts/` 목록에 없음) |
| 폐쇄망: NSSM | **부분** | `nssm.exe` 는 gitignore(`.gitignore` "deploy/windows/nssm.exe") → 새 클론엔 없고 install 이 다운로드/winget 안내 후 종료(`install_service.ps1:91-98`). 오프라인은 사람이 미리 복사해야 함 |
| 폐쇄망: 프론트 JS | **부분** | `/hub`·`index_hub.html` 은 CDN 의존 없음(grep 0). `/safety`(`themes/safety/index.html:9-15`)·`console.html:7-8,403`·`index_vigent.html`·`static/realtime_core.js:379` 는 `cdn.jsdelivr.net` 의존. 로컬판 vendor 144MB 는 `bin/download-vendor.sh`(bash) 로만 조달·개발 PC 에도 없음(`audit/verify_clean_clone…` §2) |
| 설치 검증 자동화 | **있음** | `verify_service_reinstall.ps1`(백업→중화→재설치→고의 실패→복구→원복), `tests/test_verify_service_script.py`·`test_service_entry.py`·`test_startup_services.py` 존재 |
| 릴리스 관리 | **부분** | `md/RELEASES.md` 태그 v1.0/v1.0.1 · `VERSION`=0.2.0 · `weights_manifest.product_version`=0.2.0 — 태그 이름과 VERSION 체계가 다르다 |

---

## 4. 프로세스 관리 매트릭스 + 정전 복구 시나리오

### 4-1. 매트릭스

| 항목 | 상태 | 근거 |
|---|---|---|
| 크래시 자동 재시작 | **있음** | `nssm get AppExit Default` → Restart · `install_service.ps1:140-142` 60s 지연/180s 스로틀 · 실측 연속 실패 간격 62.2s(`audit/service_reinstall…:22`) |
| 부팅 자동 기동(지연) | **있음** | `install_service.ps1:132` SERVICE_DELAYED_AUTO_START(현재 개발 PC 는 의도적으로 DISABLED — `md/DEPLOYMENT.md` §7-1) |
| 로그인 없이 기동 | **있음** | `Win32_Service.StartName = LocalSystem`; 캐시 경로를 LocalSystem 프로필이 아닌 배포 폴더로 고정(`install_service.ps1:171-184`) |
| 기동 실패 가시화 | **있음** | import 단계 `service_entry.py:57-83,131-140`(ID 1001·startup_failure.json), `_startup` 단계 `main.py:383-420`(ID 1000·1h 1회 원격 통보) · 이벤트 로그 실측 5건(§2) |
| 크래시 루프 감지 | **부분** | `service_status.ps1:38-54` 회전 파일 ≥10/1h → exit 4 — **사람이 실행해야** 안다. 작업 스케줄러 등록 없음(`Get-ScheduledTask` vigent 0건) |
| 앱 내부 워커 감독 | **있음** | hang 15s(`worker.py:44`), 재연결 백오프 상한 5s(`worker.py:55`), 기아 3단계(`starvation_guard.py:11-16,105-131`), 3단계가 `VIGENT_RESTART_CMD`(sc stop/start) 소비(`install_service.ps1:155,185`) |
| graceful shutdown | **부분** | `main.py:422-442` 워커·go2rtc·스레드 정리. NSSM 유예 **1.5s×3 단계**(`AppStopMethod* = 1500`) 뒤 강제 종료(`AppKillProcessTree=1`) — `alert_queue.stop(join 3s)`·`retention_scheduler.stop(join 2s)` 만으로 유예 초과 가능 |
| 정전 후 기기 자동 전원 | **없음(코드 밖·문서 0건)** | `grep -rn -w UPS docs deploy md` → 0 · "덮개"·"powercfg" 0 · BIOS AC 복구 언급 0 |
| 절전·덮개·화면 끄기 통제 | **없음(문서 0건)** | 위 grep. `SITE_CHECKLIST.md` 는 N-1~N-5(고정 IP·암호화·릴레이·대수·가중치)뿐 |
| Windows Update 통제 | **없음** | `grep "Windows Update" docs deploy md` → `LAPTOP_SIZING_PILOT4.md:29`(부하 항목으로만) 1건 |
| 시간 동기(NTP) | **없음** | grep NTP/w32tm — 문서 0건(바이너리·무관 매치 제외) |

### 4-2. 정전 → 통보 재개까지 코드 추적(현장 노트북·서비스 배포 가정)

| 단계 | 무엇이 일어나는가 | 근거 | 구멍 |
|---|---|---|---|
| ① 전원 복구 → 기기 켜짐 | **코드 밖.** 데스크톱은 BIOS "AC Power Loss" 설정, 노트북은 배터리 소진 후 전원 복구 시 자동 켜짐이 일반적으로 **보장되지 않는다**(기종별 확인 필요) | — | **OPS-02(P0)** — 사람이 전원 단추를 누르기 전까지 감시 공백 무기한. 원격에서 "부팅 안 됨"을 알 방법도 없다(외부 heartbeat 없음) |
| ② Windows 부팅 → BitLocker 자동 해제 | TPM 보호기 → 무인 해제(현장 노트북 실증) | `SITE_CHECKLIST.md:146-150` | TPM 상태 변경(펌웨어 업데이트) 시 복구 키 입력 요구 → 무인 깨짐(문서 자체가 경고 `:79-80`) |
| ③ 지연 자동 시작 → NSSM → `.venv\python service_entry.py --host 0.0.0.0 --port 8010` | LocalSystem, 로그인 불필요 | `install_service.ps1:124-132`, `audit/service_reinstall…:10` | 없음 |
| ④ `import main` → 보안 게이트(.env 토큰) | 토큰 없으면 SystemExit(1) → ID 1001 기록 → 60s 후 재시도 | `main.py:188-196`, `service_entry.py:133-136` | `.env` 손상 시 무한 루프(60s) — 이벤트 로그·json 으로 드러남(OK) |
| ⑤ `_startup`: 테마 로드 → go2rtc(선택) → 예열 스레드 → 기아 감시 → 경보 큐 → 통보 스레드 → 보존 스윕 | 각 단계 `_required/_optional` | `main.py:466-545` | go2rtc 는 재부팅이면 고아 없음. 예열 15~25s 동안 /health 503 |
| ⑥ 예열 완료 → `autostart_enabled()` 가 `data/cameras.json` 의 enabled 카메라 복원 | | `main.py:483-496`, `routers/cameras.py:426` | **`cameras.json` 이 비원자적 쓰기로 손상돼 있으면 `_load` 가 `{}` → 복원 0대 → `/health` 는 카메라 0대를 healthy 로 판정**(`camera_registry.py:39-48`, `health_status.py:135`) → **OPS-04(P1)** |
| ⑦ 워커 RTSP 접속 — 카메라가 아직 부팅 중이면 open 5s 타임아웃 → 백오프 1→5s → 재시도 | | `worker.py:72-87,55,668-716` | 카메라 IP 가 DHCP 로 바뀌면 영구 실패(`SITE_CHECKLIST` N-1) — 코드로는 못 잡는다 |
| ⑧ health 유예 90s 후 `stale_frame`/`ok` 판정 | | `health_status.py:36-41,54-79` | 없음 |
| ⑨ 경보 큐 이월: `alert_queue.start()` 가 pending 을 5s 주기로 drain | 정전 직전 pending 은 sqlite 에 남아 있음(write-ahead) | `alert_queue.py:9-13,83-92,335-353`, `main.py:522-528` | **인터넷(공유기·LTE)도 함께 복구 중이면 첫 ≈4분 안에 10회 소진 → dead**(§13 OPS-03). dead 요약 통보도 같은 채널로 1h 1회(`alert_queue.py:171-207`) |
| ⑩ 기동 실패 시 통보 | 원격 채널 있으면 즉시 1회 + 1h 1회 | `main.py:409-412` | 텔레그램 자체가 죽어 있으면 이벤트 로그만 남는다(문서가 인정) |
| ⑪ 보존 스윕 밀림 보정 | 마지막 스윕이 주기+1h 넘게 밀렸으면 60s 뒤 실행 | `retention_scheduler.py:43-68` | 시계가 틀리면(RTC 리셋) age 계산이 틀어져 오삭제/미삭제 가능 → **OPS-19(P3)** |

---

## 5. OTA·설정 버전 관리

| 항목 | 상태 | 근거 |
|---|---|---|
| 앱 원격 업데이트 | **없음(수동)** | `md/DEPLOYMENT.md` §8 "코드·설정 변경 후 반드시 재시작", 업데이트 명령 자체는 문서에 없음(§1 clone 만). `grep -i "git pull|rollback|롤백"` docs·md → 0건(관련 없는 B10 제외) |
| 모델 원격 업데이트 | **부분** | 매니페스트 갱신 → `fetch_weights.py` 재실행(sha 대조) — 절차는 되나 "이전 가중치 보존·되돌리기" 없음. `/health.rfdetr_slots[].sha16` 로 실제 탑재본 확인 가능(`routers/system.py:53-68`) |
| 설정 원격 업데이트 | **없음** | 현장 프로파일 = 파일 복사(`README_academy.md:23-25`), 되돌리기 = `.bak` 수동(`:41`). 런타임 변경분(`data/config/*.json`)은 git 밖(`runtime_config.py`) |
| 롤백 절차 | **없음** | 위 grep. 릴리스 태그는 있으나(`md/RELEASES.md`) 배포 단위(코드+가중치 sha+설정 스키마)로 묶이지 않음. `VERSION`=0.2.0 ↔ 태그 v1.0.1 불일치 |
| 설정 드리프트 게이트 | **있음** | `profile_intent.yaml:1-14`, `tests/test_profile_drift.py` |
| 핫 리로드 | **부분** | `data/danger_zone.json` 매 프레임 읽음(`md/DEPLOYMENT.md` §5-3), 나머지는 재시작 필요 |

---

## 6. 로깅

| 항목 | 상태 | 근거 |
|---|---|---|
| 구조화 이벤트 로그 | **있음** | `vlog.py:57-84` events.jsonl(10MB×10) · `data/recognition/events_YYYYMMDD.jsonl`(`data_engine.py:182`) · 삭제 감사 `data/retention/deletion_*.jsonl`(`retention.py:253-261`) |
| 앱 로그 회전 | **있음** | `vlog.py:42-43` 10MB×5. 실측 `vigent.log.1` 09-06, `.2` 08-28 → 개발 부하에서 ≈10MB/9일 |
| NSSM stdout/stderr 회전 | **부분** | 256MB 온라인 회전(`install_service.ps1:149-151`) · **회전본 개수 상한 없음**(NSSM 은 개수 옵션 없음) → 크래시 루프 실사고 8,139개 → retention 이 최근 50개만 유지(`retention.py:70-97`, 기본 `logs_keep_rotated 50`). 50×256MB = 최대 12.8GB 이론치 |
| 이중 기록 | 지적 | `vlog.py:37-45` StreamHandler(stderr) + 파일 → 같은 줄이 `vigent.log`(10MB 상한) 과 `vigent.err.log`(256MB 회전) 에 **두 번** 쓰인다 |
| 디스크 풀 방지 | **부분** | 보존 스윕(`retention.py:264-405`) 24h 주기 · 여유 <5GB 경고(`retention.py:99-102,284-290`) — **24h 에 1번**, `/health` 는 캐시된 status 만 읽음(`routers/system.py:94-117`) · 증거 쓰기 실패는 삼키고 경보는 계속(`data_engine.py:61-70`) — 좋은 설계. sqlite 디스크 풀 시 `enqueue` 예외 경로는 **확인 필요** |
| 민감정보 | **양호(실측)** | RTSP 마스킹 `worker.py:34,90,699,809,924,1194,1262`(`camera_registry.mask_source`) · `logs/vigent.log` 의 `rtsp://` 308건 **전부 `***:***@`** · `events.jsonl` rtsp 0·token 0 · `/health` 경로 축약 `routers/system.py:27-33` · `startup_failure.json.last_stderr` 는 게이트 안내문(실제 토큰 아님) · `data/go2rtc.log` 는 **미열람(확인 필요)** |
| 한글 인코딩 | **있음** | `PYTHONUTF8=1`(`install_service.ps1:170`) |
| Windows 이벤트 로그 | **있음** | 소스 VIGENT ID 1000/1001 실측(§2) |

---

## 7. 관측성 매트릭스

| 지표 | 상태 | 어디에 | 임계 알림 |
|---|---|---|---|
| 카메라별 프레임/검출 나이 | **있음** | `/health.cameras[*].last_frame_age_s/last_detect_age_s`(`health_status.py:81-100`) | degraded/unhealthy → HTTP 200/503(`routers/system.py:234-237`) |
| 추론 지연 분해(lock/infer/read/decode) | **있음** | `health_status.py:85-90` | 없음(값만) |
| 프레임 드랍·재연결·hang 횟수 | **있음** | `health_status.py:91-94` | 없음 |
| FPS(실효) | **부분** | `/status`(`docs/STABILITY.md` §5), `/health` 엔 없음 | 없음 |
| 경보 큐 길이·데드레터·폐기 | **있음** | `/health.alerts.{pending,dead,dead_1h,queue_depth,dropped,undeliverable}`(`routers/system.py:156-182`) | dead_1h·undeliverable → degraded; 1h 요약 통보 |
| 슬롯 저하·로드 오류 | **있음** | `slot_degraded`/`slot_errors`(`routers/system.py:56-77`) | person → unhealthy |
| 추론 장치(cuda/cpu) | **없음** | `device.py:25-39` 는 조용히 cuda→mps→cpu 폴백, `/health` 에 device 필드 없음(grep 0) | 없음 → **OPS-06** |
| GPU 메모리·온도·클럭 | **없음** | `nvidia-smi` 호출은 측정 스크립트에만(`scripts/pilot_load_test.py:133`, `capacity_probe.py:95`) | 없음 |
| CPU 온도·성능%·RSS | **없음** | 동일(키트만) | 없음 |
| 디스크 여유 | **부분** | `retention_status.json.disk_free_bytes`(24h) → `/health.disk_retention.warnings` | <5GB 경고(하루 지연) |
| 보존 스윕 생존 | **있음** | `/health.retention_sweep.thread_alive/overdue`(`retention_scheduler.py:143-157`) | 없음(값만) |
| 프라이버시(암호화·비식별화) | **있음** | `/health.privacy`(`routers/system.py:127-134`, `privacy.py:322-354`) | 없음 |
| 릴레이 OFF 실패 | **있음** | `/health.relay.off_failed` → degraded(`routers/system.py:193-194`) | degraded |
| 기동 실패 | **있음** | 이벤트 1000/1001 + 텔레그램 1h 1회 | 있음 |
| 크래시 루프 | **부분** | `service_status.ps1` exit 4 — 수동 | 없음(자동) |
| 시계열·대시보드(Prometheus/Grafana) | **없음** | `/hub` 가 2s 폴링(`index_hub.html:636`)으로 현재값만 표시 | 없음 |
| 외부 폴러(서버 무응답 감지) | **없음(Windows)** | `deploy/watchdog.sh` 는 Linux/mac. Windows 는 앱이 죽으면 NSSM 재시작뿐, "3주 크래시 루프" 가 그래서 생겼다(`md/DEPLOYMENT.md` §7-1) — 이제 이벤트/통보로 완화 | — |
| UI 상태 표시 정확성 | **결함** | `hub.py:78` `j.status==='ok'` — `/health.status` 는 `healthy/degraded/starting/unhealthy` 만 반환(`health_status.py:27-29`) → 허브 LINK 가 **항상 DEGRADED**. `themes/safety/index_local.html:472,535` 도 동일 → `/safety-local` 은 서버검출 대신 **항상 브라우저 COCO-SSD 폴백** | — |

---

## 8. 저장소 관리·백업

| 항목 | 상태 | 근거 |
|---|---|---|
| 용량 계획 | **있음(가정 명시)** | `docs/ops_disk_sizing.md:21-90` evidence 30.9KB 실측(S3)·시나리오 표 ≈0.63GB(20대·중). 이 PC 실측 평균은 **69.3KB/장**(14,175장) — S3 값의 2.2배. `audit/loadtest…dryrun.md:17,43` 모의 4대 **582MB/일**(루프 영상·판정 무효) |
| 보존 기간별 정리 | **있음** | evidence/recognition 30일 · audit/tbm/risk 1,095일 · field_eval 365일(`config/tuning.yaml:127-165`) · 첫 주기 보류·화이트리스트·pin(`retention.py:136-213,264-405`) · 자동 스윕 24h(`retention_scheduler.py`) · 실측 09-08 21:19 실행·74건 삭제 |
| 발송 경보 증거 자동 pin | **있음** | `alert_queue.py:103-130` |
| 경보 큐 정리 | **있음** | `alert_queue.prune` 30일(`alert_queue.py:240-260`, `retention.py:340-352`) |
| **DB·설정 백업/복구 절차** | **없음** | `ls scripts | grep -i "backup|restore"` → 0. 백업 대상이 흩어져 있다: `data/alert_queue.db`(sqlite, 저널 기본 — 크래시 안전), `data/cameras.json`·`camera_secrets.json`(비원자 쓰기 `camera_registry.py:46-48`), `data/retention/pinned.json`(`data_engine.py:95` 비원자), `data/config/*.json`(구역), `config/tuning.yaml`(프로파일 덮어쓰기), `config/notify.yaml`, `.env`, BitLocker 복구 키(USB 절차만 `SITE_CHECKLIST.md:91-128`). `data/cameras.json.bak`·`camera_secrets.json.bak` 는 존재하나 코드가 만든 것이 아니다(`grep "\.bak" vigent-core` → 0) |
| 증거 반출·보존 | **부분** | pin 으로 삭제만 막는다. 사고 조사용 "반출 패키지(증거+로그+경보 행+무결성 해시)" 스크립트 없음 |
| 서비스 설정 백업 | **있음(수동)** | `verify_service_reinstall.ps1:189-190` nssm dump, `audit/vigent_service_backup_2026-09-06.reg` |

---

## 9. 하드웨어 평가 — 배포기 = 현장 노트북(i7-10750H / GTX 1650 Ti 4GB / DDR4 16GB / SSD 1TB / Win10 Pro)

★기기 역할(2026-09-09 대표 정정): **배포기 = 노트북**(실제 설치 대상, `md/DEPLOYMENT.md:22` 2026-08-20 재설치 실증) · **개발기 = 이 데스크톱**(§2 현황, 현장에 가지 않음). §2 의 `powercfg`·디스크·NIC 값은 **개발기 값**이며 노트북에서는 §9-3 명령으로 다시 재야 한다.

### 9-0. 배포기 성능 근거(유일) — 2026-08-22 램프 실측(`docs/academy_visit_day.md:718-741`)
| N | 검출 p95 | 검출주기 | VRAM | GPU util | 판정 |
|---|---|---|---|---|---|
| 1 | 219ms | 0.5s | 30.8% | — | 기준 |
| 3 | 220ms | 0.5s | 31.8% | 38% | ✅ |
| **4** | **675ms** | 0.6s | 32.9% | 38% | ✅(급증 직후) |
| 5 | 868ms | 0.8s | 33.9% | 40% | ✅ |
| **6** | **972ms** | 0.9s | 34.9% ≈ 1.47GB | 37% | ✅ **한계**(CPU 94.9%) |
| 7 | 1,177ms | 0.9s | 35.9% | 39% | ⛔ |

한계 6 · 권장 4, 병목 CPU(GPU 는 40%·VRAM 36% 로 놀았다). 리포트 자체 문구: "권장 4는 급증 직후라 여유가 넉넉하지 않다 — 상시 4대면 실측을 한 번 더". 4대 4h 소크·실카메라 4대·10항목 판정(`docs/LAPTOP_SIZING_PILOT4.md` §7)은 **미측정**. 파일 카메라 2대 3h 소크만 PASS(`audit/soak_after_fixes_2026-08-26.md`). VRAM 4GB 충분 — 개발기에서 관측된 4.0GB 신호는 다른 앱 몫으로 확정(§9-4).

### 9-1. 배포기(노트북)를 현장 서버로 쓸 때의 위험표

★"확인 명령"은 **노트북에서 실행할 것** — 이 세션(개발기)에서는 실행하지 않았다. 노트북 실측값이 있는 항목만 "실증" 표기.

| # | 위험 | 왜 위험한가(근거) | 확인 명령(노트북) | 완화책 |
|---|---|---|---|---|
| H1 | **덮개 닫힘 → 절전** | Windows 노트북 기본 덮개 동작은 절전. 절전이면 서비스·RTSP·경보 전부 정지. 저장소 문서에 덮개·powercfg 절차 **0건**(§4-1). 개발기조차 USB 선택적 절전이 켜져 있었다(§2) — 노트북 기본값도 같을 가능성(추정) | `powercfg /query SCHEME_CURRENT SUB_BUTTONS 5ca83367-6e45-459f-a27b-476b1d01c936`(덮개, AC/DC 0=아무 것도 안 함) · `powercfg /query SCHEME_CURRENT SUB_SLEEP` · `powercfg /a` | `powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0`(+DC) · `powercfg /change standby-timeout-ac 0` · `/change hibernate-timeout-ac 0` · `powercfg /h off` — 스크립트화 + 재부팅 후 재확인(OPS-01) |
| H2 | **화면 꺼짐·USB 선택적 절전·NIC 절전** | 일부 기종은 화면 꺼짐과 함께 GPU 저전력 진입; USB 카메라·USB NIC 는 선택적 절전이 끊는다 | `powercfg /query SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3` · `Get-NetAdapterPowerManagement`(관리자) · `powercfg /devicequery wake_armed` | USB 선택적 절전 해제(AC) · NIC "컴퓨터가 이 장치를 끌 수 있음" 해제 · PCIe ASPM 해제 |
| H3 | **정전 후 자동 켜짐 없음** | 노트북은 배터리 소진 후 AC 복구 시 자동 부팅 기능이 BIOS 에 없는 기종이 많다(기종별 확인 필요). 문서 0건 | BIOS/UEFI "AC Power Recovery/Power On AC/Wake on AC" 유무 · `Get-CimInstance Win32_ComputerSystem \| select PCSystemType`(2=Mobile) | 기능 있으면 켜기 · 없으면 UPS 로 정전 창을 넘기고 **외부 heartbeat**(OPS-02)로 "부팅 안 됨"을 사람에게 알림 |
| H4 | **배터리 상시 100% 충전·팽창** | 24h AC 연결 시 리튬 배터리가 고온·만충 유지 → 팽창·화재 위험(제조사 권고 일반론, 수치는 확인 필요) | `Get-CimInstance Win32_Battery \| Format-List` · `powercfg /batteryreport /output D:\vigent_field\battery.html` | 제조사 도구 충전 상한(60~80%) · 분리 가능하면 분리 후 AC 전용(H3 와 상충 — UPS 필요) · 월 1회 batteryreport 보관 |
| H5 | **발열·스로틀링(24h 지속)** | i7-10750H(45W)·GTX 1650 Ti(모바일)를 얇은 섀시에서 4대 상시 추론 — 램프에서 한계 시 CPU **94.9%**, N=4 는 급증 직후(§9-0). `LAPTOP_SIZING_PILOT4.md` §1 이 3h 후 클럭 ≥80%·GPU <87°C 를 기준으로 선언했으나 §7 "미측정". 개발기 1h 소크는 다른 기계라 **판정에 쓰지 않는다**(§9-4) | `python scripts\pilot_load_test.py --cams 4 --hours 4 …` · `typeperf "\Thermal Zone Information(*)\Temperature" -sc 5` · `nvidia-smi -q -d PERFORMANCE`(Throttle Reasons) · `typeperf "\Processor Information(_Total)\% Processor Performance" -sc 5` | 4h 소크로 판정(문서 §1 기준) · 쿨링 패드·먼지 청소 주기 · 스로틀 시 §5-3 소프트웨어 감축 또는 대수 축소(N-4) |
| H6 | **소비자용 SSD 쓰기 수명** | **병목 아님(추정)**: 하루 쓰기 ≈ 증거 JPEG(개발기 실측 평균 69.3KB; S3 실측 30.9KB) × 4대×50건/일 + 로그 ≈ **20MB/일 ≈ 7GB/년**; 극단(모의 루프 드라이런) 582MB/일 ≈ 212GB/년. 1TB SSD TBW 는 제품 표기 확인 필요 — 어느 값이든 작다. 진짜 부담은 Defender 실시간 검사·소파일 I/O | `Get-PhysicalDisk \| Get-StorageReliabilityCounter \| select Wear,Temperature,PowerOnHours`(관리자) · `Get-Volume` · `Get-MpPreference \| select ExclusionPath`(관리자) | data/ Defender 제외(보안 검토 후) · 월 1회 Wear 기록 · 여유 <20% 알림(OPS-08) |
| H7 | **24h 가동 내구성(어댑터·팬·힌지)** | 노트북 어댑터·팬은 상시 가동 설계가 아니다(일반론). 노트북 소크는 파일 2대 3h 뿐 | `Get-CimInstance Win32_OperatingSystem \| select LastBootUpTime` 업타임 · 팬 소음/온도 기록 | 예비 어댑터 현장 비치 · 24h 실카메라 소크(`SOAK_24H_CHECKLIST.md` — 맥 경로라 Windows 판 재작성 필요, OPS-17) |
| H8 | **물리 보안(도난·케이블)** | 노트북은 들고 나가기 쉽다. BitLocker 는 노트북에 적용·검증됨(`SITE_CHECKLIST.md:142-153`) → 데이터는 보호되나 **감시 자체가 사라진다** | `Get-BitLockerVolume`(관리자) · `Get-Tpm` | 켄싱턴 락·잠금 캐비닛·케이블 고정 · 도난 시 외부 heartbeat 로 감지(H3 와 동일 장치) · USB 포트 정책 |
| H9 | **Windows Update 자동 재부팅·드라이버 교체** | Pro 라 정책 가능하나 절차 0건. (a) 설치 중 감시 공백 (b) WU 가 NVIDIA 드라이버를 올리면 cu126 torch 와 어긋나 `device.py:33-39` 가 **조용히 CPU 폴백** → 4대 CPU 부하 2.2배 → stale_detect(b 는 추측/미검증) | `Get-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate"` · `…\AU` · `…\UX\Settings`(ActiveHours) · `Get-ScheduledTask -TaskPath "\Microsoft\Windows\UpdateOrchestrator\"` | 그룹정책: 드라이버 제외(`ExcludeWUDriversInQualityUpdate=1`)·활성 시간·재시작 예약 창 · 재부팅 후 `service_status.ps1` 결과 텔레그램 예약 작업 · `/health` 에 device 노출(OPS-06) |
| H10 | **네트워크(Wi-Fi·4대 대역폭)** | 4대 RTSP(카메라당 수 Mbps)는 100Mbps 유선으로 충분하나 Wi-Fi 는 재연결·지연 편차 — `LAPTOP_SIZING_PILOT4.md` §6 "미측정". 노트북 Wi-Fi 링크속도 기록 1건(`audit/d3_recheck_2026-08-26.md:10`) | `Get-NetAdapter \| select Name,Status,LinkSpeed` · 키트 `net_rx_mbps` | 유선 고정 · DHCP 예약(N-1) |
| H11 | **VRAM 4GB** | **충분** — 노트북 램프 실측 ≈1.47GB(N=6), 개발기 실측 VIGENT 단독 1.4GB, 개발기의 4.0GB 관측은 다른 앱 몫으로 확정(§9-4) ★재측정 필요(F-33)(개발기 근거 — 서버가 CPU torch 였음) | `nvidia-smi --query-gpu=memory.used,memory.total --format=csv -l 5` 소크 중 | 키트 VRAM ≤3.5GB 기준으로 재확인. 학원 프로파일(YOLO 추가 모델) 조합도 램프에 포함돼 있었다 |

### 9-2. 장비 비교표(카메라 4대·2fps·3슬롯 기준) — 배포기 교체를 검토할 때만

수요 기준(저장소 실측·공식): GPU 있음 4대 **8.9 환산코어** / 5대 11.1, GPU 없음 카메라당 4.43코어 → 4대 17.7(`edgebox_purchase_guide.md:100-124,145`). VRAM 1.2~1.5GB. 후보 CPU 의 PassMark 환산값은 조회 후 산정(지어내지 않는다).

| 폼팩터 | 4대 예상 여유 | 전원 | 발열 | 코드 이식 리스크 | 비고 |
|---|---|---|---|---|---|
| **현 배포기 노트북**(i7-10750H / 1650 Ti 4GB / 16GB / 1TB / Win10 Pro) | 램프: 한계 6·권장 4(급증 직후) — **4h 소크 미측정** | 내장 배터리 = 짧은 UPS, 어댑터 1개 | H5 | **0** | 기본안. §5-3 소프트웨어 감축 → 4h 소크 2회로 확정 |
| CPU 상향 노트북/미니PC(8코어급 CPU + GPU 4~8GB, Win Pro, 두꺼운 섀시) | 가능(추정) — PassMark 환산 ≥ 8.9 확인 | 어댑터 | 소크 필수 | 0 | §5-4 C. 값싼 노트북은 Home 이라 제외 |
| 소형 GPU 워크스테이션(데스크톱 8코어급 + RTX 4060/A2000) | 여유 큼(개발기 계열 실측 한계 7·권장 5) | 300~500W, UPS | 팬 | 0 | 다현장·재학습 겸용 후보 |
| 산업용 팬리스 PC(dGPU 없음) / Jetson Orin | 불성립(CPU 전용 25.3 환산코어) / 미검증·이식 리스크 高(Windows 의존 4가지, systemd 부재 경로) | — | — | 0 / 高 | 제외 |

### 9-3. 노트북에서 실행할 명령(한 묶음, 전부 조회)

```powershell
Get-CimInstance Win32_ComputerSystem | Select-Object Name,Manufacturer,Model,PCSystemType   # 2 = Mobile
Get-CimInstance Win32_Battery | Format-List
powercfg /batteryreport /output D:\vigent_field\battery_$(Get-Date -Format yyyyMMdd).html
powercfg /getactivescheme; powercfg /a
powercfg /query SCHEME_CURRENT SUB_BUTTONS      # 덮개(LIDACTION 5ca83367…) AC/DC 색인
powercfg /query SCHEME_CURRENT SUB_SLEEP        # STANDBYIDLE·HIBERNATEIDLE AC 0 인지
powercfg /query SCHEME_CURRENT SUB_VIDEO
powercfg /query SCHEME_CURRENT 2a737441-1930-4402-8d77-b2bebba308a3   # USB 선택적 절전
powercfg /query SCHEME_CURRENT 501a4d13-42af-4429-9fd1-a8218c268e20   # PCIe ASPM
powercfg /query SCHEME_CURRENT SUB_PROCESSOR
powercfg /devicequery wake_armed
Get-NetAdapter | Select-Object Name,Status,LinkSpeed
Get-NetAdapterPowerManagement | Format-List      # 관리자
Get-PhysicalDisk | Select-Object FriendlyName,MediaType,BusType,Size,HealthStatus
Get-PhysicalDisk | Get-StorageReliabilityCounter | Select-Object DeviceId,Wear,Temperature,PowerOnHours   # 관리자
Get-Volume | Where-Object DriveLetter | Select-Object DriveLetter,Size,SizeRemaining
Get-BitLockerVolume | Select-Object MountPoint,VolumeStatus,ProtectionStatus   # 관리자
Get-Tpm | Select-Object TpmPresent,TpmReady,TpmEnabled
typeperf "\Thermal Zone Information(*)\Temperature" -sc 3
nvidia-smi --query-gpu=name,driver_version,temperature.gpu,clocks.sm,clocks.max.sm,memory.used,memory.total,power.draw --format=csv
nvidia-smi -q -d PERFORMANCE     # Throttle Reasons
Get-Service VIGENT | Select-Object Status,StartType
& .\deploy\windows\nssm.exe get VIGENT Start; & .\deploy\windows\nssm.exe get VIGENT AppRestartDelay; & .\deploy\windows\nssm.exe get VIGENT AppThrottle
Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings" | Select-Object ActiveHoursStart,ActiveHoursEnd
Get-ItemProperty "HKLM:\SOFTWARE\Policies\Microsoft\Windows\WindowsUpdate" -ErrorAction SilentlyContinue | Format-List
Get-ScheduledTask -TaskPath "\Microsoft\Windows\UpdateOrchestrator\" | Select-Object TaskName,State
w32tm /query /status
# 수용량(4시간 ×2: 기준선 → S1+S2+S9 적용) — FINAL-REPORT §5-3 절차
python scripts\pilot_load_test.py --cams 4 --hours 4 --interval 600 --overload-cams 2 --overload-min 20 --tag laptop_base
```

### 9-4. 개발기(이 데스크톱) 실측·위생 — 현장 성능 판정에 사용 불가
개발기(이 데스크톱)의 실측 사양: MSI MAG B850M MORTAR WIFI · 섀시 코드 3(Desktop) · 배터리 없음 · Ryzen 9 9900X · RTX 5070 Ti 16,303MiB · DDR5 64GB · C: SATA SSD 240GB / D: SATA HDD 1TB(저장소 위치) · Windows 11 Home · 이더넷 100Mbps.
- 2026-09-08~09 개발기 소크(4대 파일, 1h, `audit/loadtest_20260908_2356_desktop_1h.md`): 시스템 CPU 45~61%·서버 6.1~7.4코어·age p95 ≤0.5s·degraded 0·GPU 46~63°C·SM 2,782~2,872MHz·RSS 3.3→1.2GB. ★재측정 필요(F-33: 이 시점 개발기 .venv 는 CPU torch 2.12.0+cpu — GPU util·VRAM 차분·서버 코어는 CPU 추론 조건의 값, `benchmarks/FINDINGS.md` F-33) **다른 기계이고 1h<4h 라 현장 판정에 쓰지 않는다.** 소득: 서버 종료 후에도 `nvidia-smi` 7,660MiB·util 19% 잔존, `--query-compute-apps` 에 게임·브라우저·Discord·Steam·Claude 앱 등 30여 개 → 개발기에서 본 VRAM 4.0GB·util 89% 는 다른 앱 몫, 서버 몫 ≈1.1~1.2GB(기준선 1.4GB 부합).
- 개발기 위생(측정 신뢰용): GPU 지표는 다른 앱을 끈 상태에서 · 저장소·`data/`·`logs/` 가 SATA HDD(D:) 위라 I/O 지표가 현장 SSD 와 다름 · 테스트·부하시험이 운영 `data/` 를 오염(Phase 7 P1-1) → 별도 데이터 디렉터리 · Windows Home 이라 BitLocker 검증 불가(N-2 는 노트북에서 검증됨) · `powercfg` 는 USB 선택적 절전 사용·HDD 20분 스핀다운 상태(§2).

## 10. 코드 밖 체크리스트(현장 장비·설비)

`deploy/SITE_CHECKLIST.md` N-1~N-5 에 **없는** 항목만 적는다(추가 후보 N-6~).

- [ ] **N-6 전원·절전(노트북)**: 덮개 닫힘=아무 것도 안 함(AC/DC) · 절전/최대 절전 AC 0 · 화면 꺼짐은 무관하나 GPU 저전력 확인 · USB 선택적 절전 해제 · NIC/PCIe 절전 해제 · `powercfg /h off` · 재부팅 후 `powercfg /query` 로 재확인 → 결과를 `audit/power_<날짜>.txt` 로 보관
- [ ] **N-7 정전 복구**: BIOS AC Power Recovery 가능 여부(노트북 기종별) · UPS(용량 = 노트북 어댑터 + 공유기/스위치 + 카메라 PoE, 정전 지속 시간 목표 분 단위로 산정 — 값은 현장 전력 조사 후) · 공유기·카메라도 UPS 에 · 복구 후 부팅→`/health` 200 까지 시간 실측
- [ ] **N-8 외부 heartbeat**: 관제 PC 또는 폰에서 `/health` 를 주기 폴링해 무응답 N분이면 사람에게 알림(현재 Windows 에는 외부 폴러 없음) — 부팅 실패·도난·네트워크 단절을 한 장치로 잡는다
- [ ] **N-9 Windows Update**: 드라이버 제외 정책 · 활성 시간 · 재시작 예약 창 · 업데이트 후 자동 `service_status.ps1` 통보 · 대규모 기능 업데이트는 수동 승인
- [ ] **N-10 시간 동기**: NTP 서버(폐쇄망이면 내부 NTP 또는 공유기) · `w32tm /query /status` 편차 기록
- [ ] **N-11 물리**: 잠금 캐비닛/켄싱턴 락 · 케이블 고정·라벨 · 예비 어댑터 · 방진(분진 현장이면 팬리스 또는 필터) · 방수 등급(옥외면 IP 등급 함체 — 등급값은 현장 환경 조사 후) · 주변 온도 상한(장비 규격 확인)
- [ ] **N-12 배터리·저장장치**: 충전 상한 설정 가능 여부 · 월 1회 `powercfg /batteryreport` · 팽창 징후 점검 · SSD 여유 <20% 알림 · 월 1회 Wear 기록
- [ ] **N-13 백업 매체**: BitLocker 복구 키(N-2 절차) + `data/`·`config/`·`.env` 스냅샷을 **다른 매체**에 주기 보관(§13 OPS-05 스크립트 전제)
- [ ] **N-14 네트워크**: 유선 고정 · 링크 속도 기록 · 카메라 4대 동시 수신 대역폭 실측(키트 `net_rx_mbps`)

---

## 11. 다중 현장·중앙 관제 가능 여부

| 항목 | 판정 | 근거 |
|---|---|---|
| `hub.py` | **단일 서버 UI** — 같은 서버의 라우트 타일 목록(`hub.py:10-27`), `/health`·`/safety/auto/feed` 를 자기 자신에게만 요청(`:77-80`) | |
| 원격 집계 API | **없음** | `config/site.example.yaml:6` `central_url` 은 `setup_console.py:35,52,174,181` 에서 **저장·표시만** — 전송 코드 0(`grep central_url vigent-core` 1파일) |
| 다중 서버 상태 모음 | **없음** | Prometheus/exporter/푸시 없음(§7) |
| 원격 접근 | 부분 | LAN 바인드 + Bearer(`install_service.ps1:161-166`), TLS 는 역프록시 문서(`docs/TLS_DEPLOYMENT.md`) |
| 결론 | 현장 N개 = 서버 N개를 **각각** 브라우저로 여는 구조. "본사에서 5개 현장 한 화면" 은 현재 불가 | |

---

## 12. 배포·운영 관련 문서-실물 불일치(발견분)

| 문서 | 내용 | 실물 |
|---|---|---|
| `deploy/windows/README.md:15` | "죽으면 5초 뒤 자동 재시작" | `nssm get AppRestartDelay` = 60000 · `install_service.ps1:141` |
| `deploy/windows/README.md:19` | 종료코드 0~3 | `service_status.ps1:8` 은 4(크래시 루프) 포함 |
| `md/DEPLOYMENT.md:188-192` | "저장소 루트에도 같은 이름의 구판 `fetch_weights.py` 가 있다" | 루트에 없음(`ls`), `Dockerfile:38` 도 이를 전제 |
| `deploy/DEPLOYMENT.md:26-27` | `python fetch_weights.py verify/download` | 정본 CLI 는 `--all/--check`(`scripts/fetch_weights.py:16-19`) |
| `deploy/DEPLOYMENT.md:31-33` | "docker build … 자동 정리" | 빌드 불가(§3) |
| `docs/SOAK_24H_CHECKLIST.md:14-26` | 맥 launchd·`/opt/anaconda3` 경로 | Windows 서비스 배포와 불일치(2026-08-10 이후 미수정) |
| `docs/INFRA_REQUIREMENTS.md:10-21` | "현재 개발은 Apple Silicon(MPS)" | 개발 PC 는 Ryzen/RTX(§2) — 같은 문서 §1.2 는 갱신됨 |
| `deploy/academy/README_academy.md:50-52` | "`disabled_detectors` 하드코딩 결함" | `routers/system.py:226-232` 에서 이미 해소(2026-08-20) — 문서만 남음 |

---

## 13. 이슈 목록

| ID | 심각도 | 제목 | 근거 | 영향 | 권장 | 공수 |
|---|---|---|---|---|---|---|
| OPS-01 | **P0** | 배포기(노트북) 절전·덮개·USB/NIC 절전 통제 절차 0건 | `grep powercfg/덮개 docs deploy md` → 0 · `SITE_CHECKLIST.md` N-1~N-5 에 전원 항목 없음 · 이 PC 도 USB 선택적 절전 사용(§2) | 덮개를 닫거나 절전 진입 시 서비스가 멈춰 감시·경보 **무기한 공백**, /health 무응답이라 앱은 아무것도 못 남김 | `deploy/windows/set_power_plan.ps1`(powercfg 설정 + `powercfg /query` 재검증 출력 + audit 저장) · SITE_CHECKLIST N-6 · `verify_service_reinstall.ps1` 에 전원 검증 단계 추가 | S |
| OPS-02 | **P0** | 정전 → 전원 복구 시 노트북 자동 부팅 보장 없음·UPS 없음·외부 heartbeat 없음 | UPS·BIOS·heartbeat 문서 0건(§4-1) · 서비스 자동 기동은 부팅 이후만(`install_service.ps1:132`) · Windows 외부 폴러 없음(§7) | 노트북은 배터리 소진 후 사람이 켜기 전까지 죽어 있고, 원격에서 알 수 없다 | SITE_CHECKLIST N-7·N-8 · UPS 사양 산정 · 관제 PC/폰용 폴러(`service_status.ps1` 를 예약 작업 + 텔레그램) 또는 서버가 주기적으로 "살아있음" 을 외부(텔레그램)에 보내는 옵션 | S(문서)/M(폴러) |
| OPS-03 | **P1** | 경보 재시도 창이 ≈4분 — 인터넷 순단이 그보다 길면 critical 경보가 dead | `alert_queue.py:47-52` 기본 10회·상한 60s · `:133-155` 지수 백오프 1,2,4,8,16,32,60,60,60 = 243s · `config/tuning.yaml alerts:` 에 `max_attempts/backoff_cap_s` 없음(코드 기본) · dead 요약도 같은 채널 1h 1회(`:171-207`) | 정전·공유기 재부팅·LTE 순단 후 첫 4분 안에 미전송 경보 영구 폐기(수동 재전송 API 없음) | 시간 기반 재시도(예: 24h 동안, 상한 5분)로 변경 · `alert_queue_days` 처럼 tuning 에 노출 · dead 재전송 라우트(관리자) | S |
| OPS-04 | **P1** | 레지스트리·pin 파일 비원자적 쓰기 → 손상 시 카메라 전부 소실이 healthy 로 보임 | `camera_registry.py:46-48` `write_text` 직접 · `data_engine.py:95` 동일 · `_load` 실패 시 `{}`(`:39-43`) · 카메라 0대 = healthy(`health_status.py:135`) · 코드가 만드는 `.bak` 없음 | 쓰기 중 정전/크래시 → 재부팅 후 복원 0대 → **아무 경고 없이 감시 중단** | tmp 파일 + `os.replace` 원자 쓰기 + 직전본 `.bak` 유지 + 기동 시 "직전 기동 N대 → 지금 0대" 이면 degraded + 통보 | S |
| OPS-05 | **P1** | 백업·복구 절차 0건 | `scripts/` backup/restore 0 · 대상 목록 §8 · BitLocker 키는 USB 절차만 | 디스크 고장·오삭제·오설정 시 카메라·구역·자격증명·경보 이력·pin 복구 불가 | `scripts/backup_state.py`(대상 zip + sha256 + 복구 리허설 옵션) · retention 스레드에 주기 편입 · 외부 매체/관제 PC 로 복사 · 복구 런북 | M |
| OPS-06 | **P1** | CUDA→CPU 조용한 폴백 + /health 에 추론 장치 미노출 | `device.py:33-39` · `/health` 필드에 device 없음(`routers/system.py:199-232`) · torch 는 requirements 밖 수동 CUDA 휠(`requirements.txt:37-41`) | 재설치·드라이버 교체(H9)·휠 재설치 시 CPU 로 돌며 4대 부하 2.2배 → stale_detect 연쇄, 원인은 로그에서만 | `/health.device{name, cuda_available, torch_version}` + 서비스 env `VIGENT_DETECT_DEVICE=cuda` + `VIGENT_REQUIRE_CUDA=1`(없으면 기동 거부·이벤트 1000) | S |
| OPS-07 | **P1** | Windows Update 자동 재부팅·드라이버 교체 통제 없음 | 문서 1건(부하 항목) · 개발 PC 정책 키 없음(Home) · 노트북(Pro) 절차 없음 | 야간 재부팅 중 감시 공백 + 드라이버 교체 시 OPS-06 경로(추측/미검증) | 그룹정책(드라이버 제외·활성 시간·재시작 예약) 스크립트 + 재부팅 후 `service_status.ps1` 자동 통보 예약 작업 · SITE_CHECKLIST N-9 | S |
| OPS-08 | P2 | 디스크 여유·GPU/CPU 온도·RSS 메트릭 부재, 임계 알림 없음 | §7 표 · `retention.py:284-290` 24h 1회 · `nvidia-smi` 는 측정 스크립트만 | 디스크 풀·스로틀·누수를 사람이 현장에 가서야 안다 | `/health.host{disk_free_gb, gpu_temp_c, gpu_util, gpu_mem_mb, cpu_perf_pct, rss_mb}`(psutil·nvidia-smi 5s 캐시) + warnings 임계 + 일일 요약 통보 | M |
| OPS-09 | P2 | Dockerfile 빌드 불가·compose 없음·GPU 없음 | `Dockerfile:24` vs `requirements.txt:7` · `Dockerfile:38` 루트 파일 부재 · `git log` 2026-08-10 | 컨테이너 배포를 문서가 광고하나 실제 불가 → 심사·고객 신뢰 손상 | CI 에 `docker build` 스텝 추가하거나 "미지원" 으로 문서 정정 · constraints COPY · `scripts/fetch_weights.py` 경로 | S |
| OPS-10 | P2 | 폐쇄망 설치 절차 불완전(pip 휠·NSSM·vendor JS·CDN 화면) | §3 폐쇄망 4행 | 인터넷 없는 현장 설치가 사람 손·기억에 의존 | `scripts/make_offline_bundle.py`(`pip download -r requirements.txt -c constraints.txt --platform win_amd64 --python-version 3.11` + torch cu126 + weights + nssm + go2rtc + vendor) + 오프라인 설치 검증 런북(N-5 확장) | M |
| OPS-11 | P2 | OTA·롤백 절차 부재, 배포 단위 미정의 | §5 · `VERSION` 0.2.0 ↔ 태그 v1.0.1 | 현장 업데이트 실패 시 되돌릴 기준점이 없다 | 릴리스 번들(커밋 태그+가중치 sha+tuning 스키마 버전) · `deploy/windows/upgrade.ps1`(이전 트리 보존 → 교체 → /health 200 검증 → 실패 시 자동 복귀) | M |
| OPS-12 | P2 | 다중 현장 중앙 관제 없음 | §11 | 현장이 늘면 운영 인력이 비례 | 최소: 각 서버가 `/health` 요약을 중앙(HTTP)으로 푸시(central_url 소비) + 중앙 페이지 1개 | M/L |
| OPS-13 | P2 | `/health.status==='ok'` 비교 버그 → 허브 항상 DEGRADED, `/safety-local` 항상 브라우저 폴백 | `hub.py:78` · `index_local.html:472,535` · `health_status.py:27-29` | 운영자가 "DEGRADED" 에 둔감해짐(경고 피로) · 로컬판 서버검출 미사용 | `['healthy','degraded']` 판정으로 수정 + 테스트 | S |
| OPS-14 | P2 | NSSM 회전본 무제한·앱 로그 이중 기록 | `install_service.ps1:149-151` · `vlog.py:37-45` · `retention.py:70-97`(50개 유지=최대 12.8GB) | 크래시 루프·장기 운영 시 logs/ 가 data/ 보다 커질 수 있음 | 서비스 모드에서 StreamHandler 레벨 WARNING 이상 또는 파일만 · `logs_keep_rotated` 를 총 용량 기준으로 | S |
| OPS-15 | P2 | 카메라 정의 소스 2개(`site.yaml` vs `data/cameras.json`)·`VIGENT_EDGE` 서비스 미설정 | `main.py:498-506` · env 7개 · `setup_console.py:12` | 운영자가 site.yaml 을 고쳐도 서비스는 안 읽는다(혼동) | 문서에 "서비스는 cameras.json 만" 명시 또는 site.yaml 을 cameras.json 으로 가져오는 1회 마이그레이션 | S |
| OPS-16 | P3 | systemd 유닛이 부재 런처를 가리킴 | `vigent-edge.service:24` · `git ls-files bin` | Linux 경로 문서-실물 불일치 | `bin/vigent-serve.sh` 로 교체하거나 "미지원" 표기 | S |
| OPS-17 | P3 | 배포 문서 8건 불일치 | §12 | 설치자가 잘못된 값(5초·구 CLI·맥 경로)을 믿는다 | 각 줄 정정 · SOAK 체크리스트 Windows 판 | S |
| OPS-18 | P3 | NSSM 종료 유예 1.5s×3 vs `_shutdown` 최대 5s+ | `nssm get AppStopMethod*` · `main.py:422-442`, `alert_queue.py:355-373` | 강제 종료로 증거 쓰기·큐 갱신이 잘릴 수 있음(sqlite 는 저널로 복구) | `AppStopMethodConsole 10000` 으로 상향 + `_shutdown` 소요 로그 | S |
| OPS-19 | P3 | 시간 동기(NTP) 절차·검사 없음 | grep 0 · `retention.py:238-240` mtime 기반 age | RTC 어긋나면 보존 age·경보 타임스탬프·증거 파일명이 틀어진다 | SITE_CHECKLIST N-10 + `/health.host.clock_offset_s`(w32tm) | S |
| OPS-20 | P3 | `service_status.ps1` 크래시 루프 검사가 수동 | `service_status.ps1:38-54` · `Get-ScheduledTask` 0건 | 3주 크래시 루프 재발 시 여전히 사람이 실행해야 안다(이벤트·통보로 완화됨) | 설치 스크립트가 예약 작업(10분 주기, exit≥3 이면 텔레그램) 등록 | S |

---

## 14. 경쟁 대비 격차(산업안전 CCTV·엣지 AI 일반 관행 대비 — 특정 제품 수치 인용 없음)

| 영역 | 통상 기대 | VIGENT 현재 | 격차 |
|---|---|---|---|
| 중앙 관제·플릿 관리 | 다현장 대시보드, 원격 상태·설정·업데이트 | 단일 서버 UI, 수동 업데이트 | 큼(OPS-11·12) |
| 관측성 | 시계열 메트릭·알림 규칙·온도/디스크 | `/health` 스냅샷 + 텔레그램(기동 실패·데드레터) | 중(OPS-08) |
| 하드웨어 워치독·UPS 연동 | HW WDT, UPS 신호로 안전 종료/재기동 | 소프트웨어 감독만, UPS 언급 0 | 중(OPS-02) |
| VMS/ONVIF 연동 | 기존 NVR·VMS 에 이벤트/영상 연계 | 없음(`grep -i onvif vigent-core docs` → 코드 0) | 중(제품 방향 확인 질문) |
| 알림 채널 | SMS·전화·현장 사이렌·앱 푸시 | 텔레그램·이메일·웹훅·릴레이(mock 검증) | 중 |
| 폐쇄망 패키지 | 오프라인 인스톨러 1개 | 가중치·go2rtc 매니페스트 + 수동 pip/NSSM | 중(OPS-10) |
| 산업용 폼팩터 | 팬리스·광역 전원·DIN 레일 | Windows 노트북/PC 전제 | 하드웨어 선택 문제(§9-2) |
| 데이터 보호·보존 | 암호화·보존·pin·삭제 감사 | **있음**(BitLocker 검사·pin·삭제 감사·자동 스윕) | 우위 요소 |
| 기동 실패 가시화·설치 검증 | — | 이벤트 로그·상태 파일·재설치 검증 스크립트 | 우위 요소 |

---

## 15. 확인 질문(판단 유보)

1. **현장 노트북에 자동 부팅(AC Power Recovery) BIOS 항목이 있는가?** 없으면 OPS-02 의 완화는 UPS + 외부 heartbeat 밖에 없다.
2. **인터넷 경로는 무엇인가(유선 인터넷·LTE 라우터·테더링)?** 순단 길이가 OPS-03 의 재시도 창(≈4분) 설계값을 정한다.
3. **텔레그램 외 채널(SMS·전화)을 계약에 넣을 것인가?** 인터넷 단절 시 경보가 아예 안 나가는 구조라 계약 문구에 반영해야 한다.
4. **Docker·Linux(systemd) 경로를 제품 범위로 유지할 것인가, "미지원" 으로 정리할 것인가?**(OPS-09·16)
5. **`site.yaml` 을 계속 지원할 것인가?**(OPS-15) 서비스 배포는 `cameras.json` 만 읽는다.
6. **VMS/NVR 연동 요구가 고객에게서 나온 적이 있는가?**(§14) 있다면 아키텍처 항목이다.
7. **`data/go2rtc.log` 에 카메라 자격증명이 평문으로 남는가?** 이 세션에서 열지 않았다. 남는다면 파일 ACL·회전 정책이 필요하다.
8. **이 PC 에서 23:16 부터 도는 python PID 30036(WS 4.9GB, 8010 LISTEN 없음)은 무엇인가?** 부하 시험·다른 포트 서버라면 무방하나, 고아 프로세스면 GPU/메모리를 점유한다.
9. **개발 PC 의 저장소·data/ 가 HDD(D:) 위에 있는 것을 알고 있는가?** 개발 측정(디스크 I/O·retention 소요)이 현장 SSD 와 다를 수 있다.
10. **노트북 4대 키트 실측(4h)은 언제 하는가?** 이 문서의 하드웨어 판단은 전부 그 결과에 종속된다(§9-2).

---

## 16. 한 줄 요약

`D:\vigent_original\docs\review\06-operations-deploy.md` — ★역할 정정 2026-09-09: 배포기 = 현장 노트북, 개발기 = 이 데스크톱(§9). **P0 2건(노트북 절전·덮개 통제 부재, 정전 후 자동 부팅·UPS·외부 heartbeat 부재) · P1 5건(경보 재시도 창 4분, 레지스트리 비원자 쓰기, 백업 절차 부재, CUDA 조용한 폴백, Windows Update 통제)**, P2 8 · P3 5.
