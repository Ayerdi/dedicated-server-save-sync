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

$AdapterRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptRoot = if ([string]::IsNullOrWhiteSpace($ClientRoot)) {
    $AdapterRoot
} else {
    [IO.Path]::GetFullPath($ClientRoot)
}
$ClientVersion = '1.2.0'
$ConfigPath = Join-Path $ScriptRoot 'config.json'
$DataRoot = Join-Path $ScriptRoot 'data'
$SecretsPath = Join-Path $DataRoot 'secrets.json'
$StatePath = Join-Path $DataRoot 'state.json'
$PendingPath = Join-Path $DataRoot 'pending-session.json'
$HeartbeatStatePath = Join-Path $DataRoot 'heartbeat-state.json'
$BackupRoot = Join-Path $DataRoot 'backups'
$DownloadRoot = Join-Path $DataRoot 'downloads'
$PendingUploadRoot = Join-Path $DataRoot 'pending-uploads'
$TempRoot = Join-Path $DataRoot 'temp'
$LogRoot = Join-Path $DataRoot 'logs'
$LogPath = Join-Path $LogRoot ("PalworldSync-{0}.log" -f (Get-Date -Format 'yyyyMMdd'))

function Write-Info {
    param([string]$Message)
    Write-Host "[INFO] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK]   $Message" -ForegroundColor Green
}

function Write-WarningText {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-ErrorText {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Ensure-Directory {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Container)) {
        New-Item -ItemType Directory -Path $Path -Force | Out-Null
    }
}

function Write-Log {
    param(
        [string]$Level,
        [string]$Message
    )
    try {
        Ensure-Directory -Path $LogRoot
        $line = "{0} [{1}] {2}" -f (Get-Date).ToString('o'), $Level.ToUpperInvariant(), $Message
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
    catch {
        # Logging must never break the main flow.
    }
}

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $raw = Get-Content -LiteralPath $Path -Raw
    if ([string]::IsNullOrWhiteSpace($raw)) {
        return $null
    }
    return ($raw | ConvertFrom-Json)
}

function Write-JsonAtomic {
    param(
        [string]$Path,
        [object]$Value
    )
    $parent = Split-Path -Parent $Path
    Ensure-Directory -Path $parent
    $temporary = "$Path.tmp-$([Guid]::NewGuid().ToString('N'))"
    $json = $Value | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($temporary, $json, ([Text.UTF8Encoding]::new($true)))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}

function Convert-SecureStringToPlainText {
    param([Security.SecureString]$SecureString)
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureString)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Protect-SecretsFile {
    param([string]$Path)
    try {
        $identity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
        & icacls.exe $Path /inheritance:r /grant:r "${identity}:F" | Out-Null
    }
    catch {
        Write-Log -Level 'warning' -Message "Could not restrict the ACL on secrets.json: $($_.Exception.Message)"
    }
}

function Initialize-Secrets {
    Write-Host ''
    Write-Info 'Secure credential setup'
    Write-Host 'The API token and REST password will be encrypted with DPAPI for this Windows user.'

    do {
        $tokenSecure = Read-Host 'Palworld Sync token (pws_...)' -AsSecureString
        $tokenPlain = Convert-SecureStringToPlainText -SecureString $tokenSecure
        $tokenValid = $tokenPlain -match '^pws_[A-Za-z0-9_-]{48}$'
        if (-not $tokenValid) {
            Write-WarningText 'The token does not have the expected format: pws_ followed by 48 characters.'
        }
    } while (-not $tokenValid)

    do {
        $restPasswordSecure = Read-Host 'AdminPassword for the local Palworld REST API' -AsSecureString
        $restPasswordPlain = Convert-SecureStringToPlainText -SecureString $restPasswordSecure
        $passwordValid = -not [string]::IsNullOrWhiteSpace($restPasswordPlain)
        if (-not $passwordValid) {
            Write-WarningText 'The REST password cannot be empty.'
        }
    } while (-not $passwordValid)

    $protected = [ordered]@{
        schemaVersion = 1
        apiToken = ($tokenSecure | ConvertFrom-SecureString)
        restPassword = ($restPasswordSecure | ConvertFrom-SecureString)
        createdAtUtc = [DateTime]::UtcNow.ToString('o')
        windowsUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    }
    Write-JsonAtomic -Path $SecretsPath -Value $protected
    Protect-SecretsFile -Path $SecretsPath

    $tokenPlain = $null
    $restPasswordPlain = $null
    Write-Success 'Encrypted credentials saved to data\secrets.json.'
}

function Get-Secrets {
    if (-not (Test-Path -LiteralPath $SecretsPath -PathType Leaf)) {
        Initialize-Secrets
    }

    $stored = Read-JsonFile -Path $SecretsPath
    if ($null -eq $stored -or [string]::IsNullOrWhiteSpace([string]$stored.apiToken) -or [string]::IsNullOrWhiteSpace([string]$stored.restPassword)) {
        throw 'The secrets file is empty or damaged. Run Configure-Secrets.cmd.'
    }

    try {
        $tokenSecure = ConvertTo-SecureString ([string]$stored.apiToken)
        $restSecure = ConvertTo-SecureString ([string]$stored.restPassword)
    }
    catch {
        throw 'The credentials could not be decrypted. They must be opened by the same Windows user on the same machine. Run Configure-Secrets.cmd.'
    }

    $token = Convert-SecureStringToPlainText -SecureString $tokenSecure
    $restPassword = Convert-SecureStringToPlainText -SecureString $restSecure
    if ($token -notmatch '^pws_[A-Za-z0-9_-]{48}$') {
        throw 'The decrypted token does not have the expected format. Run Configure-Secrets.cmd.'
    }
    if ([string]::IsNullOrWhiteSpace($restPassword)) {
        throw 'The decrypted REST password is empty. Run Configure-Secrets.cmd.'
    }

    return [pscustomobject]@{
        ApiToken = $token
        RestPassword = $restPassword
    }
}

function Get-RequiredProperty {
    param(
        [object]$Object,
        [string]$Name
    )
    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property -or $null -eq $property.Value -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "Required value '$Name' is missing from config.json."
    }
    return $property.Value
}

function Load-AndValidateConfig {
    if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
        throw "config.json does not exist in $ScriptRoot."
    }
    $config = Read-JsonFile -Path $ConfigPath
    if ($null -eq $config) {
        throw 'config.json is empty or is not valid JSON.'
    }

    foreach ($name in @('PlayerName','ClientId','ApiBaseUrl','PalServerRoot','PalServerExecutable','SaveGamesRoot','GameUserSettingsPath','RestApiBaseUrl','RestUsername')) {
        [void](Get-RequiredProperty -Object $config -Name $name)
    }

    if ([string]$config.ApiBaseUrl -notmatch '^https://') {
        throw 'ApiBaseUrl must use HTTPS.'
    }
    if ([string]$config.RestApiBaseUrl -notmatch '^http://(127\.0\.0\.1|localhost)(:\d+)?/') {
        throw 'RestApiBaseUrl must point to localhost or 127.0.0.1.'
    }
    if (-not (Test-Path -LiteralPath ([string]$config.PalServerExecutable) -PathType Leaf)) {
        throw "PalServer.exe was not found: $($config.PalServerExecutable)"
    }
    if (-not (Test-Path -LiteralPath ([string]$config.SaveGamesRoot) -PathType Container)) {
        throw "SaveGamesRoot was not found: $($config.SaveGamesRoot)"
    }

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
    param(
        [string]$Message,
        [int]$StatusCode,
        [string]$ResponseBody
    )
    $exception = [System.Exception]::new($Message)
    $exception.Data['StatusCode'] = $StatusCode
    $exception.Data['ResponseBody'] = $ResponseBody
    return $exception
}

