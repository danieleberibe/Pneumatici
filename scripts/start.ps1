param(
    [int]$Port = 8765,
    [string]$Bind = '127.0.0.1',
    [switch]$Https
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Ambiente mancante. Eseguire prima: python -m venv .venv e .\.venv\Scripts\python.exe -m pip install -e ".[dev,https]"'
}
Set-Location -LiteralPath $projectRoot
$serverArgs = @('-m', 'uvicorn', 'stereolab.app:app', '--host', $Bind, '--port', "$Port")
if ($Https) {
    $certificate = Join-Path $projectRoot 'certs\server.pem'
    $privateKey = Join-Path $projectRoot 'certs\server-key.pem'
    if (-not (Test-Path -LiteralPath $certificate) -or -not (Test-Path -LiteralPath $privateKey)) {
        throw 'Certificati mancanti. Eseguire scripts\make_certificate.py con il proprio IP LAN.'
    }
    $serverArgs += @('--ssl-certfile', $certificate, '--ssl-keyfile', $privateKey)
}
& $pythonExe @serverArgs
exit $LASTEXITCODE
