# 실기 검증 절차 — CODE_AUDIT A 그룹 수정분 (2026-09-28, 관리자 셸 · 실기는 대표가 직접)

> 대상: 코드·테스트로는 고정했지만 **관리자 권한·실제 서비스 등록·실제 USB** 가 있어야만 확인되는 5가지.
> 각 항목은 "무엇을 · 어떻게 · 통과 기준 · 결과 적는 곳" 4줄. 전부 개발기(RTX 5070 Ti, Win11)에서 하되, 설치 대상은 `D:\VIGENT_TEST` 처럼
> **별도 폴더·별도 포트(8020)** 를 써서 개발 저장소·8010 벤치와 섞이지 않게 한다. 끝나면 `uninstall.ps1` 로 서비스를 지운다.
> 결과는 이 문서 맨 아래 표에 날짜와 함께 적고, [CODE_AUDIT_20260928.md §0-2](../review/CODE_AUDIT_20260928.md) 의 해당 행을 갱신한다.

준비물: `D:\vigent_usb_stage`(2026-09-28 academy 빌드, §1 표 참조) · **관리자 PowerShell**(`Win+X → 터미널(관리자)`) · 카메라 1대 이상의 RTSP 주소(없으면 A5 는 건너뜀).

---

## §1. USB 스테이징 자체 검증 (관리자 불필요 — 이미 자동으로 끝난 것을 눈으로 확인)

- **무엇을**: `build_usb.ps1 -Profile academy` 산출물에 fk510 지게차 가중치·학원 설정이 실렸고 CRLF 검증을 통과했는지.
- **어떻게**:
  ```powershell
  Get-Content D:\vigent_usb_stage\VERSION.txt
  Test-Path D:\vigent_usb_stage\portable\app\vigent-core\weights\forklift_rfdetr_fk510_smoke.pth
  Select-String -Path D:\vigent_usb_stage\portable\app\themes\safety\vision.yaml -Pattern "fk510"
  Select-String -Path D:\vigent_usb_stage\portable\app\config\tuning.yaml -Pattern "include_forklift|forklift: 0.50"
  Get-ChildItem D:\vigent_usb_stage\portable\python\wheels_cuda
  ```
- **통과 기준**: 가중치 파일 존재(120,797,435 B) · vision.yaml `forklift: …fk510_smoke.pth` · tuning `include_forklift: 1`·`forklift: 0.50` · wheels_cuda 에 `torch-2.12.0+cu130` 휠 · 빌드 로그에 `CRLF 검증 통과` 줄.
- **결과**: 빌드 로그 `audit/usb_build_20260928.log`(아래 표).

## §2. NSSM 자가 재기동 (기아 3단계 `exit 3` → `AppExit Default Restart`, 60 s 지연)

- **무엇을**: 앱이 스스로 종료코드 3 으로 나가면 NSSM 이 60 s 뒤 다시 띄우는지(예전 `sc stop & sc start` 방식은 실기 미검증인 채 폐기됨).
- **어떻게** (관리자 PowerShell):
  ```powershell
  # 1) 시험 설치(별도 폴더·포트). 인수시험·마법사는 -NoService 없이 실제 서비스 등록까지.
  powershell -NoProfile -ExecutionPolicy Bypass -File D:\vigent_usb_stage\installer\install.ps1 -UsbRoot D:\vigent_usb_stage -Target D:\VIGENT_TEST -Port 8020 -Bind 127.0.0.1 -SkipPreflight
  # 2) NSSM 파라미터가 스크립트대로 들어갔는지
  $n = "D:\VIGENT_TEST\app\deploy\windows\nssm.exe"
  & $n get VIGENT AppExit Default        # → Restart
  & $n get VIGENT AppRestartDelay        # → 60000
  & $n get VIGENT AppStopMethodConsole   # → 30000
  & $n get VIGENT AppEnvironmentExtra    # → VIGENT_RESTART_CMD=exit:3 포함(§4 의 4개 env 도 여기서 같이 확인)
  # 3) 재기동 실측: 서비스 파이썬 PID 를 죽이고(어떤 종료코드든 Restart) 다시 뜨는 시각을 잰다
  $p = (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*VIGENT_TEST*service_entry*" }).ProcessId; $t0 = Get-Date   # $pid 는 PowerShell 자동 변수(현재 셸 PID)라 쓰지 않는다
  Stop-Process -Id $p -Force
  do { Start-Sleep 5; $h = try { Invoke-RestMethod http://127.0.0.1:8020/health } catch { $null } } until ($h -and $h.phase -eq "ready")
  "재기동까지 $(((Get-Date) - $t0).TotalSeconds) 초"
  # 4) exit:3 경로 자체(graceful 정리 뒤 종료코드 3): 콘솔 모드로 한 번
  cd D:\VIGENT_TEST\app\vigent-core; $env:VIGENT_RESTART_CMD = "exit:3"
  ..\..\python\python.exe -c "import sys; sys.path.insert(0,'.'); import main, starvation_guard as sg; sg._escalate()"; "exit=$LASTEXITCODE"
  ```
