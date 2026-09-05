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

# uvicorn/fastapi 가 설치된 파이썬 탐색: 프로젝트 .venv → py -3.11(정본) → PATH 의 python
#   각 후보 = @(실행파일, 선행인자문자열). 검사는 숨은 창에서 돌리고 종료코드만 본다.
$candidates = @()
$venv = Join-Path $Dir ".venv\Scripts\python.exe"
if (Test-Path $venv) { $candidates += ,@($venv, "") }
if (Get-Command py -ErrorAction SilentlyContinue) { $candidates += ,@("py", "-3.11") }
if (Get-Command python -ErrorAction SilentlyContinue) { $candidates += ,@("python", "") }

$Py = $null
foreach ($c in $candidates) {
    $probeArgs = ($c[1] + ' -c "import uvicorn, fastapi"').Trim()
    try {
        $pr = Start-Process -FilePath $c[0] -ArgumentList $probeArgs -WindowStyle Hidden -Wait -PassThru -ErrorAction Stop
        if ($pr.ExitCode -eq 0) { $Py = $c; break }
    } catch { }
}
if (-not $Py) {
    Write-Host "[오류] uvicorn/fastapi 가 설치된 python 을 찾지 못했습니다. 'py -3.11 -m pip install -r requirements.txt' 후 재시도." -ForegroundColor Red
    exit 1
}

Write-Host ("VIGENT 시작: host={0} port={1} (python: {2} {3})" -f $env:VIGENT_HOST, $Port, $Py[0], $Py[1])
Set-Location (Join-Path $Dir "vigent-core")
$uvArgs = @()
if ($Py[1]) { $uvArgs += $Py[1] }
$uvArgs += @("-m", "uvicorn", "main:app", "--host", $env:VIGENT_HOST, "--port", $Port)
& $Py[0] @uvArgs
exit $LASTEXITCODE