function Invoke-ApiJson {
    param(
        [ValidateSet('GET','POST','DELETE')][string]$Method,
        [string]$Path,
        [string]$Token,
        [object]$Body = $null
    )
    $uri = ('{0}/{1}' -f ([string]$script:Config.ApiBaseUrl).TrimEnd('/'), $Path.TrimStart('/'))
    $headers = @{
        Authorization = "Bearer $Token"
        Accept = 'application/json'
    }
    $parameters = @{
        Uri = $uri
        Method = $Method
        Headers = $headers
        ErrorAction = 'Stop'
    }
    if ($null -ne $Body) {
        $parameters.ContentType = 'application/json'
        $parameters.Body = ($Body | ConvertTo-Json -Compress -Depth 8)
    }

    try {
        return Invoke-RestMethod @parameters
    }
    catch {
        $statusCode = 0
        try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}
        $responseBody = Get-WebExceptionBody -Exception $_.Exception
        $message = "The web API rejected $Method $Path (HTTP $statusCode)."
        if (-not [string]::IsNullOrWhiteSpace($responseBody)) {
            try {
                $parsed = $responseBody | ConvertFrom-Json
                $message = "$message $($parsed.error): $($parsed.message)"
            }
            catch {
                $message = "$message $responseBody"
            }
        }
        throw (New-HttpFailure -Message $message -StatusCode $statusCode -ResponseBody $responseBody)
    }
}

function New-BasicAuthorizationHeader {
    param(
        [string]$Username,
        [string]$Password
    )
    $bytes = [Text.Encoding]::UTF8.GetBytes("$Username`:$Password")
    return 'Basic ' + [Convert]::ToBase64String($bytes)
}

function Invoke-PalRest {
    param(
        [ValidateSet('GET','POST')][string]$Method,
        [string]$Path,
        [string]$Password,
        [object]$Body = $null
    )
    $uri = ('{0}/{1}' -f ([string]$script:Config.RestApiBaseUrl).TrimEnd('/'), $Path.TrimStart('/'))
    $headers = @{
        Authorization = (New-BasicAuthorizationHeader -Username ([string]$script:Config.RestUsername) -Password $Password)
        Accept = 'application/json'
    }
    $parameters = @{
        Uri = $uri
        Method = $Method
        Headers = $headers
        ErrorAction = 'Stop'
    }
    if ($null -ne $Body) {
        $parameters.ContentType = 'application/json'
        $parameters.Body = ($Body | ConvertTo-Json -Compress -Depth 6)
    }

    try {
        return Invoke-RestMethod @parameters
    }
    catch {
        $statusCode = 0
        try { $statusCode = [int]$_.Exception.Response.StatusCode } catch {}
        $responseBody = Get-WebExceptionBody -Exception $_.Exception
        throw (New-HttpFailure -Message "The local Palworld REST API rejected $Method $Path (HTTP $statusCode)." -StatusCode $statusCode -ResponseBody $responseBody)
    }
}

function Get-HeaderValue {
    param(
        [System.Net.Http.HttpResponseMessage]$Response,
        [string]$Name
    )
    $values = $null
    if ($Response.Headers.TryGetValues($Name, [ref]$values)) {
        return [string]($values | Select-Object -First 1)
    }
    $values = $null
    if ($Response.Content.Headers.TryGetValues($Name, [ref]$values)) {
        return [string]($values | Select-Object -First 1)
    }
    return $null
}

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

function Download-LatestSave {
    param(
        [string]$Token,
        [string]$Destination
    )
    $uri = ('{0}/download' -f ([string]$script:Config.ApiBaseUrl).TrimEnd('/'))
    $partial = "$Destination.part"
    Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue

    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Token)
    $client.DefaultRequestHeaders.Accept.Add(([System.Net.Http.Headers.MediaTypeWithQualityHeaderValue]::new('application/zip')))

    $response = $null
    $inputStream = $null
    $outputStream = $null
    try {
        $response = $client.GetAsync($uri, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $bodyOnError = $null
        if (-not $response.IsSuccessStatusCode) {
            $bodyOnError = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
            throw (New-HttpFailure -Message "Save download failed (HTTP $([int]$response.StatusCode)). $bodyOnError" -StatusCode ([int]$response.StatusCode) -ResponseBody $bodyOnError)
        }

        $versionHeader = Get-HeaderValue -Response $response -Name 'X-Palworld-Version'
        $shaHeader = Get-HeaderValue -Response $response -Name 'X-Palworld-SHA256'
        $guidHeader = Get-HeaderValue -Response $response -Name 'X-Palworld-World-Guid'
        if ($versionHeader -notmatch '^\d+$') { throw 'The download does not include a valid X-Palworld-Version.' }
        if ($shaHeader -notmatch '^[A-Fa-f0-9]{64}$') { throw 'The download does not include a valid X-Palworld-SHA256.' }
        if ($guidHeader -notmatch '^[A-Fa-f0-9]{32}$') { throw 'The download does not include a valid X-Palworld-World-Guid.' }

        $inputStream = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
        $outputStream = [IO.FileStream]::new($partial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $inputStream.CopyTo($outputStream)
        $outputStream.Flush()
        $outputStream.Dispose(); $outputStream = $null
        $inputStream.Dispose(); $inputStream = $null

        $actualSha = Get-Sha256 -Path $partial
        if ($actualSha -ne $shaHeader.ToLowerInvariant()) {
            throw "Download SHA-256 mismatch. Expected $shaHeader; got $actualSha."
        }
        Move-Item -LiteralPath $partial -Destination $Destination -Force

        return [pscustomobject]@{
            Version = [int]$versionHeader
            Sha256 = $actualSha
            WorldGuid = $guidHeader.Trim().ToUpperInvariant()
            Path = $Destination
        }
    }
    finally {
        if ($null -ne $outputStream) { $outputStream.Dispose() }
        if ($null -ne $inputStream) { $inputStream.Dispose() }
        if ($null -ne $response) { $response.Dispose() }
        $client.Dispose()
        $handler.Dispose()
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Force -ErrorAction SilentlyContinue }
    }
}

function Add-MultipartString {
    param(
        [System.Net.Http.MultipartFormDataContent]$Multipart,
        [string]$Name,
        [string]$Value
    )
    $content = [System.Net.Http.StringContent]::new($Value, [Text.Encoding]::UTF8)
    $Multipart.Add($content, $Name)
}

