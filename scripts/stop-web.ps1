param([ValidateSet('offline','live')][string]$Mode='live', [ValidatePattern('^[a-zA-Z0-9_-]{1,64}$')][string]$Period='live-main')
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$stateRoot=if ($env:APP_STATE_DIR) {$env:APP_STATE_DIR} else {Join-Path $root 'state'}
$directory=Join-Path $stateRoot "web\$Mode\$Period"
if (-not (Test-Path -LiteralPath $directory)) { throw 'This service period has not been started.' }
[IO.File]::WriteAllText((Join-Path $directory 'stop.request'),'stop')
Write-Host 'Requested graceful stop for this mode/period only. Wait for the service to exit.'
