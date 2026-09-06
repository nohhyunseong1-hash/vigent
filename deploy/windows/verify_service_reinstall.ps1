<#
.SYNOPSIS
  [5단계 5-2] 서비스 재설치 검증 — 관리자 PowerShell 에서 1회 실행. 결과는 audit/service_reinstall_<시각>.md 에 남는다.

.DESCRIPTION
  순서(try/finally — 원복은 finally 안이라 예외·타임아웃에도 실행됨):
    0) 관리자 확인 · 기존 서비스 상태(Status/StartType)·NSSM 설정(nssm dump) 백업
    1) 중화: data/cameras.json · data/camera_secrets.json · config/notify.yaml · .env → *.audit_hold (sha256 기록)
       → 카메라 0대·채널 미설정 상태로 기동시킨다(C4 스모크와 동일 원칙)
    2) install_service.ps1 로 재설치(py -3.11 · AppRestartDelay 60s · AppThrottle 180s · 이벤트 소스 · env 7개)
    3) /health 200 대기 → warnings 에 channels_not_configured 만 · status 가 degraded 가 아님을 기록
    4) 의도적 기동 실패: AppEnvironmentExtra 의 RF_HOME 을 없는 폴더로 → 재시작 → data/startup_failure.json 의
       count 증가·이벤트 로그(Application/VIGENT ID 1000) 기록·연속 실패 간격 ≥ 60s(AppRestartDelay) 확인
    5) 정상 복구: env 원복 → 재시작 → /health 200 → service_status.ps1 종료코드 0
    6) finally: 서비스 Stopped + Disabled(원래 상태) · 중화 파일 원복(sha256 대조) · 보고서 작성
  ★기동 실패 유도 동안 텔레그램 통보는 나가지 않는다 — .env·notify.yaml 이 중화돼 채널이 없다(startup_failure.json 의
    notified_count 로 확인).

.EXAMPLE
  cd deploy\windows ; .\verify_service_reinstall.ps1
#>
[CmdletBinding()]
param(
  [string]$ServiceName = "VIGENT",
  [int]$Port = 8010,
  [int]$FailWatchSec = 240
)

$ErrorActionPreference = "Stop"
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Error "관리자 권한 PowerShell 에서 실행하세요."; exit 1 }

$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = (Resolve-Path (Join-Path $Here "..\..")).Path
$Core = Join-Path $Root "vigent-core"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$AuditDir = Join-Path $Root "audit"
if (-not (Test-Path $AuditDir)) { New-Item -ItemType Directory $AuditDir | Out-Null }
$Report = Join-Path $AuditDir ("service_reinstall_" + $Stamp + ".md")
$Lines = New-Object System.Collections.Generic.List[string]
function Log([string]$s) { $t = (Get-Date -Format "HH:mm:ss"); Write-Host ("[" + $t + "] " + $s); $Lines.Add("- " + $t + " " + $s) }

$nssm = Get-Command nssm -ErrorAction SilentlyContinue
$nssmPath = if ($nssm) { $nssm.Source } else { Join-Path $Here "nssm.exe" }
if (-not (Test-Path $nssmPath)) { Write-Error "NSSM 을 찾을 수 없습니다: $nssmPath"; exit 2 }

function Sha256([string]$p) { if (Test-Path $p) { (Get-FileHash -Algorithm SHA256 $p).Hash } else { "(없음)" } }
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

# ── 0. 백업 ─────────────────────────────────────────────────────────────
$svc0 = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$state0 = if ($svc0) { "" + $svc0.Status + "/" + $svc0.StartType } else { "(서비스 없음)" }
Log ("기존 서비스 상태: " + $state0)
$dump0 = Join-Path $AuditDir ("service_nssm_dump_before_" + $Stamp + ".txt")
if ($svc0) { & $nssmPath dump $ServiceName 2>$null | Out-File -Encoding utf8 $dump0; Log ("NSSM 설정 백업: " + (Split-Path -Leaf $dump0)) }

