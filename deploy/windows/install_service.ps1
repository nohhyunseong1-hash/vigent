<#
.SYNOPSIS
  [B1] VIGENT 를 Windows 서비스로 등록한다(NSSM). 재부팅·크래시 후 자동 기동.

.DESCRIPTION
  감사 🔴B1: 저장소에 서비스 등록물이 0건이라 **재부팅하면 아무도 서버를 켜지 않았다**.
  정전 복구·Windows 자동 업데이트 재부팅 후 감시 공백이 무기한 이어진다.

  이 스크립트는 NSSM 으로 서비스를 만들고 다음을 설정한다:
    - 시작 유형 Automatic (Delayed)  — 부팅 후 네트워크·드라이버가 안정된 뒤 기동
    - 실패 시 60초 후 재시작(AppRestartDelay 60000 — 아래 실제 값과 일치, 2026-09-26 정정)
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
  [long]$LogMaxBytes = 268435456,
  [string]$NssmPath = "",           # 호출자가 이미 찾은 nssm.exe(검증 스크립트가 넘김). 비우면 자동 탐색
  # ★[USB 1차, 2026-09-23] 포터블 설치용 덮어쓰기 — 비우면 예전 그대로(저장소 루트 + .venv). 노트북 경로는 안 바뀐다.
  #   포터블은 <설치루트>\app 이 Root(vigent-core·data·logs 가 그 아래)이고 파이썬은 <설치루트>\python\python.exe 다.
  [string]$Root = "",
  [string]$PythonExe = "",
  [string[]]$ExtraEnv = @()         # 예: "VIGENT_PORTABLE=1","VIGENT_EXPECT_GPU=1" — AppEnvironmentExtra 에 덧붙인다
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
$PortableMode = [bool]$Root            # -Root 가 오면 포터블 설치(USB 1차). 아니면 예전 저장소 방식 그대로.
if (-not $Root) { $Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path } else { $Root = (Resolve-Path $Root).Path }
$Core = Join-Path $Root "vigent-core"
$LogDir = Join-Path $Root "logs"
if (-not (Test-Path $Core)) { Write-Error "vigent-core 를 찾을 수 없습니다: $Core"; exit 1 }
if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory $LogDir | Out-Null }

# python: **프로젝트 .venv 만** 쓴다(시스템 python·py 런처 폴백 금지 — [5단계 5-2 정정, 2026-09-06]).
#   실사고: .venv 가 없어 시스템 Python311 로 등록됐다. 서비스가 쓰는 인터프리터는 "저장소 안의 .venv" 로 고정해야
#   개발자 PC 의 PATH·py 기본값(3.14 실측)에 흔들리지 않는다. 없으면 만들라고 안내하고 중단한다.
#   ★포터블(-PythonExe)은 패키지 안의 python\python.exe 로 고정한다 — 같은 원칙(패키지 밖 인터프리터 금지).
$Py = if ($PythonExe) { $PythonExe } else { Join-Path $Root ".venv\Scripts\python.exe" }
if (-not (Test-Path $Py)) {
  if ($PortableMode) { Write-Error ("포터블 파이썬이 없습니다: " + $Py + " — USB 설치기가 portable\python\ 을 복사했는지 확인하세요."); exit 1 }
  Write-Error (".venv 가 없습니다: " + $Py + "`n  만들기: py -3.11 -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt`n" +
               "  그다음 DEPLOYMENT §3-1 opencv 정리(headless 강제) · GPU 면 §3 CUDA 휠. 시스템 python 으로는 등록하지 않습니다.")
  exit 1
}
$probe = & $Py -c "import sys, uvicorn, fastapi; sys.exit(0 if sys.version_info[:2] == (3, 11) else 3)" 2>$null; $probeCode = $LASTEXITCODE
if ($probeCode -ne 0) { Write-Error (".venv 파이썬($Py)이 3.11 이 아니거나 uvicorn/fastapi 가 없습니다(code " + $probeCode + "). .\.venv\Scripts\python.exe -m pip install -r requirements.txt"); exit 1 }
Write-Host "루트 : $Root"
Write-Host "파이썬: $Py"

