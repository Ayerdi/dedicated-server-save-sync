[CmdletBinding()]
param(
    [switch]$SetupSecrets,
    [switch]$TestOnly,
    [switch]$LibraryOnly,
    [string]$ClientRoot
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

Add-Type -AssemblyName System.Net.Http
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
try { Add-Type -AssemblyName System.Security -ErrorAction Stop } catch {}

$AdapterRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptRoot = if ([string]::IsNullOrWhiteSpace($ClientRoot)) { $AdapterRoot } else { [IO.Path]::GetFullPath($ClientRoot) }
$ClientVersion = '0.1.0'
$ConfigPath = Join-Path $ScriptRoot 'config.json'
$DataRoot = Join-Path $ScriptRoot 'data\valheim'
$SecretsPath = Join-Path $DataRoot 'secrets.json'
$StatePath = Join-Path $DataRoot 'state.json'
$PendingPath = Join-Path $DataRoot 'pending-session.json'
$HeartbeatStatePath = Join-Path $DataRoot 'heartbeat-state.json'
$BackupRoot = Join-Path $DataRoot 'backups'
$DownloadRoot = Join-Path $DataRoot 'downloads'
$PendingUploadRoot = Join-Path $DataRoot 'pending-uploads'
$TempRoot = Join-Path $DataRoot 'temp'
$LogRoot = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogRoot ("ValheimSync-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Info { param([string]$Message) Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Write-Success { param([string]$Message) Write-Host "[OK]   $Message" -ForegroundColor Green }
function Write-WarningText { param([string]$Message) Write-Host "[WARN] $Message" -ForegroundColor Yellow }
function Write-ErrorText { param([string]$Message) Write-Host "[ERROR] $Message" -ForegroundColor Red }

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Write-Log {
    param([string]$Level, [string]$Message)
    try {
        Ensure-Directory -Path $LogRoot
        Add-Content -LiteralPath $LogPath -Value ("{0} [{1}] {2}" -f (Get-Date).ToString('o'), $Level.ToUpperInvariant(), $Message) -Encoding UTF8
    }
    catch {}
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $raw = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    return ($raw | ConvertFrom-Json)
}

function Write-JsonAtomic {
    param([string]$Path, [object]$Value)
    $parent = Split-Path -Parent $Path
    Ensure-Directory -Path $parent
    $temporary = "$Path.tmp-$([Guid]::NewGuid().ToString('N'))"
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 12), ([Text.UTF8Encoding]::new($true)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$SecureString)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer) }
}

function Get-DpapiEntropy {
    return [Text.Encoding]::UTF8.GetBytes('dedicated-server-save-sync:valheim:secrets:v2')
}

function Protect-DpapiString {
    param([string]$PlainText)
    $plainBytes = [Text.Encoding]::UTF8.GetBytes($PlainText)
    $entropy = Get-DpapiEntropy
    $protectedBytes = $null
    try {
        $protectedBytes = [Security.Cryptography.ProtectedData]::Protect(
            $plainBytes,
            $entropy,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        return [Convert]::ToBase64String($protectedBytes)
    }
    finally {
        if ($null -ne $plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
        if ($null -ne $protectedBytes) { [Array]::Clear($protectedBytes, 0, $protectedBytes.Length) }
        if ($null -ne $entropy) { [Array]::Clear($entropy, 0, $entropy.Length) }
    }
}

function Unprotect-DpapiString {
    param([string]$ProtectedText)
    $protectedBytes = $null
    $plainBytes = $null
    $entropy = Get-DpapiEntropy
    try {
        $protectedBytes = [Convert]::FromBase64String($ProtectedText)
        $plainBytes = [Security.Cryptography.ProtectedData]::Unprotect(
            $protectedBytes,
            $entropy,
            [Security.Cryptography.DataProtectionScope]::CurrentUser
        )
        return [Text.Encoding]::UTF8.GetString($plainBytes)
    }
    finally {
        if ($null -ne $protectedBytes) { [Array]::Clear($protectedBytes, 0, $protectedBytes.Length) }
        if ($null -ne $plainBytes) { [Array]::Clear($plainBytes, 0, $plainBytes.Length) }
        if ($null -ne $entropy) { [Array]::Clear($entropy, 0, $entropy.Length) }
    }
}

function Protect-SecretsFile {
    param([string]$Path)
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $Path /inheritance:r /grant:r "${identity}:F" | Out-Null
    }
    catch { Write-Log -Level 'warning' -Message "Could not restrict the ACL on secrets.json: $($_.Exception.Message)" }
}

function Initialize-Secrets {
    Write-Host ''
    Write-Info 'Secure credential setup'
    Write-Host 'The Save Sync token and Valheim server password will be encrypted with DPAPI for this Windows user.'
    do {
        $tokenSecure = Read-Host 'Save Sync token (pws_...)' -AsSecureString
        $tokenPlain = Convert-SecureStringToPlainText -SecureString $tokenSecure
        $tokenValid = $tokenPlain -match '^pws_[A-Za-z0-9_-]{48}$'
        if (-not $tokenValid) { Write-WarningText 'The token must be pws_ followed by 48 characters.' }
    } while (-not $tokenValid)

    do {
        $passwordSecure = Read-Host 'Valheim dedicated-server password' -AsSecureString
        $passwordPlain = Convert-SecureStringToPlainText -SecureString $passwordSecure
        $passwordValid = -not [string]::IsNullOrWhiteSpace($passwordPlain) -and $passwordPlain.Length -ge 5
        if (-not $passwordValid) { Write-WarningText 'The Valheim server password must contain at least 5 characters.' }
    } while (-not $passwordValid)

    $protected = [ordered]@{
        schemaVersion = 2
        gameKey = 'valheim'
        protection = 'dpapi-current-user'
        apiToken = Protect-DpapiString -PlainText $tokenPlain
        serverPassword = Protect-DpapiString -PlainText $passwordPlain
        createdAtUtc = [DateTime]::UtcNow.ToString('o')
        windowsUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    }
    Write-JsonAtomic -Path $SecretsPath -Value $protected
    Protect-SecretsFile -Path $SecretsPath
    $tokenPlain = $null
    $passwordPlain = $null
    Write-Success 'Encrypted credentials saved to data\valheim\secrets.json.'
}

function Get-Secrets {
    if (-not (Test-Path -LiteralPath $SecretsPath -PathType Leaf)) { Initialize-Secrets }
    $stored = Read-JsonFile -Path $SecretsPath
    if ($null -eq $stored -or [string]::IsNullOrWhiteSpace([string]$stored.apiToken) -or [string]::IsNullOrWhiteSpace([string]$stored.serverPassword)) {
        throw 'The Valheim secrets file is missing required values. Run Configure-Secrets.cmd.'
    }
    if ($null -ne $stored.PSObject.Properties['gameKey'] -and [string]$stored.gameKey -ne 'valheim') {
        throw 'data\valheim\secrets.json belongs to another adapter. Preserve it and reconfigure the Valheim secrets.'
    }
    $schemaVersion = if ($null -ne $stored.PSObject.Properties['schemaVersion']) { [int]$stored.schemaVersion } else { 1 }
    if ($schemaVersion -ne 2 -or [string]$stored.protection -ne 'dpapi-current-user') {
        throw 'The Valheim secrets file uses a legacy protection format. Run Configure-Secrets.cmd to recreate it.'
    }
    try {
        $token = Unprotect-DpapiString -ProtectedText ([string]$stored.apiToken)
        $password = Unprotect-DpapiString -ProtectedText ([string]$stored.serverPassword)
    }
    catch { throw 'The credentials could not be decrypted by this Windows user. Run Configure-Secrets.cmd.' }
    if ($token -notmatch '^pws_[A-Za-z0-9_-]{48}$') { throw 'The decrypted API token is invalid.' }
    if ([string]::IsNullOrWhiteSpace($password) -or $password.Length -lt 5) { throw 'The decrypted Valheim server password is invalid.' }
    return [pscustomobject]@{ ApiToken = $token; ServerPassword = $password }
}

function Get-RequiredProperty {
    param([object]$Object, [string]$Name)
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "Required value '$Name' is missing from config.json."
    }
    return $property.Value
}

