# scripts/build_portable.ps1 — VIGENT USB 포터블 패키지 빌드 (Windows PowerShell 5.1 이상)
#
#   .\scripts\build_portable.ps1                        # D:\vigent_portable 에 빌드(캐시 D:\vigent_portable_cache)
#   .\scripts\build_portable.ps1 -Gpu                   # + python\wheels_cuda\ 에 CUDA torch 휠 동봉(선택, 2.5GB+)
#                                                       #   기본 cu130 — RTX 50 시리즈(sm_120) 지원
#   .\scripts\build_portable.ps1 -Root E:\pkg -Cache E:\cache
#
# 방식: Windows embeddable Python 3.11.9 + 상대경로 런처(PyInstaller 미사용). 두 번 실행해도 같은 결과가
# 나오도록, 이미 받은 파일은 SHA256 이 맞으면 재다운로드하지 않고 pip 설치도 그대로 재실행(멱등)한다.
# 다운로드 출처: python.org · pypi.org(files.pythonhosted.org) · download.pytorch.org 만.
# 반출 금지 자료(footage/ data/ runs/ logs/ .git/ .venv/ .env config/notify.yaml 등)는 복사 대상에서 제외한다.
# ★이 파일은 UTF-8 BOM 으로 저장한다 — PowerShell 5.1 은 BOM 이 없으면 한글을 ANSI 로 읽어 구문 오류를 낸다.
[CmdletBinding()]
param(
    [string]$Root = "D:\vigent_portable",
    [string]$Cache = "D:\vigent_portable_cache",
    [string]$Source = "",
    [switch]$Gpu,
    # ★[2026-09-23] 기본값 cu126 → cu130. 실측: torch 2.12.0+cu130 의 지원 아키텍처는
    #   ['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120'] 이고, RTX 50 시리즈(Blackwell)는
    #   **sm_120** 이다. cu126 은 sm_120 을 지원하지 않아 RTX 5060/5070 에서 커널이 없어
    #   실패하거나 **조용히 CPU 로 떨어진다**(조용한 성능 저하 = 이 프로젝트가 금지하는 유형).
    [string]$Cuda = "cu130",
    [switch]$SkipPip,           # 패키지 설치 단계 생략(앱·가중치·런처만 다시 복사할 때)
    # ★[CODE_AUDIT_20260928 #3] 현장 프로파일. 비우면 플랫폼 오버라이드(deploy/portable)만 적용 = 전역값(근골격 ON·화재 ON).
    #   "academy" 면 deploy/academy/portable_overrides.academy.yaml 을 **덧붙여** 적용(근골격 OFF·화재 OFF).
    [string]$Profile = ""
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
if (-not $Source) { $Source = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition) }   # <repo>\scripts\.. (PS 5.1: param 기본값에서 $PSScriptRoot 가 비어 있을 수 있음)

# ── 고정값(출처: https://www.python.org/downloads/release/python-3119/ — 페이지는 MD5 만 게시. SHA256 은 2026-09-09 실측값 고정) ──
$PyVer      = "3.11.9"
$EmbedUrl   = "https://www.python.org/ftp/python/$PyVer/python-$PyVer-embed-amd64.zip"
$EmbedMd5   = "6d9aa08531d48fcc261ba667e2df17c4"
$EmbedSha   = "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"
$PipVer     = "26.2.1"
$Headless   = "opencv-contrib-python-headless==4.13.0.92"     # requirements.txt 핀과 같아야 한다
$TorchVer   = "2.12.0"; $TvVer = "0.27.0"

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Sha256($p) { (Get-FileHash -Algorithm SHA256 -Path $p).Hash.ToLower() }
function Md5($p)    { (Get-FileHash -Algorithm MD5 -Path $p).Hash.ToLower() }
function Ensure-Dir($p) { if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p | Out-Null } }
function Download($url, $dest, $sha) {
    if ((Test-Path $dest) -and $sha -and ((Sha256 $dest) -eq $sha)) { Write-Host "  캐시 사용: $dest"; return }
    Write-Host "  받는 중: $url"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    if ($sha -and ((Sha256 $dest) -ne $sha)) { throw "SHA256 불일치: $dest" }
}
function Quiet($exe, [string[]]$argv) {
    # 실패해도 예외를 내지 않고 종료코드만 돌려준다(PS 5.1 은 $ErrorActionPreference=Stop 에서 네이티브 stderr 를 예외로 승격).
    $old = $ErrorActionPreference; $ErrorActionPreference = "Continue"
    $out = & $exe @argv 2>&1
    $code = $LASTEXITCODE
    $ErrorActionPreference = $old
    return @{ code = $code; out = ($out | Out-String) }
}
function Run($exe, [string[]]$argv) {
    Write-Host ("  > " + $exe + " " + ($argv -join " ")) -ForegroundColor DarkGray
    # ★[2026-09-23] $ErrorActionPreference="Stop" 이면 PowerShell 5.1 은 **네이티브 명령의
    #   stderr 한 줄**도 NativeCommandError 예외로 만든다. 실제로 rfdetr 의 FutureWarning
    #   한 줄 때문에 GPU 빌드가 통째로 죽었다(종료코드는 0 이었다).
    #   → 이 블록 안에서만 Continue 로 낮추고, **성패는 종료코드로만** 판정한다.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $exe @argv
    } finally {
        $ErrorActionPreference = $prev
    }
    if ($LASTEXITCODE -ne 0) { throw "실패(exit $LASTEXITCODE): $exe $($argv -join ' ')" }
}

