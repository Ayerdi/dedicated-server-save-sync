# Cliente Windows

1. Descarga `dedicated-server-save-sync-client-v2.2.2.zip` y su `.sha256` desde la release `v2.2.2`.
2. Verifica SHA-256 antes de extraer el ZIP.
3. Copia `client/config.example.json` como `client/config.json`.
4. Configura la URL pública, la ruta de PalServer y `Adapter=palworld`.
5. Ejecuta `Configurar-secretos.cmd` o el alias inglés `Configure-Secrets.cmd`.
6. Ejecuta `Probar-conexion.cmd` o `Test-Connection.cmd`.
7. Inicia con `Iniciar-PalworldSync.cmd` o `Start-PalworldSync.cmd`.

Ejemplo de verificación:

```powershell
$zip = 'dedicated-server-save-sync-client-v2.2.2.zip'
$expected = ((Get-Content "$zip.sha256") -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'El SHA-256 del cliente no coincide.' }
```

El token y la contraseña REST se guardan mediante Windows DPAPI. No copies `data/secrets.json` entre equipos.

La REST de Palworld debe escuchar únicamente en localhost. No abras ese puerto en el router.

> `clientVersion=1.2.0` es la versión interna del componente/adaptador Palworld y es independiente de la release completa `v2.2.2`.

[[Windows-Client|Read in English]]
