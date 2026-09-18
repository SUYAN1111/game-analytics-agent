param([ValidateSet('offline','live')][string]$Mode='live', [ValidatePattern('^[a-zA-Z0-9_-]{1,64}$')][string]$Period='live-main', [int]$Port=8765, [ValidateRange(0.01,5)][double]$Budget=4.9)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
. "$PSScriptRoot\read-web-key.ps1"
& "$PSScriptRoot\check-web.ps1"
if ($Mode -eq 'live') {
    # No key and no model request: fail before opening a budget if networking is blocked.
    & node -e "fetch('https://api.deepseek.com',{method:'HEAD',signal:AbortSignal.timeout(10000)}).then(r=>{if(r.status>=500)throw new Error('provider HTTP '+r.status);console.log('DeepSeek HTTPS reachable (no model call).')}).catch(e=>{console.error('DeepSeek HTTPS check failed:',e.cause?.code||e.name);process.exitCode=1})"
    if ($LASTEXITCODE -ne 0) { throw 'DeepSeek connection unavailable. Start from a network-enabled PowerShell terminal. No model request or budget reservation was made by this check.' }
}
$oldPythonPath = $env:PYTHONPATH
$oldNoSite = $env:PYTHONNOUSERSITE
$oldNoBytecode = $env:PYTHONDONTWRITEBYTECODE
$setKey = $false
Push-Location $root
try {
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    $env:PYTHONNOUSERSITE='1'
    $env:PYTHONDONTWRITEBYTECODE='1'
    if (-not (Test-Path -LiteralPath 'web\dist\index.html')) { throw 'Build first: npm.cmd --prefix web ci; npm.cmd --prefix web run build' }
    if ($Mode -eq 'live' -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        $configuredKey = Get-WebConfiguredKey -Mode $Mode -EnvPath (Join-Path $root '.env') -ExistingKey $env:DEEPSEEK_API_KEY
        if (-not [string]::IsNullOrWhiteSpace($configuredKey)) {
            $env:DEEPSEEK_API_KEY = $configuredKey
            $setKey = $true
        }
        $configuredKey = $null
    }
    if ($Mode -eq 'live' -and [string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        $secureKey = Read-Host 'DEEPSEEK_API_KEY (backend process only)' -AsSecureString
        $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
        try { $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer); $setKey=$true }
        finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer); $secureKey.Dispose() }
    }
    Write-Host "Mode=$Mode; budget period=$Period; http://127.0.0.1:$Port ; Ctrl+C to stop."
    & '.\.venv-core\Scripts\python.exe' -B -m web_api --mode $Mode --period $Period --port $Port --budget $Budget
    if ($LASTEXITCODE -ne 0) { throw 'Web service exited with an error; check the local message above.' }
} finally {
    if ($setKey) { Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue }
    $env:PYTHONPATH=$oldPythonPath; $env:PYTHONNOUSERSITE=$oldNoSite; $env:PYTHONDONTWRITEBYTECODE=$oldNoBytecode
    Pop-Location
}