$PyDir = Join-Path $Root "python"; $Py = Join-Path $PyDir "python.exe"
$App   = Join-Path $Root "app";    $State = Join-Path $Root "state"
Ensure-Dir $Root; Ensure-Dir $Cache; Ensure-Dir $App; Ensure-Dir (Join-Path $State "logs"); Ensure-Dir (Join-Path $State "data")
Write-Host "빌드 대상: $Root   캐시: $Cache   원본: $Source"
$running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Root, "OrdinalIgnoreCase") }
if ($running) { throw ("패키지 안의 프로세스가 실행 중입니다(먼저 VIGENT_종료.bat): " + (($running | ForEach-Object { $_.Name + " " + $_.ProcessId }) -join ", ")) }

# ── 1. embeddable Python ──
Step "1. Windows embeddable Python $PyVer"
$zip = Join-Path $Cache "python-$PyVer-embed-amd64.zip"
Download $EmbedUrl $zip $EmbedSha
if ((Md5 $zip) -ne $EmbedMd5) { throw "python.org 게시 MD5 와 불일치: $zip" }
Write-Host "  MD5(python.org 게시값) 일치 · SHA256 고정값 일치"
$needExtract = -not (Test-Path $Py)
if (-not $needExtract) {
    if ((Quiet $Py @("-c", "import sys; assert sys.version_info[:3]==(3,11,9)")).code -ne 0) { $needExtract = $true }
}
if ($needExtract) {
    Write-Host "  압축 해제 → $PyDir"
    Ensure-Dir $PyDir
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $z = [IO.Compression.ZipFile]::OpenRead($zip)
    foreach ($e in $z.Entries) { $t = Join-Path $PyDir $e.FullName; if ($e.Name) { [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $t, $true) } }
    $z.Dispose()
} else { Write-Host "  이미 있음(3.11.9 확인) — 유지" }

# ── 1b. Microsoft Visual C++ 재배포 패키지(x64) 동봉 — torch·onnxruntime 이 msvcp140.dll 을 시스템에서 찾는다 ──
#   출처: Microsoft 공식 단축 URL. 멱등: 이미 있고 Authenticode 서명이 Valid + 서명자 Microsoft 면 재다운로드하지 않는다.
Step "1b. vc_redist.x64.exe (Microsoft 서명 검증)"
$vcr = Join-Path $Root "vc_redist.x64.exe"
function VcRedist-Ok($p) {
    if (-not (Test-Path $p)) { return $false }
    $s = Get-AuthenticodeSignature -FilePath $p
    return ($s.Status -eq "Valid" -and $s.SignerCertificate.Subject -like "*Microsoft Corporation*")
}
if (-not (VcRedist-Ok $vcr)) {
    Write-Host "  받는 중: https://aka.ms/vs/17/release/vc_redist.x64.exe"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $vcr -UseBasicParsing
    if (-not (VcRedist-Ok $vcr)) { Remove-Item $vcr -Force; throw "vc_redist.x64.exe 서명 검증 실패 — 파일을 지웠다" }
}
$vs = Get-AuthenticodeSignature -FilePath $vcr
Write-Host ("  OK {0}  {1:N0} B  서명 {2}  {3}  v{4}" -f (Split-Path -Leaf $vcr), (Get-Item $vcr).Length, $vs.Status, $vs.SignerCertificate.Subject.Split(",")[0], (Get-Item $vcr).VersionInfo.FileVersion)

# ── 2. python311._pth ──
Step "2. python311._pth — site-packages·앱 경로 검색 활성화"
$pth = Join-Path $PyDir "python311._pth"
@("python311.zip", ".", "Lib\site-packages", "..\app\vigent-core", "", "# embeddable default skips site; without the next line no package can be imported", "import site") |
    Set-Content -Path $pth -Encoding Ascii
Ensure-Dir (Join-Path $PyDir "Lib\site-packages")
Get-Content $pth | ForEach-Object { Write-Host "    $_" }

