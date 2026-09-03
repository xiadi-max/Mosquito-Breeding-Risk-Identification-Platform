param(
    [string]$BaseUrl = 'http://127.0.0.1:8000'
)

$ErrorActionPreference = 'Stop'

$Live = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/health/live"
$Ready = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/health/ready"
$Version = Invoke-RestMethod -Method Get -Uri "$BaseUrl/api/v1/version"

if ($Live.status -ne 'ok') {
    throw 'Live check failed.'
}
if ($Ready.status -ne 'ready') {
    throw 'Ready check failed.'
}

Write-Host "Smoke test passed. API version: $($Version.version), schema: $($Version.schema_revision)"