# ── 1. 중화 ─────────────────────────────────────────────────────────────
$hold = @("data\cameras.json", "data\camera_secrets.json", "config\notify.yaml", ".env") | ForEach-Object { Join-Path $Root $_ }
$sha0 = @{}
foreach ($f in $hold) { $sha0[$f] = Sha256 $f }
$held = @()
$ok = $false
$failCountBefore = 0
try {
  foreach ($f in $hold) {
    if (Test-Path $f) { Move-Item -Force $f ($f + ".audit_hold"); $held += $f; Log ("중화: " + (Split-Path -Leaf $f) + " → .audit_hold (sha256 " + $sha0[$f].Substring(0, 12) + "…)") }
  }
  $fs = ReadFailState; if ($fs) { $failCountBefore = [int]$fs.count }

  # ── 2. 재설치 ───────────────────────────────────────────────────────
  Log "install_service.ps1 실행(재설치)"
  & (Join-Path $Here "install_service.ps1") -ServiceName $ServiceName -Port $Port -Bind "127.0.0.1"
  $pyLine = & $nssmPath get $ServiceName Application 2>$null
  Log ("서비스 Application: " + $pyLine)
  $delay = & $nssmPath get $ServiceName AppRestartDelay 2>$null; $throttle = & $nssmPath get $ServiceName AppThrottle 2>$null
  Log ("AppRestartDelay=" + $delay + "ms AppThrottle=" + $throttle + "ms")
  $envs = (& $nssmPath get $ServiceName AppEnvironmentExtra 2>$null) -join "`n"
  $envNames = ($envs -split "`r?`n" | Where-Object { $_ -match "=" } | ForEach-Object { ($_ -split "=", 2)[0] })
  Log ("env " + $envNames.Count + "개: " + ($envNames -join ", "))
  Log ("이벤트 소스 VIGENT 등록: " + [System.Diagnostics.EventLog]::SourceExists("VIGENT"))

  # ── 3. /health ───────────────────────────────────────────────────────
  $h = WaitHealth 150
  $warn = ""; $status = ""
  if ($h.body) { $status = "" + $h.body.status; $warn = ("" + ($h.body.warnings -join ",")) }
  Log ("/health code=" + $h.code + " status=" + $status + " phase=" + ("" + $h.body.phase) + " warnings=[" + $warn + "]")
  $healthOk = ($h.code -eq 200) -and ($status -ne "degraded") -and ($warn -match "channels_not_configured")
  Log ("검증 3: /health 200 · degraded 아님 · channels_not_configured 만 → " + $healthOk)
  $fs = ReadFailState
  Log ("startup_failure.json: " + $(if ($fs) { "count=" + $fs.count + " event_log_ok=" + $fs.event_log_ok } else { "(없음 — 정상 기동)" }))

  # ── 4. 의도적 기동 실패 ──────────────────────────────────────────────
  $badEnv = ($envs -split "`r?`n" | ForEach-Object { if ($_ -match "^RF_HOME=") { "RF_HOME=D:\__vigent_bad_rf_home" } else { $_ } } | Where-Object { $_ -ne "" }) -join "`r`n"
  Log "기동 실패 유도: RF_HOME → D:\__vigent_bad_rf_home 후 재시작"
  & $nssmPath set $ServiceName AppEnvironmentExtra $badEnv | Out-Null
  $t0 = Get-Date
  & $nssmPath restart $ServiceName 2>$null | Out-Null
  $stamps = New-Object System.Collections.Generic.List[double]
  $lastCount = $failCountBefore
  $tEnd = (Get-Date).AddSeconds($FailWatchSec)
  while ((Get-Date) -lt $tEnd) {
    Start-Sleep -Seconds 5
    $fs = ReadFailState
    if ($fs -and ([int]$fs.count) -gt $lastCount) {
      $lastCount = [int]$fs.count
      $stamps.Add([double]$fs.last_failure_ts)
      Log ("기동 실패 #" + $fs.count + " 기록(event_log_ok=" + $fs.event_log_ok + ", notified_count=" + $fs.notified_count + ")")
      if ($stamps.Count -ge 3) { break }
    }
  }
  $minGap = -1
  if ($stamps.Count -ge 2) { $gaps = @(); for ($i = 1; $i -lt $stamps.Count; $i++) { $gaps += ($stamps[$i] - $stamps[$i - 1]) }; $minGap = ($gaps | Measure-Object -Minimum).Minimum }
  Log ("연속 실패 간격 최소: " + $(if ($minGap -ge 0) { [math]::Round($minGap, 1).ToString() + "s (기대 ≥ 60s)" } else { "(2회 미만 관측 — 창 " + $FailWatchSec + "s)" }))
  $ev = @(Get-WinEvent -FilterHashtable @{ LogName = "Application"; ProviderName = "VIGENT"; Id = 1000; StartTime = $t0 } -ErrorAction SilentlyContinue)
  Log ("이벤트 로그 Application/VIGENT ID 1000 (유도 후): " + $ev.Count + "건")
  $failOk = ($stamps.Count -ge 1) -and ($ev.Count -ge 1) -and (($minGap -lt 0) -or ($minGap -ge 55))
  Log ("검증 4: 실패 기록 · 이벤트 1000 · 간격 ≥ 60s → " + $failOk)

  # ── 5. 정상 복구 ─────────────────────────────────────────────────────
  & $nssmPath set $ServiceName AppEnvironmentExtra $envs | Out-Null
  & $nssmPath restart $ServiceName 2>$null | Out-Null
  $h2 = WaitHealth 150
  Log ("복구 /health code=" + $h2.code + " status=" + ("" + $h2.body.status))
  & (Join-Path $Here "service_status.ps1") -ServiceName $ServiceName -Port $Port | Out-Null
  $statusExit = $LASTEXITCODE
  Log ("service_status.ps1 종료코드: " + $statusExit + " (기대 0)")
  $ok = $healthOk -and $failOk -and ($h2.code -eq 200) -and ($statusExit -eq 0)
}
finally {
  # ── 6. 원복 ─────────────────────────────────────────────────────────
  try { & $nssmPath stop $ServiceName confirm 2>$null | Out-Null; Start-Sleep -Seconds 3 } catch {}
  try { & $nssmPath set $ServiceName Start SERVICE_DISABLED 2>$null | Out-Null } catch {}
  $svc1 = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
  Log ("서비스 최종 상태: " + $(if ($svc1) { "" + $svc1.Status + "/" + $svc1.StartType } else { "(없음)" }) + " (원래: " + $state0 + ")")
  $restoreOk = $true
  foreach ($f in $held) {
    if (Test-Path $f) { Log ("★서버가 중화 중 파일을 생성함: " + (Split-Path -Leaf $f) + " — 검사용으로 " + (Split-Path -Leaf $f) + ".audit_generated 로 보관"); Move-Item -Force $f ($f + ".audit_generated") }
    Move-Item -Force ($f + ".audit_hold") $f
    $same = ((Sha256 $f) -eq $sha0[$f]); if (-not $same) { $restoreOk = $false }
    Log ("원복: " + (Split-Path -Leaf $f) + " sha256 일치=" + $same)
  }
  $dump1 = Join-Path $AuditDir ("service_nssm_dump_after_" + $Stamp + ".txt")
  try { & $nssmPath dump $ServiceName 2>$null | Out-File -Encoding utf8 $dump1 } catch {}
  $hdr = @("# 서비스 재설치 검증 " + $Stamp, "", "결과: " + $(if ($ok) { "✅ 통과" } else { "❌ 미통과(아래 로그 확인)" }) + " · 원복 sha256 " + $(if ($restoreOk) { "일치" } else { "★불일치" }), "",
           "백업: " + (Split-Path -Leaf $dump0) + " / 사후: " + (Split-Path -Leaf $dump1), "")
  ($hdr + $Lines) | Out-File -Encoding utf8 $Report
  Write-Host ("보고서: " + $Report)
}
if ($ok) { exit 0 } else { exit 1 }
