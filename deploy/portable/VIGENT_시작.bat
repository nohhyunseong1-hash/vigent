@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
rem ============================================================================
rem  VIGENT USB 포터블 런처 — 더블클릭 한 번으로 서버를 띄우고 브라우저를 연다.
rem  · 모든 경로는 이 파일이 있는 폴더(%~dp0) 기준 상대경로 — 드라이브 문자가 바뀌어도 동작.
rem  · 대상 PC 의 파이썬을 쓰지 않는다: PATH 를 잘라 USB 안의 python\ 만 보이게 한다.
rem  · 서버는 이 창에서 전경 실행된다. 창을 닫으면 서버도 종료된다.
rem  · 옵션: VIGENT_시작.bat --gpu  → python\wheels_cuda\ 의 CUDA 휠로 torch 를 교체(오프라인, 선택).
rem  · 검증 자동화용 환경변수: VIGENT_PORTABLE_NOBROWSER=1(브라우저 안 엶) · VIGENT_PORTABLE_NOPAUSE=1(멈추지 않음)
rem  이 파일은 UTF-8(BOM 없음) — 첫 줄 chcp 65001 이 한글 출력을 담당한다.
rem ============================================================================
set "PKG=%~dp0"
set "PKG=%PKG:~0,-1%"
set "PY=%PKG%\python\python.exe"
set "APP=%PKG%\app"
set "STATE=%PKG%\state"
set "PORTABLE_DIR=%APP%\deploy\portable"

rem ---- 시스템 파이썬 격리(대상 PC 에 파이썬이 없거나 다른 버전이어도 무관하게) ----
set "PATH=%PKG%\python;%PKG%\python\Scripts;%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
set "PYTHONPATH="
set "PYTHONHOME="
set "PYTHONNOUSERSITE=1"
set "PYTHONUTF8=1"

rem ---- run.ps1 과 같은 환경변수(USB 기준) ----
set "VIGENT_HOST=127.0.0.1"
if not defined VIGENT_PORT set "VIGENT_PORT=8010"
set "VIGENT_CAPTURE_MODE=thread"
set "RF_HOME=%APP%\vigent-core\weights"
set "TORCH_HOME=%APP%\vigent-core\weights\rtm_cache"
set "VIGENT_LOG_DIR=%STATE%\logs"
set "VIGENT_PORTABLE=1"
rem 사전학습 가중치 인터넷 다운로드는 허용하지 않는다(USB 에 동봉) — 없으면 기동 거부가 정상 동작.
set "VIGENT_ALLOW_PRETRAIN_DOWNLOAD="

if not exist "%STATE%\logs" mkdir "%STATE%\logs"
if not exist "%STATE%\data" mkdir "%STATE%\data"
if not exist "%APP%\data" mkdir "%APP%\data"

echo.
echo  ┌──────────────────────────────────────────────┐
echo  │  VIGENT 포터블 — 산업안전 CCTV 감시 서버       │
echo  └──────────────────────────────────────────────┘
echo   패키지 위치: %PKG%
echo.

rem ---- 자가진단 1: 파이썬·필수 패키지 ----
if not exist "%PY%" (
  echo [오류] USB 안의 파이썬이 없습니다: %PY%
  echo        패키지가 온전히 복사되지 않았습니다. scripts\copy_to_usb.ps1 로 다시 복사하세요.
  goto :fail
)
"%PY%" -c "import sys; print('  python', sys.version.split()[0], '(' + sys.executable + ')')"
if errorlevel 1 (
  echo [오류] USB 안의 파이썬이 실행되지 않습니다. USB 를 다시 꽂거나 다른 USB 포트를 써 보세요.
  goto :fail
)
"%PY%" -c "import cv2, torch, onnxruntime, rfdetr, fastapi; print('  패키지 OK: cv2', cv2.__version__, '· torch', torch.__version__, '· onnxruntime', onnxruntime.__version__)" 2>"%STATE%\logs\selftest_import.err"
if errorlevel 1 (
  rem VC++ 런타임 부재 서명: msvcp140 / vcruntime140 / "DLL load failed" / WinError 126 중 하나 → 동봉한 vc_redist 안내
  findstr /I /C:"msvcp140" /C:"vcruntime140" /C:"DLL load failed" /C:"WinError 126" "%STATE%\logs\selftest_import.err" >nul 2>&1
  if not errorlevel 1 (
    rem 괄호 블록 안이라 메시지의 ( ) 는 ^ 로 이스케이프한다(안 하면 블록이 조기 종료돼 "unexpected at this time")
    echo [원인] 이 PC 에 Microsoft Visual C++ 재배포 패키지가 없습니다. [조치] 이 USB 의 vc_redist.x64.exe 를 실행해 설치한 뒤^(관리자 권한, 1분^) VIGENT_시작.bat 를 다시 실행하세요.
    echo        vc_redist.x64.exe 위치: %PKG%\vc_redist.x64.exe   ^(상세: %STATE%\logs\selftest_import.err^)
    goto :fail
  )
  echo [오류] 필수 패키지를 불러오지 못했습니다. 상세: %STATE%\logs\selftest_import.err
  type "%STATE%\logs\selftest_import.err" | findstr /I "Error error"
  echo   ▶ 사용법.md 의 '문제가 생겼을 때' 를 보세요.
  goto :fail
)

