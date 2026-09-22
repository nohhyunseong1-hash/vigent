# preflight.ps1 - VIGENT USB 설치기 사양 검사 (설계서 docs/deploy/usb_installer_design.md §2)
#
# 무엇을 하는가
#   설치를 시작하기 **전에** 이 PC 가 VIGENT 를 돌릴 수 있는지 검사한다.
#   미달 항목을 **한 줄씩 전부** 출력하고 종료코드 1 을 낸다(통과하면 0).
#
# 왜 "전부" 인가
#   하나 고치고 다시 돌렸더니 또 다른 게 걸리는 일을 막는다. 현장에서 왕복 한 번이
#   반나절이다. 첫 실행에서 고쳐야 할 것을 다 알려준다.
#
# 쓰는 법
#   powershell -ExecutionPolicy Bypass -File scripts\deploy\preflight.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\deploy\preflight.ps1 -MinVramGB 12   # 기준 올려 시험
#   -JsonOut 결과.json  을 주면 install_report 에 실을 JSON 을 남긴다.
#
# 아직 안 하는 것 (1차 범위 밖 - 설계서 §2 의 나머지)
#   - VC++ 재배포 패키지 확인(DLL 로드 시험)
#   TODO 로 남긴다. 없는 기능을 있는 척하지 않는다.

#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$InstallPath = "C:\VIGENT",
    [int]$MinVramGB = 8,
    [int]$MinRamGB = 16,
    [int]$MinDiskGB = 20,
    # ★기본값 0 = "표($DRIVER_FLOOR)에서 CudaBuild 에 맞는 값을 쓴다".
    #   숫자를 직접 주면 그 값이 우선한다(시험용). 예전엔 기본값 580 이 박혀 있어
    #   -CudaBuild cu126 을 줘도 580 이 나왔다 - 빌드와 무관한 값이 표시되는 버그였다.
    [int]$MinDriver = 0,
    [string]$CudaBuild = "cu130",
    # nvidia-smi 실행 파일. 시험 때 일부러 없는 이름을 줘서 "GPU 미검출" 경로를 타볼 수 있다.
    # (드라이버가 깔리면 nvidia-smi 는 C:\Windows\System32 에 들어가므로 PATH 를 비워도 검출된다)
    [string]$SmiExe = "nvidia-smi",
    # ★USB 안 드라이버 설치 파일 경로 - USB 구성이 확정되면 채운다(설계서 §3).
    #   비어 있으면 안내 문구에 "경로 미정" 이라고 정직하게 찍는다.
    [string]$DriverInstallerPath = "",
    [string]$JsonOut = ""
)

$ErrorActionPreference = "Stop"

# ──────────────────────────────────────────────────────────────────────────
# 동봉 torch 빌드가 지원하는 GPU 아키텍처
#   ★추측이 아니라 실측이다: D:\vigent_portable_gpu 의 python 에서
#     torch.cuda.get_arch_list() 를 찍은 값(2026-09-23, torch 2.12.0+cu130).
#   ★빌드의 CUDA 버전을 바꾸면 이 표도 같이 고쳐야 한다.
#     build_portable.ps1 -Cuda <버전> 의 기본값과 짝을 이룬다.
# ──────────────────────────────────────────────────────────────────────────
$ARCH_LIST = @{
    "cu130" = @("sm_75", "sm_80", "sm_86", "sm_90", "sm_100", "sm_120")
}

# 드라이버 하한(설계서 §1-2, NVIDIA CUDA Toolkit Release Notes Table 3 - Windows)
$DRIVER_FLOOR = @{
    "cu126" = 528
    "cu128" = 570
    "cu130" = 580
}

$script:Checks = New-Object System.Collections.ArrayList

function Add-Check {
    param([string]$Name, [string]$Required, [string]$Actual, [bool]$Ok, [string]$Hint = "")
    [void]$script:Checks.Add([pscustomobject]@{
        name = $Name; required = $Required; actual = $Actual; ok = $Ok; hint = $Hint
    })
}

