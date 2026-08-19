<#
.SYNOPSIS
  [B1] VIGENT 를 Windows 서비스로 등록한다(NSSM). 재부팅·크래시 후 자동 기동.

.DESCRIPTION
  감사 🔴B1: 저장소에 서비스 등록물이 0건이라 **재부팅하면 아무도 서버를 켜지 않았다**.
  정전 복구·Windows 자동 업데이트 재부팅 후 감시 공백이 무기한 이어진다.

  이 스크립트는 NSSM 으로 서비스를 만들고 다음을 설정한다:
    - 시작 유형 Automatic (Delayed)  — 부팅 후 네트워크·드라이버가 안정된 뒤 기동
    - 실패 시 5초 후 재시작
    - stdout/stderr 파일 로깅 + 크기 기반 로테이션(기본 상한 2GB)
    - 운영 환경변수 주입(토큰 강제·캡처 스레드 모드·기아 3단계 재기동 명령)

  ★관리자 권한 PowerShell 에서 실행할 것.

.PARAMETER ServiceName
  서비스 이름(기본 VIGENT).

.PARAMETER Port
  수신 포트(기본 8010).

.PARAMETER Bind
  바인딩 주소(기본 0.0.0.0 — 관제 PC 에서 접속. 단독 사용이면 127.0.0.1 권장).

.PARAMETER LogMaxBytes
  로그 파일 1개당 로테이션 임계(기본 268435456 = 256MB, 8개 유지 시 약 2GB 상한).

.EXAMPLE
  .\install_service.ps1
  .\install_service.ps1 -Bind 127.0.0.1 -Port 8010
#>
[CmdletBinding()]
param(
  [string]$ServiceName = "VIGENT",
  [int]$Port = 8010,
  [string]$Bind = "0.0.0.0",
  [long]$LogMaxBytes = 268435456
)

$ErrorActionPreference = "Stop"

# ── 0. 관리자 권한 확인 ────────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Error "관리자 권한이 필요합니다. PowerShell 을 '관리자 권한으로 실행' 후 다시 시도하세요."
  exit 1
}

# ── 1. 경로 확인 ───────────────────────────────────────────────────────
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Core = Join-Path $Root "vigent-core"
$LogDir = Join-Path $Root "logs"
if (-not (Test-Path $Core)) { Write-Error "vigent-core 를 찾을 수 없습니다: $Core"; exit 1 }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory $LogDir | Out-Null }

# python: 프로젝트 venv 우선, 없으면 시스템 python
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
  $cmd = Get-Command python -ErrorAction SilentlyContinue
  if (-not $cmd) { Write-Error "python 을 찾을 수 없습니다. .venv 를 만들거나 python 을 PATH 에 두세요."; exit 1 }
  $Py = $cmd.Source
}
Write-Host "루트 : $Root"
Write-Host "파이썬: $Py"

# ── 2. NSSM 확인 ───────────────────────────────────────────────────────
$nssm = Get-Command nssm -ErrorAction SilentlyContinue
if (-not $nssm) {
  $local = Join-Path $PSScriptRoot "nssm.exe"
  if (Test-Path $local) { $nssmPath = $local }
  else {
    Write-Host ""
    Write-Host "NSSM 이 없습니다. 아래 중 하나로 설치한 뒤 다시 실행하세요:" -ForegroundColor Yellow
    Write-Host "  1) https://nssm.cc/download 에서 받아 win64\nssm.exe 를 이 폴더에 복사"
    Write-Host "     → $PSScriptRoot\nssm.exe"
    Write-Host "  2) winget install NSSM.NSSM"
    Write-Host "  3) choco install nssm"
    exit 2
  }
} else { $nssmPath = $nssm.Source }
Write-Host "NSSM : $nssmPath"

