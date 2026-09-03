param([string]$PythonPath = '')

$ErrorActionPreference = 'Stop'
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = & (Join-Path $PSScriptRoot 'resolve_python.ps1') -PythonPath $PythonPath

Push-Location -LiteralPath $BackendRoot
try {
    & $Python -m app.worker
}
finally {
    Pop-Location
}
