param([switch]$Configurar, [switch]$Diagnostico, [switch]$Migrar)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$botPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $botPython)) {
    $bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
    if (Test-Path -LiteralPath $bundledPython) {
        & $bundledPython -m venv .venv
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        py -3 -m venv .venv
    } else {
        throw 'Instale Python 3.11 ou superior e execute novamente.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar o ambiente Python.' }
}
& $botPython -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências.' }
if ($Configurar -or -not (Test-Path -LiteralPath '.env')) {
    & $botPython curabot.py --configure
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
if ($Diagnostico) { & $botPython curabot.py --check }
elseif ($Migrar) { & $botPython curabot.py --migrate }
else { & $botPython curabot.py }
exit $LASTEXITCODE