function Invoke-Native {
    # 네이티브 exe 는 stderr 한 줄에도 죽지 않게 감싼다.
    # ★PowerShell 5.1 은 $ErrorActionPreference="Stop" 이면 네이티브 stderr 를
    #   NativeCommandError 로 승격시킨다. 종료코드 0 인데 실패로 보이는 사고를 막는다
    #   (설계서 위험 R-8 - GPU 포터블 빌드가 실제로 이것 때문에 죽었다).
    param([string]$Exe, [string[]]$Argv)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = & $Exe @Argv
        return [pscustomobject]@{ exit = $LASTEXITCODE; out = ($out -join "`n") }
    } catch {
        return [pscustomobject]@{ exit = -1; out = "" }
    } finally {
        $ErrorActionPreference = $prev
    }
}

# GPU 를 못 찾으면 드라이버·아키텍처·VRAM 은 "판정 불가" 다.
# ★이것을 "부족" 으로 쓰면 안 된다. 원인은 하나(드라이버 미설치)인데 네 줄이 서로 다른
#   조치를 지시하면, 현장에서 멀쩡한 GPU 를 교체하러 간다.
$BLOCKED_HINT = "GPU 를 먼저 검출해야 확인할 수 있습니다. 위 'NVIDIA GPU' 항목을 먼저 해결하세요."

function Get-DriverHint {
    if ([string]::IsNullOrWhiteSpace($DriverInstallerPath)) {
        return "USB 안의 NVIDIA 드라이버 설치 파일을 실행한 뒤 재부팅하고 다시 시작하세요. (설치 파일 경로: ___________ - USB 구성 확정 시 기입)"
    }
    return "USB 안의 드라이버 설치 파일을 실행한 뒤 재부팅하고 다시 시작하세요: $DriverInstallerPath"
}

