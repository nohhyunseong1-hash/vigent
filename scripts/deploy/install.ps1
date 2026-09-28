# install.ps1 - USB 설치기 1차 본체. [USB 1차 계획 2 + 승인 항목 3(멱등·업데이트) + 항목 4(GPU 기본)]
#
#   설치.bat 이 관리자 권한으로 부른다:  install.ps1 -UsbRoot <USB> [-Target C:\VIGENT] [-DryRun] [-NoService] [-Port 8010]
#
#   1. USB 레이아웃 검증(usb_layout.py verify) - 미달이면 시작 안 함
#   2. preflight.ps1 - 사양 미달이면 시작 안 함(한 줄씩 전부 출력)
#   3. 기존 설치가 있으면 **업데이트 경로**(항목 3):
#        · 서비스 중지
#        · <Target> 을 통째로 <Target>_prev_<이전버전> 으로 옮긴다(1세대만 보관 - 더 오래된 _prev 는 지운다)
#        · 새 portable 복사 후 이전의 app\data\ · app\config\ · app\.env 를 **되가져온다**
#          (data/camera_secrets.json·config/notify.yaml 이 그 안에 있다 - 비밀·현장 설정은 USB 에 없다)
#        · 새로 실린 config\ 는 app\config.new\ 에 두어 사람이 차이를 볼 수 있게 한다(자동 병합 안 함)
#      없으면 **첫 설치 경로**: 복사 + app\.env 토큰 생성(VIGENT_REQUIRE_TOKEN=1 서비스 게이트용)
#   4. CUDA 휠 오프라인 교체(런처의 :gpu_switch 와 같은 명령) → torch.cuda 확인 → wheels_cuda 삭제(I-5)
#   5. NSSM 서비스 등록 - 기존 deploy\windows\install_service.ps1 을 -Root/-PythonExe/-ExtraEnv 로 재사용
#   6. install_report_<시각>.json 을 **기기**에 기록(USB 아님). 인수시험(계획 5)이 이어서 채운다.
#
#   -DryRun : 파일 복사·서비스·휠 교체를 하지 않고 무엇을 할지 단계별로 찍는다(재설치 판정 포함). 관리자 불필요.
#   ★멱등: 같은 USB 로 두 번 돌리면 두 번째는 업데이트 경로를 타고, 결과 폴더는 같다.
#   ★삭제 범위: <Target>_prev_* 중 가장 최근 하나만 남기고 지운다. 그 밖의 어떤 폴더도 지우지 않는다.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$UsbRoot,
    [string]$Target = "C:\VIGENT",
    [int]$Port = 8010,
    [string]$Bind = "0.0.0.0",
    [switch]$DryRun,
    [switch]$NoService,                  # 시험용: 서비스 등록 생략(개발기 임시 설치)
    [switch]$SkipPreflight               # 시험용: 이미 통과한 기기에서 반복할 때
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$T0 = Get-Date
$Stamp = $T0.ToString("yyyyMMdd_HHmm")
$Report = [ordered]@{ installed_at = $T0.ToString("s"); usb_root = $UsbRoot; target = $Target; dry_run = [bool]$DryRun;
                      mode = $null; version_tag = $null; prev_version = $null; steps = @(); result = $null }