- **통과 기준**: 2) 네 값이 표와 같다 · 3) `/health.phase=ready` 까지 **60~150 s**(지연 60 s + 모델 예열 ≈25 s + 여유), `state\logs` 에 재기동 기록 · 4) `exit=3` 이고 로그에 `[기아 3단계] 프로세스 자가 종료(exit 3)` 와 `_shutdown` 단계(릴레이 OFF·워커 정지·큐 이월)가 그 앞에 찍힘.
- **미통과면**: NSSM 이 60 s 안에 안 띄우면 `AppThrottle 180000`(기동 후 3분 안에 죽으면 감속) 에 걸린 것일 수 있다 — 서비스가 뜬 지 3분 뒤에 다시 시험.

## §3. 서비스 정지 대기 30 s (`AppStopMethodConsole 30000`) 가 `_shutdown` 을 끝까지 두는가

- **무엇을**: `sc stop VIGENT` 때 릴레이 OFF → 워커 병렬 정지(데드라인 20 s) → 큐 이월이 잘리지 않고 끝나는지.
- **어떻게**: 카메라 2대 이상 등록된 상태에서
  ```powershell
  $t0 = Get-Date; sc.exe stop VIGENT; do { Start-Sleep 1 } until ((Get-Service VIGENT).Status -eq "Stopped"); "정지까지 $(((Get-Date) - $t0).TotalSeconds) 초"
  Get-Content D:\VIGENT_TEST\state\logs\vigent.log -Tail 60 -Encoding UTF8 | Select-String "relay|stop_all|carried_over|_shutdown|종료"
  # 서비스 stderr 는 app\logs\vigent.err.log — ★파일은 UTF-8 이다(2026-09-28 실측: utf-8 디코드 OK·cp949 실패). PS 5.1 Get-Content 기본(ANSI)으로 열면 깨져 보이므로 반드시 -Encoding UTF8
  Get-Content D:\VIGENT_TEST\app\logs\vigent.err.log -Tail 40 -Encoding UTF8
  ```
- **통과 기준**: 정지 **< 30 s** · 로그에 `stop_all: … pending` 이 **없고**(있으면 카메라 이름과 함께 ERROR) `carried_over` 줄이 있음 · `Stopped` 뒤 파이썬 프로세스 잔존 0(`Get-Process python*`).
- **미통과면**: 30 s 를 넘겨 강제 종료됐다면 어느 단계에서 멈췄는지 마지막 줄을 적는다(워커 join 8 s×N 이 아니라 병렬 20 s 여야 한다).

## §4. `install.ps1` → `install_service.ps1` 직접 호출: `-ExtraEnv` 4개 · 토큰 검사 · `install_result.json`

