BeforeAll {
    . "$PSScriptRoot/../Adapter.ps1" -LibraryOnly -ClientRoot "$PSScriptRoot/../../.."
}

Describe 'World GUID' {
    It 'acepta y normaliza un GUID hexadecimal' {
        Test-ValidWorldGuid 'a7e97baa767db9029ef013bb71e993a0' | Should -BeTrue
        Normalize-WorldGuid 'a7e97baa767db9029ef013bb71e993a0' |
            Should -Be 'A7E97BAA767DB9029EF013BB71E993A0'
    }

    It 'rejects empty values or values with another format' {
        Test-ValidWorldGuid '' | Should -BeFalse
        Test-ValidWorldGuid '../other-world' | Should -BeFalse
        { Normalize-WorldGuid '1234' } | Should -Throw
    }
}

Describe 'Entradas ZIP' {
    It 'accepts safe relative paths' {
        Test-SafeZipEntryName 'SaveGames/0/GUID/Level.sav' | Should -BeTrue
    }

    It 'rejects traversal, absolute paths and Windows drives' {
        Test-SafeZipEntryName '../Level.sav' | Should -BeFalse
        Test-SafeZipEntryName '/tmp/Level.sav' | Should -BeFalse
        Test-SafeZipEntryName 'C:\\temp\\Level.sav' | Should -BeFalse
    }
}

Describe 'Client version' {
    It 'declares a SemVer version' {
        $ClientVersion | Should -Match '^\d+\.\d+\.\d+$'
    }
}