# ── 3. 기존 서비스 정리(있으면) ────────────────────────────────────────
$existing = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existing) {
  Write-Host "기존 서비스 '$ServiceName' 발견 → 중지 후 재설정" -ForegroundColor Yellow
  & $nssmPath stop $ServiceName confirm | Out-Null
  Start-Sleep -Seconds 2
  & $nssmPath remove $ServiceName confirm | Out-Null
  Start-Sleep -Seconds 2
}

# ── 4. 서비스 생성 ─────────────────────────────────────────────────────
$appArgs = "-m uvicorn main:app --host $Bind --port $Port"
& $nssmPath install $ServiceName $Py $appArgs
& $nssmPath set $ServiceName AppDirectory $Core
& $nssmPath set $ServiceName DisplayName "VIGENT 산업안전 비전 서버"
& $nssmPath set $ServiceName Description "RTSP 카메라 기반 산업안전 검출(사람·PPE·화재/연기). /health 로 검출 생존 확인."

# 시작 유형: 지연 자동 — 부팅 직후 네트워크·GPU 드라이버가 준비된 뒤 기동
& $nssmPath set $ServiceName Start SERVICE_DELAYED_AUTO_START

# 실패 시 재시작(5초 지연). AppExit Default Restart = 어떤 종료코드든 재시작
& $nssmPath set $ServiceName AppExit Default Restart
& $nssmPath set $ServiceName AppRestartDelay 5000
& $nssmPath set $ServiceName AppThrottle 10000       # 10초 안에 죽으면 폭주로 보고 감속

# 로그: stdout/stderr 파일 + 크기 기반 로테이션(온라인 로테이션 = 서비스 중지 없이)
$outLog = Join-Path $LogDir "vigent.out.log"
$errLog = Join-Path $LogDir "vigent.err.log"
& $nssmPath set $ServiceName AppStdout $outLog
& $nssmPath set $ServiceName AppStderr $errLog
& $nssmPath set $ServiceName AppRotateFiles 1
& $nssmPath set $ServiceName AppRotateOnline 1
& $nssmPath set $ServiceName AppRotateBytes $LogMaxBytes

# 운영 환경변수. ★VIGENT_HANG_TIMEOUT 같은 회피값은 넣지 않는다(B4 에서 근본 해소됨).
#   VIGENT_RESTART_CMD 는 기아 3단계(starvation_guard)가 실제로 소비한다.
$restartCmd = 'sc.exe stop ' + $ServiceName + ' & sc.exe start ' + $ServiceName
$envLines = @(
  "VIGENT_REQUIRE_TOKEN=1",
  "VIGENT_CAPTURE_MODE=thread",
  # ★[2026-08-20 정합 수정] uvicorn 은 --host 0.0.0.0(LAN 바인드)로 띄우면서 이 변수를
  #   안 넣으면 앱이 "루프백 바인드"로 오인해 Host 허용목록을 루프백만으로 걸어 —
  #   LAN 접속(폰 /health 점검 등)이 전부 403 "forbidden host" 가 된다(재부팅 시험에서
  #   실측 발견). 바인드 주소와 앱 인식을 반드시 일치시킨다. LAN 노출 라우트는
  #   VIGENT_REQUIRE_TOKEN=1 + Bearer 로 방어(설계 원안 그대로, /health 는 면제).
  "VIGENT_HOST=0.0.0.0",
  "VIGENT_RESTART_CMD=$restartCmd"
) -join "`r`n"
& $nssmPath set $ServiceName AppEnvironmentExtra $envLines

# ── 5. 기동 ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "서비스 시작..." -ForegroundColor Cyan
& $nssmPath start $ServiceName
Start-Sleep -Seconds 5

$svc = Get-Service -Name $ServiceName
Write-Host ""
Write-Host "서비스 '$ServiceName' 상태: $($svc.Status)" -ForegroundColor Green
Write-Host "로그 : $outLog"
Write-Host ""
Write-Host "다음 단계:"
Write-Host "  .\service_status.ps1        # 상태 + /health 확인"
Write-Host "  ※ 예열에 약 15초 걸립니다. 그동안 /health 는 phase=starting + HTTP 503 입니다(정상)."
