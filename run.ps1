# VIGENT Windows 런처 — run.sh 와 1:1 (감사 C4, 2026-09-06). Windows PowerShell 5.1 이상.
#   사용:  .\run.ps1                                   # 로컬 개발: http://127.0.0.1:8010 (무토큰)
#          $env:VIGENT_HOST="0.0.0.0"; $env:VIGENT_API_TOKEN="비밀"; .\run.ps1   # 외부 노출(토큰 필수)
#   더블클릭은 run.bat (이 파일을 -ExecutionPolicy Bypass 로 호출).
#   설정은 전부 환경변수(하드코딩 없음): VIGENT_HOST / VIGENT_PORT / VIGENT_API_TOKEN / VIGENT_EDGE
#   서비스 등록(재부팅 자동기동)은 deploy/windows/install_service.ps1 — 이 파일은 개발·데모용 전경 실행.
#   ★이 파일은 UTF-8 BOM 으로 저장한다 — PowerShell 5.1 은 BOM 이 없으면 한글 주석·문자열을 ANSI 로 읽어 구문 오류를 낸다.
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Port = if ($env:VIGENT_PORT) { $env:VIGENT_PORT } else { "8010" }
if (-not $env:VIGENT_HOST) { $env:VIGENT_HOST = "127.0.0.1" }
# ★[CODE_REVIEW M7-2, 2026-09-06] 서비스(deploy/windows/install_service.ps1)와 같은 환경 4개 — **미설정 시에만** 채운다(셸에서 준 값 우선).
#   개발에서 못 보는 캡처 경로(thread)·인코딩(UTF-8)·모델 캐시(RF_HOME/TORCH_HOME)가 현장에서만 도는 일을 없앤다.
#   실측(2026-09-06): rf-detr 캐시는 ~/.roboflow 와 vigent-core\weights 양쪽에 동일(366,287,238B) → 전환 다운로드 0.
#   rtmlib 포즈 캐시는 scripts\fetch_weights.py 가 weights\rtm_cache 로 조달한다(M7-2b).
if (-not $env:VIGENT_CAPTURE_MODE) { $env:VIGENT_CAPTURE_MODE = "thread" }
if (-not $env:PYTHONUTF8) { $env:PYTHONUTF8 = "1" }
if (-not $env:RF_HOME) { $env:RF_HOME = Join-Path $Dir "vigent-core\weights" }
if (-not $env:TORCH_HOME) { $env:TORCH_HOME = Join-Path $Dir "vigent-core\weights\rtm_cache" }

# ★[CODE_REVIEW M7-5·M7-6, 2026-09-06] 파이썬은 **3.11 정본만** 쓴다: 프로젝트 .venv(3.11 인 경우) → py -3.11.
#   PATH 의 bare python 후보는 없앴다 — 개발 PC 실측에서 py 런처 기본이 3.14 라 미검증 인터프리터로 뜰 수 있었다.
#   각 후보 = @(실행파일, 선행인자문자열). 검사(3.11 + uvicorn/fastapi)는 숨은 창에서 돌리고 종료코드만 본다.
$candidates = @()
$venv = Join-Path $Dir ".venv\Scripts\python.exe"
if (Test-Path $venv) { $candidates += ,@($venv, "") }
if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += ,@("py", "-3.11") }

$Py = $null
foreach ($c in $candidates) {
    $probeArgs = ($c[1] + ' -c "import sys, uvicorn, fastapi; sys.exit(0 if sys.version_info[:2] == (3, 11) else 3)"').Trim()
    try {
        $pr = Start-Process -FilePath $c[0] -ArgumentList $probeArgs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop
        if ($pr.ExitCode -eq 0) { $Py = $c; break }
    } catch { }
}
if (-not $Py) {
    Write-Host "[오류] Python 3.11(정본) + uvicorn/fastapi 를 찾지 못했습니다. 설치: python.org 3.11.x → 'py -3.11 -m pip install -r requirements.txt' 후 재시도. (3.13/3.14 등 다른 버전은 쓰지 않는다 — .python-version 참조)" -ForegroundColor Red
    exit 1
}

Write-Host ("VIGENT 시작: host={0} port={1} (python: {2} {3})" -f $env:VIGENT_HOST, $Port, $Py[0], $Py[1])
Set-Location (Join-Path $Dir "vigent-core")
$uvArgs = @()
if ($Py[1]) { $uvArgs += $Py[1] }
$uvArgs += @("-m", "uvicorn", "main:app", "--host", $env:VIGENT_HOST, "--port", $Port)
& $Py[0] @uvArgs
exit $LASTEXITCODE
