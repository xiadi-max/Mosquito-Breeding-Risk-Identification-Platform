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
    & $Python -m uvicorn app.main:app --host $HostAddress --port $Port
}
finally {
    Pop-Location
}
