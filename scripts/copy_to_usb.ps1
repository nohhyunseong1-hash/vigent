# scripts/copy_to_usb.ps1 — 빌드된 포터블 패키지를 USB 로 복사(robocopy + 검증)
#
#   .\scripts\copy_to_usb.ps1 -Drive E:                 # E:\VIGENT\ 에 복사(기본 하위 폴더 VIGENT)
#   .\scripts\copy_to_usb.ps1 -Drive E: -Sub ""         # USB 루트에 바로 복사
#   .\scripts\copy_to_usb.ps1 -Drive E: -Root D:\vigent_portable
#
# · 여유 용량을 먼저 계산해 부족하면 중단한다(패키지 용량 + 5% 여유).
# · robocopy /MIR 은 대상 폴더 안의 "패키지에 없는 파일"을 지운다 — 그래서 기본은 USB 루트가 아니라 하위 폴더(VIGENT)에 넣는다.
#   -Sub "" 로 루트에 넣을 때는 /MIR 대신 /E 를 써서 USB 의 다른 파일을 지우지 않는다.
# · 복사 후 파일 수·총 바이트를 대조하고, 가중치·실행 파일은 SHA256 표본 대조한다.
# ★이 파일은 UTF-8 BOM 으로 저장한다(PowerShell 5.1 한글 주석).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Drive,
    [string]$Root = "D:\vigent_portable",
    [string]$Sub = "VIGENT"
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
if ($Drive -notmatch '^[A-Za-z]:$') { throw "드라이브 문자는 'E:' 형식으로 주세요. 받은 값: $Drive" }
if (-not (Test-Path (Join-Path $Root "VIGENT_시작.bat"))) { throw "패키지가 없습니다: $Root (먼저 scripts\build_portable.ps1)" }
if (-not (Test-Path "$Drive\")) { throw "드라이브가 없습니다: $Drive" }

$dest = if ($Sub) { Join-Path "$Drive\" $Sub } else { "$Drive\" }
$vol = Get-Volume -DriveLetter $Drive.TrimEnd(':') -ErrorAction SilentlyContinue
$fs = if ($vol) { $vol.FileSystem } else { "?" }
$free = if ($vol) { $vol.SizeRemaining } else { (Get-PSDrive $Drive.TrimEnd(':')).Free }

$srcFiles = Get-ChildItem $Root -Recurse -File -Force | Where-Object { $_.FullName -notlike (Join-Path $Root "state\*") }
$srcBytes = ($srcFiles | Measure-Object -Property Length -Sum).Sum
$existing = if (Test-Path $dest) { (Get-ChildItem $dest -Recurse -File -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum } else { 0 }
$need = [math]::Ceiling(($srcBytes - $existing) * 1.05)
Write-Host ("대상: {0}  파일시스템: {1}  여유: {2:N2} GB  필요(추정): {3:N2} GB  패키지: {4:N2} GB / {5:N0} 파일" -f $dest, $fs, ($free / 1GB), ([math]::Max($need, 0) / 1GB), ($srcBytes / 1GB), $srcFiles.Count)
if ($fs -eq "FAT32") {
    $big = $srcFiles | Where-Object { $_.Length -ge 4GB }
    if ($big) { throw "FAT32 는 4GB 이상 파일을 못 담습니다: $($big.FullName -join ', ') → USB 를 exFAT/NTFS 로 포맷하세요" }
}
if ($free -lt $need) { throw ("여유 용량 부족: {0:N2} GB 남음, {1:N2} GB 필요" -f ($free / 1GB), ($need / 1GB)) }

$mode = if ($Sub) { "/MIR" } else { "/E" }
$rc_args = @($Root, $dest, $mode, "/NFL", "/NDL", "/NJH", "/NP", "/R:2", "/W:2", "/XJ", "/XD", (Join-Path $Root "state"), "/XF", "*.tmp")
Write-Host "robocopy $($rc_args -join ' ')"
& robocopy @rc_args
$rc = $LASTEXITCODE
if ($rc -ge 8) { throw "robocopy 실패(exit $rc)" }
New-Item -ItemType Directory -Path (Join-Path $dest "state\logs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest "state\data") -Force | Out-Null

# 검증 1: 파일 수·바이트
$dstFiles = Get-ChildItem $dest -Recurse -File -Force | Where-Object { $_.FullName -notlike (Join-Path $dest "state\*") }
$dstBytes = ($dstFiles | Measure-Object -Property Length -Sum).Sum
Write-Host ("검증: 원본 {0:N0} 파일 / {1:N0} B  ↔  USB {2:N0} 파일 / {3:N0} B" -f $srcFiles.Count, $srcBytes, $dstFiles.Count, $dstBytes)
if ($srcFiles.Count -ne $dstFiles.Count -or $srcBytes -ne $dstBytes) { throw "파일 수 또는 용량이 다릅니다 — 다시 실행하세요" }
# 검증 2: 핵심 파일 SHA256
$probe = @("python\python.exe", "app\bin\go2rtc.exe", "app\vigent-core\weights\rf-detr-nano.pth", "app\vigent-core\weights\ppe_rfdetr_v1.pth",
           "app\vigent-core\weights\ppe_rfdetr_v1.onnx", "app\config\tuning.yaml", "VIGENT_시작.bat")
foreach ($p in $probe) {
    $a = (Get-FileHash -Algorithm SHA256 (Join-Path $Root $p)).Hash; $b = (Get-FileHash -Algorithm SHA256 (Join-Path $dest $p)).Hash
    if ($a -ne $b) { throw "SHA256 불일치: $p" }
    Write-Host ("  OK {0}  {1}" -f $p, $a.Substring(0, 16).ToLower())
}
Write-Host "`n완료: $dest  → USB 에서 VIGENT_시작.bat 을 더블클릭하세요. 뽑기 전 '하드웨어 안전하게 제거'." -ForegroundColor Green
