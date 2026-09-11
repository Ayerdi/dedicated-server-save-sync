BeforeAll {
    . "$PSScriptRoot/../Adapter.ps1" -LibraryOnly -ClientRoot "$PSScriptRoot/../../.."

    function New-TestValheimWorld {
        param(
            [string]$Root,
            [string]$Name = 'Dedicated',
            [long]$WorldUid = 2352155610,
            [long]$Generation = 1
        )
        New-Item -ItemType Directory -Path $Root -Force | Out-Null

        $payload = [IO.MemoryStream]::new()
        $payloadWriter = [IO.BinaryWriter]::new($payload, [Text.Encoding]::UTF8, $true)
        try {
            $payloadWriter.Write([int]41)
            $payloadWriter.Write($Name)
            $payloadWriter.Write('fmBw7Z5aR6')
            $payloadWriter.Write([int]-1257619157)
            $payloadWriter.Write([long]$WorldUid)
            $payloadWriter.Write([int]2)
            $payloadWriter.Write([byte]0)
            $payloadWriter.Flush()
            $bytes = $payload.ToArray()
        }
        finally {
            $payloadWriter.Dispose()
            $payload.Dispose()
        }

        $fwl = Join-Path $Root ("_main.{0}.fwl2" -f $Generation)
        $stream = [IO.FileStream]::new($fwl, [IO.FileMode]::Create, [IO.FileAccess]::Write, [IO.FileShare]::None)
        $writer = [IO.BinaryWriter]::new($stream, [Text.Encoding]::UTF8, $false)
        try {
            $writer.Write([int]$bytes.Length)
            $writer.Write($bytes)
        }
        finally {
            $writer.Dispose()
        }

        Set-Content -LiteralPath (Join-Path $Root ("_main.{0}.db2" -f $Generation)) -Value 'database'
        Set-Content -LiteralPath (Join-Path $Root ("_main.{0}.chunks" -f $Generation)) -Value 'chunk-index'
        Set-Content -LiteralPath (Join-Path $Root ("_main.{0}.ok" -f $Generation)) -Value 'ok'
        Set-Content -LiteralPath (Join-Path $Root '00_00__0_1.chunk') -Value 'chunk-data'
        return $Root
    }

    function Set-TestConfig {
        param([string]$SaveRoot)
        $script:Config = [pscustomobject]@{
            PlayerName = 'Host A'
            ClientId = 'host-a-pc'
            SaveRoot = $SaveRoot
            WorldName = 'Dedicated'
            LocalBackupRetention = 5
        }
    }
}

Describe 'Valheim 1.0 world metadata' {
    It 'reads the intrinsic World UID from a complete folder-based generation' {
        $world = Join-Path $TestDrive 'world'
        New-TestValheimWorld -Root $world -WorldUid 2352155610 -Generation 7 | Out-Null

        $identity = Get-ValheimWorldIdentity -WorldPath $world

        $identity.WorldUid | Should -Be '2352155610'
        $identity.WorldName | Should -Be 'Dedicated'
        $identity.Generation | Should -Be 7
        $identity.WorldVersion | Should -Be 41
    }

    It 'selects the highest complete generation without using timestamps' {
        $world = Join-Path $TestDrive 'generations'
        New-TestValheimWorld -Root $world -WorldUid 42 -Generation 2 | Out-Null
        New-TestValheimWorld -Root $world -WorldUid 42 -Generation 9 | Out-Null
        (Get-Item -LiteralPath (Join-Path $world '_main.2.fwl2')).LastWriteTimeUtc = [DateTime]::UtcNow.AddHours(1)

        (Get-ValheimWorldIdentity -WorldPath $world).Generation | Should -Be 9
    }

    It 'rejects a directory containing different World UIDs' {
        $world = Join-Path $TestDrive 'mixed'
        New-TestValheimWorld -Root $world -WorldUid 42 -Generation 1 | Out-Null
        New-TestValheimWorld -Root $world -WorldUid 43 -Generation 2 | Out-Null

        { Get-ValheimWorldIdentity -WorldPath $world } | Should -Throw '*different World UIDs*'
    }

    It 'requires all four main generation files' {
        $world = Join-Path $TestDrive 'incomplete'
        New-TestValheimWorld -Root $world -WorldUid 42 -Generation 1 | Out-Null
        Remove-Item -LiteralPath (Join-Path $world '_main.1.ok')

        { Get-ValheimWorldIdentity -WorldPath $world } | Should -Throw '*No complete Valheim 1.0 world generation*'
    }
}