# ── 3. pip 부트스트랩(pypi.org JSON 으로 휠 URL·SHA 조회 → 휠 자체로 pip 설치) ──
Step "3. pip $PipVer"
if ((Quiet $Py @("-m", "pip", "--version")).code -ne 0) {
    $meta = Invoke-RestMethod -Uri "https://pypi.org/pypi/pip/$PipVer/json" -UseBasicParsing
    $w = $meta.urls | Where-Object { $_.filename -like "*.whl" } | Select-Object -First 1
    $whl = Join-Path $Cache $w.filename
    Download $w.url $whl $w.digests.sha256
    # 순수 파이썬 휠(zip) 이라 site-packages 에 풀면 곧 설치다(pip 는 자기 자신을 `python whl/pip` 로 설치하는 것을 Windows 에서 거부).
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $sp = Join-Path $PyDir "Lib\site-packages"
    $z = [IO.Compression.ZipFile]::OpenRead($whl)
    foreach ($e in $z.Entries) { if ($e.Name) { $t = Join-Path $sp $e.FullName; Ensure-Dir (Split-Path -Parent $t); [IO.Compression.ZipFileExtensions]::ExtractToFile($e, $t, $true) } }
    $z.Dispose()
    Run $Py @("-m", "pip", "install", "--no-index", "--force-reinstall", "--no-warn-script-location", "--disable-pip-version-check", $whl)   # 메타데이터·스크립트 정식 등록
} else { Write-Host "  이미 설치됨 — 유지" }
& $Py -m pip --version

# ── 4. 의존성(전부 휠만 — 컴파일 0) + opencv 정리 ──
if (-not $SkipPip) {
    Step "4. requirements.txt (+constraints.txt) 설치 — CPU torch(PyPI 기본 휠)"
    $pipCache = Join-Path $Cache "pip"
    Run $Py @("-m", "pip", "install", "-r", (Join-Path $Source "requirements.txt"), "-c", (Join-Path $Source "constraints.txt"),
              "--only-binary=:all:", "--cache-dir", $pipCache, "--no-warn-script-location", "--disable-pip-version-check")
    Write-Host "  opencv 정리: GUI 빌드 제거 → headless --no-deps 재설치(scripts/setup_env.py 와 동일)"
    $dists = ((Quiet $Py @("-m", "pip", "list", "--format=freeze")).out -split "`r?`n") | Where-Object { $_ -like "opencv-*" } | ForEach-Object { ($_ -split "==")[0] }
    $gui = $dists | Where-Object { $_ -ne "opencv-contrib-python-headless" }
    if ($gui) { Run $Py (@("-m", "pip", "uninstall", "-y") + $gui) }
    Run $Py @("-m", "pip", "install", "--force-reinstall", "--no-deps", "--cache-dir", $pipCache, "--no-warn-script-location", "--disable-pip-version-check", $Headless)
    # setup_env.verify_cv2 와 같은 기준: cv2.__version__ 은 '4.13.0'(휠 빌드번호 .92 는 배포판 메타데이터에만 있음) + GUI 빌드 항목 없음
    Run $Py @("-c", "import cv2, torch, onnxruntime, rfdetr, fastapi, rtmlib, supervision, trackers, importlib.metadata as m; assert cv2.__version__.startswith('4.13.'), cv2.__version__; assert m.version('opencv-contrib-python-headless')=='4.13.0.92'; bi=cv2.getBuildInformation(); gui=[l.strip() for l in bi.splitlines() if l.strip().startswith(('GUI','Win32 UI','QT','GTK')) and not l.strip().endswith(('NONE','NO'))]; assert not gui, gui; assert torch.__version__.startswith('$TorchVer'), torch.__version__; print('  검증 OK: cv2', cv2.__version__, '(dist 4.13.0.92, GUI 없음) · torch', torch.__version__, '(cuda 빌드:', torch.version.cuda, ') · ort', onnxruntime.__version__)")
    $ocv = ((Quiet $Py @("-m", "pip", "list", "--format=freeze")).out -split "`r?`n") | Where-Object { $_ -like "opencv-*" }
    if (@($ocv).Count -ne 1) { throw "opencv 배포판이 하나가 아니다: $ocv" }
    Write-Host "  바이트코드 사전 컴파일(USB 첫 기동 시간 단축)"
    & $Py -m compileall -q (Join-Path $PyDir "Lib\site-packages") | Out-Null
} else { Step "4. (생략 -SkipPip)" }

# ── 4b. 선택: CUDA 휠 동봉 ──
if ($Gpu) {
    # ★sm_120(RTX 50 시리즈) 지원 여부를 빌드 시점에 경고한다 — 현장에서 조용히 CPU 로
    #   떨어진 뒤에 알게 되면 늦다.
    if ($Cuda -notin @("cu128", "cu129", "cu130")) {
        Write-Host ""
        Write-Host "  ⚠ 경고: $Cuda 는 **sm_120(RTX 50 시리즈) 미지원** 입니다." -ForegroundColor Yellow
        Write-Host "    RTX 5060/5070 등에서 CUDA 커널이 없어 실패하거나 조용히 CPU 로 떨어집니다." -ForegroundColor Yellow
        Write-Host "    RTX 50 시리즈 대상이면 -Cuda cu130 을 쓰세요(기본값)." -ForegroundColor Yellow
        Write-Host ""
    }
    Step "4b. CUDA 휠($Cuda) → python\wheels_cuda\ (오프라인 교체용, --gpu 로만 사용)"
    $wc = Join-Path $PyDir "wheels_cuda"; Ensure-Dir $wc
    Run $Py @("-m", "pip", "download", "torch==$TorchVer+$Cuda", "torchvision==$TvVer+$Cuda", "--index-url", "https://download.pytorch.org/whl/$Cuda",
              "--no-deps", "--only-binary=:all:", "-d", $wc, "--disable-pip-version-check")
}

