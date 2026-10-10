<#
.SYNOPSIS
  [5단계 5-2] 서비스 재설치 검증 — 관리자 PowerShell 에서 1회 실행. 결과는 audit/service_reinstall_<시각>.md 에 남는다.

.DESCRIPTION
  순서(try/finally — 원복은 finally 안이라 예외·타임아웃에도 실행됨):
    0) 관리자 확인 · .venv 존재 확인 · 기존 서비스 상태(Status/StartType)·NSSM 설정(nssm dump) 백업
    1) 중화: data/cameras.json · data/camera_secrets.json · config/notify.yaml → *.audit_hold (sha256 기록)
       .env 는 **유지하되 키 값만 비운 임시본**으로 교체(원본은 .env.audit_hold) — VIGENT_API_TOKEN 은 무작위 임시값
       (서비스 env VIGENT_REQUIRE_TOKEN=1 이라 토큰이 없으면 main.py 보안 게이트가 import 시점에 SystemExit(1): 2026-09-06 1차 실패 원인)
    2) install_service.ps1 로 재설치(.venv 전용 · 런처 service_entry.py · AppRestartDelay 60s · AppThrottle 180s · 이벤트 소스 · env 7개)
    3) 서비스가 Running 인지 먼저 확인(아니면 즉시 실패 사유 + err 로그 마지막 20줄) → /health 200 →
       warnings 에 channels_not_configured 만 · status 가 degraded 가 아님
    4) 의도적 기동 실패: AppEnvironmentExtra 의 RF_HOME 을 없는 폴더로 → 재시작 → data/startup_failure.json count 증가 ·
       이벤트 로그(Application/VIGENT ID 1000 또는 1001) · 연속 실패 간격 ≥ 60s(AppRestartDelay)
    5) 정상 복구: env 원복 → 재시작 → Running → /health 200 → service_status.ps1 종료코드 0
    6) install 실패·예외 즉시 **서비스 격리**(nssm set Start SERVICE_DISABLED → stop) — NSSM 60s 자동 재시작이 원복된 원본 설정으로
       뜨는 창(3차 실사고 21:04:15~29)을 남기지 않는다 → finally: 격리(재확인) → 중화 파일 원복(sha256 대조) → 서비스 Start 타입·상태를
       0)에서 백업한 값(nssm get Start · Get-Service)으로 원복 — 설정 파일 원복과 같은 등급 → 보고서 작성.
       예외·install 실패 시 err 로그 꼬리 20줄(회전본 포함)과 startup_failure.json 을 콘솔·보고서에 즉시 출력

  실사고(2026-09-06, 5-2 3차): ① 헬퍼 매개변수 이름이 $Args 라 `@Args` 가 빈 자동 변수를 스플래팅 → nssm 이 인자 없이 실행되어
     dump 는 사용법 배너, finally 의 stop/set Start 는 무동작(서비스가 Paused/Automatic 으로 남음) ② 임시 .env 를
     @("머리글", "VIGENT_API_TOKEN=" + $tok) 로 만들어 쉼표가 + 보다 먼저 묶여 토큰이 다음 줄로 떨어짐 → dotenv 가 빈 토큰으로
     읽어 보안 게이트 SystemExit(1) → NSSM Paused. 둘 다 아래에서 정정하고 tests/test_verify_service_script.py 로 고정.

.EXAMPLE
  cd deploy\windows ; .\verify_service_reinstall.ps1
  .\verify_service_reinstall.ps1 -HealthTimeoutSec 300    # 개발 PC(.venv 가 CPU torch)처럼 예열이 느린 경우
#>
[CmdletBinding()]
param(
  [string]$ServiceName = "VIGENT",
  [int]$Port = 8010,
  [int]$FailWatchSec = 240,
  [int]$HealthTimeoutSec = 150      # /health 200 대기(초). CPU torch .venv(개발 PC 검증용)는 예열이 느려 300 권장
)

