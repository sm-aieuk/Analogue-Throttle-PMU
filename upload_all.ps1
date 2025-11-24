# =============================================================
# PMU — Upload ALL .py files to /sd and run main.py
# =============================================================

$port = "COM3"
$scriptPath = $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptPath
$target = "/sd"

Write-Host "=== Uploading ALL .py files ==="

# Stop anything running
mpremote connect $port soft-reset
Start-Sleep -Milliseconds 300

# Find all .py files in project folder
$files = Get-ChildItem -Recurse -Filter *.py

foreach ($file in $files) {

    # relative path inside project
    $relative = $file.FullName.Substring($projectRoot.Length).TrimStart('\')
    $local    = $file.FullName
    $remote   = "$target/$relative".Replace('\','/')

    Write-Host "Uploading: $relative"

    # Delete old file first
    mpremote rm ":$remote" 2>$null

    # Copy file to device (SCP syntax)
    mpremote cp "$local" ":$remote"
}

Write-Host "Running main.py..."
mpremote connect $port exec "import os; os.chdir('/sd'); import main"

Write-Host "Opening REPL..."
mpremote connect $port repl