# ── 5. 앱 복사(반출 금지 제외) ──
Step "5. 앱 파일 복사 → app\ (robocopy /MIR, 제외 목록 적용)"
$xd = @(".git", ".venv", "venv", "env", "data", "logs", "runs", "footage", "datasets", "business_assets", "_archive", "audit", "reports",
        "benchmarks", "tests", "docs", "__pycache__", ".github", ".claude", ".idea", ".vscode", "weights", "bin", "scripts",
        "windows", "systemd", "academy", "results", "_sweep_cache", "vendor", "VIGENT_archive", "backup", "tools", "training", "eval", "cloud", "colab", "attribution") | ForEach-Object { $_ }
$xf = @(".env", ".env.*", "notify.yaml", "site.yaml", "*.pyc", "*.pyo", "*.pt", "*.pth", "*.onnx", "*.keras", "*.tflite", "*.h5",
        "*.mp4", "*.avi", "*.mkv", "*.mov", "*.jpg", "*.jpeg", "*.png", "*.db", "*.log", "*.jsonl", "AUDIT_REPORT.md", "CLEANUP_PLAN.md",
        "CODE_REVIEW.md", "SAFETY_REVIEW_REPORT.md", "baseline_openapi.json", "requirements-agents.txt", "requirements-train.txt",
        "requirements-optional.txt", "CLAUDE.md", "Dockerfile", "run.bat", "run.ps1", "run.sh", "pyproject.toml", "VIGENT Safety 시작.bat")
