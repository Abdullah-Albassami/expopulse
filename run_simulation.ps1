<#
ExpoPulse combined monitoring runner (Windows PowerShell 5.1+ / PowerShell 7).
Windows counterpart of run_simulation.sh (macOS). Same modes, ports, videos,
locations and detector options.

Usage (from the project folder):
    .\run_simulation.ps1 crowd|restricted|fall|all

'all' runs the three CCTV detectors and the real Paris Open Data equipment
status feed. For 'all', set the token in the same window first:
    $env:EXPOPULSE_EQUIPMENT_API_TOKEN = "<your-local-token>"

If PowerShell refuses to run scripts:
    powershell -ExecutionPolicy Bypass -File .\run_simulation.ps1 all

Requirements: venv\Scripts\python.exe and ffmpeg on PATH.
(curl and lsof from the macOS script are not needed here.)
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Mode = ""
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # faster Invoke-WebRequest on 5.1

$Mode = $Mode.ToLower()
if (@("crowd", "restricted", "fall", "all") -notcontains $Mode) {
    Write-Host "Usage: .\run_simulation.ps1 {crowd|restricted|fall|all}" -ForegroundColor Red
    exit 2
}

$Root = $PSScriptRoot
Set-Location $Root
$VenvPy = Join-Path $Root "venv\Scripts\python.exe"
$env:PYTHONUNBUFFERED = "1"

$script:Owned = New-Object System.Collections.Generic.List[System.Diagnostics.Process]
$script:Cleaned = $false
$script:ExitCode = 0
$script:HasTaskkill = [bool](Get-Command taskkill.exe -ErrorAction SilentlyContinue)

# ------------------------------------------------------------------ helpers

function Fail([string]$Message) {
    throw "[ERROR] $Message"
}

function Test-PortBusy([int]$Port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $attempt = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $attempt.AsyncWaitHandle.WaitOne(300)) { return $false }
        $client.EndConnect($attempt)
        return $true
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

function Test-Http([string]$Url, [int]$TimeoutSec = 1) {
    try {
        $null = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec $TimeoutSec
        return $true
    } catch {
        return $false
    }
}

function Wait-Http([string]$Url, [string]$Label) {
    for ($n = 0; $n -lt 120; $n++) {
        if (Test-Http $Url) {
            Write-Host "[OK] $Label ready: $Url"
            return
        }
        Start-Sleep -Milliseconds 500
    }
    Fail "$Label did not become ready: $Url"
}

function Assert-File([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Fail "Missing $Path" }
}

function Format-Arg([string]$Value) {
    if ($Value -match '[\s"]') { return '"' + ($Value -replace '"', '\"') + '"' }
    return $Value
}

# Start a background process owned by this runner. Output goes to the console,
# or to <LogBase>.log (stdout) and <LogBase>.err.log (stderr) when given.
function Start-Owned([string]$File, [string[]]$Arguments, [string]$LogBase = "") {
    $params = @{
        FilePath         = $File
        ArgumentList     = (($Arguments | ForEach-Object { Format-Arg $_ }) -join " ")
        WorkingDirectory = $Root
        NoNewWindow      = $true
        PassThru         = $true
    }
    if ($LogBase) {
        $params.RedirectStandardOutput = "$LogBase.log"
        $params.RedirectStandardError = "$LogBase.err.log"
    }
    $process = Start-Process @params
    $script:Owned.Add($process)
    return $process
}

# On Windows, venv\Scripts\python.exe launches the real interpreter as a child
# process, so the whole process tree is stopped (taskkill /T).
function Stop-Owned {
    if ($script:Cleaned) { return }
    $script:Cleaned = $true
    Write-Host ""
    Write-Host "[STOP] Stopping processes started by this runner..."
    foreach ($process in $script:Owned) {
        try {
            if (-not $process.HasExited) {
                if ($script:HasTaskkill) {
                    & taskkill.exe /PID $process.Id /T /F 2>&1 | Out-Null
                } else {
                    Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                }
            }
        } catch { }
    }
    foreach ($process in $script:Owned) {
        try { $null = $process.WaitForExit(5000) } catch { }
    }
    Write-Host "[OK] Runner cleanup complete."
}

function Start-Stream([string]$Name, [int]$Port, [string]$Video, [string]$Dir, [string]$LogDir) {
    Assert-File $Video
    if (Test-PortBusy $Port) { Fail "Port $Port is occupied. Stop its existing HLS service first." }
    New-Item -ItemType Directory -Force -Path $Dir, $LogDir | Out-Null
    Remove-Item -Path (Join-Path $Dir "live.m3u8"), (Join-Path $Dir "*.ts") -Force -ErrorAction SilentlyContinue
    Write-Host "[START] $Name video stream on port $Port"
    $null = Start-Owned "ffmpeg" @(
        "-nostdin", "-loglevel", "warning", "-re", "-stream_loop", "-1", "-i", $Video,
        "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-f", "hls", "-hls_time", "2", "-hls_list_size", "5",
        "-hls_flags", "delete_segments+omit_endlist", (Join-Path $Dir "live.m3u8")
    ) (Join-Path $LogDir "$Name.ffmpeg")
    $null = Start-Owned $VenvPy @(
        "-m", "http.server", "$Port", "--bind", "127.0.0.1", "--directory", $Dir
    ) (Join-Path $LogDir "$Name.http")
    Wait-Http "http://127.0.0.1:$Port/live.m3u8" "$Name HLS"
}

