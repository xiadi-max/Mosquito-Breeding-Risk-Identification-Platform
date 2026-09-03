param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('yolov13', 'yolo11')]
    [string]$Profile,
    [string]$PythonPath = ''
)

$ErrorActionPreference = 'Stop'
$BackendRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$ProfilePath = Join-Path $BackendRoot "config\$Profile.env"
$StartScript = Join-Path $PSScriptRoot 'start_m6.ps1'

if (-not (Test-Path -LiteralPath $ProfilePath -PathType Leaf)) {
    throw "Runtime profile was not found: $ProfilePath"
}

foreach ($RawLine in Get-Content -LiteralPath $ProfilePath -Encoding utf8) {
    $Line = $RawLine.Trim()
    if (-not $Line -or $Line.StartsWith('#')) { continue }
    $Separator = $Line.IndexOf('=')
    if ($Separator -le 0) {
        throw "Invalid profile entry in ${ProfilePath}: $RawLine"
    }
    $Name = $Line.Substring(0, $Separator).Trim()
    $Value = $Line.Substring($Separator + 1).Trim()
    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
}

$ProfileDataRoot = Join-Path $BackendRoot "data\$Profile"
New-Item -ItemType Directory -Path $ProfileDataRoot -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $ProfileDataRoot 'artifacts') -Force | Out-Null

$Port = [int]$env:API_PORT
Write-Host "Starting MosquitoMapper profile '$Profile' on port $Port"
& $StartScript -HostAddress $env:API_HOST -Port $Port -PythonPath $PythonPath
exit $LASTEXITCODE
