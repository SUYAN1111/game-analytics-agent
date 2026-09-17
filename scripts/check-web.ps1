$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
try {
    foreach ($kind in @('core','dsh')) {
        $python = Join-Path $root ".venv-$kind\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $python)) { throw "Missing .venv-$kind; follow README installation." }
        & $python -c "import sys,struct; assert sys.version_info[:2]==(3,14) and struct.calcsize('P')==8; print('Python 3.14 x64: OK')"
        if ($LASTEXITCODE -ne 0) { throw "Wrong $kind Python." }
        & $python -c "import importlib.metadata as m,pathlib; lines=pathlib.Path('requirements-$kind.lock').read_text().splitlines(); assert all(m.version(n)==v for n,v in (line.split('==') for line in lines)); print('Locked dependencies: OK')"
        if ($LASTEXITCODE -ne 0) { throw "Wrong $kind dependency versions; restore from requirements-$kind.lock." }
    }
    $nodeVersion = & node -p 'process.versions.node'
    if ($LASTEXITCODE -ne 0 -or [version]$nodeVersion -lt [version]'22.12.0') { throw 'Node >=22.12 required; verified with 24.14.0.' }
    Write-Host "Node $nodeVersion; isolated core/DSH environments found."
} finally { Pop-Location }
