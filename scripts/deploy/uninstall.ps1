# uninstall.ps1 - VIGENT 제거(서비스 해제 + 설치 폴더 제거). [USB 1차 승인 항목 3]
#
#   uninstall.ps1 [-Target C:\VIGENT] [-BackupConfig yes|no|ask] [-DryRun] [-KeepPrev]
#
#   1. NSSM 서비스 해제 - 기존 deploy\windows\uninstall_service.ps1 재사용(설치 폴더 안의 사본)
#   2. 설정·데이터 백업 여부를 **묻는다**(-BackupConfig ask, 기본). yes 면 <Target>_backup_<시각>\ 에
#      app\config · app\data · app\.env · state 를 복사한 뒤 제거한다(비밀·증거·경보 DB 가 여기 있다).
#   3. <Target> 제거. <Target>_prev_* (업데이트 보관본)도 함께 제거 - -KeepPrev 면 남긴다.
#   ★삭제 범위는 정확히 <Target> 과 <Target>_prev_* 뿐이다. 다른 경로는 건드리지 않는다.
#   ★-DryRun: 아무것도 지우지 않고 무엇을 지울지 찍는다(관리자 불필요).
[CmdletBinding()]
param(
    [string]$Target = "C:\VIGENT",
    [ValidateSet("yes", "no", "ask")][string]$BackupConfig = "ask",
    [switch]$DryRun,
    [switch]$KeepPrev
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
function Step($m) { Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Act($m) { if ($DryRun) { Write-Host "  [DRY] $m" -ForegroundColor DarkGray } else { Write-Host "  $m" } }
function Fail($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

# ★서비스가 **이 설치의 것인지** 먼저 본다. 2026-09-23 개발기 실사고: 저장소 기반으로 예전에 등록된 VIGENT 서비스가 있었는데
#   -NoService 임시 설치를 지우려다 "서비스가 있으니 관리자" 로 막혔다. 남의 서비스(다른 경로)는 건드리지도, 요구하지도 않는다.
function Get-ServiceUnderTarget([string]$Name, [string]$Root) {
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if (-not $svc) { return $null }
    $qc = (& sc.exe qc $Name 2>$null | Out-String)
    $bin = ([regex]::Match($qc, "BINARY_PATH_NAME\s*:\s*(.+)")).Groups[1].Value.Trim()
    $appDir = ""
    $nssm = Join-Path $Root "app\deploy\windows\nssm.exe"
    if (Test-Path $nssm) { try { $appDir = (& $nssm get $Name AppDirectory 2>$null | Out-String).Trim() } catch { $appDir = "" } }
    $rootN = $Root.TrimEnd('\').ToLower()
    $mine = ($bin.ToLower().StartsWith($rootN)) -or ($appDir -and $appDir.ToLower().StartsWith($rootN))
    return [pscustomobject]@{ svc = $svc; bin = $bin; appDir = $appDir; mine = $mine }
}
$svcInfo = Get-ServiceUnderTarget "VIGENT" $Target
if ($svcInfo -and -not $svcInfo.mine) {
    Write-Host ("  서비스 VIGENT 는 이 설치의 것이 아니다(경로: {0}) — 건드리지 않는다" -f $(if ($svcInfo.bin) { $svcInfo.bin } else { $svcInfo.appDir })) -ForegroundColor Yellow
}
# 관리자는 **이 설치의 서비스가 등록돼 있을 때만** 필요하다(-NoService 임시 설치는 사용자 권한으로 지운다)
if (-not $DryRun -and $svcInfo -and $svcInfo.mine) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { Fail "이 설치의 서비스 VIGENT 가 등록돼 있어 관리자 권한이 필요합니다" }
}
if (-not (Test-Path $Target)) { Write-Host "설치 폴더가 없다: $Target - 할 일 없음"; exit 0 }
# 드라이브 루트·사용자 프로필 같은 곳을 Target 으로 잘못 주면 거부한다
$leaf = Split-Path $Target -Leaf
if (-not $leaf -or (Split-Path -Qualifier $Target) -eq $Target.TrimEnd('\') -or $Target -like "$env:USERPROFILE*") { Fail "Target 이 위험한 경로다: $Target" }

Step "1. 서비스 해제"
$svc = if ($svcInfo -and $svcInfo.mine) { $svcInfo.svc } else { $null }
if ($svc) {
    $us = Join-Path $Target "app\deploy\windows\uninstall_service.ps1"
    if (Test-Path $us) { Act "uninstall_service.ps1 (NSSM stop/remove)"; if (-not $DryRun) { & powershell -NoProfile -ExecutionPolicy Bypass -File $us; if ($LASTEXITCODE -ne 0) { Fail "서비스 해제 실패" } } }
    else { Act "uninstall_service.ps1 없음 → sc stop/delete"; if (-not $DryRun) { & sc.exe stop VIGENT | Out-Null; Start-Sleep -Seconds 3; & sc.exe delete VIGENT | Out-Null } }
} else { Write-Host "  서비스 VIGENT 없음" }

Step "2. 설정·데이터 백업"
$doBackup = $false
switch ($BackupConfig) {
    "yes" { $doBackup = $true }
    "no"  { $doBackup = $false }
    "ask" {
        if ($DryRun) { Write-Host "  [DRY] 실설치에서는 여기서 묻는다(y/N). DryRun 은 '예' 로 가정" ; $doBackup = $true }
        else { $ans = Read-Host "  설정·데이터(app\config · app\data · .env · state)를 ${Target}_backup_<시각> 에 백업할까요? [y/N]"; $doBackup = ($ans -match '^[yY]') }
    }
}
if ($doBackup) {
    $bk = "${Target}_backup_$(Get-Date -Format 'yyyyMMdd_HHmm')"
    foreach ($k in @("app\config", "app\data", "app\.env", "state")) {
        $src = Join-Path $Target $k; if (-not (Test-Path $src)) { continue }
        Act "백업: $k → $bk\$k"
        if (-not $DryRun) { $dst = Join-Path $bk $k; New-Item -ItemType Directory -Force (Split-Path $dst -Parent) | Out-Null
            if ((Get-Item $src).PSIsContainer) { & robocopy $src $dst /E /NFL /NDL /NJH /NP | Out-Null } else { Copy-Item -LiteralPath $src -Destination $dst -Force } }
    }
    if (-not $DryRun -and (Test-Path $bk)) { Write-Host "  백업 완료: $bk (비밀이 들어 있다 - 보관에 주의)" -ForegroundColor Yellow }
} else { Write-Host "  백업 안 함" }

Step "3. 폴더 제거"
# ★설치 폴더 안의 실행 파일로 도는 프로세스(고아 go2rtc.exe·남은 python)가 있으면 Remove-Item 이 잠긴 파일에서 죽는다
#   (2026-09-23 개발기 실사고 — B-go2rtc-orphan 과 같은 뿌리). 우리 폴더 안에서 뜬 것만 골라 멈춘다.
$rootN = $Target.TrimEnd('\').ToLower()
$held = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith($rootN + "\") }
foreach ($p in $held) { Act ("설치 폴더 안 프로세스 종료: PID {0} {1}" -f $p.ProcessId, $p.ExecutablePath); if (-not $DryRun) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } }
if ($held -and -not $DryRun) { Start-Sleep -Seconds 3 }
# ★설치기가 잠근 비밀 파일(icacls /inheritance:r)은 지우기 전에 현재 사용자에게 F 를 다시 준다.
#   만든 사용자가 소유자라 관리자 없이도 DACL 을 바꿀 수 있다. 2026-09-23: .env 가 R 만 있어 "Access denied" 로 제거가 실패했다.
foreach ($rel in @("app\.env", "app\config\notify.yaml", "app\data\camera_secrets.json")) {
    $f = Join-Path $Target $rel
    if (Test-Path $f) { Act "잠금 해제: $rel"; if (-not $DryRun) { & icacls $f /grant "$($env:USERDOMAIN)\$($env:USERNAME):F" 2>$null | Out-Null } }
}
Act "제거: $Target"
if (-not $DryRun) {
    try { Remove-Item -LiteralPath $Target -Recurse -Force -ErrorAction Stop }
    catch { Fail ("제거 실패: {0} — 잠긴 파일이 있으면 그 프로세스를 닫고 다시 실행" -f $_.Exception.Message) }
    if (Test-Path $Target) { Fail "제거 후에도 $Target 이 남아 있다" }
}
if (-not $KeepPrev) {
    $prevs = Get-ChildItem (Split-Path $Target -Parent) -Directory -Filter "${leaf}_prev_*" -ErrorAction SilentlyContinue
    foreach ($p in $prevs) { Act "제거(업데이트 보관본): $($p.FullName)"; if (-not $DryRun) { Remove-Item -LiteralPath $p.FullName -Recurse -Force } }
} else { Write-Host "  _prev_* 보관본은 남긴다(-KeepPrev)" }
Write-Host "`n완료: VIGENT 제거$(if ($DryRun) { ' (DryRun - 실제로는 아무것도 지우지 않음)' })" -ForegroundColor Green
exit 0
