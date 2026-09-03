param([string]$PythonPath = '')

$ErrorActionPreference = 'Stop'
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path

if ($PythonPath) {
    $Candidate = (Resolve-Path -LiteralPath $PythonPath).Path
}
elseif ($env:CONDA_PREFIX) {
    $Candidate = Join-Path $env:CONDA_PREFIX 'python.exe'
}
else {
    $Candidate = Join-Path $BackendRoot '.venv\Scripts\python.exe'
}

if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
    throw 'Python was not found. Run conda activate mosquito311 or pass -PythonPath.'
}

$Candidate