Describe 'Valheim whole-world archive' {
    BeforeEach {
        $saveRoot = Join-Path $TestDrive ([Guid]::NewGuid().ToString('N'))
        $world = Join-Path (Join-Path $saveRoot 'worlds_local') 'Dedicated'
        New-TestValheimWorld -Root $world -WorldUid 9001 -Generation 3 | Out-Null
        Set-TestConfig -SaveRoot $saveRoot
        $script:BackupRoot = Join-Path $TestDrive 'backups'
        Ensure-Directory -Path $script:BackupRoot
    }

    It 'archives the entire world directory including chunk files' {
        $zip = Join-Path $TestDrive 'world.zip'
        $result = New-WorldArchive -WorldPath (Get-WorldFolderPath) -Destination $zip -BaseVersion 4 -Purpose 'test'

        $result.WorldUid | Should -Be '9001'
        $manifest = Read-ArchiveManifest -ZipPath $zip
        $manifest.worldUid | Should -Be '9001'
        $manifest.worldName | Should -Be 'Dedicated'

        $archive = [IO.Compression.ZipFile]::OpenRead($zip)
        try {
            @($archive.Entries.FullName) | Should -Contain 'world/00_00__0_1.chunk'
            @($archive.Entries.FullName) | Should -Contain 'world/_main.3.fwl2'
            @($archive.Entries.FullName) | Should -Contain 'manifest.json'
        }
        finally {
            $archive.Dispose()
        }
    }

    It 'replaces the world directory instead of merging stale chunks' {
        $sourceWorld = Get-WorldFolderPath
        $zip = Join-Path $TestDrive 'replacement.zip'
        New-WorldArchive -WorldPath $sourceWorld -Destination $zip -BaseVersion 2 -Purpose 'test' | Out-Null
        Set-Content -LiteralPath (Join-Path $sourceWorld 'stale.chunk') -Value 'must disappear'

        Install-DownloadedSave -ZipPath $zip -ExpectedWorldUid '9001'

        Test-Path -LiteralPath (Join-Path (Get-WorldFolderPath) 'stale.chunk') | Should -BeFalse
        Test-Path -LiteralPath (Join-Path (Get-WorldFolderPath) '00_00__0_1.chunk') | Should -BeTrue
        (Get-ValheimWorldIdentity -WorldPath (Get-WorldFolderPath)).WorldUid | Should -Be '9001'
    }
}

Describe 'Valheim input validation' {
    It 'normalizes signed Int64 World UIDs without changing their value' {
        Test-ValidWorldUid '-42' | Should -BeTrue
        Normalize-WorldUid '-00042' | Should -Be '-42'
        Test-ValidWorldUid 'not-a-uid' | Should -BeFalse
    }

    It 'rejects unsafe world names and ZIP paths' {
        Test-SafeWorldName 'Dedicated' | Should -BeTrue
        Test-SafeWorldName '..' | Should -BeFalse
        Test-SafeWorldName '..\other' | Should -BeFalse
        Test-SafeWorldName '.. ' | Should -BeFalse
        Test-SafeWorldName 'Dedicated.' | Should -BeFalse
        Test-SafeWorldName 'NUL' | Should -BeFalse
        Test-SafeWorldName 'CON.txt' | Should -BeFalse
        Test-SafeZipEntryName 'world/00_00__0_1.chunk' | Should -BeTrue
        Test-SafeZipEntryName '../outside' | Should -BeFalse
        Test-SafeZipEntryName 'C:\\outside' | Should -BeFalse
        Test-SafeZipEntryName 'world/file.txt:stream' | Should -BeFalse
        Test-SafeZipEntryName 'world/NUL.txt' | Should -BeFalse
        Test-SafeZipEntryName 'world//duplicate-separator.chunk' | Should -BeFalse
    }

    It 'quotes Windows arguments without changing simple arguments' {
        Quote-WindowsArgument 'Dedicated' | Should -Be 'Dedicated'
        Quote-WindowsArgument 'C:\Program Files\Valheim\valheim_server.exe' |
            Should -Be '"C:\Program Files\Valheim\valheim_server.exe"'
    }
}