function Upload-SaveArchive {
    param(
        [string]$Token,
        [string]$ZipPath,
        [string]$SessionId,
        [int]$BaseVersion,
        [string]$Sha256,
        [string]$WorldGuid
    )
    $uri = ('{0}/upload' -f ([string]$script:Config.ApiBaseUrl).TrimEnd('/'))
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromMinutes(30)
    $client.DefaultRequestHeaders.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Token)

    $multipart = [System.Net.Http.MultipartFormDataContent]::new()
    $fileStream = $null
    $fileContent = $null
    $response = $null
    try {
        $fileStream = [IO.FileStream]::new($ZipPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
        $fileContent = [System.Net.Http.StreamContent]::new($fileStream)
        $fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::new('application/zip')
        $multipart.Add($fileContent, 'file', [IO.Path]::GetFileName($ZipPath))
        Add-MultipartString -Multipart $multipart -Name 'sessionId' -Value $SessionId
        Add-MultipartString -Multipart $multipart -Name 'baseVersion' -Value ([string]$BaseVersion)
        Add-MultipartString -Multipart $multipart -Name 'sha256' -Value $Sha256
        Add-MultipartString -Multipart $multipart -Name 'worldGuid' -Value $WorldGuid
        Add-MultipartString -Multipart $multipart -Name 'owner' -Value ([string]$script:Config.PlayerName)

        $response = $client.PostAsync($uri, $multipart).GetAwaiter().GetResult()
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        if (-not $response.IsSuccessStatusCode) {
            $message = "Upload failed (HTTP $([int]$response.StatusCode))."
            if (-not [string]::IsNullOrWhiteSpace($text)) {
                try {
                    $parsedError = $text | ConvertFrom-Json
                    $message = "$message $($parsedError.error): $($parsedError.message)"
                }
                catch { $message = "$message $text" }
            }
            throw (New-HttpFailure -Message $message -StatusCode ([int]$response.StatusCode) -ResponseBody $text)
        }
        return ($text | ConvertFrom-Json)
    }
    finally {
        if ($null -ne $response) { $response.Dispose() }
        if ($null -ne $fileContent) { $fileContent.Dispose() }
        if ($null -ne $fileStream) { $fileStream.Dispose() }
        $multipart.Dispose()
        $client.Dispose()
        $handler.Dispose()
    }
}

function Test-ValidWorldGuid {
    param([string]$WorldGuid)
    return (-not [string]::IsNullOrWhiteSpace($WorldGuid)) -and ($WorldGuid.Trim() -match '^[A-Fa-f0-9]{32}$')
}

function Normalize-WorldGuid {
    param([string]$WorldGuid)
    if (-not (Test-ValidWorldGuid -WorldGuid $WorldGuid)) {
        throw "Invalid World GUID: '$WorldGuid'."
    }
    return $WorldGuid.Trim().ToUpperInvariant()
}

function Get-DedicatedServerName {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $text = Get-Content -LiteralPath $Path -Raw
    $match = [regex]::Match($text, '(?im)^\s*DedicatedServerName\s*=\s*([A-Fa-f0-9]{32})\s*$')
    if ($match.Success) { return $match.Groups[1].Value.ToUpperInvariant() }
    return $null
}

function Set-DedicatedServerName {
    param(
        [string]$Path,
        [string]$WorldGuid
    )
    $WorldGuid = Normalize-WorldGuid -WorldGuid $WorldGuid
    $parent = Split-Path -Parent $Path
    Ensure-Directory -Path $parent

    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $text = Get-Content -LiteralPath $Path -Raw
        if ($text -match '(?im)^\s*DedicatedServerName\s*=.*$') {
            $text = [regex]::Replace($text, '(?im)^\s*DedicatedServerName\s*=.*$', "DedicatedServerName=$WorldGuid")
        }
        elseif ($text -match '(?im)^\s*\[/Script/Pal\.PalGameLocalSettings\]\s*$') {
            $text = [regex]::Replace(
                $text,
                '(?im)^(\s*\[/Script/Pal\.PalGameLocalSettings\]\s*)$',
                "`$1`r`nDedicatedServerName=$WorldGuid",
                1
            )
        }
        else {
            $text = $text.TrimEnd() + "`r`n`r`n[/Script/Pal.PalGameLocalSettings]`r`nDedicatedServerName=$WorldGuid`r`n"
        }
    }
    else {
        $text = "[/Script/Pal.PalGameLocalSettings]`r`nDedicatedServerName=$WorldGuid`r`n"
    }

    [IO.File]::WriteAllText($Path, $text, ([Text.UTF8Encoding]::new($true)))
    Write-Log -Level 'info' -Message "DedicatedServerName actualizado a $WorldGuid."
}

function Get-WorldFolderPath {
    param([string]$WorldGuid)
    return Join-Path (Join-Path ([string]$script:Config.SaveGamesRoot) '0') (Normalize-WorldGuid -WorldGuid $WorldGuid)
}

function Find-LocalWorldGuid {
    param([string]$PreferredGuid)
    $candidates = [Collections.Generic.List[string]]::new()

    # When the backend or config provides a preferred GUID and its folder exists,
    # that world is authoritative. Do not fail only because other worlds remain from
    # test worlds or other local copies inside SaveGames\0.
    if (Test-ValidWorldGuid -WorldGuid $PreferredGuid) {
        $candidate = Normalize-WorldGuid -WorldGuid $PreferredGuid
        if (Test-Path -LiteralPath (Get-WorldFolderPath -WorldGuid $candidate) -PathType Container) {
            return $candidate
        }
    }

    $configured = Get-DedicatedServerName -Path ([string]$script:Config.GameUserSettingsPath)
    if (Test-ValidWorldGuid -WorldGuid $configured) {
        $configured = Normalize-WorldGuid -WorldGuid $configured
        if ((Test-Path -LiteralPath (Get-WorldFolderPath -WorldGuid $configured) -PathType Container) -and (-not $candidates.Contains($configured))) {
            $candidates.Add($configured)
        }
    }

    $state = Read-JsonFile -Path $StatePath
    if ($null -ne $state -and (Test-ValidWorldGuid -WorldGuid ([string]$state.worldGuid))) {
        $stateGuid = Normalize-WorldGuid -WorldGuid ([string]$state.worldGuid)
        if ((Test-Path -LiteralPath (Get-WorldFolderPath -WorldGuid $stateGuid) -PathType Container) -and (-not $candidates.Contains($stateGuid))) {
            $candidates.Add($stateGuid)
        }
    }

    $zeroRoot = Join-Path ([string]$script:Config.SaveGamesRoot) '0'
    if (Test-Path -LiteralPath $zeroRoot -PathType Container) {
        foreach ($folder in Get-ChildItem -LiteralPath $zeroRoot -Directory -ErrorAction SilentlyContinue) {
            if ($folder.Name -match '^[A-Fa-f0-9]{32}$' -and (Test-Path -LiteralPath (Join-Path $folder.FullName 'Level.sav') -PathType Leaf)) {
                $folderGuid = $folder.Name.ToUpperInvariant()
                if (-not $candidates.Contains($folderGuid)) { $candidates.Add($folderGuid) }
            }
        }
    }

    if ($candidates.Count -eq 0) { return $null }
    if ($candidates.Count -eq 1) { return $candidates[0] }

    throw "Several local worlds are possible ($($candidates -join ', ')). Set InitialWorldGuid in config.json."
}

