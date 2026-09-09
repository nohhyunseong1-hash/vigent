# scripts/build_portable.ps1 — VIGENT USB 포터블 패키지 빌드 (Windows PowerShell 5.1 이상)
#
#   .\scripts\build_portable.ps1                        # D:\vigent_portable 에 빌드(캐시 D:\vigent_portable_cache)
#   .\scripts\build_portable.ps1 -Gpu -Cuda cu126       # + python\wheels_cuda\ 에 CUDA torch 휠 동봉(선택, 2.5GB+)
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
    [string]$Cuda = "cu126",
    [switch]$SkipPip            # 패키지 설치 단계 생략(앱·가중치·런처만 다시 복사할 때)
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
    & $exe @argv
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
$g2 = ($man.weights | Where-Object { $_.file -eq "go2rtc.exe" }).sha256
if ((Sha256 (Join-Path $App "bin\go2rtc.exe")) -ne $g2) { throw "go2rtc.exe SHA 불일치" }
Write-Host "  OK bin\go2rtc.exe (manifest SHA 일치)"

# ── 7. 포터블 프로필(원본 config 불변 — 빌드 시점 tuning.yaml + overrides) ──
Step "7. deploy\portable 프로필 적용 → app\config\tuning.yaml"
$ov = Join-Path $Source "deploy\portable\portable_overrides.yaml"
$prof = @"
import re, sys, io
src, ov, dst = sys.argv[1:4]
t = io.open(src, encoding='utf-8').read()
import yaml
o = yaml.safe_load(io.open(ov, encoding='utf-8'))
for k, v in o.items():
    n = t.count(v['from'])
    assert n == 1, f'{k}: 원본에서 {v["from"]!r} 가 {n}곳 (정확히 1곳이어야 함)'
    t = t.replace(v['from'], v['to'], 1)
hdr = '# ★USB 포터블 프로필 — scripts/build_portable.ps1 이 원본 config/tuning.yaml + deploy/portable/portable_overrides.yaml 로 생성. 직접 고치지 말 것.\n'
io.open(dst, 'w', encoding='utf-8', newline='\n').write(hdr + t)
print('  적용:', ', '.join(o.keys()))
"@
$profPy = Join-Path $Cache "apply_profile.py"; Set-Content -Path $profPy -Value $prof -Encoding UTF8
Run $Py @($profPy, (Join-Path $Source "config\tuning.yaml"), $ov, (Join-Path $App "config\tuning.yaml"))
Run $Py @("-c", "import io,sys; t=io.open(sys.argv[1],encoding='utf-8').read(); assert 'backend: onnx-cpu' in t; print('  확인: detect.backend = onnx-cpu')", (Join-Path $App "config\tuning.yaml"))

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
$md += "**총 용량: {0:N2} GB · 파일 {1:N0}개**" -f ($total / 1GB), $files.Count
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
