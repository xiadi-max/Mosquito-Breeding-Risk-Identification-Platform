param(
    [switch]$SkipInstall,
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$Python = & (Join-Path $PSScriptRoot 'resolve_python.ps1') -PythonPath $PythonPath

if (-not $SkipInstall) {
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -e "$BackendRoot[dev]"
}

Push-Location -LiteralPath $BackendRoot
try {
    & $Python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw 'Alembic migration failed.'
    }
}
finally {
    Pop-Location
}

Write-Host "Database initialization completed: $BackendRoot"
