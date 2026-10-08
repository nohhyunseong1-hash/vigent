# gate.ps1 - 로컬 품질 게이트 (CLAUDE.md "코드 품질 게이트" 와 CI 스텝을 그대로 순서대로 돈다)
#
#   1. ruff check  vigent-core tests   ← CI 와 동일 범위(청정 표면), 자동수정 없음
#   2. ruff --fix  **이번 변경 파일에만**  ← ★범위를 좁힌 이유는 아래
#   3. unittest 전체
#   4. OpenAPI 무변경 체커
#   하나라도 실패하면 그 자리에서 멈춘다(종료코드 1).
#
# ★왜 --fix 범위를 좁히는가 (2026-09-23 실제 사고)
#   게이트 재실행 전에 `ruff check scripts --fix` 를 디렉터리 전체에 돌렸더니, 이번 작업과
#   무관한 scripts/capacity_probe.py 에 빈 줄 1개가 들어갔다. 동작 무관이었지만 "내가 손대지 않은
#   파일이 바뀐" 상태로 커밋 직전까지 갔다. --fix 는 **git 이 변경으로 보는 파일**에만 건다.
#   (.pre-commit-config.yaml 의 ruff --fix 훅도 같은 원칙 — 스테이지된 파일만. 여기는 pre-commit
#    없이도 같은 범위를 지키는 로컬 판이다.)
#
# 사용:  powershell -ExecutionPolicy Bypass -File scripts\gate.ps1
#        ... -NoTests   (측정 중 CPU 를 안 먹게 unittest 만 건너뜀 - 커밋 전에는 반드시 전체로)
param([switch]$NoTests)
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Definition)
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { $py = "python" }

function Fail($msg) { Write-Host "✗ $msg" -ForegroundColor Red; exit 1 }

# ★[2026-10-08 새 환경 점검] ruff·mypy 는 .venv 의 것(requirements-dev.txt 핀 = CI)을 쓴다. 예전엔 PATH 의 전역 ruff(버전 불일치)를 썼고,
#   새 clone 에는 ruff 가 없어 여기서 멈췄다. mypy 단계는 아예 없었다(CI 만 돌았음) — CLAUDE.md 가 말하는 1~4 를 실제로 돈다.
& $py -m ruff --version *> $null; if ($LASTEXITCODE -ne 0) { Fail "ruff 가 .venv 에 없다 — `$py -m pip install -r requirements-dev.txt` (또는 scripts/setup_env.py)" }
& $py -m mypy --version *> $null; if ($LASTEXITCODE -ne 0) { Fail "mypy 가 .venv 에 없다 — `$py -m pip install -r requirements-dev.txt` (또는 scripts/setup_env.py)" }
Write-Host "== 1. ruff check vigent-core tests (CI 와 동일, 수정 없음) =="
& $py -m ruff check vigent-core tests; if ($LASTEXITCODE -ne 0) { Fail "ruff(청정 표면) 실패" }
Write-Host "== 1b. mypy (pyproject 화이트리스트, CI 와 동일) =="
& $py -m mypy; if ($LASTEXITCODE -ne 0) { Fail "mypy 실패" }

Write-Host "== 2. ruff --fix : 이번 변경 파일만 =="
$changed = @(git diff --name-only HEAD -- '*.py') + @(git diff --name-only --cached -- '*.py') + @(git ls-files --others --exclude-standard -- '*.py')
# ★반드시 @( ) 로 배열로 고정한다. 2026-09-25 실사고(재현 확인): 변경 파일이 **하나**뿐이면 Sort-Object 가
#   배열이 아닌 문자열 하나를 돌려주고, 문자열을 `@changed` 로 스플랫하면 PowerShell 5.1 은 **글자 하나하나를
#   별개 인자**로 넘긴다("scripts/eval/x.py" → s, c, r, ..., /, ., p, y = 인자 31개). 그중 "/" 와 "." 가
#   경로로 해석돼 ruff 가 저장소 전체(.venv 포함)를 스캔했다. .venv 파일 수정은 없었지만(mtime 확인 0건)
#   한 발짝 차이였다. 아래처럼 인자 배열을 먼저 만들고 "--" 뒤에 경로를 붙인다.
$changed = @($changed | Where-Object { $_ -and (Test-Path $_) } | Sort-Object -Unique)
if ($changed.Count -eq 0) {
    Write-Host "  변경된 .py 없음 - 건너뜀"
} else {
    Write-Host ("  대상 {0}개: {1}" -f $changed.Count, ($changed -join ", "))
    $ruffArgs = @("check", "--fix", "--") + $changed
    & $py -m ruff @ruffArgs; if ($LASTEXITCODE -ne 0) { Fail "ruff --fix(변경 파일) 뒤에도 오류가 남았다" }
    # --fix 가 건드린 파일이 '대상' 밖이면 안 된다 - 있으면 그 자체가 실패
    $touched = @(git diff --name-only -- '*.py') | Where-Object { $_ -notin $changed }
    if ($touched.Count -gt 0) { Fail ("--fix 가 변경 파일 밖을 건드렸다: " + ($touched -join ", ")) }
}

if ($NoTests) {
    Write-Host "== 3. unittest 건너뜀(-NoTests) - 커밋 전에는 전체로 다시 돌릴 것 ==" -ForegroundColor Yellow
} else {
    Write-Host "== 3. unittest 전체 =="
    # [2026-09-27] 출력을 파일로도 남긴다 — 비결정 실패가 나도 이름을 잡을 수 있게(2026-09-26~27 두 번 놓쳤다)
    $utLog = Join-Path $root "audit\gate_unittest_last.log"
    # Tee-Object 는 PS 5.1 에서 UTF-16 으로 써서 grep 이 못 읽는다 → UTF-8 로 직접 기록(2026-09-27)
    & $py -m unittest discover -s tests 2>&1 | ForEach-Object { $_ | Out-Host; "$_" } | Out-File -Encoding utf8 -FilePath $utLog
    if ($LASTEXITCODE -ne 0) {
        Select-String -Path $utLog -Pattern '^(FAIL|ERROR):' | ForEach-Object { Write-Host ("  " + $_.Line) -ForegroundColor Red }
        Fail "unittest 실패 (전체 로그: $utLog)"
    }
}

Write-Host "== 4. OpenAPI 무변경 =="
& $py scripts\check_openapi_diff.py; if ($LASTEXITCODE -ne 0) { Fail "OpenAPI 변경 감지" }

Write-Host "✓ 게이트 통과" -ForegroundColor Green
exit 0
