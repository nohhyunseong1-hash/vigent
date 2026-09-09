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

# ★개인정보 격리: 개발기 쪽 app\data(증거·인식 기록·카메라 등록)와 state\(로그)는 USB 로 딸려가지 않는다 — 빈 폴더 구조 + data\legal\statutes.yaml(읽기 전용 자산)만 만든다.
$excl = @((Join-Path $Root "state"), (Join-Path $Root "app\data"))
$srcFiles = Get-ChildItem $Root -Recurse -File -Force | Where-Object { $f = $_.FullName; -not ($excl | Where-Object { $f -like ($_ + "\*") }) }
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
$rc_args = @($Root, $dest, $mode, "/NFL", "/NDL", "/NJH", "/NP", "/R:2", "/W:2", "/XJ", "/XD") + $excl + @("/XF", "*.tmp")
Write-Host "robocopy $($rc_args -join ' ')"
& robocopy @rc_args
$rc = $LASTEXITCODE
if ($rc -ge 8) { throw "robocopy 실패(exit $rc)" }
New-Item -ItemType Directory -Path (Join-Path $dest "state\logs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest "app\data\legal") -Force | Out-Null
Copy-Item (Join-Path $Root "app\data\legal\statutes.yaml") (Join-Path $dest "app\data\legal\statutes.yaml") -Force
# USB 쪽 app\data 에 statutes.yaml 외 파일이 있으면(이전 현장 사용 기록) 알린다 — 지우지는 않는다(VIGENT_데이터정리.bat 의 몫)
$leftover = Get-ChildItem (Join-Path $dest "app\data") -Recurse -File -Force | Where-Object { $_.Name -ne "statutes.yaml" }
if ($leftover) { Write-Host ("★USB app\data 에 이전 기록 {0}개가 남아 있습니다 — 현장 사용 후라면 USB 에서 VIGENT_데이터정리.bat 을 실행하세요" -f @($leftover).Count) -ForegroundColor Yellow }

# 검증 1: 파일 수·바이트(app\data·state 제외 — 위에서 의도적으로 뺐다)
$dstExcl = @((Join-Path $dest "state"), (Join-Path $dest "app\data"))
$dstFiles = Get-ChildItem $dest -Recurse -File -Force | Where-Object { $f = $_.FullName; -not ($dstExcl | Where-Object { $f -like ($_ + "\*") }) }
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
