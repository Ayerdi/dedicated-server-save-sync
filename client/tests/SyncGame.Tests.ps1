Describe 'Registro de adaptadores' {
    It 'incluye un adaptador Palworld coherente con la configuración de ejemplo' {
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