$ErrorActionPreference = "Stop"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Error "관리자 권한 PowerShell 에서 실행하세요."; exit 1 }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $Here "..\..")).Path
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$VerifyStart = Get-Date            # 이 검증 시작 시각(회전된 err 로그 선별 기준)
$AuditDir = Join-Path $Root "audit"
$LogDir = Join-Path $Root "logs"
if (-not (Test-Path $AuditDir)) { New-Item -ItemType Directory $AuditDir | Out-Null }
$Report = Join-Path $AuditDir ("service_reinstall_" + $Stamp + ".md")
$Lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $t = (Get-Date -Format "HH:mm:ss"); Write-Host ("[" + $t + "] " + $s); $Lines.Add("- " + $t + " " + $s) }

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
$nssmPath = Resolve-Nssm ""
if (-not $nssmPath) { Write-Error "NSSM 을 찾을 수 없습니다(동봉본 deploy\windows\nssm.exe 확인)"; exit 2 }
Write-Host ("NSSM: " + $nssmPath)
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) { Write-Error (".venv 가 없습니다(" + $VenvPy + "). py -3.11 -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r requirements.txt 후 재실행"); exit 1 }

# nssm 은 stderr 로 진행 문구를 내보내 $ErrorActionPreference=Stop 에서 NativeCommandError 가 된다 → 호출부에서만 Continue 로 내려 흡수
# ★실사고(5-2 3차): 매개변수 이름을 $Args 로 지으면 `@Args` 는 **빈 자동 변수 $args** 를 스플래팅해 nssm 이 인자 없이 실행된다
#   (인자 없는 nssm 은 사용법 배너 또는 GUI 창 → 멈춤). 이름은 $Argv, 빈 인자 호출은 거부.
function Nssm {
  param([string[]]$Argv)
  if (-not $Argv -or $Argv.Count -eq 0) { throw "Nssm: 인자 없이 호출됨" }
  $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { $out = (& $nssmPath @Argv 2>&1) | ForEach-Object { "$_" }; return ($out -join "`n") } finally { $ErrorActionPreference = $old }
}
function Sha256([string]$p) { if (Test-Path $p) { (Get-FileHash -Algorithm SHA256 $p).Hash } else { "(없음)" } }
function Mask([string]$s) { return (($s -replace '(?i)(token|key|secret|password)=\S+', '$1=<masked>') -replace 'rtsp://\S+', 'rtsp://<masked>') }
# NSSM 은 시작마다 err 로그를 회전하므로 실패 stderr 는 회전본(vigent.err-<시각>.log)에 남는다 → 이 검증 시작 이후 회전본 + 현재본을 함께 본다
function ErrFiles() {
  $rot = @(Get-ChildItem -Path $LogDir -Filter "vigent.err-*.log" -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $VerifyStart } | Sort-Object LastWriteTime | Select-Object -Last 2 | ForEach-Object { $_.FullName })
  return @(($rot + @((Join-Path $LogDir "vigent.err.log"))) | Where-Object { Test-Path $_ })
}
function ErrTailLines([int]$n) {
  $ls = @()
  foreach ($f in (ErrFiles)) { $ls += ("-- " + (Split-Path -Leaf $f) + " 마지막 " + $n + "줄 --"); $ls += @(Get-Content -Tail $n -Encoding UTF8 $f | ForEach-Object { Mask $_ }) }
  if ($ls.Count -eq 0) { $ls = @("(err 로그 없음)") }
  return $ls
}
function ErrTail() { return ((ErrTailLines 20) -join " ⏎ ") }
function Show-Diag([string]$why) {   # install 실패·예외·Running 아님 → err 꼬리 20줄 + startup_failure.json 을 콘솔과 보고서에 즉시
  Log ("★진단(" + $why + ") — err 로그 꼬리 · startup_failure.json")
  foreach ($l in (ErrTailLines 20)) { Write-Host ("    " + $l); $Lines.Add("    " + $l) }
  $p = Join-Path $Root "data\startup_failure.json"
  if (Test-Path $p) { Log "startup_failure.json:"; foreach ($l in @(Get-Content -Encoding UTF8 $p)) { Write-Host ("    " + (Mask $l)); $Lines.Add("    " + (Mask $l)) } }
  else { Log "startup_failure.json: (없음)" }
}
function New-TempToken() { return (-join ((1..32) | ForEach-Object { "abcdefghijklmnopqrstuvwxyz0123456789"[(Get-Random -Maximum 36)] })) }
# ★실사고(5-2 3차): @("머리글", "VIGENT_API_TOKEN=" + $tok) 는 쉼표가 + 보다 먼저 묶여 @("머리글","VIGENT_API_TOKEN=") + $tok 이 된다
#   → 토큰이 다음 줄로 떨어지고 dotenv 는 VIGENT_API_TOKEN='' 로 읽어 보안 게이트 SystemExit(1). 결합은 괄호로 감싸고 줄 단위로 넣는다.
function Build-TempEnvLines([string]$Token, [string[]]$Keys, [string]$StampText) {
  $ls = New-Object System.Collections.Generic.List[string]
  $ls.Add(("# temporary .env written by verify_service_reinstall.ps1 " + $StampText + " - original kept as .env.audit_hold, restored in finally"))
  $ls.Add(("VIGENT_API_TOKEN=" + $Token))
  foreach ($k in $Keys) { if ($k -and ($k -ne "VIGENT_API_TOKEN")) { $ls.Add(($k + "=")) } }
  return $ls.ToArray()
}
function SvcStatus() { $s = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue; if ($s) { "" + $s.Status } else { "(없음)" } }
function WaitRunning([int]$sec) { $t0 = Get-Date; while (((Get-Date) - $t0).TotalSeconds -lt $sec) { if ((SvcStatus) -eq "Running") { return $true }; Start-Sleep -Seconds 2 }; return ((SvcStatus) -eq "Running") }
function ReadEnvToken() {
  # [1단계 M-2] /health 가 토큰 모드에서 인증 필요 — 그 시점의 .env 토큰을 읽어 Bearer 로 보낸다
  #   (임시본 단계에서는 이 스크립트가 넣은 무작위 임시값, 복구 단계에서는 원본 토큰이 읽힌다).
  try {
    $p = Join-Path $Root ".env"
    if (Test-Path $p) {
      $l = (Get-Content -Encoding UTF8 $p | Where-Object { $_ -match "^\s*VIGENT_API_TOKEN\s*=" } | Select-Object -First 1)
      if ($l) { return ($l -split "=", 2)[1].Trim() }
    }
  } catch {}
  return ""
}
function HealthJson() {
  $hd = @{}; $t = ReadEnvToken; if ($t) { $hd["Authorization"] = "Bearer " + $t }
  try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Headers $hd ("http://127.0.0.1:" + $Port + "/health")
        return @{ code = [int]$r.StatusCode; body = ($r.Content | ConvertFrom-Json) } }
  catch { $code = 0; try { $code = [int]$_.Exception.Response.StatusCode } catch {}
          $body = $null; try { $sr = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream()); $body = ($sr.ReadToEnd() | ConvertFrom-Json) } catch {}
          return @{ code = $code; body = $body } }
}
function WaitHealth([int]$sec) {
  $t0 = Get-Date
  while (((Get-Date) - $t0).TotalSeconds -lt $sec) {
    if ((SvcStatus) -ne "Running") { return @{ code = -1; body = $null } }     # 서비스가 죽었으면 폴링을 기다리지 않는다
    $h = HealthJson
    if ($h.code -eq 200) { return $h }
    Start-Sleep -Seconds 3
  }
  return (HealthJson)
}
function ReadFailState() {
  $p = Join-Path $Root "data\startup_failure.json"
  if (Test-Path $p) { try { return (Get-Content -Raw $p | ConvertFrom-Json) } catch { return $null } }
  return $null
}
function CountEvents([datetime]$since) {
  $n1000 = 0; $n1001 = 0
  foreach ($id in 1000, 1001) {
    $ev = @(Get-WinEvent -FilterHashtable @{ LogName = "Application"; ProviderName = "VIGENT"; Id = $id; StartTime = $since } -ErrorAction SilentlyContinue)
    if ($id -eq 1000) { $n1000 = $ev.Count } else { $n1001 = $ev.Count }
  }
  return @{ e1000 = $n1000; e1001 = $n1001 }
}

