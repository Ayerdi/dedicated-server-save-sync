Describe 'Registro de adaptadores' {
    It 'includes a Palworld adapter consistent with the example configuration' {
        $clientRoot = Resolve-Path "$PSScriptRoot/.."
        $config = Get-Content "$clientRoot/config.example.json" -Raw | ConvertFrom-Json
        $manifest = Get-Content "$clientRoot/adapters/palworld/adapter.json" -Raw |
            ConvertFrom-Json

        $config.Adapter | Should -Be $manifest.key
        $config.GameKey | Should -Be $manifest.gameKey
        Test-Path "$clientRoot/adapters/$($manifest.key)/$($manifest.entrypoint)" |
            Should -BeTrue
    }

    It 'includes a Valheim adapter consistent with the Valheim example configuration' {
        $clientRoot = Resolve-Path "$PSScriptRoot/.."
        $config = Get-Content "$clientRoot/config.valheim.example.json" -Raw | ConvertFrom-Json
        $manifest = Get-Content "$clientRoot/adapters/valheim/adapter.json" -Raw |
            ConvertFrom-Json

        $config.Adapter | Should -Be $manifest.key
        $config.GameKey | Should -Be $manifest.gameKey
        Test-Path "$clientRoot/adapters/$($manifest.key)/$($manifest.entrypoint)" |
            Should -BeTrue
        Test-Path "$PSScriptRoot/../../config/games/valheim.json" |
            Should -BeTrue
    }

    It 'pins the Valheim launchers to the Valheim adapter' {
        $clientRoot = Resolve-Path "$PSScriptRoot/.."
        foreach ($launcher in @('Start-ValheimSync.cmd','Iniciar-ValheimSync.cmd')) {
            (Get-Content "$clientRoot/$launcher" -Raw) |
                Should -Match '-ExpectedAdapter valheim'
        }
    }
}