Write-Host ""
Write-Host "=== VIGENT 설치 전 사양 검사 ===" -ForegroundColor Cyan
Write-Host ("검사 시각: {0}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
Write-Host ("설치 예정 경로: {0}   동봉 CUDA 빌드: {1}" -f $InstallPath, $CudaBuild)
Write-Host ""

# ── 1. Windows 버전 ───────────────────────────────────────────────────────
$os = Get-CimInstance Win32_OperatingSystem
$ver = [Version]$os.Version
$is64 = [Environment]::Is64BitOperatingSystem
$winOk = $is64 -and ($ver.Major -ge 10)
$archTxt = if ($is64) { "64bit" } else { "32bit" }
Add-Check -Name "Windows 버전" -Required "Windows 10 이상 · 64bit" `
    -Actual ("{0} ({1}, {2})" -f $os.Caption.Trim(), $os.Version, $archTxt) -Ok $winOk `
    -Hint "64비트 Windows 10 또는 11 이 필요합니다."

# ── 2. NVIDIA GPU / 드라이버 ──────────────────────────────────────────────
$smi = Invoke-Native -Exe $SmiExe -Argv @(
    "--query-gpu=name,driver_version,memory.total,compute_cap", "--format=csv,noheader,nounits")

$gpuName = $null; $driverVer = $null; $vramMiB = $null; $computeCap = $null
$gpuCount = 0
if ($smi.exit -eq 0 -and $smi.out.Trim()) {
    $lines = @($smi.out -split "`n" | Where-Object { $_.Trim() })
    $gpuCount = $lines.Count
    $f = $lines[0] -split "\s*,\s*"          # 첫 번째 GPU 를 기준으로 판정한다
    if ($f.Count -ge 4) {
        $gpuName = $f[0].Trim(); $driverVer = $f[1].Trim()
        $vramMiB = [double]$f[2]; $computeCap = $f[3].Trim()
    }
}
$gpuPresent = [bool]$gpuName

Add-Check -Name "NVIDIA GPU" -Required "nvidia-smi 응답" `
    -Actual $(if ($gpuPresent) { if ($gpuCount -gt 1) { "$gpuName (외 $($gpuCount - 1)대)" } else { $gpuName } } else { "검출 안 됨" }) `
    -Ok $gpuPresent -Hint (Get-DriverHint)

# 드라이버 버전 - 하한은 동봉 CUDA 빌드에 따라 달라진다
$floor = 0
if ($MinDriver -gt 0) {
    $floor = $MinDriver                       # 사람이 준 값이 우선(시험용)
} elseif ($DRIVER_FLOOR.ContainsKey($CudaBuild)) {
    $floor = $DRIVER_FLOOR[$CudaBuild]
}
$drvOk = $false; $drvActual = "확인 불가(GPU 미검출)"
if ($gpuPresent) {
    $drvMajor = 0
    if ($driverVer -match "^(\d+)") { $drvMajor = [int]$Matches[1] }
    $drvOk = $drvMajor -ge $floor
    $drvActual = $driverVer
}
if ($floor -le 0) {
    # ★"모른다" 를 "통과" 로 바꾸지 않는다. 표에 없는 빌드면 판정 자체를 못 한다고 말한다.
    Add-Check -Name "드라이버 버전" -Required "알 수 없음(표에 $CudaBuild 없음)" -Actual $drvActual -Ok $false `
        -Hint "이 스크립트에 CUDA 빌드 '$CudaBuild' 의 드라이버 하한이 없습니다. preflight.ps1 의 DRIVER_FLOOR 표를 갱신하세요."
} elseif (-not $gpuPresent) {
    Add-Check -Name "드라이버 버전" -Required (">= $floor ($CudaBuild 요구)") -Actual $drvActual -Ok $false `
        -Hint $BLOCKED_HINT
} else {
    Add-Check -Name "드라이버 버전" -Required (">= $floor ($CudaBuild 요구)") -Actual $drvActual -Ok $drvOk `
        -Hint ("드라이버가 오래됐습니다(현재 {0}, 필요 {1} 이상). {2}" -f $drvActual, $floor, (Get-DriverHint))
}

# GPU 아키텍처 - 동봉 torch 빌드가 그 GPU 를 지원하는가
$supported = $ARCH_LIST[$CudaBuild]
$archKnown = [bool]$supported
if (-not $supported) { $supported = @() }

if (-not $archKnown) {
    # ★빈 목록을 "지원 안 함" 처럼 보여주면 안 된다. 모르는 것은 모른다고 쓴다.
    Add-Check -Name "GPU 아키텍처" -Required "알 수 없음(표에 $CudaBuild 없음)" -Actual $(if ($gpuPresent) { $computeCap } else { "확인 불가(GPU 미검출)" }) -Ok $false `
        -Hint "이 스크립트에 CUDA 빌드 '$CudaBuild' 의 지원 아키텍처 목록이 없습니다. 해당 빌드에서 torch.cuda.get_arch_list() 를 찍어 preflight.ps1 의 ARCH_LIST 를 갱신하세요."
} elseif (-not $gpuPresent) {
    Add-Check -Name "GPU 아키텍처" -Required ("$CudaBuild 지원: " + ($supported -join ", ")) `
        -Actual "확인 불가(GPU 미검출)" -Ok $false -Hint $BLOCKED_HINT
} else {
    $ccParts = $computeCap -split "\."
    $smTag = "sm_{0}{1}" -f $ccParts[0], $(if ($ccParts.Count -gt 1) { $ccParts[1] } else { "0" })
    $archOk = $supported -contains $smTag
    Add-Check -Name "GPU 아키텍처" -Required ("$CudaBuild 지원: " + ($supported -join ", ")) `
        -Actual "$computeCap ($smTag)" -Ok $archOk `
        -Hint "이 GPU($smTag)는 동봉된 CUDA 빌드($CudaBuild)가 지원하지 않습니다. 지원: $($supported -join ', ')"
}

# ── 3. VRAM ───────────────────────────────────────────────────────────────
$vramOk = $false; $vramActual = "확인 불가(GPU 미검출)"
if ($gpuPresent -and $vramMiB) {
    $vramGB = [Math]::Round($vramMiB / 1024, 1)
    $vramActual = "$vramGB GB"
    $vramOk = $vramGB -ge $MinVramGB
}
Add-Check -Name "VRAM" -Required ">= $MinVramGB GB" -Actual $vramActual -Ok $vramOk `
    -Hint $(if ($gpuPresent) { "VRAM이 부족합니다(현재 $vramActual, 필요 ${MinVramGB}GB). GPU 교체가 필요합니다." } else { $BLOCKED_HINT })

# ── 4. RAM ────────────────────────────────────────────────────────────────
$ramGB = [Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
Add-Check -Name "RAM" -Required ">= $MinRamGB GB" -Actual "$ramGB GB" -Ok ($ramGB -ge $MinRamGB) `
    -Hint ("메모리가 부족합니다(현재 {0}GB, 필요 {1}GB). 메모리 증설이 필요합니다." -f $ramGB, $MinRamGB)

# ── 5. 디스크 여유 (설치 대상 드라이브) ───────────────────────────────────
$targetRoot = $null
try { $targetRoot = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($InstallPath)) } catch { $targetRoot = $null }
$freeGB = $null; $diskOk = $false; $diskActual = "확인 불가"
if ($targetRoot) {
    $drv = Get-CimInstance Win32_LogicalDisk -Filter ("DeviceID='{0}'" -f $targetRoot.TrimEnd('\'))
    if ($drv) {
        $freeGB = [Math]::Round($drv.FreeSpace / 1GB, 1)
        $diskActual = "$targetRoot $freeGB GB 여유"
        $diskOk = $freeGB -ge $MinDiskGB
    } else {
        $diskActual = "드라이브 $targetRoot 없음"
    }
}
Add-Check -Name "디스크 여유" -Required ">= $MinDiskGB GB ($InstallPath)" -Actual $diskActual -Ok $diskOk `
    -Hint ("디스크 여유가 부족합니다(현재 {0}, 필요 {1}GB). 다른 드라이브를 -InstallPath 로 지정하거나 공간을 비우세요." -f $diskActual, $MinDiskGB)

# ── 결과 출력 ─────────────────────────────────────────────────────────────
Write-Host "--- 검사 결과 ---"
foreach ($c in $script:Checks) {
    $mark = if ($c.ok) { "[통과]" } else { "[미달]" }
    $color = if ($c.ok) { "Green" } else { "Red" }
    Write-Host ("{0} {1,-14} 필요: {2,-34} 실제: {3}" -f $mark, $c.name, $c.required, $c.actual) -ForegroundColor $color
}

$failed = @($script:Checks | Where-Object { -not $_.ok })
Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host ("!! 미달 {0}건 - 설치를 시작할 수 없습니다." -f $failed.Count) -ForegroundColor Red
    Write-Host ""
    foreach ($c in $failed) {
        # ★한 줄씩 전부 - 하나 고치고 또 걸리는 왕복을 막는다
        Write-Host ("  - {0}: {1}" -f $c.name, $(if ($c.hint) { $c.hint } else { "필요 $($c.required) / 현재 $($c.actual)" })) -ForegroundColor Yellow
    }
    Write-Host ""
} else {
    Write-Host "모든 항목 통과 - 설치를 진행할 수 있습니다." -ForegroundColor Green
    Write-Host ""
}

if ($JsonOut) {
    $report = [pscustomobject]@{
        checked_at  = (Get-Date -Format "o")
        host        = $env:COMPUTERNAME
        install_path = $InstallPath
        cuda_build  = $CudaBuild
        thresholds  = @{ vram_gb = $MinVramGB; ram_gb = $MinRamGB; disk_gb = $MinDiskGB; driver = $floor }
        passed      = ($failed.Count -eq 0)
        failed_count = $failed.Count
        checks      = @($script:Checks)
    }
    $dir = Split-Path -Parent $JsonOut
    if ($dir -and -not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $report | ConvertTo-Json -Depth 5 | Out-File -FilePath $JsonOut -Encoding utf8
    Write-Host ("검사 보고서 저장: {0}" -f $JsonOut)
}

if ($failed.Count -gt 0) { exit 1 }
exit 0