Describe 'Valheim secret protection' {
    It 'round-trips secrets through Windows DPAPI without PowerShell.Security cmdlets' {
        $protected = Protect-DpapiString -PlainText 'dummy-secret'

        $protected | Should -Not -Be 'dummy-secret'
        { [Convert]::FromBase64String($protected) } | Should -Not -Throw
        (Unprotect-DpapiString -ProtectedText $protected) | Should -Be 'dummy-secret'
    }
}

Describe 'Valheim session safety' {
    It 'rejects a pending session when the lock base advanced during acquisition' {
        $pending = [pscustomobject]@{ baseVersion = 4; worldUid = '42' }
        $lock = [pscustomobject]@{ baseVersion = 5; worldUid = '42' }

        { Assert-PendingSessionMatchesLock -Pending $pending -Lock $lock } |
            Should -Throw '*remote version changed while acquiring the lock*'
    }

    It 'rejects a pending session when the freshly acquired lock has another UID' {
        $pending = [pscustomobject]@{ baseVersion = 4; worldUid = '42' }
        $lock = [pscustomobject]@{ baseVersion = 4; worldUid = '43' }

        { Assert-PendingSessionMatchesLock -Pending $pending -Lock $lock } |
            Should -Throw '*does not match the newly acquired lock*'
    }

    It 'requires three heartbeat attempts to fit before lock expiry' {
        $healthyLock = [pscustomobject]@{ expiresAt = [DateTimeOffset]::UtcNow.AddSeconds(300).ToString('o') }
        $shortLock = [pscustomobject]@{ expiresAt = [DateTimeOffset]::UtcNow.AddSeconds(120).ToString('o') }

        { Assert-HeartbeatFitsLockTtl -Lock $healthyLock -IntervalSeconds 60 } |
            Should -Not -Throw
        { Assert-HeartbeatFitsLockTtl -Lock $shortLock -IntervalSeconds 60 } |
            Should -Throw '*too large for the acquired lock TTL*'
    }

    It 'fails heartbeat status closed when the last known lock expiry is stale' {
        $stateFile = Join-Path $TestDrive 'expired-heartbeat.json'
        Write-JsonAtomic -Path $stateFile -Value ([ordered]@{
            status = 'ok'
            expiresAt = [DateTimeOffset]::UtcNow.AddSeconds(-1).ToString('o')
            consecutiveFailures = 0
        })

        Get-HeartbeatStatus -Job $null -StateFile $stateFile | Should -Be 'fatal'
    }

    It 'bounds each heartbeat request below the normal interval' {
        Get-HeartbeatRequestTimeoutSeconds -IntervalSeconds 60 | Should -Be 30
        Get-HeartbeatRequestTimeoutSeconds -IntervalSeconds 5 | Should -Be 2
    }

    It 'treats a terminated heartbeat job as fatal even with a fresh state file' {
        $stateFile = Join-Path $TestDrive 'fresh-heartbeat.json'
        Write-JsonAtomic -Path $stateFile -Value ([ordered]@{
            status = 'ok'
            expiresAt = [DateTimeOffset]::UtcNow.AddMinutes(5).ToString('o')
            consecutiveFailures = 0
        })
        $job = Start-Job -ScriptBlock { return }
        try {
            Wait-Job -Job $job | Out-Null
            Get-HeartbeatStatus -Job $job -StateFile $stateFile | Should -Be 'fatal'
        }
        finally {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
    }

    It 'refuses to continue pre-session work after heartbeat expiry' {
        $stateFile = Join-Path $TestDrive 'expired-before-start.json'
        Write-JsonAtomic -Path $stateFile -Value ([ordered]@{
            status = 'ok'
            expiresAt = [DateTimeOffset]::UtcNow.AddSeconds(-1).ToString('o')
            consecutiveFailures = 0
        })

        { Assert-HeartbeatCanContinue -Job $null -Context 'server startup' -StateFile $stateFile } |
            Should -Throw '*remote lock is no longer reliable*'
    }
}

Describe 'Valheim client version' {
    It 'declares a SemVer version' {
        $ClientVersion | Should -Match '^\d+\.\d+\.\d+$'
    }
}
