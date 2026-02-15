param(
    [string]$BackendHost = "127.0.0.1",
    [int]$BackendPort = 8000,
    [string]$FrontendHost = "127.0.0.1",
    [int]$FrontendPort = 5173,
    [switch]$DryRun
)

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$webRoot = Join-Path $repoRoot "web"

$backendCmd = "Set-Location '$repoRoot'; py -3 -m uvicorn app.main:app --host $BackendHost --port $BackendPort"
$frontendCmd = "Set-Location '$webRoot'; npm run dev -- --host $FrontendHost --port $FrontendPort"

if ($DryRun) {
    Write-Host "Backend command: $backendCmd"
    Write-Host "Frontend command: $frontendCmd"
    exit 0
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd | Out-Null
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd | Out-Null

Write-Host "Backend:  http://${BackendHost}:${BackendPort}"
Write-Host "Frontend: http://${FrontendHost}:${FrontendPort}"
Write-Host "Opened two terminals automatically."
