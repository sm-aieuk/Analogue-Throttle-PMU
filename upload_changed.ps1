# =============================================================
# PMU — Upload CHANGED .py files to /sd and run main.py
# =============================================================

$port = "COM3"
$scriptPath = $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptPath
$target = "/sd"

Write-Host "=== Uploading CHANGED files ==="

# Stop anything running
 
mpremote connect $port soft-reset
Start-Sleep -Milliseconds 300

# Detect changed files
$changes = git status --porcelain | Where-Object { $_ -match "^\s*[MA]" }

foreach ($entry in $changes) {

    $relative = $entry.Substring(3)
    if ($relative -notmatch "\.py$") { continue }

    $local = Join-Path $projectRoot $relative
    $remote = "$target/$relative".Replace('\', '/')

    Write-Host "Uploading: $relative"

    # Delete old version
    mpremote rm ":$remote" 2>$null

    # Correct SCP-style copy syntax
    mpremote cp "$local" ":$remote"
}

Write-Host "Running main.py..."
mpremote connect $port exec "import os; os.chdir('/sd'); import main"

Write-Host "Opening REPL..."
mpremote connect $port repl
