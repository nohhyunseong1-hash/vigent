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
    $h = $sr.ReadToEnd() | ConvertFrom-Json
  } else {
    Write-Host "서비스=$svcState | /health 응답 없음 (서버 미기동 또는 포트 불일치)" -ForegroundColor Red
    exit 3
  }
}

$status = $h.status; $phase = $h.phase
if ($h.cameras) {
  $cams = $h.cameras.PSObject.Properties | ForEach-Object {
    "{0}={1}(f{2}/d{3})" -f $_.Name, $_.Value.status, $_.Value.last_frame_age_s, $_.Value.last_detect_age_s
  }
}
$camStr = if ($cams.Count) { $cams -join ", " } else { "카메라 없음" }

$color = switch ($status) { "healthy" { "Green" } "degraded" { "Yellow" } default { "Red" } }
Write-Host ("서비스={0} | HTTP {1} | status={2} phase={3} | {4}" -f $svcState, $code, $status, $phase, $camStr) -ForegroundColor $color

switch ($status) {
  "healthy"  { exit 0 }
  "degraded" { exit 1 }
  default    { exit 2 }
}
