BeforeAll {
    . "$PSScriptRoot/../Adapter.ps1" -LibraryOnly -ClientRoot "$PSScriptRoot/../../.."
}

Describe 'World GUID' {
    It 'acepta y normaliza un GUID hexadecimal' {
        Test-ValidWorldGuid 'a7e97baa767db9029ef013bb71e993a0' | Should -BeTrue
        Normalize-WorldGuid 'a7e97baa767db9029ef013bb71e993a0' |
            Should -Be 'A7E97BAA767DB9029EF013BB71E993A0'
    }

    It 'rechaza valores vacíos o con otro formato' {
        Test-ValidWorldGuid '' | Should -BeFalse
        Test-ValidWorldGuid '../otro-mundo' | Should -BeFalse
        { Normalize-WorldGuid '1234' } | Should -Throw
    }
}

Describe 'Entradas ZIP' {
    It 'acepta rutas relativas seguras' {
        Test-SafeZipEntryName 'SaveGames/0/GUID/Level.sav' | Should -BeTrue
    }

    It 'rechaza traversal, rutas absolutas y unidades Windows' {
        Test-SafeZipEntryName '../Level.sav' | Should -BeFalse
        Test-SafeZipEntryName '/tmp/Level.sav' | Should -BeFalse
        Test-SafeZipEntryName 'C:\\temp\\Level.sav' | Should -BeFalse
    }
}

Describe 'Versión del cliente' {
    It 'declara una versión SemVer' {
        $ClientVersion | Should -Match '^\d+\.\d+\.\d+$'
    }
}
