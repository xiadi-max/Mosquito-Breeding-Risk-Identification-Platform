param(
    [string]$PythonPath = 'D:\Anaconda3\envs\mosquito311-yolov11\python.exe'
)

$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'start_profile.ps1') `
    -Profile yolo11 `
    -PythonPath $PythonPath
exit $LASTEXITCODE
