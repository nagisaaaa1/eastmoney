param(
    [int[]]$Ports = @(8000, 5173)
)

foreach ($port in $Ports) {
    $listeners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue
    foreach ($listener in $listeners) {
        try {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
            Write-Host "Stopped PID $($listener.OwningProcess) on port $port"
        }
        catch {
            Write-Warning "Failed to stop PID $($listener.OwningProcess) on port ${port}: $($_.Exception.Message)"
        }
    }
}
