param(
    [ValidateSet('Backend','Frontend')][string]$Service='Backend',
    [string]$PythonPath='',
    [switch]$Department
)
$ErrorActionPreference='Stop'
Set-Location $PSScriptRoot
if($Service -eq 'Frontend') {
    Set-Location 'frontend'
    if(-not (Test-Path -LiteralPath 'node_modules')) { throw 'Run npm ci in frontend first.' }
    & npm run dev -- --configLoader runner
    exit $LASTEXITCODE
}
if(-not $PythonPath) { $PythonPath=Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe' }
$PythonPath=(Resolve-Path -LiteralPath $PythonPath).Path
if($Department) {
    $config=Join-Path $PSScriptRoot '.local/settings.json'
    if(-not (Test-Path -LiteralPath $config)) { throw 'Department settings missing. Follow README to initialize a clean installation.' }
    $settings=Get-Content -LiteralPath $config -Raw | ConvertFrom-Json
    foreach($key in @('JWT_SECRET','DATABASE_URL','UPLOAD_DIR')) {
        [Environment]::SetEnvironmentVariable($key,[string]$settings.$key,'Process')
    }
}
if(-not $env:JWT_SECRET) { throw 'Set JWT_SECRET before starting a non-department server.' }
Set-Location 'backend'
& $PythonPath -m uvicorn app.main:app --host 127.0.0.1 --port 8000
exit $LASTEXITCODE
