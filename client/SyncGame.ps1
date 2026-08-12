[CmdletBinding()]
param(
    [switch]$SetupSecrets,
    [switch]$TestOnly
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$ClientRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ConfigPath = Join-Path $ClientRoot 'config.json'
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "config.json does not exist. Copy config.example.json and adjust it."
}

$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$adapter = [string]$config.Adapter
if ($adapter -notmatch '^[a-z0-9][a-z0-9-]{0,62}$') {
    throw 'Adapter must use lowercase letters, numbers and hyphens.'
}

$adapterScript = Join-Path $ClientRoot ("adapters\{0}\Adapter.ps1" -f $adapter)
$adapterManifest = Join-Path $ClientRoot ("adapters\{0}\adapter.json" -f $adapter)
if (-not (Test-Path -LiteralPath $adapterScript -PathType Leaf)) {
    throw "Adapter '$adapter' does not exist: $adapterScript"
}
if (-not (Test-Path -LiteralPath $adapterManifest -PathType Leaf)) {
    throw "Adapter '$adapter' does not contain adapter.json."
}
$manifest = Get-Content -LiteralPath $adapterManifest -Raw | ConvertFrom-Json
if ([string]$manifest.key -ne $adapter -or [string]$manifest.gameKey -ne [string]$config.GameKey) {
    throw 'Adapter, adapter.json and GameKey do not match.'
}

$parameters = @{ ClientRoot = $ClientRoot }
if ($SetupSecrets) { $parameters.SetupSecrets = $true }
if ($TestOnly) { $parameters.TestOnly = $true }
& $adapterScript @parameters
if (-not $?) { exit 1 }
exit 0
