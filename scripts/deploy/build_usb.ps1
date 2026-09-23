# build_usb.ps1 - USB 설치기 1차: USB 루트를 만든다. [USB 1차 계획 1]
#
#   <UsbRoot>\
#     VERSION.txt · usb_manifest.json · 설치.bat
#     installer\  (preflight.ps1 · install.ps1 · uninstall.ps1 - 아직 없는 것은 경고만)
#     portable\   (build_portable.ps1 -Gpu 산출물 그대로: python\ · wheels_cuda\ · app\ · 런처 · vc_redist)
#     driver\README.txt (NVIDIA 드라이버 exe 는 사람이 넣는다 - 경로 빈칸, 설계서 §2)
#   레이아웃 계약·검증은 scripts/deploy/usb_layout.py 하나가 정본이다(테스트도 같은 것을 본다).
#
# 사용:
#   .\scripts\deploy\build_usb.ps1 -UsbRoot E:\VIGENT_USB                       # 포터블을 새로 빌드해 넣는다
#   .\scripts\deploy\build_usb.ps1 -UsbRoot D:\vigent_usb_stage -SkipBuild -PortableRoot D:\vigent_portable_gpu2
#                                                                                # 이미 있는 포터블을 복사(스테이징·시험용)
# ★USB E: 는 포맷하지 않는다. 기존 파일이 있는 드라이브라도 <UsbRoot> 폴더 하나만 만든다.
# ★비밀은 USB 에 넣지 않는다 - notify.yaml·camera_secrets.json 이 portable\app 에 있으면 빌드가 실패한다(usb_layout FORBIDDEN).
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$UsbRoot,
    [string]$PortableRoot = "",          # -SkipBuild 일 때 복사할 기존 포터블
    # ★-SkipBuild 원본이 이미 --gpu 교체·휠 삭제된 포터블이면 wheels_cuda 가 없다(런처가 지운다, I-5).
    #   USB 는 '설치 전' 상태라 휠이 있어야 한다 — 여기서 준 폴더의 휠을 채워 넣는다(예: D:\vigent_portable_gpu\python\wheels_cuda).
    [string]$WheelsCudaFrom = "",
    [switch]$SkipBuild,
    [string]$Cache = "D:\vigent_portable_cache",
    [string]$Tag = ""                    # 비우면 git describe --tags --always
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$Repo = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition))
$Py = Join-Path $Repo ".venv\Scripts\python.exe"; if (-not (Test-Path $Py)) { $Py = "python" }
function Step($m) { Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Fail($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

# 드라이브 루트 자체를 UsbRoot 로 주면 거부한다 - 기존 USB 내용물과 섞이거나 포맷으로 오해될 수 있다
if ((Split-Path -Qualifier $UsbRoot) -eq $UsbRoot.TrimEnd('\')) { Fail "UsbRoot 는 드라이브 루트가 아니라 폴더여야 한다(예: E:\VIGENT_USB)" }
New-Item -ItemType Directory -Force $UsbRoot | Out-Null
$portable = Join-Path $UsbRoot "portable"
$commit = ((git -C $Repo rev-parse --short HEAD) 2>$null); if (-not $commit) { $commit = "unknown" }
if (-not $Tag) { $Tag = ((git -C $Repo describe --tags --always) 2>$null); if (-not $Tag) { $Tag = "untagged-$commit" } }

Step "1. 포터블 → $portable"
if ($SkipBuild) {
    if (-not $PortableRoot -or -not (Test-Path (Join-Path $PortableRoot "python\python.exe"))) { Fail "-SkipBuild 면 -PortableRoot 에 기존 포터블이 있어야 한다" }
    if (-not (Test-Path (Join-Path $PortableRoot "python\wheels_cuda"))) { Write-Host "  ★주의: 원본에 wheels_cuda 가 없다(이미 --gpu 교체·삭제된 포터블). -WheelsCudaFrom 으로 채우지 않으면 오프라인 CUDA 교체를 못 한다." -ForegroundColor Yellow }
    $tv = Join-Path $PortableRoot "python\Lib\site-packages\torch\version.py"
    if ((Test-Path $tv) -and ((Get-Content $tv -Raw) -match "\+cu\d+")) {
        # 2026-09-23 실측: gpu2(교체 후 4.69GB) + 휠 1.80GB = 6.49GB — 새 빌드(4.23GB)보다 2.26GB 크고 --gpu 가 cu130 위에 cu130 을 다시 깐다.
        Write-Host "  ★주의: 원본 torch 가 이미 CUDA 판이다(교체 완료 상태). 이 스테이지는 스크립트 시험용이다 — 실제 USB 는 -SkipBuild 없이 새로 빌드하라." -ForegroundColor Yellow
    }
    # robocopy: 상태 로그·벤치 흔적은 제외 - USB 는 '설치 전' 상태여야 한다
    $rc = @($PortableRoot, $portable, "/E", "/NFL", "/NDL", "/NJH", "/NP", "/MT:16",
            "/XD", (Join-Path $PortableRoot "state"), (Join-Path $PortableRoot "app\data"), (Join-Path $PortableRoot "app\logs"),
                   (Join-Path $PortableRoot "app\.mypy_cache"), (Join-Path $PortableRoot "app\.ruff_cache"),
            "/XF", "notify.yaml", "camera_secrets.json")
    & robocopy @rc | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy 실패(exit $LASTEXITCODE)" }
    $wcDst = Join-Path $portable "python\wheels_cuda"
    if (-not (Test-Path $wcDst) -and $WheelsCudaFrom) {
        if (-not (Get-ChildItem $WheelsCudaFrom -Filter "torch-*+cu*.whl" -ErrorAction SilentlyContinue)) { Fail "-WheelsCudaFrom 에 torch cu 휠이 없다: $WheelsCudaFrom" }
        & robocopy $WheelsCudaFrom $wcDst /E /NFL /NDL /NJH /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { Fail "wheels_cuda 복사 실패(exit $LASTEXITCODE)" }
        $wb = (Get-ChildItem $wcDst -Recurse -File | Measure-Object Length -Sum).Sum
        Write-Host ("  wheels_cuda 를 {0} 에서 채움 ({1:N2} GB)" -f $WheelsCudaFrom, ($wb / 1GB))
    }
} else {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo "scripts\build_portable.ps1") -Gpu -Root $portable -Cache $Cache
    if ($LASTEXITCODE -ne 0) { Fail "build_portable.ps1 -Gpu 실패" }
}
# 빈 폴더는 '설치 전' 상태로 다시 만든다(런처가 기대한다)
foreach ($d in @("state\logs", "state\data", "app\data", "app\logs")) { New-Item -ItemType Directory -Force (Join-Path $portable $d) | Out-Null }

Step "2. installer\ · 설치.bat · driver\ · VERSION.txt"
$inst = Join-Path $UsbRoot "installer"; New-Item -ItemType Directory -Force $inst | Out-Null
foreach ($f in @("preflight.ps1", "install.ps1", "uninstall.ps1")) {
    $src = Join-Path $Repo "scripts\deploy\$f"
    if (Test-Path $src) { Copy-Item $src (Join-Path $inst $f) -Force; Write-Host "  installer\$f" }
    else { Write-Host "  (아직 없음) installer\$f - 1차 계획 순서상 뒤에 온다" -ForegroundColor Yellow }
}
Copy-Item (Join-Path $Repo "scripts\deploy\usb_layout.py") (Join-Path $inst "usb_layout.py") -Force
# 서비스 런처·NSSM·서비스 스크립트 — 포터블 빌드는 app\deploy\windows 를 잘라내므로(잔재 제거) USB 가 따로 싣는다.
#   install.ps1 이 설치 시 <Target>\app\deploy\windows\ 로 되돌려 놓는다(service_entry.py 는 parents[2]=app 을 뿌리로 본다).
$iw = Join-Path $inst "windows"; New-Item -ItemType Directory -Force $iw | Out-Null
foreach ($f in @("service_entry.py", "nssm.exe", "install_service.ps1", "uninstall_service.ps1", "service_status.ps1")) {
    $src = Join-Path $Repo "deploy\windows\$f"
    if (-not (Test-Path $src)) { Fail "deploy\windows\$f 가 없다 — 서비스 등록에 필요하다" }
    Copy-Item $src (Join-Path $iw $f) -Force
}
Write-Host "  installer\windows\ (service_entry.py · nssm.exe · install/uninstall/status_service.ps1)"
Copy-Item (Join-Path $Repo "deploy\usb\설치.bat") (Join-Path $UsbRoot "설치.bat") -Force
$drv = Join-Path $UsbRoot "driver"; New-Item -ItemType Directory -Force $drv | Out-Null
@"
NVIDIA 드라이버 설치 파일을 이 폴더에 넣으세요.
  - 요구: CUDA 13.0 Windows → 드라이버 버전 580 이상 (설계서 §1-2, preflight 가 검사)
  - 파일 예: 5xx.xx-desktop-win10-win11-64bit-international-dch-whql.exe
  - 경로: ___________  (USB 구성 확정 시 기입 - preflight.ps1 -DriverInstallerPath 로 넘긴다)
설치기는 이 폴더를 검사만 하고 자동 실행하지 않습니다. 드라이버는 사람이 설치하고 재부팅합니다.
"@ | Out-File -FilePath (Join-Path $drv "README.txt") -Encoding utf8
$pbytes = (Get-ChildItem $portable -Recurse -File | Measure-Object Length -Sum).Sum
@"
VIGENT USB 설치기
태그      : $Tag
커밋      : $commit
빌드일    : $(Get-Date -Format 'yyyy-MM-dd HH:mm')
포터블    : {0:N2} GB (wheels_cuda 포함, --gpu 교체 후 런처가 삭제)
CUDA 빌드 : cu130 (sm_75~sm_120 · 드라이버 ≥ 580)
원본      : $Repo (audit/cleanup-20260906)
"@ -f ($pbytes / 1GB) | Out-File -FilePath (Join-Path $UsbRoot "VERSION.txt") -Encoding utf8
Write-Host ("  VERSION.txt: {0} · {1} · 포터블 {2:N2} GB" -f $Tag, $commit, ($pbytes / 1GB))

Step "3. 매니페스트 + 레이아웃 검증 (usb_layout.py - 테스트와 같은 계약)"
& $Py (Join-Path $Repo "scripts\deploy\usb_layout.py") manifest $UsbRoot --tag $Tag --commit $commit
if ($LASTEXITCODE -ne 0) { Fail "매니페스트 생성 실패" }
& $Py (Join-Path $Repo "scripts\deploy\usb_layout.py") verify $UsbRoot
if ($LASTEXITCODE -ne 0) { Fail "USB 레이아웃 검증 미달 - 위 [미달] 항목을 고쳐라" }
$tot = (Get-ChildItem $UsbRoot -Recurse -File | Measure-Object Length -Sum)
Write-Host ("`n완료: {0}  총 {1:N2} GB · {2:N0} 파일" -f $UsbRoot, ($tot.Sum / 1GB), $tot.Count) -ForegroundColor Green
exit 0
