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
param([string]$ServiceName = "VIGENT")

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()
           ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) { Write-Error "관리자 권한이 필요합니다."; exit 1 }

$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $svc) { Write-Host "서비스 '$ServiceName' 이 없습니다 — 할 일 없음."; exit 0 }

$nssm = Get-Command nssm -ErrorAction SilentlyContinue
$nssmPath = if ($nssm) { $nssm.Source } else { Join-Path $PSScriptRoot "nssm.exe" }
if (-not (Test-Path $nssmPath)) { Write-Error "NSSM 을 찾을 수 없습니다: $nssmPath"; exit 2 }

Write-Host "서비스 중지..." -ForegroundColor Cyan
& $nssmPath stop $ServiceName confirm | Out-Null
Start-Sleep -Seconds 3
Write-Host "서비스 제거..." -ForegroundColor Cyan
& $nssmPath remove $ServiceName confirm | Out-Null
Start-Sleep -Seconds 2

$still = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($still) { Write-Warning "서비스가 아직 남아 있습니다 — 재부팅 후 사라질 수 있습니다." }
else { Write-Host "제거 완료. (logs/ 와 data/ 는 보존됨)" -ForegroundColor Green }
