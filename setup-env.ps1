$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (Test-Path -LiteralPath '.env') { Write-Host '.env exists; no changes made.'; exit 0 }
function New-Secret([int]$Length) {
    $bytes = New-Object byte[] $Length
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}
$dbSecret = New-Secret 24
$jwtSecret = New-Secret 32
$demoSecret = New-Secret 12
$adminSecret = New-Secret 18
@("DB_PASSWORD=$dbSecret", "JWT_SECRET=$jwtSecret", "DEMO_PASSWORD=$demoSecret", "ADMIN_PASSWORD=$adminSecret") | Set-Content -LiteralPath '.env' -Encoding ascii
Write-Host 'Created .env with random local secrets. Read DEMO_PASSWORD in .env to sign in. Do not share this file.'
