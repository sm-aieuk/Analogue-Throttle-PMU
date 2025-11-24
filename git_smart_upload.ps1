# ============================================================
# PMU — Git-Smart Upload (CHANGED *.py ONLY)
# ============================================================

$port = "COM3"
$mp = "mpremote"
$projectRoot = "$PSScriptRoot"
$targetRoot = "/sd"

Write-Host "=== PMU Git-Smart Upload (changed .py only) ===" -ForegroundColor Cyan

# ------------------------------------------------------------
# STOP RUNNING PROGRAM
# ------------------------------------------------------------
mpremote connect $port soft-reset
Start-Sleep -Seconds 2

# ------------------------------------------------------------
# GET CHANGED FILES
# ------------------------------------------------------------
$changes = git status --porcelain | Where-Object { $_ -match "^\s*[MA]" }

if ($changes.Count -eq 0) {
    Write-Host "No modified files." -ForegroundColor DarkGray
    exit 0
}

foreach ($entry in $changes) {

    $relative = $entry.Substring(3)

    # Only *.py files
    if ($relative -notmatch "\.py$") { continue }

    $localPath = Join-Path $projectRoot $relative
    $remotePath = "$targetRoot/$relative".Replace('\', '/')
    $remoteDir = Split-Path $remotePath

    Write-Host "→ Uploading $relative" -ForegroundColor Green

    mpremote connect $port fs mkdir $remoteDir 2>$null
    mpremote connect $port fs put $localPath $remotePath
}

# ------------------------------------------------------------
# RUN main.py
# ------------------------------------------------------------
Write-Host "Running main.py..." -ForegroundColor Yellow
mpremote connect $port soft-reset
Start-Sleep -Seconds 2
mpremote connect $port run "/sd/main.py"