- **무엇을**: 예전 `-File` 호출은 배열이 문자열로 풀려 첫 값만 들어갈 수 있었다. 이제 4개 env 가 전부 서비스 환경에 들어가고, 외부 바인드면 토큰 없이는 설치가 서고, 설치 결과 파일을 마법사·인수시험이 읽는지.
- **어떻게**:
  ```powershell
  & $n get VIGENT AppEnvironmentExtra      # VIGENT_PORTABLE=1 · VIGENT_EXPECT_GPU=1 · VIGENT_LOG_DIR=D:\VIGENT_TEST\state\logs · PYTHONNOUSERSITE=1 네 줄 전부
  Get-Content D:\VIGENT_TEST\app\data\install_result.json    # port 8020 · target D:\VIGENT_TEST
  Get-Content $env:TEMP\vigent_install_result.env
  D:\VIGENT_TEST\python\python.exe D:\VIGENT_TEST\app\scripts\deploy\acceptance_test.py --non-interactive   # --base 없이 8020 을 스스로 찾아야 한다
  # 토큰 검사(설치가 서야 정상): .env 를 잠시 치우고 외부 바인드로 DryRun 아닌 설치를 시도
  Rename-Item D:\VIGENT_TEST\app\.env .env.bak; powershell -File D:\vigent_usb_stage\installer\install.ps1 -UsbRoot D:\vigent_usb_stage -Target D:\VIGENT_TEST -Port 8020 -Bind 0.0.0.0 -SkipPreflight; "exit=$LASTEXITCODE"; Rename-Item D:\VIGENT_TEST\app\.env.bak .env
  ```
- **통과 기준**: env 4줄 전부 · `install_result.json` 의 port/target 이 인자와 같음 · 인수시험이 `--base` 없이 8020 으로 A2 통과 · 토큰 없는 외부 바인드는 `외부 바인드(0.0.0.0)에는 VIGENT_API_TOKEN 이 필수` 로 exit 1.
- **주의**: 업데이트 모드 설치는 기존 `app\.env` 를 보존한다 — 토큰 검사 시험은 위처럼 잠시 치워야 재현된다.

## §5. go2rtc DELETE 파라미터 — `name=`(starvation_guard) vs `src=`(routers/cameras)

- **무엇을**: 기아 1단계가 확대뷰 스트림을 실제로 해제하는지. go2rtc 1.9.14 [문서상 주장: `DELETE /api/streams?src=<이름>`] — 코드 두 곳이 다르므로 GET 으로 확인해 한쪽으로 맞춘다.
- **어떻게** (go2rtc 가 떠 있는 상태, 관리자 불필요):
  ```powershell
  curl.exe -X PUT "http://127.0.0.1:1984/api/streams?name=t1&src=rtsp://127.0.0.1:554/none"   # 등록은 PUT(GET 은 목록 조회) — 연결 안 돼도 목록엔 남는다
  curl.exe http://127.0.0.1:1984/api/streams                                            # t1 보임
  curl.exe -X DELETE "http://127.0.0.1:1984/api/streams?name=t1"; curl.exe http://127.0.0.1:1984/api/streams   # ① name= 로 지워지나
  curl.exe -X DELETE "http://127.0.0.1:1984/api/streams?src=t1";  curl.exe http://127.0.0.1:1984/api/streams   # ② src= 로 지워지나
  ```
- **통과 기준**: ①②중 실제로 목록에서 사라지는 쪽을 기록. `src=` 만 통하면 `vigent-core/starvation_guard.py:54` 를 `src=` 로 고치고 테스트(`tests/test_starvation_guard.py`)에 파라미터를 고정한다. 둘 다 통하면 그대로 두되 주석에 실측 날짜를 적는다.

---

## 결과 기록 (실기 뒤 채운다)