function Test-SafeWorldName {
    param([string]$WorldName)
    if ([string]::IsNullOrWhiteSpace($WorldName) -or $WorldName.Length -gt 64) { return $false }
    if ($WorldName -ne $WorldName.Trim() -or $WorldName.EndsWith('.') -or $WorldName.EndsWith(' ')) { return $false }
    if ($WorldName.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) { return $false }
    if ($WorldName -in @('.', '..')) { return $false }
    $deviceBase = ($WorldName -split '\.', 2)[0]
    if ($deviceBase -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { return $false }
    return $true
}

function Load-AndValidateConfig {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) { throw "config.json does not exist in $ScriptRoot." }
    $config = Read-JsonFile -Path $ConfigPath
    if ($null -eq $config) { throw 'config.json is empty or is not valid JSON.' }
    foreach ($name in @('PlayerName','ClientId','ApiBaseUrl','ServerRoot','ServerExecutable','SaveRoot','WorldName','ServerName','ServerPort')) {
        [void](Get-RequiredProperty -Object $config -Name $name)
    }
    if ([string]$config.ApiBaseUrl -notmatch '^https://') { throw 'ApiBaseUrl must use HTTPS.' }
    if (-not (Test-Path -LiteralPath ([string]$config.ServerExecutable) -PathType Leaf)) { throw "valheim_server.exe was not found: $($config.ServerExecutable)" }
    if (-not (Test-Path -LiteralPath ([string]$config.ServerRoot) -PathType Container)) { throw "ServerRoot was not found: $($config.ServerRoot)" }
    if (-not (Test-SafeWorldName -WorldName ([string]$config.WorldName))) { throw 'WorldName is not safe for a Windows directory name.' }
    $port = [int]$config.ServerPort
    if ($port -lt 1 -or $port -gt 65533) { throw 'ServerPort must be between 1 and 65533.' }
    foreach ($name in @('HeartbeatSeconds','StartupTimeoutSeconds','ShutdownTimeoutSeconds','PostExitGraceSeconds','LocalBackupRetention')) {
        if ($null -ne $config.PSObject.Properties[$name] -and [int]$config.$name -lt 1) { throw "$name must be at least 1." }
    }
    if ($null -ne $config.PSObject.Properties['ServerArguments'] -and $null -ne $config.ServerArguments) {
        $reserved = @('-nographics','-batchmode','-name','-port','-world','-password','-savedir','-public','-logfile','-crossplay')
        foreach ($argument in @($config.ServerArguments)) {
            $candidate = ([string]$argument).Trim().ToLowerInvariant()
            if ($candidate -in $reserved -or @($reserved | Where-Object { $candidate.StartsWith("$_=") }).Count -gt 0) {
                throw "ServerArguments must not override adapter-managed option '$argument'."
            }
        }
    }
    Ensure-Directory -Path ([string]$config.SaveRoot)
    if ($null -eq $config.PSObject.Properties['HeartbeatSeconds']) { $config | Add-Member -NotePropertyName HeartbeatSeconds -NotePropertyValue 60 }
    if ($null -eq $config.PSObject.Properties['StartupTimeoutSeconds']) { $config | Add-Member -NotePropertyName StartupTimeoutSeconds -NotePropertyValue 180 }
    if ($null -eq $config.PSObject.Properties['StartupReadyPattern']) { $config | Add-Member -NotePropertyName StartupReadyPattern -NotePropertyValue 'Game server connected' }
    if ($null -eq $config.PSObject.Properties['ShutdownTimeoutSeconds']) { $config | Add-Member -NotePropertyName ShutdownTimeoutSeconds -NotePropertyValue 180 }
    if ($null -eq $config.PSObject.Properties['PostExitGraceSeconds']) { $config | Add-Member -NotePropertyName PostExitGraceSeconds -NotePropertyValue 2 }
    if ($null -eq $config.PSObject.Properties['LocalBackupRetention']) { $config | Add-Member -NotePropertyName LocalBackupRetention -NotePropertyValue 5 }
    if ($null -eq $config.PSObject.Properties['Public']) { $config | Add-Member -NotePropertyName Public -NotePropertyValue $false }
    if ($null -eq $config.PSObject.Properties['Crossplay']) { $config | Add-Member -NotePropertyName Crossplay -NotePropertyValue $false }
    if ([string]::IsNullOrWhiteSpace([string]$config.StartupReadyPattern)) { throw 'StartupReadyPattern must not be empty.' }
    return $config
}

function Get-WebExceptionBody {
    param([System.Exception]$Exception)
    try {
        if ($null -ne $Exception.Response) {
            $stream = $Exception.Response.GetResponseStream()
            if ($null -ne $stream) {
                $reader = [IO.StreamReader]::new($stream)
                try { return $reader.ReadToEnd() } finally { $reader.Dispose() }
            }
        }
    }
    catch {}
    return $null
}

function New-HttpFailure {
    param([string]$Message, [int]$StatusCode, [string]$ResponseBody)
    $exception = [System.Exception]::new($Message)
    $exception.Data['StatusCode'] = $StatusCode
    $exception.Data['ResponseBody'] = $ResponseBody
    return $exception
}

function Invoke-ApiJson {
    param([ValidateSet('GET','POST','DELETE')][string]$Method, [string]$Path, [string]$Token, [object]$Body = $null)
    $uri = ('{0}/{1}' -f ([string]$script:Config.ApiBaseUrl).TrimEnd('/'), $Path.TrimStart('/'))
    $parameters = @{ Uri = $uri; Method = $Method; Headers = @{ Authorization = "Bearer $Token"; Accept = 'application/json' }; ErrorAction = 'Stop' }
    if ($null -ne $Body) { $parameters.ContentType = 'application/json'; $parameters.Body = ($Body | ConvertTo-Json -Compress -Depth 8) }
    try { return Invoke-RestMethod @parameters }
    catch {
        $statusCode = 0
        try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}
        $responseBody = Get-WebExceptionBody -Exception $_.Exception
        $message = "The web API rejected $Method $Path (HTTP $statusCode)."
        if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
            try { $parsed = $responseBody | ConvertFrom-Json; $message = "$message $($parsed.error): $($parsed.message)" }
            catch { $message = "$message $responseBody" }
        }
        throw (New-HttpFailure -Message $message -StatusCode $statusCode -ResponseBody $responseBody)
    }
}

function Get-HeaderValue {
    param([System.Net.Http.HttpResponseMessage]$Response, [string]$Name)
    $values = $null
    if ($Response.Headers.TryGetValues($Name, [ref]$values)) { return [string]($values | Select-Object -First 1) }
    $values = $null
    if ($Response.Content.Headers.TryGetValues($Name, [ref]$values)) { return [string]($values | Select-Object -First 1) }
    return $null
}

function Get-Sha256 { param([string]$Path) return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }

function Test-ValidWorldUid {
    param([string]$WorldUid)
    if ([string]::IsNullOrWhiteSpace($WorldUid) -or $WorldUid.Trim() -notmatch '^-?[0-9]{1,19}$') { return $false }
    $parsed = 0L
    return [long]::TryParse($WorldUid.Trim(), [Globalization.NumberStyles]::Integer, [Globalization.CultureInfo]::InvariantCulture, [ref]$parsed)
}

function Normalize-WorldUid {
    param([string]$WorldUid)
    if (-not (Test-ValidWorldUid -WorldUid $WorldUid)) { throw "Invalid Valheim World UID: '$WorldUid'." }
    return [long]::Parse($WorldUid.Trim(), [Globalization.CultureInfo]::InvariantCulture).ToString([Globalization.CultureInfo]::InvariantCulture)
}

function Read-ValheimWorldHeader {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Valheim metadata file was not found: $Path" }
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
    $reader = [IO.BinaryReader]::new($stream, [Text.Encoding]::UTF8, $false)
    try {
        if ($stream.Length -lt 32) { throw 'The Valheim .fwl2 header is too short.' }
        $packageLength = $reader.ReadInt32()
        $worldVersion = $reader.ReadInt32()
        if ($packageLength -lt 1 -or $packageLength -gt ($stream.Length - 4)) { throw 'The Valheim .fwl2 package length is invalid.' }
        if ($worldVersion -lt 1) { throw 'The Valheim world version is invalid.' }
        $name = $reader.ReadString()
        $seedName = $reader.ReadString()
        $seed = $reader.ReadInt32()
        $worldUidValue = $reader.ReadInt64()
        $worldGenVersion = $reader.ReadInt32()
        return [pscustomobject]@{
            PackageLength = $packageLength
            WorldVersion = $worldVersion
            Name = $name
            SeedName = $seedName
            Seed = $seed
            WorldUid = $worldUidValue.ToString([Globalization.CultureInfo]::InvariantCulture)
            WorldGenVersion = $worldGenVersion
        }
    }
    catch [IO.EndOfStreamException] { throw 'The Valheim .fwl2 header ended unexpectedly.' }
    finally { $reader.Dispose() }
}

