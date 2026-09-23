@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem ============================================================================
rem  VIGENT USB 설치기 - 더블클릭 진입점. 실제 일은 installer\install.ps1 이 한다.
rem  · 이 파일은 USB 루트에 있다. 경로는 전부 이 파일 위치(%~dp0) 기준.
rem  · 관리자 권한이 필요하다(서비스 등록·C:\VIGENT 쓰기). 아니면 안내하고 끝낸다.
rem  · 옵션: 설치.bat --dry-run  → 복사·교체·서비스 등록 없이 단계만 찍는다(시험용)
rem  ★UTF-8(BOM 없음) - 첫 줄 chcp 65001 이 한글 출력을 담당한다. 괄호 블록 안에 괄호를 쓰지 말 것.
rem ============================================================================
set "USB=%~dp0"
set "USB=%USB:~0,-1%"
net session >nul 2>&1
if errorlevel 1 (
  echo   관리자 권한이 필요합니다. 이 파일을 마우스 오른쪽 - "관리자 권한으로 실행" 으로 여세요.
  pause
  exit /b 1
)
if not exist "%USB%\installer\install.ps1" (
  echo   installer\install.ps1 이 없습니다. 이 USB 는 아직 설치기 본체가 들어가기 전 상태입니다.
  echo   사양 검사만 하려면: powershell -ExecutionPolicy Bypass -File "%USB%\installer\preflight.ps1"
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%USB%\installer\install.ps1" -UsbRoot "%USB%" %*
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" (
  echo   설치 미완료 - 위 메시지를 확인하세요. 코드 %RC%
  pause
  exit /b %RC%
)
echo   설치 완료.
rem ---- 계획 3: 첫 실행 마법사(대화식). --dry-run 이면 건너뛴다. 설치 대상은 install.ps1 기본값 C:\VIGENT ----
rem  · 마법사는 기기 안의 파이썬·앱 모듈로 돈다. 토큰·비밀번호는 화면에 다시 찍지 않고 USB 에 저장하지 않는다.
set "TARGET=C:\VIGENT"
set "WIZ=%TARGET%\app\scripts\deploy\setup_wizard.py"
set "SKIPWIZ="
if /I "%~1"=="--dry-run" set "SKIPWIZ=1"
if /I "%~1"=="-DryRun" set "SKIPWIZ=1"
if "%SKIPWIZ%"=="1" (
  echo   [dry-run] 마법사는 건너뜁니다.
) else if exist "%WIZ%" (
  echo.
  echo   이어서 첫 실행 마법사를 시작합니다. 카메라 RTSP 주소·텔레그램 토큰·chat_id 를 준비하세요.
  "%TARGET%\python\python.exe" "%WIZ%"
  if errorlevel 1 (
    echo   마법사가 중단됐습니다. 나중에 다시 실행: "%TARGET%\python\python.exe" "%WIZ%"
  )
) else (
  echo   마법사 파일이 없습니다: %WIZ%  - 업데이트 설치이거나 USB 구성이 불완전합니다.
)
pause
exit /b 0