| § | 날짜 | 결과 | 측정값·비고 |
|---|---|---|---|
| 1 USB 스테이징 | 2026-09-28 13:55 | **통과** [실측] | `build_usb.ps1 -Profile academy` exit 0 · 태그 audit-before-cleanup-191-g5d5b69e · 총 4.34 GB · 49,146 파일 · fk510_smoke 120,797,435 B SHA=manifest(b409c98d…) · vision `fk510_smoke.pth` · tuning `include_forklift: 1`·`forklift: 0.50` · wheels_cuda torch/torchvision 2.12.0/0.27.0+cu130 · CRLF 검증 통과(스테이지 3파일 LF-only 0줄) · notify.yaml·camera_secrets.json·.env 없음 · 이전 스테이지는 `D:\vigent_usb_stage_prev_20260923` 로 이동(삭제 안 함) · 로그 `audit/usb_build_20260928.log` |
| 1′ USB 재빌드(결함 1~4 반영) | 2026-09-28 14:48 | **통과** [실측] | 커밋 `f766c8a` · 태그 audit-before-cleanup-194-gf766c8a · 4.34 GB·49,146 파일 · 스테이지 파일 확인: starvation_guard `src=`(name= 0건)·install_service `VIGENT_HOST=$Bind`·install.ps1 사용 중 검사/복구·acceptance `parse_sc_state`·fk510 SHA b409c98d… · CRLF 0/0/0 · 비밀 없음 · 13:55 스테이지는 `D:\vigent_usb_stage_prev_20260928_1355` 로 이동 · 로그 `audit/usb_build_20260928_r2.log`. **§2~§4 는 이 재빌드로 다시 설치해 재확인 필요(결함 2·4 의 수정 효과)** |
| 1″ USB 재빌드(회귀 결함 8 반영) | 2026-09-28 15:39 | **통과** [실측] | 커밋 `88ea5ad` · 태그 audit-before-cleanup-196-g88ea5ad · 4.34 GB·49,146 파일 · 스테이지 확인: install.ps1 `Get-ExternalBusyProcesses`·starvation `src=`·`VIGENT_HOST=$Bind`·`parse_sc_state`·fk510 SHA b409c98d… · CRLF 0/0/0 · 비밀 없음 · 14:48 스테이지는 `D:\vigent_usb_stage_prev_20260928_1448` 로 이동 · 로그 `audit/usb_build_20260928_r3.log`. **이 스테이지로 §미측정 3건 재검증** |
| 2 NSSM 재기동 | 2026-09-28 | **통과** [실측] | NSSM AppExit Restart · AppRestartDelay 60000 · AppStopMethodConsole 30000 · env 4/4 · 프로세스 kill 후 재기동 80 s · `_escalate` exit=3 |
| 3 정지 30 s | 2026-09-28 | **통과** [실측] | `sc stop` 3.06 s · stop_all ok(pending 없음, 카메라 0대 — 카메라 있는 상태는 미측정) · python 잔존 0 · ★relay 로그 0줄 → 결함 7 |
| 4 ExtraEnv·토큰·result | 2026-09-28 | **통과** [실측] | install_result.json 8020/D:\VIGENT_TEST · 인수시험 --base 없이 8020 자동 A2 ✓ · 0.0.0.0+.env 없음 → exit 1 "VIGENT_API_TOKEN 필수" · ★A1 오판(결함 4) · ★VIGENT_HOST=0.0.0.0(결함 2) |
| 2′·4′ 재검증(재빌드본 `f766c8a`) | 2026-09-28 | **통과** [실측] | `VIGENT_HOST=127.0.0.1`(결함 2 수정 확인) · 인수시험 A1 RUNNING(결함 4 수정 확인) · A2 통과 · 시험 서비스 제거 완료 |
| 3′ 회귀(결함 3 수정분) | 2026-09-28 | **회귀 발견 → 수정** [실측] | 업데이트 설치의 "사용 중" 검사가 서비스 자신의 nssm.exe·go2rtc.exe 를 잡아 서비스 Running 이면 항상 exit 1(수동 `sc stop` 으로 우회). 수정: 서비스 PID 트리 제외 + 순서 "외부 점유 검사 → 서비스 중지 → 이동 → 실패 시 복구"(결함 8) |
| 3″ 재검증(재빌드본 `88ea5ad`) | 2026-09-28 | **통과** [실측] | 업데이트 설치 exit=0 · 서비스 Running 상태에서 `sc stop` 없이 업데이트 exit=0 · 설치 폴더 안 셸에서 시도 → "서비스는 아직 멈추지 않았다" 안내 후 exit=1, 서비스 Running 유지 · 시험 서비스 제거 완료 |

**결과표 완결(2026-09-28)** — §1~§5·재검증·회귀 전부 실기 통과. 남는 것은 아래 "미측정" 2건(학원 실기 항목).
| 5 go2rtc DELETE | 2026-09-28 | **src= 만 삭제** [실측] | PUT 등록 뒤 DELETE `name=` → 목록 그대로 · DELETE `src=` → 삭제 → `starvation_guard.py` 를 `src=` 로 수정(결함 1) |

## 실기에서 새로 발견한 결함 7건과 조치 (2026-09-28)