function Get-WorldsLocalRoot { return Join-Path ([string]$script:Config.SaveRoot) 'worlds_local' }
function Get-WorldFolderPath { return Join-Path (Get-WorldsLocalRoot) ([string]$script:Config.WorldName) }

function Get-ValheimWorldIdentity {
    param([string]$WorldPath = (Get-WorldFolderPath))
    if (-not (Test-Path -LiteralPath $WorldPath -PathType Container)) { return $null }
    $expectedWorldName = $null
    $configVariable = Get-Variable -Name Config -Scope Script -ErrorAction SilentlyContinue
    if ($null -ne $configVariable -and $null -ne $configVariable.Value -and $null -ne $configVariable.Value.PSObject.Properties['WorldName']) {
        $configuredWorldName = [string]$configVariable.Value.WorldName
        if (-not [string]::IsNullOrWhiteSpace($configuredWorldName)) { $expectedWorldName = $configuredWorldName }
    }
    $complete = [Collections.Generic.List[object]]::new()
    $okGenerations = [Collections.Generic.HashSet[long]]::new()
    foreach ($file in Get-ChildItem -LiteralPath $WorldPath -File -Filter '_main.*.ok' -ErrorAction SilentlyContinue) {
        if ($file.Name -match '^_main\.(\d+)\.ok$') { [void]$okGenerations.Add([long]$Matches[1]) }
    }
    foreach ($generation in $okGenerations) {
        $prefix = "_main.$generation"
        $missing = @(@('db2','fwl2','chunks','ok') | Where-Object { -not (Test-Path -LiteralPath (Join-Path $WorldPath "$prefix.$_") -PathType Leaf) })
        if ($missing.Count -gt 0) { throw "Committed generation $generation is incomplete; missing: $($missing -join ', ')." }
        $header = Read-ValheimWorldHeader -Path (Join-Path $WorldPath "$prefix.fwl2")
        if ([string]::IsNullOrWhiteSpace($expectedWorldName)) { $expectedWorldName = [string]$header.Name }
        elseif ([string]$header.Name -ne $expectedWorldName) { throw "The .fwl2 world name '$($header.Name)' does not match expected WorldName '$expectedWorldName'." }
        $complete.Add([pscustomobject]@{ Generation=[long]$generation; Header=$header })
    }
    if ($complete.Count -eq 0) { throw "No complete Valheim 1.0 world generation exists in '$WorldPath'. Old .db/.fwl saves are not supported by this adapter." }
    $uids = @($complete | ForEach-Object { Normalize-WorldUid ([string]$_.Header.WorldUid) } | Select-Object -Unique)
    if ($uids.Count -ne 1) { throw 'The Valheim world directory contains complete generations with different World UIDs; refusing to choose one automatically.' }
    $selected = $complete | Sort-Object Generation -Descending | Select-Object -First 1
    return [pscustomobject]@{
        Path = $WorldPath
        Generation = [long]$selected.Generation
        WorldUid = $uids[0]
        WorldName = $expectedWorldName
        WorldVersion = [int]$selected.Header.WorldVersion
        WorldGenVersion = [int]$selected.Header.WorldGenVersion
        SeedName = [string]$selected.Header.SeedName
    }
}

function Get-CommittedWorldSnapshot { param([string]$WorldPath = (Get-WorldFolderPath)) return Get-ValheimWorldIdentity -WorldPath $WorldPath }

function Test-SafeZipEntryName {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    $normalized = $Name.Replace('\','/')
    if ($normalized.StartsWith('/') -or $normalized -match '^[A-Za-z]:') { return $false }
    $parts = $normalized.Split('/')
    for ($index = 0; $index -lt $parts.Length; $index++) {
        $part = $parts[$index]
        if ([string]::IsNullOrEmpty($part)) {
            if ($index -eq ($parts.Length - 1) -and $normalized.EndsWith('/')) { continue }
            return $false
        }
        if ($part -in @('.', '..') -or $part -ne $part.Trim() -or $part.EndsWith('.') -or $part.EndsWith(' ')) { return $false }
        if ($part.IndexOfAny([IO.Path]::GetInvalidFileNameChars()) -ge 0) { return $false }
        $deviceBase = ($part -split '\.', 2)[0]
        if ($deviceBase -match '^(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$') { return $false }
    }
    return $true
}

function Read-ArchiveManifest {
    param([string]$ZipPath)
    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $entry = $archive.GetEntry('manifest.json')
        if ($null -eq $entry) { throw 'The ZIP does not contain manifest.json.' }
        $reader = [IO.StreamReader]::new($entry.Open(), [Text.Encoding]::UTF8, $true)
        try { $manifest = ($reader.ReadToEnd() | ConvertFrom-Json) } finally { $reader.Dispose() }
        if ([string]$manifest.gameKey -ne 'valheim') { throw 'The ZIP manifest is not a Valheim save.' }
        if ([int]$manifest.schemaVersion -ne 1) { throw 'Unsupported Valheim archive manifest version.' }
        if ([string]$manifest.worldName -ne [string]$script:Config.WorldName) { throw 'The ZIP worldName does not match config.json.' }
        $uid = Normalize-WorldUid -WorldUid ([string]$manifest.worldUid)
        $prefix = 'world/'
        $hasFwl2 = $false; $hasDb2 = $false; $hasChunks = $false; $hasOk = $false
        $generation = [int64]$manifest.committedGeneration
        foreach ($archiveEntry in $archive.Entries) {
            if (-not (Test-SafeZipEntryName -Name $archiveEntry.FullName)) { throw "Unsafe ZIP entry: $($archiveEntry.FullName)" }
            if ($archiveEntry.FullName -eq 'manifest.json') { continue }
            if (-not $archiveEntry.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw "The ZIP contains an entry outside world/: $($archiveEntry.FullName)" }
            if ($archiveEntry.FullName.Equals("world/_main.$generation.fwl2", [StringComparison]::OrdinalIgnoreCase)) { $hasFwl2 = $true }
            if ($archiveEntry.FullName.Equals("world/_main.$generation.db2", [StringComparison]::OrdinalIgnoreCase)) { $hasDb2 = $true }
            if ($archiveEntry.FullName.Equals("world/_main.$generation.chunks", [StringComparison]::OrdinalIgnoreCase)) { $hasChunks = $true }
            if ($archiveEntry.FullName.Equals("world/_main.$generation.ok", [StringComparison]::OrdinalIgnoreCase)) { $hasOk = $true }
        }
        if (-not ($hasFwl2 -and $hasDb2 -and $hasChunks -and $hasOk)) { throw 'The ZIP does not contain a complete committed Valheim generation.' }
        $manifest.worldUid = $uid
        return $manifest
    }
    finally { $archive.Dispose() }
}

