# sample_server_proc.ps1 - 서버 프로세스 자원 샘플러 (psutil 불필요). [H-3]
#
# ★왜 따로 있는가 (실측 근거, 2026-09-23 개발기)
#   scripts/pilot_load_test.py 의 find_server_pid() 는
#     Name='python.exe' 이고 CommandLine 이 '*uvicorn*main:app*' 인 것 중 **-First 1**
#   을 고른다. 그런데 uvicorn 기동 시 이 조건에 **두 개**가 걸린다:
#     PID 26976  RSS    5 MB  CPU    0.0s   <- 스텁(런처). 여기가 먼저 걸렸다
#     PID 33936  RSS 3175 MB  CPU 1572.3s   <- 진짜 서버
#   그 결과 소크 리포트의 "서버 RSS" 와 "서버 환산코어" 가 **스텁을 잰 값**이 된다
#   (RSS 5.0MB · cpu_s 0.0156 이 창마다 상수로 찍힌다 = 아무 일도 안 하는 프로세스).
#   → 이 스크립트는 **RSS 가 가장 큰 후보**를 서버로 보고 잰다.
#
# 사용:
#   powershell -ExecutionPolicy Bypass -File scripts\bench\sample_server_proc.ps1 `
#       -Out audit\bench4ch_<tag>_serverproc.csv -Minutes 40 -PeriodSec 15
param(
    [Parameter(Mandatory = $true)][string]$Out,
    [double]$Minutes = 40,
    [double]$PeriodSec = 15,
    [int]$Pid0 = 0            # 0 이면 매번 다시 찾는다(재시작 대비)
)

function Find-ServerPid {
    # ★RSS 최대인 후보를 고른다 - 스텁(5MB)을 피하는 유일하게 확실한 기준
    $cands = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like '*uvicorn*main:app*' -or $_.CommandLine -like '*service_entry.py*' }
    $best = $null; $bestRss = -1
    foreach ($c in $cands) {
        $p = Get-Process -Id $c.ProcessId -ErrorAction SilentlyContinue
        if ($p -and $p.WorkingSet64 -gt $bestRss) { $bestRss = $p.WorkingSet64; $best = $c.ProcessId }
    }
    return $best
}

"ts,elapsed_s,server_pid,server_rss_mb,server_cpu_s,server_cores,sys_cpu_pct,sys_avail_mb,vram_used_mb" |
    Out-File -FilePath $Out -Encoding utf8

$t0 = Get-Date
$prevCpu = $null
$prevT = $null
$deadline = $t0.AddMinutes($Minutes)

while ((Get-Date) -lt $deadline) {
    $target = if ($Pid0 -gt 0) { $Pid0 } else { Find-ServerPid }
    $rss = ""; $cpuS = ""; $cores = ""
    if ($target) {
        $p = Get-Process -Id $target -ErrorAction SilentlyContinue
        if ($p) {
            $rss = [math]::Round($p.WorkingSet64 / 1MB, 1)
            $cpuS = [math]::Round($p.TotalProcessorTime.TotalSeconds, 2)
            $now = Get-Date
            if ($null -ne $prevCpu) {
                $dt = ($now - $prevT).TotalSeconds
                # 환산코어 = 구간 CPU 시간 / 구간 실제 시간 (1.0 = 코어 1개를 100% 쓴 것)
                if ($dt -gt 0) { $cores = [math]::Round(($cpuS - $prevCpu) / $dt, 2) }
            }
            $prevCpu = $cpuS; $prevT = $now
        }
    }
    $os = Get-CimInstance Win32_OperatingSystem
    $avail = [math]::Round($os.FreePhysicalMemory / 1024)
    $syscpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor |
        Where-Object { $_.Name -eq '_Total' }).PercentProcessorTime
    $vram = ""
    try {
        $v = & nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>$null
        if ($LASTEXITCODE -eq 0 -and $v) { $vram = ($v | Select-Object -First 1).Trim() }
    } catch {}
    $el = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
    "$((Get-Date).ToString('s')),$el,$target,$rss,$cpuS,$cores,$syscpu,$avail,$vram" |
        Out-File -FilePath $Out -Encoding utf8 -Append
    Start-Sleep -Seconds $PeriodSec
}
Write-Host "샘플러 종료: $Out"
