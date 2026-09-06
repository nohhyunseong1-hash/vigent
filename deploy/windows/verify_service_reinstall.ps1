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
    6) finally: 서비스 Stopped + Disabled(원래 상태) · 중화 파일 원복(sha256 대조) · 보고서 작성

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
function Nssm { param([string[]]$Args) $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { $out = (& $nssmPath @Args 2>&1) | ForEach-Object { "$_" }; return ($out -join "`n") } finally { $ErrorActionPreference = $old } }
function Sha256([string]$p) { if (Test-Path $p) { (Get-FileHash -Algorithm SHA256 $p).Hash } else { "(없음)" } }
function ErrTail() { $e = Join-Path $LogDir "vigent.err.log"; if (Test-Path $e) { (Get-Content -Tail 20 -Encoding UTF8 $e) -join " ⏎ " } else { "(err 로그 없음)" } }
function SvcStatus() { $s = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue; if ($s) { "" + $s.Status } else { "(없음)" } }
function WaitRunning([int]$sec) { $t0 = Get-Date; while (((Get-Date) - $t0).TotalSeconds -lt $sec) { if ((SvcStatus) -eq "Running") { return $true }; Start-Sleep -Seconds 2 }; return ((SvcStatus) -eq "Running") }
function HealthJson() {
  try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 ("http://127.0.0.1:" + $Port + "/health")
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
Log ("기존 서비스 상태: " + $state0)
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
  $tmpToken = -join ((1..32) | ForEach-Object { "abcdefghijklmnopqrstuvwxyz0123456789"[(Get-Random -Maximum 36)] })
  $tmpEnv = @("# 검증용 임시 .env (verify_service_reinstall.ps1 " + $Stamp + ") — 원본은 .env.audit_hold, finally 에서 원복", "VIGENT_API_TOKEN=" + $tmpToken)
  if (Test-Path $envFile) {
    Move-Item -Force $envFile ($envFile + ".audit_hold"); $envHeld = $true
    $keys = Get-Content -Encoding UTF8 ($envFile + ".audit_hold") | Where-Object { $_ -match "^\s*[A-Za-z_][A-Za-z0-9_]*\s*=" } | ForEach-Object { ($_ -split "=", 2)[0].Trim() } | Where-Object { $_ -ne "VIGENT_API_TOKEN" }
    foreach ($k in $keys) { $tmpEnv += ($k + "=") }
    Log ("중화: .env → .env.audit_hold (sha256 " + $sha0[$envFile].Substring(0, 12) + "…), 임시본 키 " + ($keys.Count + 1) + "개(값 비움·토큰 임시값)")
  } else { Log "중화: .env 없음 → 임시 .env(토큰 임시값)만 생성" }
  $tmpEnv | Out-File -Encoding ascii $envFile
  $fs = ReadFailState; if ($fs) { $failCountBefore = [int]$fs.count }

  # ── 2. 재설치 ───────────────────────────────────────────────────────
  Log "install_service.ps1 실행(재설치)"
  & (Join-Path $Here "install_service.ps1") -ServiceName $ServiceName -Port $Port -Bind "127.0.0.1" -NssmPath $nssmPath
  if ($LASTEXITCODE -ne 0) { throw ("install_service.ps1 실패(exit " + $LASTEXITCODE + ") — 위 출력 확인") }
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
    Log ("★서비스가 Running 이 아님: " + (SvcStatus) + " — err 로그: " + (ErrTail))
    $fs = ReadFailState; if ($fs) { Log ("startup_failure.json: stage=" + $fs.stage + " count=" + $fs.count + " last_error=" + $fs.last_error) }
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
  $badEnv = ($envs -split "`r?`n" | ForEach-Object { if ($_ -match "^RF_HOME=") { "RF_HOME=D:\__vigent_bad_rf_home" } else { $_ } } | Where-Object { $_.Trim() -ne "" }) -join "`r`n"
  Log "기동 실패 유도: RF_HOME → D:\__vigent_bad_rf_home 후 재시작"
  Nssm @("set", $ServiceName, "AppEnvironmentExtra", $badEnv) | Out-Null
  $t0 = Get-Date
  Nssm @("restart", $ServiceName, "confirm") | Out-Null
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
  Nssm @("set", $ServiceName, "AppEnvironmentExtra", $envs) | Out-Null
  Nssm @("restart", $ServiceName, "confirm") | Out-Null
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
finally {
  # ── 6. 원복 ─────────────────────────────────────────────────────────
  try { Nssm @("stop", $ServiceName, "confirm") | Out-Null; Start-Sleep -Seconds 3 } catch {}
  try { Nssm @("set", $ServiceName, "Start", "SERVICE_DISABLED") | Out-Null } catch {}
  $svc1 = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  Log ("서비스 최종 상태: " + $(if ($svc1) { "" + $svc1.Status + "/" + $svc1.StartType } else { "(없음)" }) + " (원래: " + $state0 + ")")
  $restoreOk = $true
  foreach ($f in $held) {
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
  $dump1 = Join-Path $AuditDir ("service_nssm_dump_after_" + $Stamp + ".txt")
  try { (Nssm @("dump", $ServiceName)) | Out-File -Encoding utf8 $dump1 } catch {}
  $hdr = @("# 서비스 재설치 검증 " + $Stamp, "", "결과: " + $(if ($ok) { "✅ 통과" } else { "❌ 미통과(아래 로그 확인)" }) + " · 원복 sha256 " + $(if ($restoreOk) { "일치" } else { "★불일치" }), "",
           "백업: " + (Split-Path -Leaf $dump0) + " / 사후: " + (Split-Path -Leaf $dump1), "")
  ($hdr + $Lines) | Out-File -Encoding utf8 $Report
  Write-Host ("보고서: " + $Report)
}
if ($ok) { exit 0 } else { exit 1 }