$rcArgs = @($Source, $App, "/MIR", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1", "/XJ") + @("/XD") + $xd + @("/XF") + $xf
& robocopy @rcArgs | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy 실패(exit $LASTEXITCODE)" }
# /XD 는 대상 쪽 같은 이름 폴더도 미러링에서 제외해 이전 빌드 잔재가 남는다 → 앱 루트의 제외 대상은 직접 지운다(app\data 는 실행 기록이라 보존)
foreach ($d in ($xd | Where-Object { $_ -notin @("data", "weights", "bin", "scripts", "windows", "systemd", "academy", "results", "_sweep_cache", "vendor") })) {
    $dd = Join-Path $App $d; if (Test-Path $dd) { Remove-Item $dd -Recurse -Force; Write-Host "  잔재 제거: app\$d" }
}
foreach ($f in @("Dockerfile", "run.bat", "run.ps1", "run.sh", "pyproject.toml", "VIGENT Safety 시작.bat", "CLAUDE.md", "AUDIT_REPORT.md", "CLEANUP_PLAN.md", "CODE_REVIEW.md", "SAFETY_REVIEW_REPORT.md", "baseline_openapi.json", "requirements-agents.txt", "requirements-train.txt", "requirements-optional.txt")) {
    $ff = Join-Path $App $f; if (Test-Path $ff) { Remove-Item $ff -Force; Write-Host "  잔재 제거: app\$f" }
}
foreach ($d in @("deploy\windows", "deploy\systemd", "deploy\academy")) { $dd = Join-Path $App $d; if (Test-Path $dd) { Remove-Item $dd -Recurse -Force; Write-Host "  잔재 제거: app\$d" } }
Get-ChildItem $App -Directory -Recurse -Filter "__pycache__" -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
# 예외 복구: 데모 이미지(얼굴 없음, 저장소 추적)·법령 화이트리스트(읽기 전용)·go2rtc
Ensure-Dir (Join-Path $App "vigent-core\demo_assets")
Copy-Item (Join-Path $Source "vigent-core\demo_assets\*") (Join-Path $App "vigent-core\demo_assets") -Force
Ensure-Dir (Join-Path $App "data\legal")
Copy-Item (Join-Path $Source "data\legal\statutes.yaml") (Join-Path $App "data\legal\statutes.yaml") -Force
Ensure-Dir (Join-Path $App "scripts")
Copy-Item (Join-Path $Source "scripts\offline_probe.py") (Join-Path $App "scripts\offline_probe.py") -Force
Ensure-Dir (Join-Path $App "bin")
$g2src = Join-Path $Source "bin\go2rtc.exe"; $g2dst = Join-Path $App "bin\go2rtc.exe"
if (-not (Test-Path $g2dst) -or ((Sha256 $g2dst) -ne (Sha256 $g2src))) { Copy-Item $g2src $g2dst -Force }
Write-Host "  app\ 파일 수: $((Get-ChildItem $App -Recurse -File).Count)"

# ── 6. 가중치(매니페스트 SHA256 대조) ──
Step "6. 가중치 복사·검증 → app\vigent-core\weights"
$man = Get-Content (Join-Path $Source "weights_manifest.json") -Raw -Encoding UTF8 | ConvertFrom-Json
$wsrc = Join-Path $Source "vigent-core\weights"; $wdst = Join-Path $App "vigent-core\weights"
Ensure-Dir (Join-Path $wdst "rtm_cache\hub\checkpoints")
$weightRows = @()
function Copy-Verified($rel, $wantSha, $note) {
    $s = Join-Path $wsrc $rel; $d = Join-Path $wdst $rel
    if (-not (Test-Path $s)) { throw "원본 가중치 없음: $s" }
    $ss = Sha256 $s
    if ($wantSha -and ($ss -ne $wantSha)) { throw "원본이 매니페스트 SHA 와 다름: $rel" }
    if (-not (Test-Path $d) -or ((Sha256 $d) -ne $ss)) { Copy-Item $s $d -Force }
    $ds = Sha256 $d
    if ($ds -ne $ss) { throw "복사 후 SHA 불일치: $rel" }
    $script:weightRows += [pscustomobject]@{ file = $rel; bytes = (Get-Item $d).Length; sha16 = $ds.Substring(0, 16); source = $note }
    Write-Host ("  OK {0,-70} {1,12:N0} B  {2}" -f $rel, (Get-Item $d).Length, $note)
}
foreach ($e in $man.weights) {
    if ($e.required -ne $true) { continue }
    if ($e.root_dest) { continue }                     # go2rtc 는 5 에서 처리(아래 검증)
    $rel = if ($e.slot -eq "pose") { "rtm_cache\hub\checkpoints\" + $e.file } else { $e.file }
    Copy-Verified $rel $e.sha256 "manifest required"
}
Copy-Verified "face_detection_yunet.onnx" (($man.weights | Where-Object { $_.file -eq "face_detection_yunet.onnx" }).sha256) "manifest(privacy)"
foreach ($f in @("ppe_rfdetr_v1.onnx", "forklift_rfdetr_v1.onnx", "fire_smoke_rfdetr_v1_e17.onnx")) { Copy-Verified $f $null "onnx-cpu 슬롯(매니페스트 미등재 → 원본 SHA 대조)" }
Copy-Item (Join-Path $wsrc "MANIFEST.md") (Join-Path $wdst "MANIFEST.md") -Force
# ★[2026-09-28 USB 재빌드] 프로파일 오버라이드의 to: 가 가리키는 가중치(예: academy 의 forklift_rfdetr_fk510_smoke.pth)는 manifest
#   required=false 라 위 루프에서 빠진다 — to: 줄에서 vigent-core/weights/<파일> 을 찾아 manifest SHA 로 검증 복사한다(manifest 에 없으면 실패).
if ($Profile) {
    $ovp = Join-Path $Source ("deploy\" + $Profile + "\portable_overrides." + $Profile + ".yaml")
    if (-not (Test-Path $ovp)) { throw "프로파일 오버라이드가 없다: $ovp" }
    $refs = Select-String -Path $ovp -Pattern '^\s*to:\s*.*vigent-core/weights/([\w\-\.]+\.(?:pth|onnx|pt))' -AllMatches |
            ForEach-Object { $_.Matches } | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
    foreach ($wf in @($refs)) {
        $me = $man.weights | Where-Object { $_.file -eq $wf }
        if (-not $me) { throw "프로파일 $Profile 이 가리키는 가중치가 weights_manifest.json 에 없다: $wf" }
        Copy-Verified $wf $me.sha256 ("profile:" + $Profile)
    }
    if (-not $refs) { Write-Host "  (프로파일 $Profile 은 추가 가중치를 가리키지 않음)" }
}
$g2 = ($man.weights | Where-Object { $_.file -eq "go2rtc.exe" }).sha256
if ((Sha256 (Join-Path $App "bin\go2rtc.exe")) -ne $g2) { throw "go2rtc.exe SHA 불일치" }
Write-Host "  OK bin\go2rtc.exe (manifest SHA 일치)"

# ── 7. 포터블 프로필(원본 config 불변 — 빌드 시점 tuning.yaml + overrides) ──
Step "7. deploy\portable 프로필 적용 → app\config\tuning.yaml · app\themes\safety\vision.yaml"
$ov = Join-Path $Source "deploy\portable\portable_overrides.yaml"
$ovProfile = ""
if ($Profile) {
    $ovProfile = Join-Path $Source ("deploy\" + $Profile + "\portable_overrides." + $Profile + ".yaml")
    if (-not (Test-Path $ovProfile)) { throw "프로파일 오버라이드가 없다: $ovProfile" }
    Write-Host ("  프로파일 " + $Profile + " 오버라이드 덧붙임: " + $ovProfile)
}
# overrides 항목의 file(tuning|vision, 기본 tuning)별로 원본을 읽어 치환한다. 원본(config/·themes/)은 불변, 산출물은 app\ 아래.
$prof = @"
import sys, io, os
src_root, ov, dst_root, gpu, ov_profile = sys.argv[1:6]
gpu = gpu == '1'
import yaml
o = yaml.safe_load(io.open(ov, encoding='utf-8')) or {}
if ov_profile:   # [CODE_AUDIT #3] 프로파일 오버라이드를 덧붙인다(같은 키면 프로파일이 이긴다)
    o.update(yaml.safe_load(io.open(ov_profile, encoding='utf-8')) or {})
FILES = {'tuning': ('config/tuning.yaml', 'config/tuning.yaml'), 'vision': ('themes/safety/vision.yaml', 'themes/safety/vision.yaml')}
# [I-1] -Gpu 빌드에서는 skip_when_gpu 항목을 건너뛴다(예: detect.backend).
#   GPU 에서 onnx-cpu 는 인수시험 미달이라 치환하면 안 된다 — 근거는 overrides 의 주석.
skipped = [k for k, v in o.items() if gpu and v.get('skip_when_gpu')]
applied = {}
for fkey, (rel_src, rel_dst) in FILES.items():
    items = [(k, v) for k, v in o.items()
             if (v.get('file') or 'tuning') == fkey and not (gpu and v.get('skip_when_gpu'))]
    if not items:
        continue
    t = io.open(os.path.join(src_root, rel_src), encoding='utf-8').read()
    for k, v in items:
        n = t.count(v['from'])
        assert n == 1, k + ': 원본(' + rel_src + ')에서 ' + repr(v['from']) + ' 가 ' + str(n) + '곳 (정확히 1곳이어야 함)'
        t = t.replace(v['from'], v['to'], 1)
    hdr = '# ★USB 포터블 프로필 — scripts/build_portable.ps1 이 원본 ' + rel_src + ' + deploy/portable/portable_overrides.yaml 로 생성. 직접 고치지 말 것.\n'
    dst = os.path.join(dst_root, rel_dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    io.open(dst, 'w', encoding='utf-8', newline='\n').write(hdr + t)
    applied[rel_dst] = [k for k, _ in items]
for d, ks in applied.items():
    print('  적용 ' + d + ': ' + ', '.join(ks))
for k in skipped:
    print('  [GPU 빌드] 건너뜀 ' + k + ' (skip_when_gpu)')
"@
$profPy = Join-Path $Cache "apply_profile.py"; Set-Content -Path $profPy -Value $prof -Encoding UTF8
Run $Py @($profPy, $Source, $ov, $App, $(if ($Gpu) { "1" } else { "0" }), $ovProfile)
# [I-1] 빌드 종류별로 **기대하는 backend 가 다르다** — 산출물을 열어 확인한다(설정값 믿지 않는다).
$expectBackend = if ($Gpu) { "torch" } else { "onnx-cpu" }
Run $Py @("-c", "import io,sys; t=io.open(sys.argv[1],encoding='utf-8').read(); want='backend: '+sys.argv[2]; assert want in t, '기대 '+want+' 가 산출물에 없다'; print('  확인: detect.backend = '+sys.argv[2])", (Join-Path $App "config\tuning.yaml"), $expectBackend)
if ($Profile -eq "academy") {
    Run $Py @("-c", "import io,sys,yaml; t=io.open(sys.argv[1],encoding='utf-8').read(); d=yaml.safe_load(t); erg=d['judgment']['ergonomics']; assert 'joints' not in erg and 'joints_off_portable' in erg, list(erg); print('  확인(academy): judgment.ergonomics.joints 없음(근골격 규칙 OFF, 값은 joints_off_portable 로 보존)')", (Join-Path $App "themes\safety\vision.yaml"))
} else {
    Run $Py @("-c", "import io,sys,yaml; t=io.open(sys.argv[1],encoding='utf-8').read(); d=yaml.safe_load(t); erg=d['judgment']['ergonomics']; assert 'joints' in erg, list(erg); print('  확인(기본): judgment.ergonomics.joints 유지(근골격 규칙 ON = 전역값)')", (Join-Path $App "themes\safety\vision.yaml"))
}

if ($Profile -eq "academy") {
    # ★[2026-09-28] 학원 산출물 사후 검증 — 지게차 가중치 fk510_smoke · include_forklift 1 · conf.forklift 0.50 · 가중치 파일 실재(설정값 믿지 않는다)
    Run $Py @("-c", "import io,os,sys,yaml; v=yaml.safe_load(io.open(sys.argv[1],encoding='utf-8')); t=yaml.safe_load(io.open(sys.argv[2],encoding='utf-8')); app=sys.argv[3]
def find(d,k):
    if isinstance(d,dict):
        if k in d: return d[k]
        for x in d.values():
            r=find(x,k)
            if r is not None: return r
    return None
w=find(v,'rfdetr_weights')['forklift']; assert w.endswith('forklift_rfdetr_fk510_smoke.pth'), w
assert os.path.isfile(os.path.join(app,w)), 'weight file missing: '+w
d=t['detect']; assert int(d.get('include_forklift',0))==1, d.get('include_forklift'); assert abs(float(d['conf']['forklift'])-0.5)<1e-9, d['conf']['forklift']
print('  확인(academy): forklift='+os.path.basename(w)+' 실재 · include_forklift=1 · conf.forklift=0.50')", (Join-Path $App "themes\safety\vision.yaml"), (Join-Path $App "config\tuning.yaml"), $App)
}

# ── 8. 런처·문서 ──
Step "8. 런처·사용법 → 패키지 루트"
foreach ($f in @("VIGENT_시작.bat", "VIGENT_종료.bat", "VIGENT_데이터정리.bat", "사용법.md")) { Copy-Item (Join-Path $Source "deploy\portable\$f") (Join-Path $Root $f) -Force }
Write-Host "  VIGENT_시작.bat · VIGENT_종료.bat · VIGENT_데이터정리.bat · 사용법.md"

# ── 9. 패키지 매니페스트·용량 ──
Step "9. PACKAGE_MANIFEST.md"
$files = Get-ChildItem $Root -Recurse -File -Force
$total = ($files | Measure-Object -Property Length -Sum).Sum
$top = Get-ChildItem $Root -Directory -Force | ForEach-Object { [pscustomobject]@{ dir = $_.Name; bytes = ((Get-ChildItem $_.FullName -Recurse -File -Force | Measure-Object -Property Length -Sum).Sum) } } | Sort-Object bytes -Descending
$sp = Get-ChildItem (Join-Path $PyDir "Lib\site-packages") -Directory | ForEach-Object { [pscustomobject]@{ dir = $_.Name; bytes = ((Get-ChildItem $_.FullName -Recurse -File | Measure-Object -Property Length -Sum).Sum) } } | Sort-Object bytes -Descending | Select-Object -First 10
$pyv = (& $Py -c "import sys,torch,cv2,onnxruntime,fastapi,importlib.metadata as m; print('python', sys.version.split()[0], '/ torch', torch.__version__, '/ cv2', cv2.__version__, '(dist', m.version('opencv-contrib-python-headless') + ')', '/ onnxruntime', onnxruntime.__version__, '/ rfdetr', m.version('rfdetr'), '/ fastapi', fastapi.__version__, '/ pip', m.version('pip'))")
$srcCommit = ((Quiet "git" @("-C", $Source, "rev-parse", "--short", "HEAD")).out).Trim()
$md = @()
$md += "# VIGENT USB 포터블 패키지 — 내용물 목록"
$md += ""
$md += "빌드: $(Get-Date -Format 'yyyy-MM-dd HH:mm') · 원본 $Source (git $srcCommit) · scripts/build_portable.ps1"
$md += ""
$md += "**총 용량(빌드 직후): {0:N2} GB · 파일 {1:N0}개**" -f ($total / 1GB), $files.Count
# ── [I-5] --gpu 교체 후 **최종** 용량 산정 ──────────────────────────────────────────────
# ★왜: 예전엔 이 줄 하나만 찍어서 그 값을 "패키지 용량" 으로 보고했는데, 그건 **교체 전** 값이다.
#   --gpu 를 하면 (1) CUDA torch 가 설치돼 site-packages 가 커지고 (2) wheels_cuda 는
#   런처가 지운다. 2026-09-23 에 4.23GB 로 보고한 패키지의 실제 배포 상태는 6.49GB 였다.
#   → 빌드 시점에 **둘 다** 계산해 적는다. 추정이 아니라 휠 안의 실제 크기로 계산한다.
$whDir = Join-Path $PyDir "wheels_cuda"
if (Test-Path $whDir) {
    $whBytes = (Get-ChildItem $whDir -Recurse -File | Measure-Object -Property Length -Sum).Sum
    # 휠(zip) 안의 압축 해제 크기 합 = 설치 후 대략 크기. 추측 대신 zip 목차를 읽는다.
    $unzipPy = @"
import sys, zipfile, glob, os
tot = 0
for w in glob.glob(os.path.join(sys.argv[1], '*.whl')):
    with zipfile.ZipFile(w) as z:
        tot += sum(i.file_size for i in z.infolist())
print(tot)
"@
    $uzp = Join-Path $Cache "unzip_size.py"; Set-Content -Path $uzp -Value $unzipPy -Encoding UTF8
    $instBytes = [double]((Quiet $Py @($uzp, $whDir)).out.Trim())
    # 교체 대상(현 CPU torch/torchvision)은 지워지고 그 자리에 CUDA 판이 들어간다
    $oldTorch = 0
    foreach ($d in @("torch", "torchvision")) {
        $p = Join-Path $PyDir "Lib\site-packages\$d"
        if (Test-Path $p) { $oldTorch += (Get-ChildItem $p -Recurse -File | Measure-Object -Property Length -Sum).Sum }
    }
    $final = $total - $whBytes - $oldTorch + $instBytes
    $md += ""
    $md += "**★--gpu 교체 후 최종 용량(예상): {0:N2} GB**" -f ($final / 1GB)
    $md += ""
    $md += "| 구간 | 용량 |"
    $md += "|---|---|"
    $md += "| 빌드 직후(이 패키지 그대로) | {0:N2} GB |" -f ($total / 1GB)
    $md += "| `python\wheels_cuda\`(교체 후 런처가 삭제) | −{0:N2} GB |" -f ($whBytes / 1GB)
    $md += "| CPU torch/torchvision(교체로 대체됨) | −{0:N2} GB |" -f ($oldTorch / 1GB)
    $md += "| CUDA torch/torchvision 설치분 | +{0:N2} GB |" -f ($instBytes / 1GB)
    $md += "| **= --gpu 후 최종** | **{0:N2} GB** |" -f ($final / 1GB)
    $md += ""
    $md += "★위 '최종' 은 휠 안의 파일 크기 합으로 계산한 값이다. 실제 교체 후 측정값이 아니다."
    Write-Host ("  --gpu 교체 후 최종 예상: {0:N2} GB (휠 {1:N2} GB 는 교체 후 런처가 삭제)" -f ($final / 1GB), ($whBytes / 1GB))
}
$md += ""
$md += "구성: $pyv"
$md += ""
$md += "## 상위 폴더 용량"; $md += ""; $md += "| 폴더 | 용량 |"; $md += "|---|---:|"
foreach ($r in $top) { $md += ("| {0} | {1:N1} MB |" -f $r.dir, ($r.bytes / 1MB)) }
$md += ""; $md += "## site-packages 상위 10"; $md += ""; $md += "| 패키지 | 용량 |"; $md += "|---|---:|"
foreach ($r in $sp) { $md += ("| {0} | {1:N1} MB |" -f $r.dir, ($r.bytes / 1MB)) }
$md += ""; $md += "## 동봉 가중치(SHA256 대조 완료)"; $md += ""; $md += "| 파일 | 바이트 | sha256(16) | 근거 |"; $md += "|---|---:|---|---|"
foreach ($r in $weightRows) { $md += ("| {0} | {1:N0} | {2} | {3} |" -f $r.file, $r.bytes, $r.sha16, $r.source) }
$md += ""
$md += "## 넣은 것"
$md += "- python\ : Windows embeddable Python $PyVer (python.org, MD5 게시값 일치) + pip $PipVer + requirements.txt 전체(CPU torch, opencv headless 4.13.0.92)"
$md += "- vc_redist.x64.exe : Microsoft Visual C++ 2015-2022 재배포 패키지(x64) v$((Get-Item $vcr).VersionInfo.FileVersion), Authenticode $($vs.Status) — torch/onnxruntime 이 msvcp140.dll 을 시스템에서 찾으므로 없는 PC 에서 설치(런처가 안내)"
$md += "- VIGENT_데이터정리.bat : 현장 사용 후 app\data(증거 사진·인식 기록)·state\logs 삭제. 기본은 카메라 등록 보존, --all 은 전부"
$md += "- app\vigent-core\ : 서버 코드·정적 파일·demo_assets(저장소 추적 데모 이미지 3장) · app\themes\ · app\config\(tuning.yaml = 포터블 프로필, notify.example.yaml, security.json) · app\bin\go2rtc.exe · app\deploy\portable\ · app\data\legal\statutes.yaml(법령 화이트리스트, 읽기 전용) · app\scripts\offline_probe.py · README.md·md\·VERSION·weights_manifest.json·requirements.txt·constraints.txt"
$md += "- state\ : 실행 중 생기는 기록(logs). ※ data\(증거·인식 로그·카메라 등록)는 코드가 app\data 를 고정 사용 — 아래 '뺀 것' 참고"
$md += "- 가중치: 위 표(필수 .pth 4 + onnx-cpu 슬롯 .onnx 3 + RTMPose 2 + YuNet 1). rf-detr-nano.pth 동봉 → 기동 시 인터넷 다운로드 없음(RF_HOME 고정)"
$md += ""
$md += "## 뺀 것(반출 금지·불필요)"
$md += "- .git/ .venv/ footage/ data/(statutes.yaml 제외) runs/ logs/ datasets/ business_assets/ _archive/ audit/ reports/ benchmarks/ tests/ docs/ deploy\windows(nssm·서비스) deploy\academy deploy\systemd"
$md += "- .env, .env.*, config\notify.yaml(실제 토큰), config\site.yaml, 모든 *.pt(YOLO)·MEASURE_ONLY.onnx·영상·이미지·*.db·*.log·*.jsonl"
$md += "- 원본 저장소의 개발용 문서(AUDIT_REPORT·CLEANUP_PLAN·CODE_REVIEW·SAFETY_REVIEW_REPORT·CLAUDE.md)"
$md += "- CUDA torch 휠: 기본 미포함. build_portable.ps1 -Gpu 로 받으면 python\wheels_cuda\ 에 들어가고 VIGENT_시작.bat --gpu 로만 쓴다"
$md += ""
$md += "## 쓰기 경로"
$md += "- 로그: state\logs (VIGENT_LOG_DIR) · 증거·인식·카메라 등록·경보 큐: app\data (코드 13개 모듈이 <앱루트>\data 고정 — 환경변수 없음, 원본 수정 0 으로 두기 위해 그대로 둠. USB 안이므로 대상 PC 에는 남지 않는다)"
$md -join "`n" | Set-Content -Path (Join-Path $Root "PACKAGE_MANIFEST.md") -Encoding UTF8
Write-Host ("  총 {0:N2} GB · {1:N0} 파일" -f ($total / 1GB), $files.Count)
$top | ForEach-Object { Write-Host ("    {0,-10} {1,9:N1} MB" -f $_.dir, ($_.bytes / 1MB)) }
Write-Host "`n완료: $Root" -ForegroundColor Green