function Test-SafeZipEntryName {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return $false }
    $normalized = $Name.Replace('\','/')
    if ($normalized.StartsWith('/') -or $normalized -match '^[A-Za-z]:') { return $false }
    foreach ($part in $normalized.Split('/')) {
        if ($part -eq '..') { return $false }
    }
    return $true
}

function Read-ArchiveManifest {
    param([string]$ZipPath)
    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        $manifestEntry = $archive.GetEntry('manifest.json')
        if ($null -eq $manifestEntry) { throw 'The ZIP does not contain manifest.json.' }
        $reader = [IO.StreamReader]::new($manifestEntry.Open(), [Text.Encoding]::UTF8, $true)
        try { $manifestRaw = $reader.ReadToEnd() } finally { $reader.Dispose() }
        $manifest = $manifestRaw | ConvertFrom-Json
        $guid = Normalize-WorldGuid -WorldGuid ([string]$manifest.worldGuid)
        $prefix = "SaveGames/0/$guid/"
        $hasLevel = $false

        foreach ($entry in $archive.Entries) {
            if (-not (Test-SafeZipEntryName -Name $entry.FullName)) {
                throw "Unsafe ZIP entry: $($entry.FullName)"
            }
            if ($entry.FullName -eq 'manifest.json') { continue }
            if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
                throw "The ZIP contains an entry outside the expected world: $($entry.FullName)"
            }
            if ($entry.FullName.Equals("${prefix}Level.sav", [StringComparison]::OrdinalIgnoreCase)) {
                $hasLevel = $true
            }
        }
        if (-not $hasLevel) { throw 'The ZIP does not contain Level.sav.' }
        return $manifest
    }
    finally {
        $archive.Dispose()
    }
}