# ── 0. 백업 ─────────────────────────────────────────────────────────────
$svc0 = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$state0 = if ($svc0) { "" + $svc0.Status + "/" + $svc0.StartType } else { "(서비스 없음)" }
$status0 = if ($svc0) { "" + $svc0.Status } else { "" }
$nssmStart0 = ""                   # finally 에서 그대로 되돌릴 nssm Start 값(SERVICE_DISABLED 등)
if ($svc0) { try { $nssmStart0 = (Nssm @("get", $ServiceName, "Start")).Trim() } catch { $nssmStart0 = "" } }
if ($svc0 -and ($nssmStart0 -notmatch "^SERVICE_")) {   # nssm get 이 실패하면 Win32_Service 로 환산
  $w = Get-CimInstance Win32_Service -Filter ("Name='" + $ServiceName + "'") -ErrorAction SilentlyContinue
  $nssmStart0 = switch ("" + $w.StartMode) { "Auto" { if ($w.DelayedAutoStart) { "SERVICE_DELAYED_AUTO_START" } else { "SERVICE_AUTO_START" } } "Manual" { "SERVICE_DEMAND_START" } default { "SERVICE_DISABLED" } }
}
Log ("기존 서비스 상태: " + $state0 + $(if ($nssmStart0) { " (nssm Start=" + $nssmStart0 + ")" } else { "" }))
function Restore-ServiceState() {   # 서비스 Start 타입·상태를 백업값으로 — 원래 서비스가 없었으면 재설치본을 Stopped/Disabled 로
  if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) { Log "서비스 원복: 서비스 없음(설치 전 중단)"; return $true }
  $target = if ($nssmStart0) { $nssmStart0 } else { "SERVICE_DISABLED" }
  $wantRunning = ($status0 -eq "Running")
  try { Nssm @("set", $ServiceName, "Start", $target) | Out-Null } catch { Log ("★nssm set Start 실패: " + $_) }
  if ($wantRunning) { try { Nssm @("start", $ServiceName) | Out-Null } catch { Log ("★nssm start 실패: " + $_) } }
  else {
    try { Nssm @("stop", $ServiceName) | Out-Null } catch { Log ("★nssm stop 실패: " + $_) }
    $tw = Get-Date; while ((((Get-Date) - $tw).TotalSeconds -lt 20) -and ((SvcStatus) -ne "Stopped")) { Start-Sleep -Seconds 2 }
    if ((SvcStatus) -ne "Stopped") { try { Stop-Service -Name $ServiceName -Force -ErrorAction Stop } catch { Log ("★Stop-Service 실패: " + $_) } }
  }
  $svc1 = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  $nowStart = ""; try { $nowStart = (Nssm @("get", $ServiceName, "Start")).Trim() } catch {}
  $wantStatus = if ($wantRunning) { "Running" } else { "Stopped" }
  $match = [bool]($svc1 -and (("" + $svc1.Status) -eq $wantStatus) -and ($nowStart -eq $target))
  Log ("서비스 원복: " + $(if ($svc1) { "" + $svc1.Status + "/" + $svc1.StartType } else { "(없음)" }) + " nssm Start=" + $nowStart + " → 기대 " + $wantStatus + "/" + $target + " 일치=" + $match + " (원래: " + $state0 + ")")
  if (-not $match) { Log ("★서비스 원복 불일치 — 수동: nssm set " + $ServiceName + " Start " + $target + " ; nssm " + $(if ($wantRunning) { "start" } else { "stop" }) + " " + $ServiceName) }
  return $match
}
function Quarantine-Service([string]$why) {   # install 실패·예외 직후, 그리고 finally 첫 단계: 파일 원복보다 먼저 서비스가 다시 뜨지 못하게
  if (-not (Get-Service -Name $ServiceName -ErrorAction SilentlyContinue)) { return }
  try { Nssm @("set", $ServiceName, "Start", "SERVICE_DISABLED") | Out-Null } catch { Log ("★격리 set Start 실패: " + $_) }   # 먼저 Disabled — stop 뒤 재기동 경로 차단
  try { Nssm @("stop", $ServiceName) | Out-Null } catch { Log ("★격리 stop 실패: " + $_) }
  $tw = Get-Date; while ((((Get-Date) - $tw).TotalSeconds -lt 20) -and ((SvcStatus) -ne "Stopped")) { Start-Sleep -Seconds 2 }
  if ((SvcStatus) -ne "Stopped") { try { Stop-Service -Name $ServiceName -Force -ErrorAction Stop } catch { Log ("★격리 Stop-Service 실패: " + $_) } }
  $st = "?"; try { $st = (Nssm @("get", $ServiceName, "Start")).Trim() } catch {}
  Log ("서비스 격리(" + $why + "): " + (SvcStatus) + " / nssm Start=" + $st)
}
$dump0 = Join-Path $AuditDir ("service_nssm_dump_before_" + $Stamp + ".txt")
if ($svc0) { (Nssm @("dump", $ServiceName)) | Out-File -Encoding utf8 $dump0; Log ("NSSM 설정 백업: " + (Split-Path -Leaf $dump0)) }

