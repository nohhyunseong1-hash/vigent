<#
.SYNOPSIS
  [B1] VIGENT Windows 서비스 제거(NSSM). 로그 파일은 남긴다.

.DESCRIPTION
  서비스만 내리고 지운다. logs/ 의 기록과 data/(카메라 등록·증거)는 **건드리지 않는다** —
  운영 이력·증거는 서비스 제거와 무관하게 보존돼야 한다.

  ★관리자 권한 PowerShell 에서 실행할 것.

.EXAMPLE
  .\uninstall_service.ps1
#>
[CmdletBinding()]
param([string]$ServiceName = "VIGENT", [string]$NssmPath = "")

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Error "관리자 권한이 필요합니다."; exit 1 }

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) { Write-Host "서비스 '$ServiceName' 이 없습니다 — 할 일 없음."; exit 0 }

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
if (-not $nssmPath) { Write-Error "NSSM 을 찾을 수 없습니다(동봉본 deploy\windows\nssm.exe 확인 또는 -NssmPath 지정)"; exit 2 }

Write-Host "서비스 중지..." -ForegroundColor Cyan
& $nssmPath stop $ServiceName confirm | Out-Null
Start-Sleep -Seconds 3
Write-Host "서비스 제거..." -ForegroundColor Cyan
& $nssmPath remove $ServiceName confirm | Out-Null
Start-Sleep -Seconds 2

$still = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($still) { Write-Warning "서비스가 아직 남아 있습니다 — 재부팅 후 사라질 수 있습니다." }
else { Write-Host "제거 완료. (logs/ 와 data/ 는 보존됨)" -ForegroundColor Green }