function New-WorldArchive {
    param(
        [string]$WorldGuid,
        [string]$Destination,
        [int]$BaseVersion,
        [string]$ServerVersion,
        [string]$Purpose
    )
    $WorldGuid = Normalize-WorldGuid -WorldGuid $WorldGuid
    $worldPath = Get-WorldFolderPath -WorldGuid $WorldGuid
    if (-not (Test-Path -LiteralPath $worldPath -PathType Container)) {
        throw "The world folder does not exist: $worldPath"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $worldPath 'Level.sav') -PathType Leaf)) {
        throw "The world does not contain Level.sav: $worldPath"
    }

    $parent = Split-Path -Parent $Destination
    Ensure-Directory -Path $parent
    $temporary = "$Destination.part"
    Remove-Item -LiteralPath $temporary -Force -ErrorAction SilentlyContinue

    $fileStream = [IO.FileStream]::new($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::ReadWrite, [IO.FileShare]::None)
    $archive = [IO.Compression.ZipArchive]::new($fileStream, [IO.Compression.ZipArchiveMode]::Create, $false)
    try {
        $manifest = [ordered]@{
            schemaVersion = 1
            clientVersion = $ClientVersion
            worldGuid = $WorldGuid
            baseVersion = $BaseVersion
            createdBy = [string]$script:Config.PlayerName
            clientId = [string]$script:Config.ClientId
            createdAtUtc = [DateTime]::UtcNow.ToString('o')
            palworldServerVersion = $ServerVersion
            purpose = $Purpose
            includedPath = "SaveGames/0/$WorldGuid"
            internalBackupsExcluded = [bool]$script:Config.ExcludeInternalBackups
        }
        $manifestEntry = $archive.CreateEntry('manifest.json', [IO.Compression.CompressionLevel]::Optimal)
        $manifestStream = $manifestEntry.Open()
        $writer = [IO.StreamWriter]::new($manifestStream, [Text.UTF8Encoding]::new($false))
        try { $writer.Write(($manifest | ConvertTo-Json -Depth 8)) } finally { $writer.Dispose() }

        foreach ($file in Get-ChildItem -LiteralPath $worldPath -File -Recurse) {
            $relative = $file.FullName.Substring($worldPath.Length).TrimStart([char[]]@('\','/'))
            $relativeNormalized = $relative.Replace('\','/')
            if ([bool]$script:Config.ExcludeInternalBackups -and ($relativeNormalized -match '^(?i)backup/')) { continue }
            if ($relativeNormalized -match '(?i)\.(tmp|log)$') { continue }
            $entryName = "SaveGames/0/$WorldGuid/$relativeNormalized"
            [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $entryName, [IO.Compression.CompressionLevel]::Optimal)
        }
    }
    finally {
        $archive.Dispose()
        $fileStream.Dispose()
    }

    [void](Read-ArchiveManifest -ZipPath $temporary)
    Move-Item -LiteralPath $temporary -Destination $Destination -Force
    return [pscustomobject]@{
        Path = $Destination
        Sha256 = Get-Sha256 -Path $Destination
        Size = (Get-Item -LiteralPath $Destination).Length
        WorldGuid = $WorldGuid
    }
}

function Remove-OldLocalBackups {
    $retention = [int]$script:Config.LocalBackupRetention
    if ($retention -lt 1) { return }
    $all = @(Get-ChildItem -LiteralPath $BackupRoot -Filter '*.zip' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTimeUtc -Descending)
    if ($all.Count -le $retention) { return }
    foreach ($old in $all[$retention..($all.Count - 1)]) {
        Remove-Item -LiteralPath $old.FullName -Force -ErrorAction SilentlyContinue
    }
}

function Backup-LocalWorld {
    param(
        [string]$WorldGuid,
        [string]$Reason,
        [int]$BaseVersion
    )
    if (-not (Test-ValidWorldGuid -WorldGuid $WorldGuid)) { return $null }
    $worldPath = Get-WorldFolderPath -WorldGuid $WorldGuid
    if (-not (Test-Path -LiteralPath $worldPath -PathType Container)) { return $null }
    $safeReason = ($Reason -replace '[^A-Za-z0-9_-]', '_')
    $name = '{0}_{1}_{2}.zip' -f (Get-Date -Format 'yyyyMMdd-HHmmss'), $safeReason, $WorldGuid
    $destination = Join-Path $BackupRoot $name
    Write-Info "Creando backup local: $name"
    $result = New-WorldArchive -WorldGuid $WorldGuid -Destination $destination -BaseVersion $BaseVersion -ServerVersion 'unknown' -Purpose "local-backup-$Reason"
    Remove-OldLocalBackups
    return $result
}

function Expand-WorldArchive {
    param(
        [string]$ZipPath,
        [string]$WorldGuid,
        [string]$DestinationWorldPath
    )
    $WorldGuid = Normalize-WorldGuid -WorldGuid $WorldGuid
    $prefix = "SaveGames/0/$WorldGuid/"
    Ensure-Directory -Path $DestinationWorldPath
    $destinationRoot = [IO.Path]::GetFullPath($DestinationWorldPath).TrimEnd('\') + '\'

    $archive = [IO.Compression.ZipFile]::OpenRead($ZipPath)
    try {
        foreach ($entry in $archive.Entries) {
            if ($entry.FullName -eq 'manifest.json') { continue }
            if (-not $entry.FullName.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { continue }
            $relative = $entry.FullName.Substring($prefix.Length).Replace('/', '\')
            if ([string]::IsNullOrWhiteSpace($relative)) { continue }
            $destination = [IO.Path]::GetFullPath((Join-Path $DestinationWorldPath $relative))
            if (-not $destination.StartsWith($destinationRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Unsafe extraction path: $($entry.FullName)"
            }
            if ($entry.FullName.EndsWith('/')) {
                Ensure-Directory -Path $destination
                continue
            }
            Ensure-Directory -Path (Split-Path -Parent $destination)
            $input = $entry.Open()
            $output = [IO.FileStream]::new($destination, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
        }
    }
    finally {
        $archive.Dispose()
    }
    if (-not (Test-Path -LiteralPath (Join-Path $DestinationWorldPath 'Level.sav') -PathType Leaf)) {
        throw 'Extraction did not produce Level.sav.'
    }
}

function Install-DownloadedSave {
    param(
        [string]$ZipPath,
        [string]$WorldGuid
    )
    $WorldGuid = Normalize-WorldGuid -WorldGuid $WorldGuid
    $target = Get-WorldFolderPath -WorldGuid $WorldGuid
    $extractRoot = Join-Path $TempRoot ("extract-" + [Guid]::NewGuid().ToString('N'))
    $extractedWorld = Join-Path $extractRoot $WorldGuid
    $rollback = Join-Path $TempRoot ("rollback-" + [Guid]::NewGuid().ToString('N'))

    try {
        Expand-WorldArchive -ZipPath $ZipPath -WorldGuid $WorldGuid -DestinationWorldPath $extractedWorld
        Ensure-Directory -Path (Split-Path -Parent $target)
        if (Test-Path -LiteralPath $target -PathType Container) {
            Move-Item -LiteralPath $target -Destination $rollback
        }
        try {
            Move-Item -LiteralPath $extractedWorld -Destination $target
            Set-DedicatedServerName -Path ([string]$script:Config.GameUserSettingsPath) -WorldGuid $WorldGuid
        }
        catch {
            if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction SilentlyContinue }
            if (Test-Path -LiteralPath $rollback) { Move-Item -LiteralPath $rollback -Destination $target -Force }
            throw
        }
        if (Test-Path -LiteralPath $rollback) { Remove-Item -LiteralPath $rollback -Recurse -Force }
    }
    finally {
        if (Test-Path -LiteralPath $extractRoot) { Remove-Item -LiteralPath $extractRoot -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Start-HeartbeatJob {
    param(
        [string]$ApiBaseUrl,
        [string]$Token,
        [string]$SessionId,
        [int]$IntervalSeconds,
        [string]$StateFile
    )
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    return Start-Job -ScriptBlock {
        param($ApiBaseUrl, $Token, $SessionId, $IntervalSeconds, $StateFile)
        $ErrorActionPreference = 'Stop'
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $consecutiveFailures = 0
        while ($true) {
            Start-Sleep -Seconds $IntervalSeconds
            try {
                $headers = @{ Authorization = "Bearer $Token"; Accept = 'application/json' }
                $body = @{ sessionId = $SessionId } | ConvertTo-Json -Compress
                $response = Invoke-RestMethod -Uri ($ApiBaseUrl.TrimEnd('/') + '/heartbeat') -Method Post -Headers $headers -ContentType 'application/json' -Body $body
                $consecutiveFailures = 0
                $state = @{
                    status = 'ok'
                    lastSuccessUtc = [DateTime]::UtcNow.ToString('o')
                    expiresAt = $response.expiresAt
                    consecutiveFailures = 0
                } | ConvertTo-Json -Compress
                [IO.File]::WriteAllText($StateFile, $state)
            }
            catch {
                $consecutiveFailures++
                $status = if ($consecutiveFailures -ge 3) { 'fatal' } else { 'degraded' }
                $state = @{
                    status = $status
                    lastFailureUtc = [DateTime]::UtcNow.ToString('o')
                    consecutiveFailures = $consecutiveFailures
                    message = $_.Exception.Message
                } | ConvertTo-Json -Compress
                [IO.File]::WriteAllText($StateFile, $state)
                if ($consecutiveFailures -ge 3) { throw }
            }
        }
    } -ArgumentList $ApiBaseUrl, $Token, $SessionId, $IntervalSeconds, $StateFile
}

function Get-HeartbeatStatus {
    param([System.Management.Automation.Job]$Job)
    if (Test-Path -LiteralPath $HeartbeatStatePath -PathType Leaf) {
        try {
            $state = Read-JsonFile -Path $HeartbeatStatePath
            if ($null -ne $state) { return [string]$state.status }
        }
        catch {}
    }
    if ($null -ne $Job -and $Job.State -in @('Failed','Stopped','Completed')) { return 'fatal' }
    return 'pending'
}

function Stop-HeartbeatJob {
    param([System.Management.Automation.Job]$Job)
    if ($null -eq $Job) { return }
    Stop-Job -Job $Job -ErrorAction SilentlyContinue
    Remove-Job -Job $Job -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $HeartbeatStatePath -Force -ErrorAction SilentlyContinue
}

function Wait-ForPalRestInfo {
    param(
        [Diagnostics.Process]$Process,
        [string]$RestPassword,
        [System.Management.Automation.Job]$HeartbeatJob
    )
    $deadline = (Get-Date).AddSeconds([int]$script:Config.RestStartupTimeoutSeconds)
    $lastError = $null
    while ((Get-Date) -lt $deadline) {
        $Process.Refresh()
        if ($Process.HasExited) { throw 'PalServer.exe exited before the REST API became available.' }
        if ((Get-HeartbeatStatus -Job $HeartbeatJob) -eq 'fatal') { throw 'The web lock was lost during startup.' }
        try {
            $info = Invoke-PalRest -Method GET -Path 'info' -Password $RestPassword
            if (Test-ValidWorldGuid -WorldGuid ([string]$info.worldguid)) { return $info }
        }
        catch { $lastError = $_.Exception.Message }
        Start-Sleep -Seconds 3
    }
    throw "The Palworld REST API did not respond in time. Last error: $lastError"
}

function Wait-ForSessionEndRequest {
    param(
        [Diagnostics.Process]$Process,
        [System.Management.Automation.Job]$HeartbeatJob
    )
    Write-Host ''
    Write-Host 'Server active. Press ENTER in this window to save, stop and synchronize.' -ForegroundColor Green
    Write-Host 'Do not close this PowerShell window while the server is running.'

    while ($true) {
        $Process.Refresh()
        if ($Process.HasExited) {
            return [pscustomobject]@{ Reason = 'ProcessExited'; HeartbeatValid = $true }
        }
        if ((Get-HeartbeatStatus -Job $HeartbeatJob) -eq 'fatal') {
            return [pscustomobject]@{ Reason = 'HeartbeatFailed'; HeartbeatValid = $false }
        }
        try {
            if (-not [Console]::IsInputRedirected -and [Console]::KeyAvailable) {
                $key = [Console]::ReadKey($true)
                if ($key.Key -eq [ConsoleKey]::Enter) {
                    return [pscustomobject]@{ Reason = 'UserRequested'; HeartbeatValid = $true }
                }
            }
        }
        catch {}
        Start-Sleep -Milliseconds 500
    }
}

function Stop-PalServerGracefully {
    param(
        [Diagnostics.Process]$Process,
        [string]$RestPassword,
        [string]$ExpectedWorldGuid
    )
    $Process.Refresh()
    if ($Process.HasExited) { return }

    $infoBeforeStop = Invoke-PalRest -Method GET -Path 'info' -Password $RestPassword
    $guidBeforeStop = Normalize-WorldGuid -WorldGuid ([string]$infoBeforeStop.worldguid)
    if ($guidBeforeStop -ne $ExpectedWorldGuid) {
        throw "The server changed worlds before shutdown: $guidBeforeStop, expected $ExpectedWorldGuid."
    }

    Write-Info 'Requesting Palworld to save the world...'
    [void](Invoke-PalRest -Method POST -Path 'save' -Password $RestPassword)
    Start-Sleep -Seconds ([int]$script:Config.SaveGraceSeconds)

    Write-Info 'Requesting a clean PalServer shutdown...'
    $shutdownBody = @{
        waittime = [int]$script:Config.ShutdownWaitSeconds
        message = 'The server will shut down to synchronize the save.'
    }
    [void](Invoke-PalRest -Method POST -Path 'shutdown' -Password $RestPassword -Body $shutdownBody)

    $deadline = (Get-Date).AddSeconds([int]$script:Config.ShutdownTimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 1
        $Process.Refresh()
        if ($Process.HasExited) {
            Write-Success 'PalServer shut down cleanly.'
            return
        }
    }
    throw 'PalServer did not stop within the timeout. The process will not be forced and the save will not be archived while it is still running.'
}

function Stop-PalServerBestEffort {
    param(
        [Diagnostics.Process]$Process,
        [string]$RestPassword
    )
    $Process.Refresh()
    if ($Process.HasExited) { return }

    try {
        Write-WarningText 'Attempting to save and stop PalServer without GUID validation...'
        [void](Invoke-PalRest -Method POST -Path 'save' -Password $RestPassword)
        Start-Sleep -Seconds ([int]$script:Config.SaveGraceSeconds)
        [void](Invoke-PalRest -Method POST -Path 'shutdown' -Password $RestPassword -Body @{
            waittime = [int]$script:Config.ShutdownWaitSeconds
            message = 'The server will shut down because of a synchronization error.'
        })
        $deadline = (Get-Date).AddSeconds([int]$script:Config.ShutdownTimeoutSeconds)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 1
            $Process.Refresh()
            if ($Process.HasExited) { return }
        }
        throw 'PalServer did not stop within the timeout.'
    }
    catch {
        throw "Could not perform the emergency REST shutdown: $($_.Exception.Message)"
    }
}

function Save-LocalState {
    param(
        [int]$Version,
        [string]$WorldGuid,
        [string]$Sha256,
        [string]$UpdatedBy
    )
    $state = [ordered]@{
        schemaVersion = 1
        version = $Version
        worldGuid = (Normalize-WorldGuid -WorldGuid $WorldGuid)
        sha256 = $Sha256
        updatedBy = $UpdatedBy
        updatedAtUtc = [DateTime]::UtcNow.ToString('o')
    }
    Write-JsonAtomic -Path $StatePath -Value $state
}

function Save-PendingSession {
    param(
        [int]$BaseVersion,
        [string]$WorldGuid,
        [string]$SessionId,
        [string]$ArchivePath = $null,
        [string]$ArchiveSha256 = $null
    )
    $pending = [ordered]@{
        schemaVersion = 1
        baseVersion = $BaseVersion
        worldGuid = (Normalize-WorldGuid -WorldGuid $WorldGuid)
        owner = [string]$script:Config.PlayerName
        clientId = [string]$script:Config.ClientId
        startedAtUtc = [DateTime]::UtcNow.ToString('o')
        sessionIdHint = if ($SessionId.Length -ge 8) { $SessionId.Substring(0,8) } else { 'redacted' }
        archivePath = $ArchivePath
        archiveSha256 = $ArchiveSha256
    }
    Write-JsonAtomic -Path $PendingPath -Value $pending
}

function Reconcile-Upload {
    param(
        [string]$Token,
        [int]$BaseVersion,
        [string]$Sha256,
        [string]$WorldGuid
    )
    try {
        $status = Invoke-ApiJson -Method GET -Path 'status' -Token $Token
        $expectedVersion = $BaseVersion + 1
        return (
            [bool]$status.initialized -and
            [int]$status.version -eq $expectedVersion -and
            ([string]$status.sha256).ToLowerInvariant() -eq $Sha256.ToLowerInvariant() -and
            (Normalize-WorldGuid -WorldGuid ([string]$status.worldGuid)) -eq $WorldGuid -and
            ([string]$status.updatedBy).Equals([string]$script:Config.PlayerName, [StringComparison]::OrdinalIgnoreCase)
        )
    }
    catch {
        Write-Log -Level 'warning' -Message "Could not reconcile the upload: $($_.Exception.Message)"
        return $false
    }
}

function Unlock-Session {
    param(
        [string]$Token,
        [string]$SessionId
    )
    try {
        [void](Invoke-ApiJson -Method POST -Path 'unlock' -Token $Token -Body @{ sessionId = $SessionId })
        Write-Success 'Lock liberado.'
        return $true
    }
    catch {
        Write-WarningText "Could not release the lock: $($_.Exception.Message)"
        return $false
    }
}

function Test-Environment {
    param(
        [object]$Secrets
    )
    Write-Info 'Probando API web...'
    $status = Invoke-ApiJson -Method GET -Path 'status' -Token $Secrets.ApiToken
    Write-Success ("Web API reachable. Remote version: {0}; initialized: {1}; worldGuid: {2}" -f $status.version, $status.initialized, $status.worldGuid)

    $running = Get-Process -Name 'PalServer' -ErrorAction SilentlyContinue
    if ($null -ne $running) {
        Write-Info 'PalServer is running; testing local REST...'
        $info = Invoke-PalRest -Method GET -Path 'info' -Password $Secrets.RestPassword
        Write-Success ("Local REST reachable. Version: {0}; worldGuid: {1}" -f $info.version, $info.worldguid)
    }
    else {
        Write-WarningText 'PalServer is not running; the local REST API was not tested.'
    }
}

# ------------------------------ Main entrypoint ------------------------------

# Allows Pester to load functions without creating directories, requesting
# secrets or starting the server. This is not part of the normal user flow.
if ($LibraryOnly) { return }

foreach ($directory in @($DataRoot,$BackupRoot,$DownloadRoot,$PendingUploadRoot,$TempRoot,$LogRoot)) {
    Ensure-Directory -Path $directory
}

$script:Config = $null
$secrets = $null
$heartbeatJob = $null
$serverProcess = $null
$scriptExitCode = 0
$lockHeld = $false
$sessionEntered = $false
$uploadConfirmed = $false
$sessionId = $null
$verifiedWorldGuid = $null
$baseVersion = -1
$finalArchive = $null

try {
    Write-Info "Palworld Sync Client $ClientVersion"
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        throw 'Windows PowerShell 5.1 or later is required.'
    }
    if ($env:OS -ne 'Windows_NT') {
        throw 'This client is designed for Windows.'
    }

    $script:Config = Load-AndValidateConfig

    if ($SetupSecrets) {
        Initialize-Secrets
        Write-Host ''
        Write-Success 'Configuration complete.'
        return
    }

    $secrets = Get-Secrets

    if ($TestOnly) {
        Test-Environment -Secrets $secrets
        return
    }

    $alreadyRunning = Get-Process -Name 'PalServer' -ErrorAction SilentlyContinue
    if ($null -ne $alreadyRunning) {
        throw 'PalServer.exe is already running. Close it before running this launcher.'
    }

    Write-Info 'Checking remote status...'
    $status = Invoke-ApiJson -Method GET -Path 'status' -Token $secrets.ApiToken
    Write-Info ("Remote: version {0}; initialized={1}; lock={2}; worldGuid={3}" -f $status.version, $status.initialized, $status.locked, $status.worldGuid)

    $existingPending = Read-JsonFile -Path $PendingPath
    if ($null -ne $existingPending) {
        Write-WarningText 'A pending local session from a previous run was found.'
        if ([int]$status.version -ne [int]$existingPending.baseVersion) {
            throw "The remote version advanced since the pending session (local base $($existingPending.baseVersion), remote $($status.version)). Nothing will be overwritten. Review data\pending-uploads and local backups."
        }
        if ([bool]$status.initialized -and (Normalize-WorldGuid -WorldGuid ([string]$status.worldGuid)) -ne (Normalize-WorldGuid -WorldGuid ([string]$existingPending.worldGuid))) {
            throw 'The pending session belongs to a different worldGuid than the remote authority. Manual intervention is required.'
        }
    }

    Write-Info 'Adquiriendo lock exclusivo...'
    $lock = Invoke-ApiJson -Method POST -Path 'lock' -Token $secrets.ApiToken -Body @{
        owner = [string]$script:Config.PlayerName
        clientId = [string]$script:Config.ClientId
    }
    $sessionId = [string]$lock.sessionId
    $baseVersion = [int]$lock.baseVersion
    $lockHeld = $true
    Write-Success ("Lock acquired on version $baseVersion.")

    $heartbeatJob = Start-HeartbeatJob -ApiBaseUrl ([string]$script:Config.ApiBaseUrl) -Token $secrets.ApiToken -SessionId $sessionId -IntervalSeconds ([int]$script:Config.HeartbeatSeconds) -StateFile $HeartbeatStatePath

    $localState = Read-JsonFile -Path $StatePath
    $localGuid = $null

    if ($null -ne $existingPending) {
        $localGuid = Normalize-WorldGuid -WorldGuid ([string]$existingPending.worldGuid)
        if (-not (Test-Path -LiteralPath (Get-WorldFolderPath -WorldGuid $localGuid) -PathType Container)) {
            throw "The pending session references $localGuid, but its local folder does not exist."
        }
        Write-Info 'The pending local copy will be preserved; the remote save will not be downloaded.'
    }
    elseif ($baseVersion -eq 0) {
        $preferred = $null
        if ($null -ne $script:Config.PSObject.Properties['InitialWorldGuid']) { $preferred = [string]$script:Config.InitialWorldGuid }
        $localGuid = Find-LocalWorldGuid -PreferredGuid $preferred
        if (-not (Test-ValidWorldGuid -WorldGuid $localGuid)) {
            throw 'The remote service is still empty and no valid local world was found to initialize it.'
        }
        Write-Info "Initialization: using local world $localGuid."
    }
    else {
        $remoteGuid = Normalize-WorldGuid -WorldGuid ([string]$lock.worldGuid)
        $localMatches = $false
        if ($null -ne $localState) {
            try {
                $localMatches = (
                    [int]$localState.version -eq $baseVersion -and
                    (Normalize-WorldGuid -WorldGuid ([string]$localState.worldGuid)) -eq $remoteGuid -and
                    (Test-Path -LiteralPath (Get-WorldFolderPath -WorldGuid $remoteGuid) -PathType Container)
                )
            }
            catch { $localMatches = $false }
        }

        if (-not $localMatches) {
            $currentLocalGuid = Find-LocalWorldGuid -PreferredGuid $remoteGuid
            if (Test-ValidWorldGuid -WorldGuid $currentLocalGuid) {
                [void](Backup-LocalWorld -WorldGuid $currentLocalGuid -Reason 'before-download' -BaseVersion $baseVersion)
            }

            Write-Info "Downloading remote version $baseVersion..."
            $downloadPath = Join-Path $DownloadRoot ("remote-v{0:D6}.zip" -f $baseVersion)
            $download = Download-LatestSave -Token $secrets.ApiToken -Destination $downloadPath
            if ($download.Version -ne $baseVersion) { throw "The download returned version $($download.Version), but the lock fixed base version $baseVersion." }
            if ($download.WorldGuid -ne $remoteGuid) { throw 'The downloaded worldGuid does not match the lock.' }

            $manifest = Read-ArchiveManifest -ZipPath $download.Path
            if ((Normalize-WorldGuid -WorldGuid ([string]$manifest.worldGuid)) -ne $remoteGuid) {
                throw 'The ZIP manifest.json does not match the remote worldGuid.'
            }

            Write-Info 'Installing the validated remote copy...'
            Install-DownloadedSave -ZipPath $download.Path -WorldGuid $remoteGuid
            Save-LocalState -Version $baseVersion -WorldGuid $remoteGuid -Sha256 $download.Sha256 -UpdatedBy ([string]$status.updatedBy)
            $localGuid = $remoteGuid
            Write-Success 'Remote save installed.'
        }
        else {
            $localGuid = $remoteGuid
            Write-Success 'The local copy already matches the remote version.'
        }
    }

    $localGuid = Normalize-WorldGuid -WorldGuid $localGuid
    Set-DedicatedServerName -Path ([string]$script:Config.GameUserSettingsPath) -WorldGuid $localGuid
    [void](Backup-LocalWorld -WorldGuid $localGuid -Reason 'before-session' -BaseVersion $baseVersion)

    Write-Info 'Iniciando PalServer.exe...'
    $startParameters = @{
        FilePath = [string]$script:Config.PalServerExecutable
        WorkingDirectory = [string]$script:Config.PalServerRoot
        PassThru = $true
    }
    $arguments = @()
    if ($null -ne $script:Config.PSObject.Properties['ServerArguments'] -and $null -ne $script:Config.ServerArguments) {
        $arguments = @($script:Config.ServerArguments | ForEach-Object { [string]$_ })
    }
    if ($arguments.Count -gt 0) { $startParameters.ArgumentList = $arguments }
    $serverProcess = Start-Process @startParameters

    Write-Info 'Waiting for the local REST API to verify the world...'
    $serverInfo = Wait-ForPalRestInfo -Process $serverProcess -RestPassword $secrets.RestPassword -HeartbeatJob $heartbeatJob
    $verifiedWorldGuid = Normalize-WorldGuid -WorldGuid ([string]$serverInfo.worldguid)
    if ($verifiedWorldGuid -ne $localGuid) {
        throw "PalServer loaded $verifiedWorldGuid, but the script prepared $localGuid. Playing and uploading will not be allowed."
    }
    if ($baseVersion -gt 0) {
        $authoritativeGuid = Normalize-WorldGuid -WorldGuid ([string]$lock.worldGuid)
        if ($verifiedWorldGuid -ne $authoritativeGuid) {
            throw "PalServer loaded $verifiedWorldGuid, but the remote authority allows $authoritativeGuid."
        }
    }

    Write-Success ("World verified through REST: $verifiedWorldGuid. Server $($serverInfo.version).")
    Save-PendingSession -BaseVersion $baseVersion -WorldGuid $verifiedWorldGuid -SessionId $sessionId
    $sessionEntered = $true

    $endRequest = Wait-ForSessionEndRequest -Process $serverProcess -HeartbeatJob $heartbeatJob
    if ($endRequest.Reason -eq 'HeartbeatFailed') {
        Write-ErrorText 'The heartbeat failed three times. The server will shut down and progress will NOT be published automatically.'
        Stop-PalServerGracefully -Process $serverProcess -RestPassword $secrets.RestPassword -ExpectedWorldGuid $verifiedWorldGuid
        throw 'Remote lock is no longer reliable. The local save remains pending and protected.'
    }
    elseif ($endRequest.Reason -eq 'UserRequested') {
        Stop-PalServerGracefully -Process $serverProcess -RestPassword $secrets.RestPassword -ExpectedWorldGuid $verifiedWorldGuid
    }
    else {
        Write-WarningText 'PalServer was stopped by another mechanism. Its latest available save will be used.'
    }

    $serverProcess.Refresh()
    if (-not $serverProcess.HasExited) {
        throw 'PalServer is still running; the save will not be archived.'
    }
    if ((Get-HeartbeatStatus -Job $heartbeatJob) -eq 'fatal') {
        throw 'The heartbeat is no longer valid. Progress will not be published automatically.'
    }

    $archiveName = 'palworld-save-{0}-base-v{1:D6}.zip' -f ([string]$script:Config.PlayerName), $baseVersion
    $archivePath = Join-Path $TempRoot $archiveName
    Write-Info 'Archiving the closed save...'
    $finalArchive = New-WorldArchive -WorldGuid $verifiedWorldGuid -Destination $archivePath -BaseVersion $baseVersion -ServerVersion ([string]$serverInfo.version) -Purpose 'web-upload'
    Save-PendingSession -BaseVersion $baseVersion -WorldGuid $verifiedWorldGuid -SessionId $sessionId -ArchivePath $archivePath -ArchiveSha256 $finalArchive.Sha256
    Write-Success ("ZIP created: {0:N2} MiB; SHA-256 {1}" -f ($finalArchive.Size / 1MB), $finalArchive.Sha256)

    Write-Info 'Uploading the new version to the central service...'
    try {
        $upload = Upload-SaveArchive -Token $secrets.ApiToken -ZipPath $archivePath -SessionId $sessionId -BaseVersion $baseVersion -Sha256 $finalArchive.Sha256 -WorldGuid $verifiedWorldGuid
        $uploadConfirmed = $true
        $lockHeld = $false
        Save-LocalState -Version ([int]$upload.version) -WorldGuid ([string]$upload.worldGuid) -Sha256 ([string]$upload.sha256) -UpdatedBy ([string]$script:Config.PlayerName)
        Remove-Item -LiteralPath $PendingPath -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
        Write-Success "Save published as version $($upload.version)."
    }
    catch {
        Write-WarningText "The upload response failed: $($_.Exception.Message)"
        Write-Info 'Checking whether the server received the upload despite the connection loss...'
        if (Reconcile-Upload -Token $secrets.ApiToken -BaseVersion $baseVersion -Sha256 $finalArchive.Sha256 -WorldGuid $verifiedWorldGuid) {
            $remoteStatus = Invoke-ApiJson -Method GET -Path 'status' -Token $secrets.ApiToken
            $uploadConfirmed = $true
            $lockHeld = $false
            Save-LocalState -Version ([int]$remoteStatus.version) -WorldGuid ([string]$remoteStatus.worldGuid) -Sha256 ([string]$remoteStatus.sha256) -UpdatedBy ([string]$remoteStatus.updatedBy)
            Remove-Item -LiteralPath $PendingPath -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue
            Write-Success "Upload reconciled: remote version $($remoteStatus.version)."
        }
        else {
            $preserved = Join-Path $PendingUploadRoot ("{0}_{1}" -f (Get-Date -Format 'yyyyMMdd-HHmmss'), [IO.Path]::GetFileName($archivePath))
            Move-Item -LiteralPath $archivePath -Destination $preserved -Force
            Save-PendingSession -BaseVersion $baseVersion -WorldGuid $verifiedWorldGuid -SessionId $sessionId -ArchivePath $preserved -ArchiveSha256 $finalArchive.Sha256
            throw "The upload could not be confirmed. The ZIP is preserved at: $preserved"
        }
    }
}
catch {
    Write-ErrorText $_.Exception.Message
    Write-Log -Level 'error' -Message $_.Exception.ToString()

    if ($null -ne $serverProcess) {
        try {
            $serverProcess.Refresh()
            if (-not $serverProcess.HasExited -and $null -ne $secrets) {
                Write-WarningText 'Attempting a clean PalServer shutdown after the error...'
                if (Test-ValidWorldGuid -WorldGuid $verifiedWorldGuid) {
                    Stop-PalServerGracefully -Process $serverProcess -RestPassword $secrets.RestPassword -ExpectedWorldGuid $verifiedWorldGuid
                }
                else {
                    Stop-PalServerBestEffort -Process $serverProcess -RestPassword $secrets.RestPassword
                }
            }
        }
        catch {
            Write-ErrorText "Could not stop PalServer automatically: $($_.Exception.Message)"
        }
    }

    if ($lockHeld -and -not $sessionEntered -and -not [string]::IsNullOrWhiteSpace($sessionId) -and $null -ne $secrets) {
        [void](Unlock-Session -Token $secrets.ApiToken -SessionId $sessionId)
        $lockHeld = $false
    }
    elseif ($lockHeld -and $sessionEntered) {
        Write-WarningText 'The lock is not released after an unpublished modified session; it will expire when heartbeats stop. Do not start the server on the other PC until the state is reviewed.'
    }

    $scriptExitCode = 1
}
finally {
    Stop-HeartbeatJob -Job $heartbeatJob
    if ($null -ne $secrets) {
        $secrets.ApiToken = $null
        $secrets.RestPassword = $null
    }
}

if ($uploadConfirmed) {
    Write-Host ''
    Write-Success 'Process complete. The remote save is the latest authority.'
}
elseif ($TestOnly -or $SetupSecrets) {
    # The corresponding result was already displayed.
}
else {
    Write-Host ''
    Write-WarningText 'Process ended without confirming a new publication. Review the previous messages and data\pending-uploads.'
}

exit $scriptExitCode