# ── 1. 중화 ─────────────────────────────────────────────────────────────
$hold = @("data\cameras.json", "data\camera_secrets.json", "config\notify.yaml") | ForEach-Object { Join-Path $Root $_ }
$envFile = Join-Path $Root ".env"
$sha0 = @{}
foreach ($f in ($hold + $envFile)) { $sha0[$f] = Sha256 $f }
$held = @()
$envHeld = $false
$ok = $false
$failCountBefore = 0
try {
  foreach ($f in $hold) {
    if (Test-Path $f) { Move-Item -Force $f ($f + ".audit_hold"); $held += $f; Log ("중화: " + (Split-Path -Leaf $f) + " → .audit_hold (sha256 " + $sha0[$f].Substring(0, 12) + "…)") }
  }
  # .env: 키 값만 비운 임시본 — 채널 키는 빈값, VIGENT_API_TOKEN 은 무작위 임시값(보안 게이트 통과용, 실제 토큰 미사용)
  $tmpToken = New-TempToken
  $keys = @()
  if (Test-Path $envFile) {
    Move-Item -Force $envFile ($envFile + ".audit_hold"); $envHeld = $true
    $keys = @(Get-Content -Encoding UTF8 ($envFile + ".audit_hold") | Where-Object { $_ -match "^\s*[A-Za-z_][A-Za-z0-9_]*\s*=" } | ForEach-Object { ($_ -split "=", 2)[0].Trim() } | Where-Object { $_ -ne "VIGENT_API_TOKEN" })
    Log ("중화: .env → .env.audit_hold (sha256 " + $sha0[$envFile].Substring(0, 12) + "…), 임시본 키 " + ($keys.Count + 1) + "개(값 비움·토큰 임시값)")
  } else { Log "중화: .env 없음 → 임시 .env(토큰 임시값)만 생성" }
  (Build-TempEnvLines $tmpToken $keys $Stamp) | Out-File -Encoding ascii $envFile
  # 규칙 11: 쓴 파일을 같은 실행 안에서 다시 읽어 토큰 줄이 정확히 1줄인지 확인 — 아니면 설치 전에 중단
  $tokLines = @(Get-Content -Encoding ascii $envFile | Where-Object { $_ -match "^VIGENT_API_TOKEN=[a-z0-9]{32}$" })
  if ($tokLines.Count -ne 1) { throw ("임시 .env 자가검증 실패: VIGENT_API_TOKEN 줄 " + $tokLines.Count + "개(기대 1) — 설치 전 중단") }
  Log "임시 .env 자가검증: VIGENT_API_TOKEN 줄 1개(32자) 확인"
  $fs = ReadFailState; if ($fs) { $failCountBefore = [int]$fs.count }

  # ── 2. 재설치 ───────────────────────────────────────────────────────
  Log "install_service.ps1 실행(재설치)"
  & (Join-Path $Here "install_service.ps1") -ServiceName $ServiceName -Port $Port -Bind "127.0.0.1" -NssmPath $nssmPath
  if ($LASTEXITCODE -ne 0) { Quarantine-Service ("install exit " + $LASTEXITCODE); throw ("install_service.ps1 실패(exit " + $LASTEXITCODE + ") — 위 출력 확인") }
  $appExe = Nssm @("get", $ServiceName, "Application"); $appParams = Nssm @("get", $ServiceName, "AppParameters")
  Log ("서비스 Application: " + $appExe.Trim() + " | 인자: " + $appParams.Trim())
  $venvOk = ($appExe.Trim().ToLower() -eq $VenvPy.ToLower()) -and ($appParams -match "service_entry\.py")
  Log ("검증 2: .venv 파이썬 + 런처 등록 → " + $venvOk)
  $delay = (Nssm @("get", $ServiceName, "AppRestartDelay")).Trim(); $throttle = (Nssm @("get", $ServiceName, "AppThrottle")).Trim()
  Log ("AppRestartDelay=" + $delay + "ms AppThrottle=" + $throttle + "ms")
  $envs = Nssm @("get", $ServiceName, "AppEnvironmentExtra")
  $envNames = ($envs -split "`r?`n" | Where-Object { $_ -match "=" } | ForEach-Object { ($_ -split "=", 2)[0].Trim() })
  Log ("env " + $envNames.Count + "개: " + ($envNames -join ", "))
  Log ("이벤트 소스 VIGENT 등록: " + [System.Diagnostics.EventLog]::SourceExists("VIGENT"))

  # ── 3. Running → /health ─────────────────────────────────────────────
  $healthOk = $false
  if (-not (WaitRunning 40)) {
    Log ("★서비스가 Running 이 아님: " + (SvcStatus))
    Show-Diag "Running 아님"
  } else {
    $h = WaitHealth $HealthTimeoutSec
    $warn = ""; $status = ""
    if ($h.body) { $status = "" + $h.body.status; $warn = ("" + ($h.body.warnings -join ",")) }
    Log ("/health code=" + $h.code + " status=" + $status + " phase=" + ("" + $h.body.phase) + " warnings=[" + $warn + "]")
    if ($h.code -ne 200) { Log ("★/health 미응답 — 서비스 " + (SvcStatus) + " · err 로그: " + (ErrTail)) }
    $healthOk = ($h.code -eq 200) -and ($status -ne "degraded") -and ($warn -match "channels_not_configured")
  }
  Log ("검증 3: Running · /health 200 · degraded 아님 · channels_not_configured 만 → " + $healthOk)
  $fs = ReadFailState
  Log ("startup_failure.json: " + $(if ($fs) { "count=" + $fs.count + " stage=" + $fs.stage + " event_log_ok=" + $fs.event_log_ok } else { "(없음 — 정상 기동)" }))

  # ── 4. 의도적 기동 실패 ──────────────────────────────────────────────
  # AppEnvironmentExtra(REG_MULTI_SZ)는 항목마다 별도 인자로 넘긴다 — 줄바꿈으로 묶은 한 인자는 변수 하나로 저장된다
  $envArr = @($envs -split "`r?`n" | Where-Object { $_ -match "=" })
  $badEnv = @($envArr | ForEach-Object { if ($_ -match "^RF_HOME=") { "RF_HOME=D:\__vigent_bad_rf_home" } else { $_ } })
  Log "기동 실패 유도: RF_HOME → D:\__vigent_bad_rf_home 후 재시작"
  Nssm (@("set", $ServiceName, "AppEnvironmentExtra") + $badEnv) | Out-Null
  $t0 = Get-Date
  Nssm @("restart", $ServiceName) | Out-Null
  $stamps = New-Object System.Collections.Generic.List[double]
  $lastCount = $failCountBefore
  $tEnd = (Get-Date).AddSeconds($FailWatchSec)
  while ((Get-Date) -lt $tEnd) {
    Start-Sleep -Seconds 5
    $fs = ReadFailState
    if ($fs -and ([int]$fs.count) -gt $lastCount) {
      $lastCount = [int]$fs.count
      $stamps.Add([double]$fs.last_failure_ts)
      Log ("기동 실패 #" + $fs.count + " 기록(stage=" + $fs.stage + " event_log_ok=" + $fs.event_log_ok + " notified_count=" + $fs.notified_count + ") 서비스=" + (SvcStatus))
      if ($stamps.Count -ge 3) { break }
    }
  }
  $minGap = -1
  if ($stamps.Count -ge 2) { $gaps = @(); for ($i = 1; $i -lt $stamps.Count; $i++) { $gaps += ($stamps[$i] - $stamps[$i - 1]) }; $minGap = ($gaps | Measure-Object -Minimum).Minimum }
  Log ("연속 실패 간격 최소: " + $(if ($minGap -ge 0) { [math]::Round($minGap, 1).ToString() + "s (기대 ≥ 60s)" } else { "(2회 미만 관측 — 창 " + $FailWatchSec + "s)" }))
  $ev = CountEvents $t0
  Log ("이벤트 로그 Application/VIGENT (유도 후): ID1000=" + $ev.e1000 + " ID1001=" + $ev.e1001)
  if ($stamps.Count -eq 0) { Log ("★실패 기록 없음 — 서비스 " + (SvcStatus) + " · err 로그: " + (ErrTail)) }
  $failOk = ($stamps.Count -ge 1) -and (($ev.e1000 + $ev.e1001) -ge 1) -and (($minGap -lt 0) -or ($minGap -ge 55))
  Log ("검증 4: 실패 기록 · 이벤트 1000/1001 · 간격 ≥ 60s → " + $failOk)

  # ── 5. 정상 복구 ─────────────────────────────────────────────────────
  Nssm (@("set", $ServiceName, "AppEnvironmentExtra") + $envArr) | Out-Null
  Nssm @("restart", $ServiceName) | Out-Null
  $recovOk = $false; $statusExit = -1
  if (WaitRunning 40) {
    $h2 = WaitHealth $HealthTimeoutSec
    Log ("복구 /health code=" + $h2.code + " status=" + ("" + $h2.body.status))
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    & (Join-Path $Here "service_status.ps1") -ServiceName $ServiceName -Port $Port | Out-Null
    $statusExit = $LASTEXITCODE; $ErrorActionPreference = $old
    Log ("service_status.ps1 종료코드: " + $statusExit + " (기대 0)")
    $recovOk = ($h2.code -eq 200) -and ($statusExit -eq 0)
  } else { Log ("★복구 후 Running 아님: " + (SvcStatus) + " · err 로그: " + (ErrTail)) }
  Log ("검증 5: 복구 Running · /health 200 · status exit 0 → " + $recovOk)
  $ok = $venvOk -and $healthOk -and $failOk -and $recovOk
}
catch {
  Log ("★예외로 중단: " + $_)
  try { Quarantine-Service "예외" } catch { Log ("★격리 예외: " + $_) }
  if ($_.ScriptStackTrace) { $Lines.Add("    " + (("" + $_.ScriptStackTrace) -replace "`r?`n", " ⏎ ")) }
  Show-Diag "예외"
}
finally {
  # ── 6. 원복 ─────────────────────────────────────────────────────────
  $restoreOk = $true
  try { Quarantine-Service "원복 전" } catch { Log ("★격리 예외: " + $_) }   # 1) 파일 원복 동안 서비스가 뜨지 못하게
  foreach ($f in $held) {   # 2) 파일 원복
    if (Test-Path $f) { Log ("★서버가 중화 중 파일을 생성함: " + (Split-Path -Leaf $f) + " — " + (Split-Path -Leaf $f) + ".audit_generated 로 보관"); Move-Item -Force $f ($f + ".audit_generated") }
    Move-Item -Force ($f + ".audit_hold") $f
    $same = ((Sha256 $f) -eq $sha0[$f]); if (-not $same) { $restoreOk = $false }
    Log ("원복: " + (Split-Path -Leaf $f) + " sha256 일치=" + $same)
  }
  if ($envHeld) {
    Remove-Item -Force $envFile -ErrorAction SilentlyContinue
    Move-Item -Force ($envFile + ".audit_hold") $envFile
    $same = ((Sha256 $envFile) -eq $sha0[$envFile]); if (-not $same) { $restoreOk = $false }
    Log ("원복: .env sha256 일치=" + $same)
  } else { Remove-Item -Force $envFile -ErrorAction SilentlyContinue; Log "원복: 임시 .env 제거(원본 없었음)" }
  $svcRestoreOk = $false   # 3) 파일이 돌아온 뒤에야 서비스 Start 타입·상태를 백업값으로
  try { $svcRestoreOk = Restore-ServiceState } catch { Log ("★서비스 원복 예외: " + $_) }
  if (-not $svcRestoreOk) { $restoreOk = $false }
  $dump1 = Join-Path $AuditDir ("service_nssm_dump_after_" + $Stamp + ".txt")
  try { (Nssm @("dump", $ServiceName)) | Out-File -Encoding utf8 $dump1 } catch {}
  $hdr = @("# 서비스 재설치 검증 " + $Stamp, "", "결과: " + $(if ($ok) { "✅ 통과" } else { "❌ 미통과(아래 로그 확인)" }) + " · 원복(파일 sha256·서비스 상태) " + $(if ($restoreOk) { "일치" } else { "★불일치" }), "",
           "백업: " + (Split-Path -Leaf $dump0) + " / 사후: " + (Split-Path -Leaf $dump1), "")
  ($hdr + $Lines) | Out-File -Encoding utf8 $Report
  Write-Host ("보고서: " + $Report)
}
if ($ok) { exit 0 } else { exit 1 }
