@echo off
rem VIGENT Windows 런처(더블클릭용) — run.ps1 을 실행 정책 우회로 호출한다. (감사 C4, 2026-09-06)
rem 환경변수(VIGENT_HOST/VIGENT_PORT/VIGENT_API_TOKEN)는 그대로 전달된다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
