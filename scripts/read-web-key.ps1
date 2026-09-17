function Get-WebConfiguredKey {
    param(
        [ValidateSet('offline','live')][string]$Mode,
        [string]$EnvPath,
        [AllowEmptyString()][string]$ExistingKey
    )
    # Read one literal setting only. Never execute or expand dotenv content.
    if ($Mode -ne 'live') { return $null }
    if (-not [string]::IsNullOrWhiteSpace($ExistingKey)) { return $ExistingKey }
    if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) { return $null }
    $found = $false
    $key = $null
    foreach ($line in [IO.File]::ReadAllLines($EnvPath, [Text.Encoding]::UTF8)) {
        if ($line -notmatch '^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=(.*)$') { continue }
        if ($found) { throw 'Duplicate DEEPSEEK_API_KEY in .env; keep one entry.' }
        $found = $true
        $value = $Matches[1].Trim()
        if ($value.StartsWith('"') -or $value.StartsWith("'")) {
            if ($value -notmatch '^(?:"([^"\r\n]*)"|''([^''\r\n]*)'')\s*(?:#.*)?$') {
                throw 'Invalid DEEPSEEK_API_KEY in .env; use one line with matching quotes.'
            }
            if ($value.StartsWith('"')) { $value = $Matches[1] } else { $value = $Matches[2] }
        } else {
            $value = ($value -replace '\s+#.*$', '').Trim()
        }
        if ($value -match '[\s\x00-\x1f\x7f]') {
            throw 'Invalid DEEPSEEK_API_KEY in .env; whitespace is not allowed inside a key.'
        }
        $key = $value
    }
    return $key
}