function New-WorldArchive {
    param([string]$WorldPath = (Get-WorldFolderPath), [string]$Destination, [int]$BaseVersion, [string]$Purpose)
    $snapshot = Get-ValheimWorldIdentity -WorldPath $WorldPath
    if ($null -eq $snapshot) { throw "The configured Valheim world does not exist: $(Get-WorldFolderPath)" }
    $parent = Split-Path -Parent $Destination
    Ensure-Directory -Path $parent
    $temporary = "$Destination.part"
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue
    $stream = [IO.FileStream]::new($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $archive = [IO.Compression.ZipArchive]::new($stream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        $manifest = [ordered]@{
            schemaVersion = 1
            gameKey = 'valheim'
            clientVersion = $ClientVersion
            worldName = [string]$script:Config.WorldName
            worldUid = [string]$snapshot.WorldUid
            saveFormat = 'chunked-1.0'
            committedGeneration = [int64]$snapshot.Generation
            valheimWorldVersion = [int]$snapshot.WorldVersion
            worldGenVersion = [int]$snapshot.WorldGenVersion
            baseVersion = $BaseVersion
            createdBy = [string]$script:Config.PlayerName
            clientId = [string]$script:Config.ClientId
            createdAtUtc = [DateTime]::UtcNow.ToString('o')
            purpose = $Purpose
            includedPath = 'world'
        }
        $manifestEntry = $archive.CreateEntry('manifest.json', [IO.Compression.CompressionLevel]::Optimal)
        $writer = [IO.StreamWriter]::new($manifestEntry.Open(), [Text.UTF8Encoding]::new($false))
        try { $writer.Write(($manifest | ConvertTo-Json -Depth 8)) } finally { $writer.Dispose() }
        foreach ($file in Get-ChildItem -LiteralPath $snapshot.Path -File -Recurse) {
            $relative = $file.FullName.Substring($snapshot.Path.Length).TrimStart([char[]]@('\','/')).Replace('\','/')
            if (-not (Test-SafeZipEntryName -Name $relative)) { throw "Unsafe world file path: $relative" }
            [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, "world/$relative", [IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally { $archive.Dispose(); $stream.Dispose() }
    $validated = Read-ArchiveManifest -ZipPath $temporary
    if ((Normalize-WorldUid -WorldUid ([string]$validated.worldUid)) -ne [string]$snapshot.WorldUid) { throw 'Archive identity validation failed.' }
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
    return [pscustomobject]@{ Path = $Destination; Sha256 = Get-Sha256 -Path $Destination; Size = (Get-Item -LiteralPath $Destination).Length; WorldUid = [string]$snapshot.WorldUid; Generation = [int64]$snapshot.Generation }
}

function Remove-OldLocalBackups {
    $retention = [int]$script:Config.LocalBackupRetention
    if ($retention -lt 1) { return }
    $all = @(Get-ChildItem -LiteralPath $BackupRoot -Filter '*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending)
    if ($all.Count -le $retention) { return }
    foreach ($old in $all[$retention..($all.Count - 1)]) { Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue }
}

function Backup-LocalWorld {
    param([string]$Reason, [int]$BaseVersion)
    if (-not (Test-Path -LiteralPath (Get-WorldFolderPath) -PathType Container)) { return $null }
    $safeReason = ($Reason -replace '[^A-Za-z0-9_-]', '_')
    $destination = Join-Path $BackupRoot ('{0}_{1}_{2}.zip' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $safeReason, [string]$script:Config.WorldName)
    Write-Info "Creating local backup: $([IO.Path]::GetFileName($destination))"
    $result = New-WorldArchive -Destination $destination -BaseVersion $BaseVersion -Purpose "local-backup-$Reason"
    Remove-OldLocalBackups
    return $result
}

function Expand-WorldArchive {
    param([string]$ZipPath, [string]$DestinationWorldPath)
    Ensure-Directory -Path $DestinationWorldPath
    $root = [IO.Path]::GetFullPath($DestinationWorldPath).TrimEnd('\') + '\'
    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -eq 'manifest.json') { continue }
            if (-not $entry.FullName.StartsWith('world/', [StringComparison]::OrdinalIgnoreCase)) { continue }
            $relative = $entry.FullName.Substring(6).Replace('/', '\')
            if ([string]::IsNullOrWhiteSpace($relative)) { continue }
            $destination = [IO.Path]::GetFullPath((Join-Path $DestinationWorldPath $relative))
            if (-not $destination.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe extraction path: $($entry.FullName)" }
            if ($entry.FullName.EndsWith('/')) { Ensure-Directory -Path $destination; continue }
            Ensure-Directory -Path (Split-Path -Parent $destination)
            $input = $entry.Open()
            $output = [IO.FileStream]::new($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    }
    finally { $archive.Dispose() }
}

function Install-DownloadedSave {
    param([string]$ZipPath, [string]$ExpectedWorldUid)
    $manifest = Read-ArchiveManifest -ZipPath $ZipPath
    $expected = Normalize-WorldUid -WorldUid $ExpectedWorldUid
    if ((Normalize-WorldUid -WorldUid ([string]$manifest.worldUid)) -ne $expected) { throw 'Downloaded manifest World UID does not match the remote authority.' }
    $worldsRoot = Get-WorldsLocalRoot
    Ensure-Directory -Path $worldsRoot
    $target = Get-WorldFolderPath
    $stagingRoot = Join-Path $worldsRoot ('.save-sync-staging-' + [Guid]::NewGuid().ToString('N'))
    $stagedWorld = Join-Path $stagingRoot ([string]$script:Config.WorldName)
    $rollback = Join-Path $worldsRoot ('.save-sync-rollback-' + [Guid]::NewGuid().ToString('N'))
    try {
        Expand-WorldArchive -ZipPath $ZipPath -DestinationWorldPath $stagedWorld
        $staged = Get-CommittedWorldSnapshot -WorldPath $stagedWorld
        if ($null -eq $staged -or [string]$staged.WorldUid -ne $expected) { throw 'The extracted Valheim world failed identity validation.' }
        if ([int64]$staged.Generation -ne [int64]$manifest.committedGeneration) { throw 'The extracted Valheim committed generation does not match the manifest.' }
        if (Test-Path -LiteralPath $target -PathType Container) { Move-Item -LiteralPath $target -Destination $rollback }
        try {
            Move-Item -LiteralPath $stagedWorld -Destination $target
            $installed = Get-CommittedWorldSnapshot -WorldPath $target
            if ($null -eq $installed -or [string]$installed.WorldUid -ne $expected) { throw 'Installed Valheim world failed post-install identity validation.' }
            if ([int64]$installed.Generation -ne [int64]$manifest.committedGeneration) { throw 'Installed Valheim generation does not match the manifest.' }
        }
        catch {
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue }
            if (Test-Path -LiteralPath $rollback) { Move-Item -LiteralPath $rollback -Destination $target }
            throw
        }
        if (Test-Path -LiteralPath $rollback) {
            try { Remove-Item -LiteralPath $rollback -Recurse -Force }
            catch { Write-Log -Level 'warning' -Message "Installed world is valid, but rollback cleanup failed: $($_.Exception.Message)" }
        }
    }
    finally { if (Test-Path -LiteralPath $stagingRoot) { Remove-Item -LiteralPath $stagingRoot -Recurse -Force -ErrorAction SilentlyContinue } }
}

function Download-LatestSave {
    param([string]$Token, [string]$Destination)
    $uri = ('{0}/download' -f ([string]$script:Config.ApiBaseUrl).TrimEnd('/'))
    $partial = "$Destination.part"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Token)
    $client.DefaultRequestHeaders.Accept.Add([System.Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new('application/zip'))
    $response = $null; $inputStream = $null; $outputStream = $null
    try {
        $response = $client.GetAsync($uri, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            throw (New-HttpFailure -Message "Save download failed (HTTP $([int]$response.StatusCode)). $text" -StatusCode ([int]$response.StatusCode) -ResponseBody $text)
        }
        $versionHeader = Get-HeaderValue -Response $response -Name 'X-Save-Sync-Version'
        $shaHeader = Get-HeaderValue -Response $response -Name 'X-Save-Sync-SHA256'
        $identityHeader = Get-HeaderValue -Response $response -Name 'X-Save-Sync-Identity'
        if ($versionHeader -notmatch '^\d+$') { throw 'The download does not include a valid X-Save-Sync-Version.' }
        if ($shaHeader -notmatch '^[A-Fa-f0-9]{64}$') { throw 'The download does not include a valid X-Save-Sync-SHA256.' }
        $identity = Normalize-WorldUid -WorldUid $identityHeader
        $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $outputStream = [IO.FileStream]::new($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $inputStream.CopyTo($outputStream); $outputStream.Flush(); $outputStream.Dispose(); $outputStream = $null; $inputStream.Dispose(); $inputStream = $null
        $actual = Get-Sha256 -Path $partial
        if ($actual -ne $shaHeader.ToLowerInvariant()) { throw "Download SHA-256 mismatch. Expected $shaHeader; got $actual." }
        Move-Item -LiteralPath $partial -Destination $Destination -Force
        return [pscustomobject]@{ Version = [int]$versionHeader; Sha256 = $actual; WorldUid = $identity; Path = $Destination }
    }
    finally {
        if ($null -ne $outputStream) { $outputStream.Dispose() }; if ($null -ne $inputStream) { $inputStream.Dispose() }; if ($null -ne $response) { $response.Dispose() }
        $client.Dispose(); $handler.Dispose(); if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
    }
}

function Add-MultipartString {
    param([System.Net.Http.MultipartFormDataContent]$Multipart, [string]$Name, [string]$Value)
    $Multipart.Add([System.Net.Http.StringContent]::new($Value, [Text.Encoding]::UTF8), $Name)
}

function Upload-SaveArchive {
    param([string]$Token, [string]$ZipPath, [string]$SessionId, [int]$BaseVersion, [string]$Sha256, [string]$WorldUid)
    $uri = ('{0}/upload' -f ([string]$script:Config.ApiBaseUrl).TrimEnd('/'))
    $handler = [System.Net.Http.HttpClientHandler]::new(); $client = [System.Net.Http.HttpClient]::new($handler); $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Token)
    $multipart = [System.Net.Http.MultipartFormDataContent]::new(); $fileStream = $null; $fileContent = $null; $response = $null
    try {
        $fileStream = [IO.FileStream]::new($ZipPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $fileContent = [System.Net.Http.StreamContent]::new($fileStream); $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/zip')
        $multipart.Add($fileContent, 'file', [IO.Path]::GetFileName($ZipPath))
        Add-MultipartString $multipart 'sessionId' $SessionId
        Add-MultipartString $multipart 'baseVersion' ([string]$BaseVersion)
        Add-MultipartString $multipart 'sha256' $Sha256
        Add-MultipartString $multipart 'worldUid' (Normalize-WorldUid $WorldUid)
        Add-MultipartString $multipart 'saveIdentity' (Normalize-WorldUid $WorldUid)
        Add-MultipartString $multipart 'owner' ([string]$script:Config.PlayerName)
        $response = $client.PostAsync($uri, $multipart).GetAwaiter().GetResult(); $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) { throw (New-HttpFailure -Message "Upload failed (HTTP $([int]$response.StatusCode)). $text" -StatusCode ([int]$response.StatusCode) -ResponseBody $text) }
        return ($text | ConvertFrom-Json)
    }
    finally { if ($null -ne $response) { $response.Dispose() }; if ($null -ne $fileContent) { $fileContent.Dispose() }; if ($null -ne $fileStream) { $fileStream.Dispose() }; $multipart.Dispose(); $client.Dispose(); $handler.Dispose() }
}

function Get-HeartbeatRequestTimeoutSeconds {
    param([int]$IntervalSeconds)
    return [int][Math]::Max(1, [Math]::Min(30, [Math]::Floor($IntervalSeconds / 2.0)))
}

function Get-ShutdownSafetyReserveSeconds {
    # Fail closed early enough that a controlled shutdown can finish before
    # another host is allowed to acquire the same lease after TTL expiry.
    return [int]$script:Config.ShutdownTimeoutSeconds +
        [int]$script:Config.PostExitGraceSeconds + 10
}

function Start-HeartbeatJob {
    param([string]$ApiBaseUrl, [string]$Token, [string]$SessionId, [int]$IntervalSeconds, [string]$StateFile, [string]$InitialExpiresAt)
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    Write-JsonAtomic -Path $StateFile -Value ([ordered]@{ status='pending'; expiresAt=$InitialExpiresAt; consecutiveFailures=0; startedAtUtc=[DateTime]::UtcNow.ToString('o') })
    $requestTimeoutSeconds = Get-HeartbeatRequestTimeoutSeconds -IntervalSeconds $IntervalSeconds
    return Start-Job -ScriptBlock {
        param($ApiBaseUrl, $Token, $SessionId, $IntervalSeconds, $StateFile, $InitialExpiresAt, $RequestTimeoutSeconds)
        $ErrorActionPreference = 'Stop'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $failures = 0; $lastExpiresAt = $InitialExpiresAt
        while ($true) {
            Start-Sleep -Seconds $IntervalSeconds
            try {
                $response = Invoke-RestMethod -Uri ($ApiBaseUrl.TrimEnd('/') + '/heartbeat') -Method Post -TimeoutSec $RequestTimeoutSeconds -Headers @{ Authorization = "Bearer $Token"; Accept = 'application/json' } -ContentType 'application/json' -Body (@{ sessionId = $SessionId } | ConvertTo-Json -Compress)
                if ([string]::IsNullOrWhiteSpace([string]$response.expiresAt)) { throw 'Heartbeat response did not include expiresAt.' }
                $lastExpiresAt = [string]$response.expiresAt
                $failures = 0
                [IO.File]::WriteAllText($StateFile, (@{ status='ok'; lastSuccessUtc=[DateTime]::UtcNow.ToString('o'); expiresAt=$lastExpiresAt; consecutiveFailures=0 } | ConvertTo-Json -Compress))
            }
            catch {
                $statusCode = 0
                try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}
                $terminal = $statusCode -ge 400 -and $statusCode -lt 500 -and $statusCode -notin @(408,429)
                if ($terminal) { $failures = 3 } else { $failures++ }
                $status = if ($terminal -or $failures -ge 3) { 'fatal' } else { 'degraded' }
                [IO.File]::WriteAllText($StateFile, (@{ status=$status; lastFailureUtc=[DateTime]::UtcNow.ToString('o'); expiresAt=$lastExpiresAt; consecutiveFailures=$failures; httpStatus=$statusCode; message=$_.Exception.Message } | ConvertTo-Json -Compress))
                if ($terminal -or $failures -ge 3) { throw }
            }
        }
    } -ArgumentList $ApiBaseUrl, $Token, $SessionId, $IntervalSeconds, $StateFile, $InitialExpiresAt, $requestTimeoutSeconds
}

function Assert-PendingSessionMatchesLock {
    param([object]$Pending, [object]$Lock)
    if ($null -eq $Pending) { return }
    if ([int]$Pending.baseVersion -ne [int]$Lock.baseVersion) {
        throw "The remote version changed while acquiring the lock (pending base $($Pending.baseVersion), lock base $($Lock.baseVersion)). Manual recovery is required."
    }
    if ([int]$Lock.baseVersion -gt 0) {
        $pendingUid = Normalize-WorldUid -WorldUid ([string]$Pending.worldUid)
        $lockUid = Normalize-WorldUid -WorldUid ([string]$Lock.worldUid)
        if ($pendingUid -ne $lockUid) { throw 'The pending Valheim session World UID does not match the newly acquired lock.' }
    }
}

function Assert-HeartbeatFitsLockTtl {
    param([object]$Lock, [int]$IntervalSeconds)
    if ($IntervalSeconds -lt 1) { throw 'HeartbeatSeconds must be at least 1.' }
    if ($null -eq $Lock.PSObject.Properties['expiresAt'] -or [string]::IsNullOrWhiteSpace([string]$Lock.expiresAt)) {
        throw 'The lock response does not include expiresAt; safe heartbeat timing cannot be verified.'
    }
    try {
        $expiresAt = [DateTimeOffset]::Parse([string]$Lock.expiresAt, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
    }
    catch { throw 'The lock response contains an invalid expiresAt value.' }
    $remainingSeconds = ($expiresAt - [DateTimeOffset]::UtcNow).TotalSeconds
    if ($remainingSeconds -le 5) { throw 'The acquired lock is already too close to expiry.' }
    $requestTimeoutSeconds = Get-HeartbeatRequestTimeoutSeconds -IntervalSeconds $IntervalSeconds
    $shutdownReserveSeconds = Get-ShutdownSafetyReserveSeconds
    if (($IntervalSeconds + $requestTimeoutSeconds + $shutdownReserveSeconds) -ge ($remainingSeconds - 5)) {
        throw "HeartbeatSeconds=$IntervalSeconds is too large for the acquired lock TTL; one heartbeat attempt plus the clean-shutdown safety reserve must fit before expiry."
    }
}

function Get-HeartbeatStatus {
    param([System.Management.Automation.Job]$Job, [string]$StateFile = $HeartbeatStatePath)
    if ($null -ne $Job -and $Job.State -in @('Failed','Stopped','Completed')) { return 'fatal' }
    if (Test-Path -LiteralPath $StateFile -PathType Leaf) {
        try {
            $state = Read-JsonFile $StateFile
            if ($null -eq $state -or $null -eq $state.PSObject.Properties['expiresAt'] -or [string]::IsNullOrWhiteSpace([string]$state.expiresAt)) { return 'fatal' }
            $expiresAt = [DateTimeOffset]::Parse([string]$state.expiresAt, [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::RoundtripKind)
            if (($expiresAt - [DateTimeOffset]::UtcNow).TotalSeconds -le (Get-ShutdownSafetyReserveSeconds)) { return 'fatal' }
            return [string]$state.status
        }
        catch { return 'fatal' }
    }
    return 'pending'
}

function Assert-HeartbeatCanContinue {
    param([System.Management.Automation.Job]$Job, [string]$Context, [string]$StateFile = $HeartbeatStatePath)
    if ((Get-HeartbeatStatus -Job $Job -StateFile $StateFile) -eq 'fatal') {
        throw "The remote lock is no longer reliable during $Context. Local changes will not be started or published automatically."
    }
}

function Stop-HeartbeatJob {
    param([System.Management.Automation.Job]$Job)
    if ($null -ne $Job) { Stop-Job -Job $Job -ErrorAction SilentlyContinue; Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue }
    Remove-Item -LiteralPath $HeartbeatStatePath -Force -ErrorAction SilentlyContinue
}

function Initialize-WindowsProcessGroupSupport {
    if ($null -ne ('SaveSync.ValheimProcessGroup' -as [type])) { return }
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace SaveSync {
    public static class ValheimProcessGroup {
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
        struct STARTUPINFO {
            public int cb; public string lpReserved; public string lpDesktop; public string lpTitle;
            public int dwX; public int dwY; public int dwXSize; public int dwYSize; public int dwXCountChars; public int dwYCountChars;
            public int dwFillAttribute; public int dwFlags; public short wShowWindow; public short cbReserved2; public IntPtr lpReserved2;
            public IntPtr hStdInput; public IntPtr hStdOutput; public IntPtr hStdError;
        }
        [StructLayout(LayoutKind.Sequential)]
        struct PROCESS_INFORMATION { public IntPtr hProcess; public IntPtr hThread; public uint dwProcessId; public uint dwThreadId; }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        static extern bool CreateProcessW(string applicationName, string commandLine, IntPtr processAttributes, IntPtr threadAttributes,
            bool inheritHandles, uint creationFlags, IntPtr environment, string currentDirectory, ref STARTUPINFO startupInfo, out PROCESS_INFORMATION processInformation);
        [DllImport("kernel32.dll", SetLastError = true)] static extern bool CloseHandle(IntPtr handle);
        const uint CREATE_NEW_PROCESS_GROUP = 0x00000200;
        const uint CREATE_NEW_CONSOLE = 0x00000010;
        const int STARTF_USESHOWWINDOW = 0x00000001;
        const short SW_HIDE = 0;

        public static int Start(string executable, string commandLine, string workingDirectory) {
            var si = new STARTUPINFO();
            si.cb = Marshal.SizeOf(si);
            si.dwFlags = STARTF_USESHOWWINDOW;
            si.wShowWindow = SW_HIDE;
            PROCESS_INFORMATION pi;
            if (!CreateProcessW(executable, commandLine, IntPtr.Zero, IntPtr.Zero, false, CREATE_NEW_PROCESS_GROUP | CREATE_NEW_CONSOLE, IntPtr.Zero, workingDirectory, ref si, out pi))
                throw new Win32Exception(Marshal.GetLastWin32Error());
            try { return checked((int)pi.dwProcessId); }
            finally { CloseHandle(pi.hThread); CloseHandle(pi.hProcess); }
        }
    }
}
'@
}

function Quote-WindowsArgument {
    param([string]$Value)
    if ($null -eq $Value) { return ([string][char]34 + [char]34) }
    if ($Value.Length -gt 0 -and $Value -notmatch '[\s"]') { return $Value }
    $builder = [Text.StringBuilder]::new(); [void]$builder.Append([char]34); $slashes = 0
    foreach ($char in $Value.ToCharArray()) {
        if ($char -eq '\') { $slashes++; continue }
        if ($char -eq [char]34) { [void]$builder.Append(('\' * ($slashes * 2 + 1))); [void]$builder.Append([char]34); $slashes = 0; continue }
        if ($slashes -gt 0) { [void]$builder.Append(('\' * $slashes)); $slashes = 0 }
        [void]$builder.Append($char)
    }
    if ($slashes -gt 0) { [void]$builder.Append(('\' * ($slashes * 2))) }
    [void]$builder.Append([char]34); return $builder.ToString()
}

function Start-ValheimServer {
    param([string]$Password, [string]$ServerLogPath)
    Initialize-WindowsProcessGroupSupport
    $args = @('-nographics','-batchmode','-name',[string]$script:Config.ServerName,'-port',[string][int]$script:Config.ServerPort,'-world',[string]$script:Config.WorldName,'-password',$Password,'-savedir',[string]$script:Config.SaveRoot,'-public',$(if ([bool]$script:Config.Public) {'1'} else {'0'}),'-logFile',$ServerLogPath)
    if ($null -ne $script:Config.PSObject.Properties['Crossplay'] -and [bool]$script:Config.Crossplay) { $args += '-crossplay' }
    if ($null -ne $script:Config.PSObject.Properties['ServerArguments'] -and $null -ne $script:Config.ServerArguments) { $args += @($script:Config.ServerArguments | ForEach-Object { [string]$_ }) }
    $commandLine = (Quote-WindowsArgument ([string]$script:Config.ServerExecutable)) + ' ' + (($args | ForEach-Object { Quote-WindowsArgument $_ }) -join ' ')
    $previousSteamAppId = [Environment]::GetEnvironmentVariable('SteamAppId', [EnvironmentVariableTarget]::Process)
    try {
        # Valheim's stock Windows dedicated-server launcher sets the parent-game
        # Steam App ID before starting app 896660. The child inherits this process
        # environment at CreateProcess time; restore our own environment immediately.
        [Environment]::SetEnvironmentVariable('SteamAppId', '892970', [EnvironmentVariableTarget]::Process)
        $processId = [SaveSync.ValheimProcessGroup]::Start([string]$script:Config.ServerExecutable, $commandLine, [string]$script:Config.ServerRoot)
    }
    finally {
        [Environment]::SetEnvironmentVariable('SteamAppId', $previousSteamAppId, [EnvironmentVariableTarget]::Process)
    }
    return [Diagnostics.Process]::GetProcessById($processId)
}

function Wait-ForValheimReady {
    param([Diagnostics.Process]$Process, [string]$ServerLogPath, [System.Management.Automation.Job]$HeartbeatJob)
    $deadline = (Get-Date).AddSeconds([int]$script:Config.StartupTimeoutSeconds); $pattern = [string]$script:Config.StartupReadyPattern
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh(); if ($Process.HasExited) { throw 'valheim_server.exe exited before startup completed.' }
        if ((Get-HeartbeatStatus $HeartbeatJob) -eq 'fatal') { throw 'The web lock was lost during Valheim startup.' }
        if (Test-Path -LiteralPath $ServerLogPath -PathType Leaf) {
            $text = Get-Content -LiteralPath $ServerLogPath -Raw -ErrorAction SilentlyContinue
            if (-not [string]::IsNullOrWhiteSpace($text) -and $text -match [regex]::Escape($pattern)) { return }
        }
        Start-Sleep -Seconds 2
    }
    throw "Valheim did not emit the configured startup marker '$pattern' before timeout."
}

function Stop-ValheimGracefully {
    param([Diagnostics.Process]$Process)
    $Process.Refresh(); if ($Process.HasExited) { throw 'Valheim exited before a controlled shutdown could be requested.' }
    Write-Info 'Requesting clean Valheim shutdown with CTRL+C...'
    $helperPath = Join-Path $TempRoot ("ctrlc-{0}.exe" -f [Guid]::NewGuid().ToString('N'))
    $helperSource = @'
using System;
using System.Runtime.InteropServices;
using System.Threading;

public static class SaveSyncCtrlC {
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool FreeConsole();
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AttachConsole(uint processId);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetConsoleCtrlHandler(IntPtr handlerRoutine, bool add);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GenerateConsoleCtrlEvent(uint ctrlEvent, uint processGroupId);

    public static int Main(string[] args) {
        uint pid;
        if (args.Length != 1 || !UInt32.TryParse(args[0], out pid)) return 30;
        FreeConsole();
        if (!AttachConsole(pid)) return 31;
        if (!SetConsoleCtrlHandler(IntPtr.Zero, true)) return 32;
        if (!GenerateConsoleCtrlEvent(0, 0)) return 33;
        Thread.Sleep(250);
        FreeConsole();
        return 0;
    }
}
'@
    try {
        Add-Type -TypeDefinition $helperSource -OutputAssembly $helperPath -OutputType ConsoleApplication
        $signal = Start-Process -FilePath $helperPath -ArgumentList ([string]$Process.Id) -WindowStyle Hidden -Wait -PassThru
        if ($signal.ExitCode -ne 0) { throw "Could not deliver CTRL+C to Valheim (signal helper exit code $($signal.ExitCode))." }
    }
    finally {
        if (Test-Path -LiteralPath $helperPath -PathType Leaf) { Remove-Item -LiteralPath $helperPath -Force -ErrorAction SilentlyContinue }
    }
    $deadline = (Get-Date).AddSeconds([int]$script:Config.ShutdownTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 500; $Process.Refresh()
        if ($Process.HasExited) {
            Start-Sleep -Seconds ([int]$script:Config.PostExitGraceSeconds)
            Write-Success 'Valheim shut down cleanly.'
            return
        }
    }
    throw 'Valheim did not exit after CTRL+C. The process will not be killed and the save will not be published.'
}

function Wait-ForSessionEndRequest {
    param([Diagnostics.Process]$Process, [System.Management.Automation.Job]$HeartbeatJob)
    Write-Host ''; Write-Host 'Server active. Press ENTER in this window to stop cleanly and synchronize.' -ForegroundColor Green
    Write-Host 'Do not close this PowerShell window while the server is running.'
    while ($true) {
        $Process.Refresh(); if ($Process.HasExited) { return [pscustomobject]@{ Reason='ProcessExited'; HeartbeatValid=$true } }
        if ((Get-HeartbeatStatus $HeartbeatJob) -eq 'fatal') { return [pscustomobject]@{ Reason='HeartbeatFailed'; HeartbeatValid=$false } }
        try { if (-not [Console]::IsInputRedirected -and [Console]::KeyAvailable -and [Console]::ReadKey($true).Key -eq [ConsoleKey]::Enter) { return [pscustomobject]@{ Reason='UserRequested'; HeartbeatValid=$true } } } catch {}
        Start-Sleep -Milliseconds 500
    }
}

function Save-LocalState {
    param([int]$Version, [string]$WorldUid, [string]$Sha256, [string]$UpdatedBy)
    Write-JsonAtomic -Path $StatePath -Value ([ordered]@{ schemaVersion=1; gameKey='valheim'; version=$Version; worldUid=(Normalize-WorldUid $WorldUid); sha256=$Sha256; updatedBy=$UpdatedBy; updatedAtUtc=[DateTime]::UtcNow.ToString('o') })
}

function Save-PendingSession {
    param([int]$BaseVersion, [string]$WorldUid, [string]$SessionId, [string]$ArchivePath=$null, [string]$ArchiveSha256=$null)
    Write-JsonAtomic -Path $PendingPath -Value ([ordered]@{ schemaVersion=1; gameKey='valheim'; baseVersion=$BaseVersion; worldUid=(Normalize-WorldUid $WorldUid); owner=[string]$script:Config.PlayerName; clientId=[string]$script:Config.ClientId; startedAtUtc=[DateTime]::UtcNow.ToString('o'); sessionIdHint=$(if ($SessionId.Length -ge 8) {$SessionId.Substring(0,8)} else {'redacted'}); archivePath=$ArchivePath; archiveSha256=$ArchiveSha256 })
}

function Reconcile-Upload {
    param([string]$Token, [int]$BaseVersion, [string]$Sha256, [string]$WorldUid)
    try {
        $status = Invoke-ApiJson GET 'status' $Token
        return [bool]$status.initialized -and [int]$status.version -eq ($BaseVersion + 1) -and ([string]$status.sha256).ToLowerInvariant() -eq $Sha256.ToLowerInvariant() -and (Normalize-WorldUid ([string]$status.worldUid)) -eq (Normalize-WorldUid $WorldUid) -and ([string]$status.updatedBy).Equals([string]$script:Config.PlayerName, [StringComparison]::OrdinalIgnoreCase)
    }
    catch { Write-Log -Level 'warning' -Message "Could not reconcile upload: $($_.Exception.Message)"; return $false }
}

function Unlock-Session {
    param([string]$Token, [string]$SessionId)
    try { [void](Invoke-ApiJson POST 'unlock' $Token @{ sessionId=$SessionId }); Write-Success 'Lock released.'; return $true }
    catch { Write-WarningText "Could not release the lock: $($_.Exception.Message)"; return $false }
}

function Test-Environment {
    param([object]$Secrets)
    Write-Info 'Testing web API...'; $status = Invoke-ApiJson GET 'status' $Secrets.ApiToken
    Write-Success ("Web API reachable. Remote version: {0}; initialized: {1}; worldUid: {2}" -f $status.version, $status.initialized, $status.worldUid)
    $local = Get-CommittedWorldSnapshot
    if ($null -ne $local) { Write-Success ("Local Valheim 1.0 world verified. UID: {0}; generation: {1}; world version: {2}" -f $local.WorldUid, $local.Generation, $local.WorldVersion) }
    else { Write-WarningText 'The configured local world does not exist yet.' }
}

if ($LibraryOnly) { return }

foreach ($directory in @($DataRoot,$BackupRoot,$DownloadRoot,$PendingUploadRoot,$TempRoot,$LogRoot)) { Ensure-Directory $directory }
$script:Config = $null; $secrets = $null; $heartbeatJob = $null; $serverProcess = $null; $scriptExitCode = 0
$lockHeld = $false; $sessionEntered = $false; $uploadConfirmed = $false; $sessionId = $null; $baseVersion = -1; $worldUid = $null; $finalArchive = $null

try {
    Write-Info "Valheim Sync Client $ClientVersion"
    if ($PSVersionTable.PSVersion.Major -lt 5) { throw 'Windows PowerShell 5.1 or later is required.' }
    if ($env:OS -ne 'Windows_NT') { throw 'This adapter is designed for Windows.' }
    $script:Config = Load-AndValidateConfig
    if ($SetupSecrets) { Initialize-Secrets; Write-Host ''; Write-Success 'Configuration complete.'; return }
    $secrets = Get-Secrets
    if ($TestOnly) { Test-Environment $secrets; return }
    if ($null -ne (Get-Process -Name 'valheim_server' -ErrorAction SilentlyContinue)) { throw 'valheim_server.exe is already running. Close it before using Save Sync.' }

    Write-Info 'Checking remote status...'; $status = Invoke-ApiJson GET 'status' $secrets.ApiToken
    Write-Info ("Remote: version {0}; initialized={1}; lock={2}; worldUid={3}" -f $status.version, $status.initialized, $status.locked, $status.worldUid)
    $existingPending = Read-JsonFile $PendingPath
    if ($null -ne $existingPending) {
        if ($null -ne $existingPending.PSObject.Properties['gameKey'] -and [string]$existingPending.gameKey -ne 'valheim') { throw 'pending-session.json belongs to another adapter/client directory.' }
        if ([int]$status.version -ne [int]$existingPending.baseVersion) { throw "Remote version advanced since the pending Valheim session (local base $($existingPending.baseVersion), remote $($status.version)). Manual recovery is required." }
        if ([bool]$status.initialized -and (Normalize-WorldUid ([string]$status.worldUid)) -ne (Normalize-WorldUid ([string]$existingPending.worldUid))) { throw 'The pending Valheim session belongs to a different World UID.' }
    }

    Write-Info 'Acquiring exclusive lock...'
    $lock = Invoke-ApiJson POST 'lock' $secrets.ApiToken @{ owner=[string]$script:Config.PlayerName; clientId=[string]$script:Config.ClientId }
    $sessionId = [string]$lock.sessionId; $baseVersion = [int]$lock.baseVersion; $lockHeld = $true
    Write-Success "Lock acquired on version $baseVersion."
    Assert-PendingSessionMatchesLock -Pending $existingPending -Lock $lock
    Assert-HeartbeatFitsLockTtl -Lock $lock -IntervalSeconds ([int]$script:Config.HeartbeatSeconds)
    $heartbeatJob = Start-HeartbeatJob ([string]$script:Config.ApiBaseUrl) $secrets.ApiToken $sessionId ([int]$script:Config.HeartbeatSeconds) $HeartbeatStatePath ([string]$lock.expiresAt)
    $localState = Read-JsonFile $StatePath

    if ($null -ne $existingPending) {
        $snapshot = Get-CommittedWorldSnapshot
        if ($null -eq $snapshot -or [string]$snapshot.WorldUid -ne (Normalize-WorldUid ([string]$existingPending.worldUid))) { throw 'The pending Valheim world is missing or its UID changed.' }
        $worldUid = [string]$snapshot.WorldUid
        Write-Info 'The pending local copy is preserved; the remote save will not be downloaded.'
    }
    elseif ($baseVersion -eq 0) {
        $snapshot = Get-CommittedWorldSnapshot
        if ($null -eq $snapshot) { throw 'The remote service is empty and the configured local Valheim 1.0 world was not found.' }
        $worldUid = [string]$snapshot.WorldUid
        Write-Info "Initialization: using local world '$([string]$script:Config.WorldName)' with UID $worldUid."
    }
    else {
        $remoteUid = Normalize-WorldUid ([string]$lock.worldUid)
        $localMatches = $false
        if ($null -ne $localState) {
            try {
                $snapshot = Get-CommittedWorldSnapshot
                $localMatches = [int]$localState.version -eq $baseVersion -and (Normalize-WorldUid ([string]$localState.worldUid)) -eq $remoteUid -and $null -ne $snapshot -and [string]$snapshot.WorldUid -eq $remoteUid
            }
            catch { $localMatches = $false }
        }
        if (-not $localMatches) {
            if (Test-Path -LiteralPath (Get-WorldFolderPath) -PathType Container) { [void](Backup-LocalWorld 'before-download' $baseVersion) }
            Write-Info "Downloading remote version $baseVersion..."
            $downloadPath = Join-Path $DownloadRoot ("remote-v{0:D6}.zip" -f $baseVersion)
            $download = Download-LatestSave $secrets.ApiToken $downloadPath
            if ($download.Version -ne $baseVersion) { throw "Download returned version $($download.Version), but lock fixed base version $baseVersion." }
            if ($download.WorldUid -ne $remoteUid) { throw 'Downloaded World UID does not match the lock.' }
            $manifest = Read-ArchiveManifest $download.Path
            if ((Normalize-WorldUid ([string]$manifest.worldUid)) -ne $remoteUid) { throw 'Downloaded manifest does not match the remote World UID.' }
            Assert-HeartbeatCanContinue -Job $heartbeatJob -Context 'remote download validation'
            Install-DownloadedSave $download.Path $remoteUid
            Assert-HeartbeatCanContinue -Job $heartbeatJob -Context 'remote save installation'
            Save-LocalState $baseVersion $remoteUid $download.Sha256 ([string]$status.updatedBy)
            Write-Success 'Remote Valheim world installed.'
        }
        else { Write-Success 'The local Valheim world already matches the remote version.' }
        $worldUid = $remoteUid
    }

    [void](Backup-LocalWorld 'before-session' $baseVersion)
    Assert-HeartbeatCanContinue -Job $heartbeatJob -Context 'pre-session backup'
    $serverLogPath = Join-Path $LogRoot ("valheim-server-session-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
    Remove-Item -LiteralPath $serverLogPath -Force -ErrorAction SilentlyContinue
    Save-PendingSession $baseVersion $worldUid $sessionId
    Assert-HeartbeatCanContinue -Job $heartbeatJob -Context 'server startup'
    $sessionEntered = $true
    Write-Info 'Starting valheim_server.exe in a dedicated Windows process group...'
    $serverProcess = Start-ValheimServer $secrets.ServerPassword $serverLogPath
    Wait-ForValheimReady $serverProcess $serverLogPath $heartbeatJob
    $runningSnapshot = Get-CommittedWorldSnapshot
    if ($null -eq $runningSnapshot -or [string]$runningSnapshot.WorldUid -ne $worldUid) { throw 'Valheim startup changed or failed to preserve the expected World UID.' }
    Write-Success ("Valheim world verified: UID {0}; committed generation {1}." -f $worldUid, $runningSnapshot.Generation)

    $end = Wait-ForSessionEndRequest $serverProcess $heartbeatJob
    if ($end.Reason -eq 'HeartbeatFailed') {
        Write-ErrorText 'The heartbeat failed three times. Valheim will be stopped cleanly but progress will not be published automatically.'
        Stop-ValheimGracefully $serverProcess
        throw 'Remote exclusion is no longer reliable. The local save remains pending.'
    }
    if ($end.Reason -eq 'ProcessExited') { throw 'Valheim exited outside the controlled Save Sync shutdown path. The world will not be published automatically.' }
    Stop-ValheimGracefully $serverProcess
    if ((Get-HeartbeatStatus $heartbeatJob) -eq 'fatal') { throw 'The heartbeat is no longer valid after shutdown. Progress will not be published automatically.' }
    $finalSnapshot = Get-CommittedWorldSnapshot
    if ($null -eq $finalSnapshot -or [string]$finalSnapshot.WorldUid -ne $worldUid) { throw 'The closed Valheim world failed final identity validation.' }

    $safePlayerName = (([string]$script:Config.PlayerName) -replace '[^A-Za-z0-9._-]', '_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($safePlayerName)) { $safePlayerName = 'host' }
    $archivePath = Join-Path $TempRoot ('valheim-save-{0}-base-v{1:D6}.zip' -f $safePlayerName, $baseVersion)
    Write-Info 'Archiving the closed Valheim world directory...'
    $finalArchive = New-WorldArchive -WorldPath (Get-WorldFolderPath) -Destination $archivePath -BaseVersion $baseVersion -Purpose 'web-upload'
    Save-PendingSession $baseVersion $worldUid $sessionId $archivePath $finalArchive.Sha256
    Write-Success ("ZIP created: {0:N2} MiB; SHA-256 {1}; generation {2}" -f ($finalArchive.Size / 1MB), $finalArchive.Sha256, $finalArchive.Generation)
    try {
        Write-Info 'Uploading the new version to the central service...'
        $upload = Upload-SaveArchive $secrets.ApiToken $archivePath $sessionId $baseVersion $finalArchive.Sha256 $worldUid
        $uploadConfirmed = $true; $lockHeld = $false
        Save-LocalState ([int]$upload.version) ([string]$upload.worldUid) ([string]$upload.sha256) ([string]$script:Config.PlayerName)
        Remove-Item -LiteralPath $PendingPath -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        Write-Success "Save published as version $($upload.version)."
    }
    catch {
        Write-WarningText "The upload response failed: $($_.Exception.Message)"; Write-Info 'Checking whether the server received the upload...'
        if (Reconcile-Upload $secrets.ApiToken $baseVersion $finalArchive.Sha256 $worldUid) {
            $remoteStatus = Invoke-ApiJson GET 'status' $secrets.ApiToken; $uploadConfirmed = $true; $lockHeld = $false
            Save-LocalState ([int]$remoteStatus.version) ([string]$remoteStatus.worldUid) ([string]$remoteStatus.sha256) ([string]$remoteStatus.updatedBy)
            Remove-Item -LiteralPath $PendingPath -Force -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
            Write-Success "Upload reconciled: remote version $($remoteStatus.version)."
        }
        else {
            $preserved = Join-Path $PendingUploadRoot ("{0}_{1}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), [IO.Path]::GetFileName($archivePath))
            Move-Item -LiteralPath $archivePath -Destination $preserved -Force
            Save-PendingSession $baseVersion $worldUid $sessionId $preserved $finalArchive.Sha256
            throw "The upload could not be confirmed. The ZIP is preserved at: $preserved"
        }
    }
}
catch {
    Write-ErrorText $_.Exception.Message; Write-Log -Level 'error' -Message $_.Exception.ToString()
    if ($null -ne $serverProcess) {
        try { $serverProcess.Refresh(); if (-not $serverProcess.HasExited) { Write-WarningText 'Attempting clean Valheim shutdown after the error...'; Stop-ValheimGracefully $serverProcess } }
        catch { Write-ErrorText "Could not stop Valheim cleanly: $($_.Exception.Message)" }
    }
    if ($lockHeld -and -not $sessionEntered -and -not [string]::IsNullOrWhiteSpace($sessionId) -and $null -ne $secrets) { [void](Unlock-Session $secrets.ApiToken $sessionId); $lockHeld = $false }
    elseif ($lockHeld -and $sessionEntered) { Write-WarningText 'The lock is not released after an unpublished Valheim session. Let it expire and do not start the other host until the pending state is reviewed.' }
    $scriptExitCode = 1
}
finally {
    Stop-HeartbeatJob $heartbeatJob
    if ($null -ne $secrets) { $secrets.ApiToken = $null; $secrets.ServerPassword = $null }
}

if ($uploadConfirmed) { Write-Host ''; Write-Success 'Process complete. The remote Valheim world is the latest authority.' }
elseif (-not ($TestOnly -or $SetupSecrets)) { Write-Host ''; Write-WarningText 'Process ended without confirming a new publication. Review the previous messages and data\pending-uploads.' }
exit $scriptExitCode
