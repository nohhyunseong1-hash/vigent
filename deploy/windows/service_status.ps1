<#
.SYNOPSIS
  [B1] VIGENT 서비스 상태 + /health 를 한 줄로 확인.

.DESCRIPTION
  서비스가 Running 이어도 검출이 죽어 있을 수 있다(P0 — 영상은 살고 검출만 죽음).
  그래서 서비스 상태와 **/health 의 검출 생존 판정을 함께** 본다.
  종료 코드: 0=정상(healthy) · 1=degraded · 2=unhealthy/starting · 3=응답없음 · 4=크래시 루프 의심(최근 1h err 회전 파일 ≥ 임계)

.EXAMPLE
  .\service_status.ps1
  .\service_status.ps1 -Port 8010
#>
[CmdletBinding()]
param([string]$ServiceName = "VIGENT", [int]$Port = 8010,
      [string]$LogDir = "", [int]$CrashLoopThreshold = 10)

# LogDir 기본값 = <저장소>\logs (param 기본값에서 $PSScriptRoot 가 비는 호출 경로가 있어 본문에서 계산)
if (-not $LogDir) {
  $here = Split-Path -Parent $MyInvocation.MyCommand.Path
  $LogDir = Join-Path $here "..\..\logs"
}

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$svcState = if ($svc) { $svc.Status } else { "미등록" }

# ★[CODE_REVIEW M4-5(c), 2026-09-06] 크래시 루프 검사 — 서비스가 죽고 다시 뜨기를 반복하면 NSSM 이 vigent.err-* 회전
#   파일을 매번 만든다(실사고: 3주간 8,139개, 아무도 못 봄). /health 는 프로세스가 없어 응답조차 없으므로 여기서 본다.
#   최근 1시간 회전 파일 수가 임계(기본 10) 이상이면 종료코드 4.
$rotate1h = 0; $crashLoop = $false
try {
  if (Test-Path $LogDir) {
    $since = (Get-Date).AddHours(-1)
    $rotate1h = @(Get-ChildItem -Path $LogDir -Filter "vigent.err-*" -File -ErrorAction SilentlyContinue |
                  Where-Object { $_.LastWriteTime -ge $since }).Count
    $crashLoop = ($rotate1h -ge $CrashLoopThreshold)
  }
} catch { $rotate1h = -1 }
$rotStr = if ($rotate1h -ge 0) { " | err회전(1h)=$rotate1h" } else { "" }
if ($crashLoop) {
  $msg = "★크래시 루프 의심: 최근 1시간 vigent.err-* 회전 파일 {0}개(임계 {1}) — logs/vigent.err.log 의 기동 실패 원인·data/startup_failure.json·Windows 이벤트 로그(Application/VIGENT) 확인" -f $rotate1h, $CrashLoopThreshold
  Write-Host $msg -ForegroundColor Red
}

$code = 0; $status = "?"; $phase = "?"; $cams = @()
try {
  $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 10
  $code = $resp.StatusCode
  $h = $resp.Content | ConvertFrom-Json
} catch {
  if ($_.Exception.Response) {
    $code = [int]$_.Exception.Response.StatusCode
    $sr = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $raw = $sr.ReadToEnd()
    # 기동 극초기에는 HTTP 코드는 오는데 **본문이 비어 있거나 JSON 이 아닐 수 있다**.
    #   그때 ConvertFrom-Json 이 $null 을 주면 status/phase 가 빈칸으로 찍혀 "응답 없음"과
    #   구분이 안 된다(2026-08-17 서비스 등록 직후 실제 관측). 파싱 실패를 명시 구분한다.
    if ($raw) { try { $h = $raw | ConvertFrom-Json } catch { $h = $null } } else { $h = $null }
  } else {
    Write-Host "서비스=$svcState | HTTP 연결 실패 — /health 응답 없음 (서버 미기동·포트 불일치·방화벽)$rotStr" -ForegroundColor Red
    if ($crashLoop) { exit 4 }
    exit 3
  }
}

# 응답은 왔는데 본문을 못 읽은 경우 = 앱이 아직 라우트를 서빙하기 전(기동 중)
if (-not $h -or -not $h.status) {
  Write-Host ("서비스={0} | HTTP {1} | 앱 기동 중 — /health 본문 아직 없음(잠시 후 재시도)" -f $svcState, $code) -ForegroundColor Yellow
  exit 2
}

$status = $h.status; $phase = $h.phase
if ($h.cameras) {
  $cams = $h.cameras.PSObject.Properties | ForEach-Object {
    "{0}={1}(f{2}/d{3})" -f $_.Name, $_.Value.status, $_.Value.last_frame_age_s, $_.Value.last_detect_age_s
  }
}
$camStr = if ($cams.Count) { $cams -join ", " } else { "카메라 없음" }
# [CODE_REVIEW M4-2] 통보 전달 상태 — 데드레터(폐기)·채널 없어 폐기된 critical/high 는 텔레그램으로도 못 알릴 수 있어 여기서 본다.
$alertStr = ""
if ($h.alerts) {
  $a = $h.alerts
  $alertStr = " | 경보 pending={0} dead_1h={1} undeliverable={2}" -f $a.pending, $a.dead_1h, $a.undeliverable
  if ($a.channels_configured -eq $false) { $alertStr += " (채널 미설정)" }
  if ($a.last_config_error) { $alertStr += (" (설정 오류: {0} HTTP {1})" -f $a.last_config_error.channel, $a.last_config_error.status) }
}
if ($h.warnings -and $h.warnings.Count) { $alertStr += " | 경고: " + ($h.warnings -join ",") }

# 예열 중(starting)은 장애가 아니라 '아직 준비 안 됨' — 빨강이 아니라 노랑으로 구분한다.
$color = switch ($status) {
  "healthy"  { "Green" }
  "degraded" { "Yellow" }
  "starting" { "Yellow" }
  default    { "Red" }
}
$hint = if ($status -eq "starting") { "  ← 예열 중(약 15초), 정상" } else { "" }
Write-Host ("서비스={0} | HTTP {1} | status={2} phase={3} | {4}{5}{6}{7}" -f $svcState, $code, $status, $phase, $camStr, $alertStr, $rotStr, $hint) -ForegroundColor $color

if ($crashLoop) { exit 4 }   # 지금은 살아 있어도 최근 1시간 반복 재시작 흔적 = 조사 필요
switch ($status) {
  "healthy"  { exit 0 }
  "degraded" { exit 1 }
  default    { exit 2 }   # starting·unhealthy
}
