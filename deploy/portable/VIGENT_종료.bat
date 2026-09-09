@echo off
chcp 65001 >nul
setlocal
rem VIGENT USB 포터블 — 종료. 이 USB 패키지 폴더 안에서 실행된 프로세스(uvicorn 파이썬·go2rtc)만 종료한다.
rem 다른 곳에 설치된 VIGENT 나 대상 PC 의 다른 파이썬은 건드리지 않는다(실행 파일 경로로 구분).
rem go2rtc 는 서버가 실경로로 띄우므로(가상 드라이브·subst 에서는 드라이브 문자가 달라질 수 있음) "\app\bin\go2rtc.exe" 로도 잡는다.
set "PKG=%~dp0"
set "PKG=%PKG:~0,-1%"
echo   VIGENT 포터블 종료: %PKG% 아래에서 실행 중인 프로세스를 찾습니다...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = '%PKG%'; $n = 0; $mine = Get-CimInstance Win32_Process | Where-Object { ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($p, 'OrdinalIgnoreCase')) -or ($_.Name -eq 'go2rtc.exe' -and $_.ExecutablePath -like ('*' + [char]92 + 'app' + [char]92 + 'bin' + [char]92 + 'go2rtc.exe')) }; $mine | ForEach-Object { Write-Host ('   종료: ' + $_.Name + ' (PID ' + $_.ProcessId + ') ' + $_.ExecutablePath); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $n++ }; if ($n -eq 0) { Write-Host '   실행 중인 VIGENT 포터블 프로세스가 없습니다.' } else { Write-Host ('   ' + $n + '개 종료했습니다.') }"
echo.
echo   USB 를 뽑기 전에 작업 표시줄의 '하드웨어 안전하게 제거' 를 쓰세요(기록 손상 방지).
"%SystemRoot%\System32\timeout.exe" /t 5 >nul
exit /b 0
