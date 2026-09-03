param(
    [string]$PythonPath = 'D:\Anaconda3\envs\mosquito311\python.exe'
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start_profile.ps1') `
    -Profile yolov13 `
    -PythonPath $PythonPath
exit $LASTEXITCODE