function Step($m) { Write-Host "`n== $m ==" -ForegroundColor Cyan; $script:Report.steps += $m }
function Fail($m) { Write-Host "✗ $m" -ForegroundColor Red; $script:Report.result = "미완료: $m"; Write-Report; exit 1 }
function Act($m) { if ($DryRun) { Write-Host "  [DRY] $m" -ForegroundColor DarkGray } else { Write-Host "  $m" } }
# ★[2026-09-28 실기 결함 #3 → 회귀 수정] 업데이트 모드 "사용 중" 검사. 처음 판은 <Target> 아래 실행 파일을 쓰는 프로세스를 전부 잡아
#   서비스 자신의 nssm.exe·go2rtc.exe 까지 걸려 **서비스가 살아 있으면 항상 exit 1**(현장 업데이트 불가)이었다(실기 재검증에서 발견).
#   이제 VIGENT 서비스 PID(nssm)에서 내려가는 프로세스 트리(service_entry python·go2rtc 등)는 "서비스 소유" 로 제외하고,
#   그 밖의 점유(탐색기·편집기·다른 셸이 띄운 exe)와 현재 셸 위치만 본다. 순수 함수라 tests/test_field_fixes_20260928 이 가짜 목록으로 검사한다.
function Get-ExternalBusyProcesses([string]$Target, [object[]]$Procs, [int]$ServicePid, [string]$Cwd) {
    $tgt = $Target.TrimEnd('\').ToLower()
    $owned = New-Object 'System.Collections.Generic.HashSet[int]'
    if ($ServicePid -gt 0) {
        [void]$owned.Add($ServicePid); $changed = $true
        while ($changed) {
            $changed = $false
            foreach ($pr in $Procs) {
                $cid = [int]$pr.ProcessId; $ppid = [int]$pr.ParentProcessId
                if (-not $owned.Contains($cid) -and $owned.Contains($ppid)) { [void]$owned.Add($cid); $changed = $true }
            }
        }
    }
    $busy = @($Procs | Where-Object {
        $_.ExecutablePath -and $_.ExecutablePath.ToLower().StartsWith($tgt + '\') -and -not $owned.Contains([int]$_.ProcessId) })
    return @{ cwd_inside = [bool]($Cwd -and $Cwd.ToLower().StartsWith($tgt)); busy = $busy; owned_count = $owned.Count }
}
function Write-Report {
    # ★아무것도 복사하기 전에 실패(레이아웃·사양 미달)하면 보고서를 <Target> 에 쓰지 않는다 — 그러면 빈 껍데기 설치 폴더가
    #   생겨 다음 실행이 "기존 설치" 로 오인하거나(2026-09-23 실측: 사양 미달 뒤 C:\VIGENT\app\data 만 남았다) 제거 대상이 된다.
    $installed = (-not $DryRun) -and (Test-Path (Join-Path $Target "app\vigent-core"))
    $dir = if ($DryRun) { Join-Path $env:TEMP "vigent_install_dryrun" } elseif ($installed) { Join-Path $Target "app\data" } else { Join-Path $env:TEMP "vigent_install_failed" }
    try { New-Item -ItemType Directory -Force $dir | Out-Null
          $p = Join-Path $dir "install_report_$Stamp.json"
          # ★BOM 없이 쓴다. PS 5.1 의 Out-File -Encoding utf8 은 BOM 을 붙여 인수시험(json.loads)이 죽었다(2026-09-23 실설치).
          [IO.File]::WriteAllText($p, ($script:Report | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding $false))
          Write-Host "  보고서: $p" } catch { Write-Host "  보고서 기록 실패: $($_.Exception.Message)" -ForegroundColor Yellow }
}
$Inst = Join-Path $UsbRoot "installer"
$UsbPy = Join-Path $UsbRoot "portable\python\python.exe"
$UsbPortable = Join-Path $UsbRoot "portable"

# ── 0. 관리자 — 서비스를 등록할 때만 필수(-NoService 실설치는 사용자 권한으로 가능: 개발기 임시 설치용) ──
if (-not $DryRun -and -not $NoService) {
    $isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) { Fail "관리자 권한이 필요합니다(설치.bat 을 관리자 권한으로 실행). 서비스 없이 시험만 하려면 -NoService" }
}

# ── 1. USB 레이아웃 ──
Step "1. USB 레이아웃 검증"
if (-not (Test-Path $UsbPy)) { Fail "USB 에 portable\python\python.exe 가 없다: $UsbRoot" }
& $UsbPy (Join-Path $Inst "usb_layout.py") verify $UsbRoot
if ($LASTEXITCODE -ne 0) { Fail "USB 레이아웃 미달" }
$verTxt = Get-Content (Join-Path $UsbRoot "VERSION.txt") -Raw
$Report.version_tag = ([regex]::Match($verTxt, "태그\s*:\s*(\S+)")).Groups[1].Value
Write-Host "  버전: $($Report.version_tag)"

# ── 2. 사양 검사 ──
Step "2. 사양 검사(preflight)"
if ($SkipPreflight) { Write-Host "  건너뜀(-SkipPreflight)" -ForegroundColor Yellow }
else {
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Inst "preflight.ps1") -InstallPath $Target -JsonOut (Join-Path $env:TEMP "vigent_preflight_$Stamp.json")
    if ($LASTEXITCODE -ne 0) { Fail "사양 미달 - 위 [미달] 항목을 해결한 뒤 다시 실행" }
    $Report.preflight = Join-Path $env:TEMP "vigent_preflight_$Stamp.json"
}

# ── 3. 첫 설치 / 업데이트 판정 ──
Step "3. 설치 경로 판정"
$App = Join-Path $Target "app"
$existing = Test-Path (Join-Path $App "vigent-core\main.py")
$prevVer = $null
if ($existing) {
    $pv = Join-Path $Target "VERSION.txt"
    if (Test-Path $pv) { $prevVer = ([regex]::Match((Get-Content $pv -Raw), "태그\s*:\s*(\S+)")).Groups[1].Value }
    if (-not $prevVer) { $prevVer = "unknown_$Stamp" }
    $Report.mode = "update"; $Report.prev_version = $prevVer
    Write-Host "  기존 설치 발견 → 업데이트 (이전 $prevVer → $($Report.version_tag))"
} else { $Report.mode = "fresh"; Write-Host "  기존 설치 없음 → 첫 설치" }

$svcName = "VIGENT"
$svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue
$svcWasRunning = [bool]($svc -and $svc.Status -ne "Stopped")
# ★[2026-09-28 실기 결함 #3] 업데이트 모드에서 <Target> 을 옮기는 Move-Item 이 "사용 중" 으로 실패하면 서비스만 멈춘 채 끝났다.
#   ① 서비스를 멈추기 **전에** <Target> 아래에서 도는 프로세스(서비스 파이썬 제외)·현재 셸 위치를 검사해 미리 안내한다.
if ($existing -and -not $DryRun) {
    # 순서: 외부 점유 검사(서비스 소유 트리 제외) → 서비스 중지 → 이동 → 실패 시 Start-Service 복구
    $svcPid = 0
    try { $svcPid = [int](Get-CimInstance Win32_Service -Filter "Name='$svcName'" -ErrorAction Stop).ProcessId } catch { $svcPid = 0 }
    $chk = Get-ExternalBusyProcesses -Target $Target -Procs @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue) -ServicePid $svcPid -Cwd $PWD.Path
    if ($chk.cwd_inside) { Fail "현재 셸 위치가 설치 폴더 안이다($($PWD.Path)) — 다른 폴더로 이동한 뒤 다시 실행(서비스는 아직 멈추지 않았다)" }
    if ($chk.busy.Count -gt 0) {
        $list = ($chk.busy | ForEach-Object { "$($_.ProcessId) $($_.Name)" }) -join ", "
        Fail "설치 폴더 안의 실행 파일을 쓰는 외부 프로세스가 있어 폴더를 옮길 수 없다: $list — 종료(또는 탐색기·셸 닫기) 후 다시 실행(서비스는 아직 멈추지 않았다)"
    }
    Write-Host ("  사용 중 검사 통과 (서비스 소유 프로세스 " + $chk.owned_count + "개 제외)")
}
if ($svcWasRunning) { Act "서비스 $svcName 중지"; if (-not $DryRun) { Stop-Service $svcName -Force; Start-Sleep -Seconds 3 } }

$Prev = "${Target}_prev_$($prevVer -replace '[^\w\.\-]', '_')"
if ($existing) {
    # 이전 세대 정리: _prev_* 중 가장 최근 1개만 남긴다(★그 외 어떤 경로도 지우지 않는다)
    $olds = Get-ChildItem (Split-Path $Target -Parent) -Directory -Filter ((Split-Path $Target -Leaf) + "_prev_*") -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    foreach ($o in $olds) { Act "이전 세대 보관본 제거(1세대만 보관): $($o.FullName)"; if (-not $DryRun) { Remove-Item -LiteralPath $o.FullName -Recurse -Force } }
    Act "현재 설치 → 보관: $Target → $Prev"
    if (-not $DryRun) {
        try { Move-Item -LiteralPath $Target -Destination $Prev -Force -ErrorAction Stop }
        catch {
            # ② 그래도 실패(열린 핸들 등)하면 멈춘 서비스를 되살리고 끝낸다 — 설치 전 상태 그대로 두는 것이 "서비스 죽은 채 방치" 보다 낫다
            $why = $_.Exception.Message
            if ($svcWasRunning) { try { Start-Service $svcName; Write-Host "  서비스 $svcName 다시 시작(설치 중단)" } catch { Write-Host "  ★서비스 재시작 실패: $($_.Exception.Message)" -ForegroundColor Red } }
            Fail "설치 폴더를 옮기지 못했다($why) — 폴더를 연 탐색기·셸·편집기를 닫고 다시 실행(서비스는 되살렸다)"
        }
    }
}

# ── 4. 복사 ──
Step "4. portable 복사 → $Target"
Act "robocopy $UsbPortable → $Target (state·app\data 는 USB 에 없다)"
if (-not $DryRun) {
    New-Item -ItemType Directory -Force $Target | Out-Null
    & robocopy $UsbPortable $Target /E /NFL /NDL /NJH /NP /MT:16 | Out-Null
    if ($LASTEXITCODE -ge 8) { Fail "robocopy 실패(exit $LASTEXITCODE)" }
    Copy-Item (Join-Path $UsbRoot "VERSION.txt") (Join-Path $Target "VERSION.txt") -Force
    Copy-Item (Join-Path $UsbRoot "usb_manifest.json") (Join-Path $Target "usb_manifest.json") -Force
    # 서비스 런처(service_entry.py)·nssm 은 포터블 빌드가 잘라내는 deploy\windows 에 있다 - USB installer\ 에서 채운다
    $dw = Join-Path $App "deploy\windows"; New-Item -ItemType Directory -Force $dw | Out-Null
    foreach ($f in @("service_entry.py", "nssm.exe", "install_service.ps1", "uninstall_service.ps1", "service_status.ps1")) {
        $s = Join-Path $Inst "windows\$f"; if (Test-Path $s) { Copy-Item $s (Join-Path $dw $f) -Force } }
    foreach ($d in @("app\data", "app\logs", "state\logs", "state\data")) { New-Item -ItemType Directory -Force (Join-Path $Target $d) | Out-Null }
    # 계획 3: 첫 실행 마법사를 기기에 둔다(앱 뿌리 = parents[2] = <Target>\app 이라 vigent-core 모듈을 그대로 쓴다)
    $wd = Join-Path $App "scripts\deploy"; New-Item -ItemType Directory -Force $wd | Out-Null
    foreach ($f in @("setup_wizard.py", "acceptance_test.py")) {   # 계획 3·5: 마법사·인수시험을 기기에 둔다
        $s = Join-Path $Inst $f; if (Test-Path $s) { Copy-Item $s (Join-Path $wd $f) -Force } }
}

# ── 5. 기기 상태 되가져오기 / 첫 설치 초기화 ──
Step "5. 기기 상태(데이터·설정·비밀) $(if ($existing) { '되가져오기' } else { '초기화' })"
if ($existing) {
    $keep = @("app\data", "app\config", "app\.env", "state")
    # DryRun 은 Move-Item 을 안 했으므로 '이전 설치' 는 아직 $Target 에 있다 — 거기서 읽어야 목록이 찍힌다
    $srcBase = if ($DryRun) { $Target } else { $Prev }
    foreach ($k in $keep) {
        $src = Join-Path $srcBase $k; if (-not (Test-Path $src)) { continue }
        $dst = Join-Path $Target $k
        if ($k -eq "app\config") {
            Act "새 config 는 app\config.new 로, 이전 config 를 app\config 로 (자동 병합 안 함 - 사람이 차이를 본다)"
            if (-not $DryRun) { if (Test-Path $dst) { Move-Item -LiteralPath $dst -Destination (Join-Path $App "config.new") -Force }
                                Copy-Item -LiteralPath $src -Destination $dst -Recurse -Force }
        } else {
            Act "보존: $k"
            if (-not $DryRun) { if ((Get-Item $src).PSIsContainer) { & robocopy $src $dst /E /NFL /NDL /NJH /NP | Out-Null } else { Copy-Item -LiteralPath $src -Destination $dst -Force } }
        }
    }
} else {
    $envFile = Join-Path $App ".env"
    Act "app\.env 생성(VIGENT_API_TOKEN 무작위 64자 - 서비스 보안 게이트용, 값은 출력하지 않는다)"
    if (-not $DryRun) {
        if (-not (Test-Path $envFile)) {
            $tok = -join ((1..64) | ForEach-Object { "0123456789abcdef"[(Get-Random -Maximum 16)] })
            "VIGENT_API_TOKEN=$tok`n" | Out-File -FilePath $envFile -Encoding ascii -NoNewline
            # ★설치한 사용자도 읽어야 한다 — 런처(VIGENT_시작.bat)는 그 사용자로 서버를 띄운다. 2026-09-23 실설치에서
            #   Administrators·SYSTEM 만 주자 dotenv 가 PermissionError 로 죽었다(서비스=LocalSystem 은 됐을 것이지만 런처가 안 됐다).
            #   R(읽기)만 주면 그 사용자가 자기 설치를 **지우지 못한다** — 2026-09-23 제거 시험이 "Access denied" 로 실패했다. M(수정)으로.
            & icacls $envFile /inheritance:r /grant:r "Administrators:F" "SYSTEM:F" "$($env:USERDOMAIN)\$($env:USERNAME):M" | Out-Null
        }
    }
    Act "config\notify.yaml · data\camera_secrets.json 은 마법사(계획 3)가 만든다 - 지금은 없음이 정상"
}

# ── 6. CUDA 휠 오프라인 교체(항목 4: GPU 빌드는 GPU 가 기본) ──
Step "6. CUDA 휠 교체(오프라인) → cuda 확인 → wheels_cuda 삭제"
$Py = Join-Path $Target "python\python.exe"
$wc = Join-Path $Target "python\wheels_cuda"
if ($DryRun) { Act "pip install --no-index --no-deps --force-reinstall wheels_cuda\torch-*.whl · torchvision-*.whl → cuda:True 확인 → wheels_cuda 삭제" }
else {
    $torchWhl = Get-ChildItem $wc -Filter "torch-*.whl" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($torchWhl) {
        foreach ($w in (Get-ChildItem $wc -Filter "*.whl")) { & $Py -m pip install --no-index --no-deps --force-reinstall --no-warn-script-location $w.FullName | Select-Object -Last 1 }
        & $Py -c "import sys,torch; print('  torch', torch.__version__, 'cuda', torch.cuda.is_available()); sys.exit(0 if torch.cuda.is_available() else 1)"
        if ($LASTEXITCODE -ne 0) { Fail "CUDA 휠을 설치했지만 torch.cuda.is_available() 가 False - 드라이버(≥580)·GPU 를 확인. wheels_cuda 는 남겨 둔다" }
        Remove-Item -LiteralPath $wc -Recurse -Force; Write-Host "  wheels_cuda 삭제(I-5)"
    } else {
        & $Py -c "import sys,torch; print('  torch', torch.__version__, 'cuda', torch.cuda.is_available()); sys.exit(0 if torch.cuda.is_available() else 1)"
        if ($LASTEXITCODE -ne 0) { Fail "wheels_cuda 도 없고 torch.cuda 도 False - 이 USB 는 GPU 빌드가 아니거나 GPU 를 못 쓴다" }
    }
}

# ── 7. 서비스 ──
Step "7. NSSM 서비스 등록(install_service.ps1 재사용, 포터블 경로)"
$extra = @("VIGENT_PORTABLE=1", "VIGENT_EXPECT_GPU=1", "VIGENT_LOG_DIR=$(Join-Path $Target 'state\logs')", "PYTHONNOUSERSITE=1")
if ($NoService) { Write-Host "  건너뜀(-NoService)" -ForegroundColor Yellow }
elseif ($DryRun) { Act "install_service.ps1 -Root $App -PythonExe $Py -Bind $Bind -Port $Port -ExtraEnv $($extra -join ',')" }
else {
    $isv = Join-Path $App "deploy\windows\install_service.ps1"
    if (-not (Test-Path $isv)) { Fail "install_service.ps1 이 없다: $isv (USB installer\windows\ 확인)" }
    # ★[CODE_AUDIT_20260928 #5] 외부 바인드(0.0.0.0 등)면 app\.env 의 VIGENT_API_TOKEN 이 있어야 한다 — 없으면 무인증 노출이므로 등록하지 않는다.
    if ($Bind -ne "127.0.0.1" -and $Bind -ne "localhost") {
        $envCheck = Join-Path $App ".env"
        $hasTok = (Test-Path $envCheck) -and (Select-String -Path $envCheck -Pattern '^VIGENT_API_TOKEN=\S{16,}' -Quiet)
        if (-not $hasTok) { Fail "외부 바인드($Bind)에는 VIGENT_API_TOKEN 이 필수인데 app\.env 에 없다 — 토큰 생성 단계 확인" }
        Write-Host "  외부 바인드 $Bind — app\.env 토큰 확인(값은 출력하지 않음)"
    }
    # ★[CODE_AUDIT_20260928 #5] 예전 `& powershell -File $isv ... -ExtraEnv $extra` 는 배열을 문자열로 풀어 첫 값만 바인딩되고
    #   나머지가 위치 인자(ServiceName·LogMaxBytes)로 흘러갈 수 있었다(실기 미검증). 같은 세션에서 직접 호출해 배열을 그대로 넘긴다.
    & $isv -Root $App -PythonExe $Py -Bind $Bind -Port $Port -ExtraEnv $extra
    if ($LASTEXITCODE -ne 0) { Fail "서비스 등록 실패" }
}

# ★[CODE_AUDIT_20260928 #5] 설치 결과(Target·Port·Bind)를 고정 위치에 남긴다 — 설치.bat(마법사·인수시험 경로)과 acceptance_test.py 가 읽는다.
#   예전엔 설치.bat 이 C:\VIGENT 를, 인수시험이 8010 을 각자 고정해 -Target/-Port 를 바꾸면 엉뚱한 곳을 봤다.
if (-not $DryRun) {
    $resObj = [ordered]@{ target = $Target; app = $App; python = $Py; port = $Port; bind = $Bind; installed_at = $T0.ToString("s"); mode = $Report.mode }
    $resDir = Join-Path $App "data"; New-Item -ItemType Directory -Force $resDir | Out-Null
    [IO.File]::WriteAllText((Join-Path $resDir "install_result.json"), ($resObj | ConvertTo-Json -Depth 3), (New-Object Text.UTF8Encoding $false))
    $resEnv = "TARGET=$Target`r`nAPP=$App`r`nPYTHON=$Py`r`nPORT=$Port`r`nBIND=$Bind`r`n"
    [IO.File]::WriteAllText((Join-Path $env:TEMP "vigent_install_result.env"), $resEnv, (New-Object Text.UTF8Encoding $false))
    Write-Host ("  설치 결과 기록: " + (Join-Path $resDir "install_result.json") + " · " + (Join-Path $env:TEMP "vigent_install_result.env"))
}

$Report.result = "완료(인수시험 전)"
Step "8. 완료"
Write-Host ("  {0} · {1} · {2:N1}분" -f $Report.mode, $Report.version_tag, ((Get-Date) - $T0).TotalMinutes)
if ($Report.mode -eq "fresh") {
    Write-Host "  다음: 첫 실행 마법사(카메라·텔레그램·이메일·필수 보호구) — 설치.bat 이 이어서 띄운다. 직접 띄우려면:"
    Write-Host ("    `"{0}`" `"{1}`"" -f $Py, (Join-Path $App "scripts\deploy\setup_wizard.py"))
} else { Write-Host "  업데이트라 기존 설정을 그대로 썼다. 마법사는 필요할 때만 다시 실행한다." }
Write-Report
exit 0
