param(
    [string]$HostAddress = '127.0.0.1',
    [int]$Port = 8000,
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = & (Join-Path $PSScriptRoot 'resolve_python.ps1') -PythonPath $PythonPath

Push-Location -LiteralPath $BackendRoot
try {
    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) { throw 'Database migration failed.' }

    $WorkerArgs = @('-m', 'app.worker')
    $Worker = Start-Process -FilePath $Python -ArgumentList $WorkerArgs -WorkingDirectory $BackendRoot -WindowStyle Hidden -PassThru
    Write-Host "Worker started. PID=$($Worker.Id)"
    Write-Host "Open in browser: http://$HostAddress`:$Port/"
    Write-Host 'Press Ctrl+C to stop the API and the worker started by this script.'
    try {
        & $Python -m uvicorn app.main:app --host $HostAddress --port $Port
    }
    finally {
        if ($Worker -and -not $Worker.HasExited) { Stop-Process -Id $Worker.Id }
    }
}
finally {
    Pop-Location
}
