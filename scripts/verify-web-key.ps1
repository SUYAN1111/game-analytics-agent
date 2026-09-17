$ErrorActionPreference = 'Stop'
. "$PSScriptRoot\read-web-key.ps1"
$testPath = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
$utf8 = [Text.UTF8Encoding]::new($true)
$checks = 0
function Assert-Key([string]$Content, [string]$Expected) {
    [IO.File]::WriteAllText($testPath, $Content, $utf8)
    $actual = Get-WebConfiguredKey -Mode live -EnvPath $testPath -ExistingKey ''
    if ([string]$actual -cne $Expected) { throw "Dotenv value assertion failed at check $checks (values omitted)." }
    $script:checks++
}
function Assert-Invalid([string]$Content) {
    [IO.File]::WriteAllText($testPath, $Content, $utf8)
    $failure = $null
    try { $null = Get-WebConfiguredKey -Mode live -EnvPath $testPath -ExistingKey '' }
    catch { $failure = $_.Exception.Message }
    if (-not $failure -or $failure.Contains('fake-secret')) { throw 'Dotenv rejection or redaction assertion failed.' }
    $script:checks++
}
try {
    Assert-Key "# comment`r`nDEEPSEEK_API_KEY=fake-secret`r`n" 'fake-secret'
    Assert-Key ' DEEPSEEK_API_KEY = "fake-secret" # comment' 'fake-secret'
    Assert-Key "export DEEPSEEK_API_KEY='fake-secret'" 'fake-secret'
    Assert-Key 'DEEPSEEK_API_KEY=fake-secret # comment' 'fake-secret'
    Assert-Key 'DEEPSEEK_API_KEY=' ''
    Assert-Key 'UNRELATED_SETTING=ignored' ''
    Assert-Key 'DEEPSEEK_API_KEY=$(not-executed)' '$(not-executed)'
    Assert-Key 'DEEPSEEK_API_KEY=${NOT_EXPANDED}' '${NOT_EXPANDED}'
    Assert-Invalid "DEEPSEEK_API_KEY=fake-secret`nDEEPSEEK_API_KEY=duplicate"
    Assert-Invalid 'DEEPSEEK_API_KEY="fake-secret'
    Assert-Invalid 'DEEPSEEK_API_KEY=fake-secret with-spaces'
    Assert-Invalid "DEEPSEEK_API_KEY='fake-secret`nsecond-line'"
    # Invalid file must not be read in offline mode or when environment wins.
    $offline = Get-WebConfiguredKey -Mode offline -EnvPath $testPath -ExistingKey 'existing-fake'
    if ($null -ne $offline) { throw 'Offline mode must not return a key.' }
    $checks++
    $existing = Get-WebConfiguredKey -Mode live -EnvPath $testPath -ExistingKey 'existing-fake'
    if ($existing -cne 'existing-fake') { throw 'Environment precedence failed.' }
    $checks++
    Remove-Item -LiteralPath $testPath
    $missing = Get-WebConfiguredKey -Mode live -EnvPath $testPath -ExistingKey ''
    if ($null -ne $missing) { throw 'Missing file fallback failed.' }
    $checks++
    Write-Host "$checks dotenv checks passed; fake keys only, no API requests."
} finally {
    if (Test-Path -LiteralPath $testPath) { Remove-Item -LiteralPath $testPath }
}