# ── 2. NSSM 확인 ───────────────────────────────────────────────────────
# ── NSSM 탐색(5단계 5-2 2차 실패 정정, 2026-09-06): 저장소 동봉본 우선 → Get-Command(Source/Path) → winget Links. 빈 값은 거부 ──
#   실사고: 관리자 -NoProfile 세션에서 Get-Command nssm 이 Source 가 빈 개체를 돌려줘 `& $nssmPath` 가 "잘못된 개체" 로 죽었다.
function Resolve-Nssm([string]$Preferred) {
  $cands = @()
  if ($Preferred) { $cands += $Preferred }
  $here = $PSScriptRoot; if (-not $here) { $here = Split-Path -Parent $MyInvocation.ScriptName }   # 함수 안에서는 MyCommand.Path 가 비어 있다
  $cands += (Join-Path $here "nssm.exe")
  $c = Get-Command nssm -ErrorAction SilentlyContinue
  if ($c) { if ($c.Source) { $cands += $c.Source }; if ($c.Path) { $cands += $c.Path } }
  if ($env:LOCALAPPDATA) { $cands += (Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Links\nssm.exe") }
  foreach ($p in $cands) {
    $ok = $false; try { $ok = ($p -and (Test-Path -LiteralPath $p -PathType Leaf -ErrorAction SilentlyContinue)) } catch { $ok = $false }   # 잘못된 경로 문자열도 후보 하나로만 취급
    if ($ok) { return (Resolve-Path -LiteralPath $p).Path }
  }
  return $null
}
$nssmPath = Resolve-Nssm $NssmPath
if (-not $nssmPath) {
  Write-Host ""
  Write-Host "NSSM 을 찾지 못했습니다. 아래 중 하나로 준비한 뒤 다시 실행하세요:" -ForegroundColor Yellow
  Write-Host "  1) https://nssm.cc/download 에서 받아 win64\nssm.exe 를 이 폴더에 복사(저장소에는 동봉본이 있어야 정상)"
  Write-Host ("     → " + (Split-Path -Parent $MyInvocation.MyCommand.Path) + "\nssm.exe")
  Write-Host "  2) winget install NSSM.NSSM   3) -NssmPath <경로> 로 직접 지정"
  exit 2
}
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

# ── 3.5 [CODE_REVIEW M4-5(a)] Windows 이벤트 로그 소스 등록(관리자 컨텍스트에서 1회) ─────────────
#   기동 실패 시 main._startup 이 Application/VIGENT/ID 1000 에 ERROR 를 남긴다. 소스가 등록돼 있어야
#   비관리자 세션(run.ps1 개발 실행)에서도 Write-EventLog 가 통한다. 이미 있으면 건너뜀.
try {
  if (-not [System.Diagnostics.EventLog]::SourceExists("VIGENT")) {
    New-EventLog -LogName Application -Source VIGENT
    Write-Host "이벤트 로그 소스 'VIGENT' 등록(Application)"
  } else { Write-Host "이벤트 로그 소스 'VIGENT' 이미 등록됨" }
} catch { Write-Host "이벤트 로그 소스 등록 실패(무시, 서비스 계정의 eventcreate 가 자동 등록): $($_.Exception.Message)" -ForegroundColor Yellow }

# ── 4. 서비스 생성 ─────────────────────────────────────────────────────
# ★[5단계 5-2 정정] 서비스는 얇은 런처(deploy\windows\service_entry.py)를 거친다 — import·인터프리터 단계 실패도
#   이벤트 로그(ID 1001)·data\startup_failure.json 에 남는다(예전 `-m uvicorn main:app` 은 그 단계 실패가 무흔적).
$Entry = Join-Path $PSScriptRoot "service_entry.py"
$appArgs = ("`"" + $Entry + "`" --host $Bind --port $Port")
& $nssmPath install $ServiceName $Py $appArgs
& $nssmPath set $ServiceName AppDirectory $Core
& $nssmPath set $ServiceName DisplayName "VIGENT 산업안전 비전 서버"
& $nssmPath set $ServiceName Description "RTSP 카메라 기반 산업안전 검출(사람·PPE·화재/연기). /health 로 검출 생존 확인."

# 시작 유형: 지연 자동 — 부팅 직후 네트워크·GPU 드라이버가 준비된 뒤 기동
& $nssmPath set $ServiceName Start SERVICE_DELAYED_AUTO_START

# 실패 시 재시작. AppExit Default Restart = 어떤 종료코드든 재시작
# ★[CODE_REVIEW M4-5(b), 2026-09-06] 크래시 루프 완화 — 실사고: 기동 실패(가중치 부재)가 130초 주기로 3주·4,067회
#   반복됐는데 AppThrottle 10s 는 "10초 안에 죽을 때"만 감속해 무력했다. 모델 로드(~25s)+실패까지가 10초를 넘기 때문.
#   → AppThrottle 를 기동 시간보다 길게(180s) 두어 "기동 후 3분 안에 죽으면 폭주"로 보고 감속하고,
#     재시작 지연을 60s 로 늘려 루프 자체를 완만하게 한다(정상 크래시 복구는 1분 지연을 감수).
#   기동 실패 자체는 main._startup 이 통보·이벤트로그(Application/VIGENT ID 1000)로 드러낸다(M4-5(a)).
& $nssmPath set $ServiceName AppExit Default Restart
# ★[CODE_AUDIT_20260928 #4] 정지 방법·대기: 기본(콘솔 Ctrl+C 뒤 약 1.5 s 강제 종료)은 _shutdown(릴레이 OFF·워커 정지·큐 이월)이 끝나기 전에 잘랐다.
#   콘솔 신호 뒤 30 s 를 기다린 다음에야 다음 단계(창·스레드·종료)로 넘어간다. 앱 쪽 stop_all 은 병렬+데드라인 20 s.
& $nssmPath set $ServiceName AppStopMethodSkip 0
& $nssmPath set $ServiceName AppStopMethodConsole 30000
& $nssmPath set $ServiceName AppStopMethodWindow 5000
& $nssmPath set $ServiceName AppStopMethodThreads 5000
& $nssmPath set $ServiceName AppRestartDelay 60000    # 재시작 지연 60초(구 5초)
& $nssmPath set $ServiceName AppThrottle 180000       # 기동 후 180초 안에 죽으면 폭주로 보고 감속(구 10초)

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
# ★[CODE_AUDIT_20260928 #4] 예전 'sc.exe stop X & sc.exe start X' 는 서비스의 자식 cmd 가 자기 서비스를 멈추는 순간 NSSM 이 트리를
#   죽여 start 가 안 돌 수 있었다(실기 미검증). 이제 앱이 exit 3 으로 스스로 종료하고 NSSM AppExit Restart(60 s 지연)가 다시 띄운다.
$restartCmd = 'exit:3'
$WeightsDir = Join-Path $Core "weights"
$RtmCacheDir = Join-Path $WeightsDir "rtm_cache"
$envLines = @(
  "VIGENT_REQUIRE_TOKEN=1",
  "VIGENT_CAPTURE_MODE=thread",
  # ★[2026-08-20 정합 수정] uvicorn 은 --host 0.0.0.0(LAN 바인드)로 띄우면서 이 변수를
  #   안 넣으면 앱이 "루프백 바인드"로 오인해 Host 허용목록을 루프백만으로 걸어 —
  #   LAN 접속(폰 /health 점검 등)이 전부 403 "forbidden host" 가 된다(재부팅 시험에서
  #   실측 발견). 바인드 주소와 앱 인식을 반드시 일치시킨다. LAN 노출 라우트는
  #   VIGENT_REQUIRE_TOKEN=1 + Bearer 로 방어(설계 원안 그대로, /health 는 면제).
  # ★[2026-09-28 실기 결함 #2] 위 원칙("바인드 주소와 앱 인식 일치")을 적어 놓고 값은 0.0.0.0 으로 박아 두어, install.ps1 -Bind 127.0.0.1 로
  #   설치해도 서비스 env 는 0.0.0.0 이 됐다(uvicorn 은 127.0.0.1, 앱은 LAN 바인드로 오인). -Bind 그대로 쓴다.
  "VIGENT_HOST=$Bind",
  # ★[2026-08-20] 서비스 로그 한글 깨짐 수정. 서비스는 cp949 인코딩을 물려받아
  #   readiness 등의 한글 로그가 "???? slot=ppe" 로 찍혔다 — 현장 장애 때 봐야 할
  #   로그가 읽히지 않는다(scripts/*.py 의 UnicodeEncodeError 와 같은 뿌리).
  "PYTHONUTF8=1",
  # ★[2026-08-20] RF-DETR 사전학습 캐시를 배포 폴더로 고정.
  #   기본값(~/.roboflow/models)은 **계정별**이라 서비스가 LocalSystem 으로 돌면
  #   \Windows\System32\config\systemprofile\.roboflow\models 를 보게 된다.
  #   그래서 사용자 계정에서 미리 데워둔 캐시가 서비스엔 무용지물이었고, 서비스 첫
  #   기동에서 349MB 를 인터넷에서 새로 받았다(실측). 인터넷 없는 현장이면 기동 실패다.
  #   이 위치는 scripts/fetch_weights.py 의 다운로드 경로와 같아 매니페스트로 조달된다.
  "RF_HOME=$WeightsDir",
  # ★[2026-08-21] 포즈(RTMPose/rtmlib) 모델 캐시도 배포 폴더로 고정.
  #   rtmlib 은 **첫 사람 검출 시점에** yolox_m(101MB) + rtmpose-m(54MB) 를 인터넷에서
  #   받는다(합 156MB). 기본 캐시가 ~/.cache/rtmlib 이라 RF_HOME 과 똑같이 LocalSystem
  #   프로필로 흩어진다. ★이건 기동이 아니라 **검출 경로**라 "서비스가 떴으니 오프라인
  #   OK" 로는 안 잡힌다 — 2026-08-20 오프라인 시험이 카메라 없이 돌아 놓쳤고,
  #   2026-08-21 지게차 영상을 물리자마자 다운로드가 관측됐다.
  "TORCH_HOME=$RtmCacheDir",
  "VIGENT_RESTART_CMD=$restartCmd"
) -join "`r`n"
# [USB 1차] 포터블 설치가 넘기는 추가 env(VIGENT_PORTABLE=1 · VIGENT_EXPECT_GPU=1 · VIGENT_LOG_DIR 등). 예전 경로는 빈 배열.
if ($ExtraEnv -and $ExtraEnv.Count -gt 0) { $envLines += "`r`n" + ($ExtraEnv -join "`r`n"); Write-Host ("추가 env: " + ($ExtraEnv -join ", ")) }
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
