# PMU — STOP (clean & safe)

$port = "COM3"

# harmless command that always succeeds
mpremote connect $port exec "pass"

# double soft reset to clear imports & unlock FS
mpremote connect $port soft-reset
Start-Sleep -Milliseconds 300
mpremote connect $port soft-reset
Start-Sleep -Milliseconds 300