| # | 결함 | 조치 | 고정 테스트 |
|---|---|---|---|
| 1 | `starvation_guard._release_go2rtc_slot` 이 `name=` 으로 DELETE → go2rtc 1.9.14 는 200 을 주면서 지우지 않음 = **기아 1단계 무효** | `GO2RTC_DELETE_URL` = `…/api/streams?src={cid}` | `test_field_fixes_20260928.F1Go2rtcDelete` |
| 2 | `install.ps1 -Bind 127.0.0.1` 인데 서비스 env `VIGENT_HOST=0.0.0.0`(install_service.ps1 에 값이 박혀 있었음) | `"VIGENT_HOST=$Bind"` | `F2BindEnv` |
| 3 | 업데이트 설치에서 `Move-Item` "사용 중" 실패 시 서비스를 멈춘 채 종료 | 서비스 중지 **전** 설치 폴더 안 프로세스·현재 셸 위치 검사 → 안내 후 중단 · Move-Item 실패 시 서비스 재시작 후 중단 | `F3UpdateMoveGuard` |
| 4 | 인수시험 A1 이 한국어 Windows `sc query` 출력을 못 읽어 "서비스 없음" 오판 | 1순위 `Get-Service` enum 이름, 폴백 `sc query` 의 SCM 상태 코드(4=RUNNING) | `F4ServiceState` |
| 5 | 서비스 stderr 로그(`app\logs\vigent.err.log`) 한글 깨짐 | **파일은 UTF-8 이다**(실측: utf-8 디코드 OK·cp949 실패, `PYTHONUTF8=1` 유효). 깨짐은 PS 5.1 `Get-Content` 기본 ANSI 읽기 — `service_status.ps1` 은 이미 `-Encoding UTF8`, 절차서 §3 에도 명시. 코드 변경 없음 | `F5F6Procedure` |
| 6 | 절차서 오류: `$pid` 자동 변수 · 등록은 GET 이 아니라 PUT · 경과 초 수식 괄호 | 정정 | `F5F6Procedure` |
| 7 | 릴레이 미설정 시 `_shutdown` 에 relay 줄 0 | `relay 미설정(enabled=False) — OFF 건너뜀` / `이미 OFF — 건너뜀` info 1줄 | `F7ShutdownRelayLog` |
| 8 (회귀) | 결함 3 의 "사용 중" 검사가 서비스 자신의 nssm.exe·go2rtc.exe 를 잡아 **서비스 Running 이면 업데이트 설치가 항상 중단** | `Get-ExternalBusyProcesses` 순수 함수: VIGENT 서비스 PID(nssm)에서 내려가는 프로세스 트리는 제외, 외부 점유·현재 셸 위치만 검사. 순서 "외부 점유 검사 → 서비스 중지 → 이동 → 실패 시 Start-Service 복구" | `F3UpdateMoveGuard`(서비스 Running 상태에서 검사 통과 · 외부 셸이 폴더 안이면 서비스 중지 전 안내 후 중단) |

결함 1·2·3·4·8 은 USB(`portable\app` 의 starvation_guard, `installer\` 의 install.ps1·install_service.ps1·acceptance_test.py)에 실리는 코드라 **USB 재빌드 대상**이다.

## 미측정 (다음 실기 때)

| 항목 | 이유 | 방법 |
|---|---|---|
| 카메라가 있는 상태의 `sc stop` 정지 시간 | §3 실기는 카메라 0대(3.06 s) — **학원 실기 항목** | 카메라 2대 이상 등록 후 §3 재실행, 30 s 이내·pending 없음 확인 |
| 결함 3 Move-Item 실패 시 서비스 복구 | 실패를 인위로 만들지 않았다 — **학원 실기 항목** | 설치 폴더 안 파일을 다른 프로그램(메모장 등)으로 열어 둔 채 업데이트 → `Start-Service` 복구 메시지·서비스 Running 확인 |

(결함 3 회귀 수정 뒤 업데이트 설치·폴더 안 셸 안내는 2026-09-28 재검증 3″ 로 통과 — 미측정 목록에서 제외.)

## 제거 경로 (2026-09-28 추가 발견)

`uninstall.ps1` 이 USB `installer\` 에만 있고 설치본에는 없어 **USB 없이는 현장에서 제거할 수 없었다**. `install.ps1` 4단계가 이제 `<Target>\app\scripts\deploy\uninstall.ps1` 로 함께 복사한다. 제거는 관리자 PowerShell 에서:
```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File <Target>\app\scripts\deploy\uninstall.ps1 -Target <Target>   # 설정·데이터 백업 여부를 묻는다
```