function Get-DetectorArgs([string]$Name, [int]$Port) {
    $url = "http://127.0.0.1:$Port/live.m3u8"
    switch ($Name) {
        "crowd" {
            return @("manage.py", "detect_crowding", "--video", $url,
                "--location", "Transport Hub", "--threshold", "5", "--frames", "3",
                "--sample-every", "5", "--demo-priority", "high")
        }
        "restricted" {
            return @("manage.py", "detect_restricted_area", "--video", $url,
                "--location", "Zone A", "--zone-config", "configs/restricted_zone.example.json",
                "--confirm-frames", "5", "--sample-every", "1", "--confidence", "0.35",
                "--demo-priority", "medium")
        }
        "fall" {
            return @("manage.py", "detect_falls", "--video", $url,
                "--location", "Zone A", "--sample-every", "3", "--confirm-frames", "5",
                "--confidence", "0.25", "--retry-delay", "5", "--max-retries", "0",
                "--demo-priority", "critical")
        }
    }
}

# --------------------------------------------------------------------- main

try {
    if (-not (Test-Path -LiteralPath $VenvPy)) { Fail "Missing venv\Scripts\python.exe." }
    Assert-File (Join-Path $Root "manage.py")
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) { Fail "Missing ffmpeg (install it and add it to PATH)." }

    # Reuse a running Django instance; never terminate processes we did not start.
    if ($Mode -eq "all" -and -not $env:EXPOPULSE_EQUIPMENT_API_TOKEN) {
        Fail 'Set $env:EXPOPULSE_EQUIPMENT_API_TOKEN before running all.'
    }

    if (Test-PortBusy 8000) {
        if (Test-Http "http://127.0.0.1:8000/" 2) {
            if ($Mode -eq "all") {
                Fail "Port 8000 occupied. Stop the existing server; all mode must start Django with the matching equipment API token."
            }
            Write-Host "[INFO] Reusing HTTP service on port 8000; confirm it is ExpoPulse."
        } else {
            Fail "Port 8000 is occupied by an unresponsive HTTP service."
        }
    } else {
        Write-Host "[START] Django (port 8000)"
        $null = Start-Owned $VenvPy @("manage.py", "runserver", "--noreload", "127.0.0.1:8000")
        Wait-Http "http://127.0.0.1:8000/" "Django"
    }

    Assert-File "configs/restricted_zone.example.json"
    $LogDir = Join-Path $Root "streams\logs"
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    Write-Host "[DEMO] Incident priorities: restricted=MEDIUM, crowd=HIGH, fall=CRITICAL (simulation only)."
    Write-Host "Dashboard: http://127.0.0.1:8000/"

    if ($Mode -ne "all") {
        $videos = @{
            crowd      = "footage/indoor_mall_cctv.mp4"
            restricted = "footage/restricted_zone_normal.mp4"
            fall       = "footage/fall-01-rgb.mp4"
        }
        Start-Stream $Mode 8080 $videos[$Mode] (Join-Path $Root "streams\demo_$Mode") $LogDir
        Write-Host "[RUN] $Mode detector. Press Ctrl+C to stop."
        & $VenvPy @(Get-DetectorArgs $Mode 8080)
        $script:ExitCode = $LASTEXITCODE
    } else {
        # Dedicated ports allow all three live feeds to operate concurrently.
        # Preflight before creating streams, to avoid partially starting on port collisions.
        foreach ($port in 8081, 8082, 8083) {
            if (Test-PortBusy $port) { Fail "Port $port is already in use; cannot start all mode." }
        }
        Assert-File "footage/indoor_mall_cctv.mp4"
        Assert-File "footage/restricted_zone_normal.mp4"
        Assert-File "footage/fall-01-rgb.mp4"
        Start-Stream "crowd" 8081 "footage/indoor_mall_cctv.mp4" (Join-Path $Root "streams\all_crowd") $LogDir
        Start-Stream "restricted" 8082 "footage/restricted_zone_normal.mp4" (Join-Path $Root "streams\all_restricted") $LogDir
        Start-Stream "fall" 8083 "footage/fall-01-rgb.mp4" (Join-Path $Root "streams\all_fall") $LogDir

        foreach ($spec in @(@("crowd", 8081), @("restricted", 8082), @("fall", 8083))) {
            $name = $spec[0]
            $detector = Start-Owned $VenvPy (Get-DetectorArgs $name $spec[1]) (Join-Path $LogDir "$name.detector")
            Write-Host "[RUN] $name detector PID $($detector.Id) | log: streams\logs\$name.detector.log (+ .err.log)"
        }

        Write-Host "[START] Live Paris equipment-status polling (every 300 seconds)"
        $equipment = Start-Owned $VenvPy @(
            "manage.py", "monitor_equipment_feed", "--live", "--polls", "0", "--poll-interval", "300"
        ) (Join-Path $LogDir "equipment.detector")
        Write-Host "[RUN] equipment monitor PID $($equipment.Id) | log: streams\logs\equipment.detector.log (+ .err.log)"
        Write-Host "[OK] Three CCTV detectors plus live external equipment monitoring running."
        Write-Host "Follow a log in another window: Get-Content streams\logs\crowd.detector.log -Wait"
        Write-Host "Press Ctrl+C to stop the processes started by this runner."

        while ($true) {
            Start-Sleep -Seconds 2
            foreach ($process in $script:Owned) {
                if ($process.HasExited) {
                    Fail "A simulation process (PID $($process.Id)) exited; see streams\logs\."
                }
            }
        }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    $script:ExitCode = 1
} finally {
    Stop-Owned
}
exit $script:ExitCode