rem ---- 자가진단 2: 필수 가중치 ----
set "W=%APP%\vigent-core\weights"
set "MISSING="
for %%F in (rf-detr-nano.pth ppe_rfdetr_v1.pth forklift_rfdetr_v1.pth fire_smoke_rfdetr_v1_e17.pth face_detection_yunet.onnx) do (
  if not exist "%W%\%%F" set "MISSING=!MISSING! %%F"
)
for %%F in (yolox_m_8xb8-300e_humanart-c2c7a14a.onnx rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.onnx) do (
  if not exist "%W%\rtm_cache\hub\checkpoints\%%F" set "MISSING=!MISSING! rtm_cache\%%F"
)
if not "!MISSING!"=="" (
  echo [오류] 필수 모델 파일이 없습니다:!MISSING!
  echo        인터넷에서 받지 않습니다. 개발 PC 에서 scripts\build_portable.ps1 로 다시 빌드해 복사하세요.
  goto :fail
)
echo   모델 파일 OK: %W%

rem ---- 선택: --gpu (CUDA 휠 오프라인 교체) ----
if /I "%~1"=="--gpu" set "VIGENT_PORTABLE_GPU=1"
if "%VIGENT_PORTABLE_GPU%"=="1" call :gpu_switch

rem ---- 자가진단 3: 포트 ----
set "PORT=%VIGENT_PORT%"
call :port_busy %PORT%
if "%BUSY%"=="1" (
  echo   포트 %PORT% 사용 중 → 8011 로 전환합니다.
  set "PORT=8011"
  call :port_busy 8011
  if "!BUSY!"=="1" (
    echo [오류] 8010·8011 포트가 모두 사용 중입니다. VIGENT_종료.bat 을 먼저 실행하거나 다른 프로그램을 닫으세요.
    goto :fail
  )
)
set "VIGENT_PORT=%PORT%"

echo.
echo   서버를 시작합니다: http://127.0.0.1:%PORT%/home
echo   (모델 예열에 15~60초 걸립니다. 준비되면 브라우저가 자동으로 열립니다. 이 창을 닫으면 서버가 종료됩니다.)
echo.
start "" /b "%PY%" "%PORTABLE_DIR%\portable_wait.py" %PORT% 90
cd /d "%APP%\vigent-core"
"%PY%" -m uvicorn main:app --host 127.0.0.1 --port %PORT%
set "RC=%ERRORLEVEL%"
echo.
echo   서버가 종료됐습니다(코드 %RC%). 로그: %STATE%\logs\vigent.log
if not "%RC%"=="0" goto :fail
goto :end

:port_busy
set "BUSY=0"
for /f "tokens=*" %%L in ('netstat -ano ^| findstr /R /C:":%~1 .*LISTENING"') do set "BUSY=1"
exit /b

:gpu_switch
echo   [--gpu] python\wheels_cuda\ 의 CUDA 휠로 torch 를 교체합니다(오프라인, 시간이 걸립니다)...
if not exist "%PKG%\python\wheels_cuda\torch-*.whl" (
  echo   [--gpu] python\wheels_cuda\ 에 torch 휠이 없습니다. 개발 PC 에서 build_portable.ps1 -Gpu 로 받아 두세요. CPU 로 계속합니다.
  exit /b
)
for %%W in ("%PKG%\python\wheels_cuda\torch-*.whl" "%PKG%\python\wheels_cuda\torchvision-*.whl") do (
  "%PY%" -m pip install --no-index --no-deps --force-reinstall --no-warn-script-location "%%~W"
)
"%PY%" -c "import torch; print('  torch', torch.__version__, 'cuda:', torch.cuda.is_available())"
exit /b

:fail
echo.
if not "%VIGENT_PORTABLE_NOPAUSE%"=="1" pause
exit /b 1

:end
if not "%VIGENT_PORTABLE_NOPAUSE%"=="1" pause
exit /b 0
