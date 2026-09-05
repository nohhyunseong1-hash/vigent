@echo off
chcp 65001 >nul
rem ════════════════════════════════════════════════════════════
rem  VIGENT Safety — 바탕화면 더블클릭 실행기 (Windows)
rem  mac 의 'VIGENT Safety 시작.command'(→ _archive/macos/) 대응. 감사 C4, 2026-09-06
rem  하는 일: 서버가 떠 있으면 브라우저만 열고, 아니면 run.ps1 로 서버를 띄운 뒤 /health 200 을 기다려 연다.
rem  종료: 서버 창을 닫거나 Ctrl+C
rem ════════════════════════════════════════════════════════════
set PORT=8010
set HEALTH=http://127.0.0.1:%PORT%/health
set URL=http://127.0.0.1:%PORT%/safety-local
cd /d "%~dp0"

powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%HEALTH%'; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
  echo 서버가 이미 동작 중 - 페이지를 엽니다.
  start "" "%URL%"
  exit /b 0
)

echo 서버 시작 중 (모델 로드 포함 최대 90초)...
start "VIGENT 서버" powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
for /l %%i in (1,1,90) do (
  powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 1 '%HEALTH%'; exit 0 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 goto up
  timeout /t 1 /nobreak >nul
)
echo [경고] 90초 안에 /health 가 200 을 주지 않았습니다. 서버 창의 오류를 확인하세요.
pause
exit /b 1

:up
start "" "%URL%"
echo ------------------------------------------------
echo  관제 화면:  %URL%   (로컬판·CDN 불필요)
echo  서버 창을 닫으면 서버가 종료됩니다.
echo ------------------------------------------------
