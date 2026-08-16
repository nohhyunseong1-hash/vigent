<#
.SYNOPSIS
  [B1] VIGENT 서비스 상태 + /health 를 한 줄로 확인.

.DESCRIPTION
  서비스가 Running 이어도 검출이 죽어 있을 수 있다(P0 — 영상은 살고 검출만 죽음).
  그래서 서비스 상태와 **/health 의 검출 생존 판정을 함께** 본다.
  종료 코드: 0=정상(healthy) · 1=degraded · 2=unhealthy/starting · 3=응답없음

.EXAMPLE
  .\service_status.ps1
  .\service_status.ps1 -Port 8010
#>
[CmdletBinding()]
param([string]$ServiceName = "VIGENT", [int]$Port = 8010)

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
$svcState = if ($svc) { $svc.Status } else { "미등록" }

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
    Write-Host "서비스=$svcState | HTTP 연결 실패 — /health 응답 없음 (서버 미기동·포트 불일치·방화벽)" -ForegroundColor Red
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

# 예열 중(starting)은 장애가 아니라 '아직 준비 안 됨' — 빨강이 아니라 노랑으로 구분한다.
$color = switch ($status) {
  "healthy"  { "Green" }
  "degraded" { "Yellow" }
  "starting" { "Yellow" }
  default    { "Red" }
}
$hint = if ($status -eq "starting") { "  ← 예열 중(약 15초), 정상" } else { "" }
Write-Host ("서비스={0} | HTTP {1} | status={2} phase={3} | {4}{5}" -f $svcState, $code, $status, $phase, $camStr, $hint) -ForegroundColor $color

switch ($status) {
  "healthy"  { exit 0 }
  "degraded" { exit 1 }
  default    { exit 2 }   # starting·unhealthy
}
