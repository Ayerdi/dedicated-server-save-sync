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
}
