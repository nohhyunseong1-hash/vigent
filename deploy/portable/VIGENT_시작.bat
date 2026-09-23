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
rem ---- [USB 1차 항목 4, 확정] 기본값: CUDA 휠이 있으면 --gpu 다. 끄려면 --cpu 를 명시한다 ----
rem  · 예전엔 --gpu 를 안 주면 CPU 판 torch 로 조용히 돌았다 - GPU 빌드를 받아 놓고 CPU 로 도는 사고의 뿌리.
rem  · GPU 빌드 판정 = python\wheels_cuda\torch-*.whl 이 있거나(교체 전) torch 가 이미 +cu 판(교체 후).
rem    그 경우 VIGENT_EXPECT_GPU=1 을 서버에 넘긴다 → CUDA 를 못 쓰면 서버가 CRITICAL 로그 + /health gpu.fallback + 붉은 배너.
if /I "%~1"=="--gpu" set "VIGENT_PORTABLE_GPU=1"
if /I "%~1"=="--cpu" set "VIGENT_PORTABLE_CPU=1"
set "VIGENT_GPU_BUILD="
if exist "%PKG%\python\wheels_cuda\torch-*.whl" set "VIGENT_GPU_BUILD=1"
"%PY%" -c "import sys,torch; sys.exit(0 if '+cu' in torch.__version__ else 1)" >nul 2>&1
if not errorlevel 1 set "VIGENT_GPU_BUILD=1"
if "%VIGENT_GPU_BUILD%"=="1" if not "%VIGENT_PORTABLE_CPU%"=="1" (
  set "VIGENT_EXPECT_GPU=1"
  if exist "%PKG%\python\wheels_cuda\torch-*.whl" set "VIGENT_PORTABLE_GPU=1"
)
rem  --cpu 는 정말로 CPU 로 돈다(VIGENT_DETECT_DEVICE=cpu). 2026-09-23 실측: 교체·기대만 건너뛰면 torch 가 이미 cu 판일 때
rem  여전히 device=cuda 로 돌아 "--cpu 인데 GPU" 가 됐다. 옵션 이름이 거짓말을 하면 안 된다.
if "%VIGENT_PORTABLE_CPU%"=="1" set "VIGENT_DETECT_DEVICE=cpu"
if "%VIGENT_PORTABLE_CPU%"=="1" echo   [--cpu] CPU 모드로 기동합니다 - CUDA 교체·GPU 기대 없음, 추론 장치 cpu 강제.
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
echo   서버를 시작합니다: 관제 화면 http://127.0.0.1:%PORT%/safety-hub   ^(메뉴^(허브^)는 /home^)
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
rem ---- [I-5] 교체가 **실제로 됐는지** 확인한 뒤에만 휠을 지운다 ----
rem  휠은 1.8GB 다. 설치가 끝나면 다시 쓸 일이 없는데 그대로 남아 패키지가 그만큼 커진다.
rem  ★확인 없이 지우면 실패했을 때 되돌릴 방법이 사라진다 - cuda:True 일 때만 지운다.
"%PY%" -c "import sys,torch; sys.exit(0 if torch.cuda.is_available() else 1)"
rem  ★괄호 블록 안에서는 echo 든 rem 이든 괄호를 쓰면 안 된다 - 닫는 괄호가 블록을 끝내 버린다.
rem    2026-09-23 실제 사고: 블록 안 echo 의 "...남겨 둡니다." 뒤 괄호 때문에 ". was unexpected at this time." 로 런처가 죽었다.
rem    아래 블록의 rem 과 echo 는 그래서 괄호가 없다. 고칠 때도 넣지 말 것.
if errorlevel 1 (
  echo   [--gpu] CUDA 를 못 씁니다. torch 는 교체됐을 수 있으나 GPU 가 안 잡힙니다.
  echo   [--gpu] wheels_cuda 는 지우지 않습니다 - 되돌릴 수 있게 남겨 둡니다.
  "%PY%" -c "import torch; print('  torch', torch.__version__, 'cuda:', torch.cuda.is_available())"
  exit /b
)
"%PY%" -c "import torch; print('  torch', torch.__version__, 'cuda:', torch.cuda.is_available())"
rem  ★for /f 의 명령은 작은따옴표로 감싸므로 그 안에 작은따옴표를 쓰면 안 된다.
rem    → usebackq + 파이썬으로 크기를 잰다. 파이프·따옴표 충돌이 없다.
if exist "%PKG%\python\wheels_cuda\" (
  rem  ★명령이 따옴표로 시작하면 cmd /c 가 바깥 따옴표를 벗겨 버린다 - 앞에 call 을 둬서 막는다.
  rem    2026-09-23 실제 사고: 이 줄이 빈 값을 돌려 "-  GB 회수했습니다" 로 찍혔다. 삭제는 됐지만 숫자가 비었다.
  for /f "usebackq delims=" %%S in (`call "%PY%" -c "import os,sys;print(round(sum(os.path.getsize(os.path.join(r,f)) for r,_,fs in os.walk(sys.argv[1]) for f in fs)/1024**3,2))" "%PKG%\python\wheels_cuda"`) do set "WHGB=%%S"
  rd /s /q "%PKG%\python\wheels_cuda"
  if exist "%PKG%\python\wheels_cuda\" (
    echo   [--gpu] wheels_cuda 삭제 실패 - 수동으로 지워도 됩니다.
  ) else (
    echo   [--gpu] wheels_cuda 삭제 완료 - !WHGB! GB 회수했습니다.
  )
)
exit /b

:fail
echo.
if not "%VIGENT_PORTABLE_NOPAUSE%"=="1" pause
exit /b 1

:end
if not "%VIGENT_PORTABLE_NOPAUSE%"=="1" pause
exit /b 0
