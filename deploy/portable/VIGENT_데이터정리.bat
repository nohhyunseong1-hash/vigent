@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
rem ============================================================================
rem  VIGENT USB 포터블 — 데이터 정리. USB 안에 쌓인 개인영상정보(증거 사진·인식 기록)와 로그를 지운다.
rem  기본:   app\data\ 의 증거·인식·감사·TBM·위험성평가·보존 기록·경보 큐·go2rtc 런타임 파일 + state\logs\  삭제
rem          카메라 등록(data\cameras.json · data\camera_secrets.json)과 법령 화이트리스트(data\legal\statutes.yaml)는 남긴다
rem  --all:  카메라 등록·자격증명(cameras.json, camera_secrets.json, *.bak)·go2rtc.runtime.yaml 까지 지운다
rem  근거: vigent-core\camera_registry.py(_PUB=data\cameras.json · _SEC=data\camera_secrets.json) ·
rem        vigent-core\retention.py(evidence·recognition·audit·tbm·risk_assessments · retention_status.json · data\retention) ·
rem        vigent-core\alert_queue.py(data\alert_queue.db) · routers\cameras.py(data\go2rtc.runtime.yaml·go2rtc.pid·go2rtc.log) ·
rem        vigent-core\legal_whitelist.py(data\legal\statutes.yaml — 읽기 전용 자산, 삭제 금지)
rem  서버가 켜져 있으면 먼저 VIGENT_종료.bat 으로 끈다(파일 잠김·기록 중 삭제 방지).
rem ============================================================================
set "PKG=%~dp0"
set "PKG=%PKG:~0,-1%"
set "PY=%PKG%\python\python.exe"
set "DATA=%PKG%\app\data"
set "LOGS=%PKG%\state\logs"
set "MODE=keep"
if /I "%~1"=="--all" set "MODE=all"
set "PATH=%PKG%\python;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\WindowsPowerShell\v1.0"
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONUTF8=1"

echo.
echo  ┌──────────────────────────────────────────────┐
echo  │  VIGENT 포터블 — 데이터 정리                    │
echo  └──────────────────────────────────────────────┘
if "%MODE%"=="all" (echo   모드: --all  ^(카메라 등록·자격증명까지 삭제^)) else (echo   모드: 기본  ^(카메라 등록은 남김 — 전부 지우려면 --all^))
echo.

rem 서버 실행 중이면 중단
powershell -NoProfile -ExecutionPolicy Bypass -Command "$p='%PKG%'; $n=@(Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($p,'OrdinalIgnoreCase') }).Count; exit $n"
if not "%ERRORLEVEL%"=="0" (
  echo [중단] VIGENT 서버가 아직 실행 중입니다. 먼저 VIGENT_종료.bat 을 실행한 뒤 다시 하세요.
  goto :fail
)
if not exist "%PY%" (
  echo [오류] USB 안의 파이썬이 없습니다: %PY%
  goto :fail
)

rem 1) 삭제 대상 계산·표시 (파이썬 — 파일 수·용량·목록)
"%PY%" "%PKG%\app\deploy\portable\portable_cleanup.py" plan "%DATA%" "%LOGS%" %MODE%
if errorlevel 2 (
  echo   지울 것이 없습니다.
  goto :end
)
if errorlevel 1 goto :fail

echo.
set /p "ANS=  위 파일을 지웁니다. 계속하려면 Y 를 입력하세요 [Y/N]: "
if /I not "%ANS%"=="Y" (
  echo   취소했습니다. 아무것도 지우지 않았습니다.
  goto :end
)

rem 2) 삭제 실행 + 남은 파일 목록
"%PY%" "%PKG%\app\deploy\portable\portable_cleanup.py" run "%DATA%" "%LOGS%" %MODE%
if errorlevel 1 goto :fail
goto :end

:fail
echo.
if not "%VIGENT_PORTABLE_NOPAUSE%"=="1" pause
exit /b 1

:end
echo.
if not "%VIGENT_PORTABLE_NOPAUSE%"=="1" pause
exit /b 0
