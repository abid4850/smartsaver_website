$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}

$logDir = Join-Path $projectRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$logFile = Join-Path $logDir "auto_add_products.log"
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

"[$timestamp] Starting auto_add_products" | Add-Content -Path $logFile
& $pythonExe manage.py auto_add_products --markets amazon,ebay,bestbuy,newegg --count-per-market 10 *>> $logFile
$exitCode = $LASTEXITCODE

$doneStamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
"[$doneStamp] Finished auto_add_products with exit code $exitCode" | Add-Content -Path $logFile

exit $exitCode
