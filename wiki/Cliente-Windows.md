# Cliente Windows

1. Descarga `dedicated-server-save-sync-client-v2.2.0.zip` y su `.sha256` desde
   la release `v2.2.0`.
2. Verifica el SHA-256 antes de extraer el ZIP.
3. Copia `client/config.example.json` como `client/config.json`.
4. Configura URL, PalServer y `Adapter=palworld`.
5. Ejecuta `Configurar-secretos.cmd`.
6. Ejecuta `Probar-conexion.cmd`.
7. Inicia sesiones con `Iniciar-PalworldSync.cmd`.

Ejemplo de verificación en PowerShell:

```powershell
$zip = 'dedicated-server-save-sync-client-v2.2.0.zip'
$expected = ((Get-Content "$zip.sha256") -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'El SHA-256 del cliente no coincide.' }
```

El token y la contraseña REST se guardan cifrados con DPAPI.

La REST de Palworld debe escuchar únicamente en localhost. No abras su puerto
en el router.

> El adaptador Palworld muestra internamente `clientVersion=1.2.0`. Esa es la
> versión del componente/adaptador Windows y no el número de la release del
> producto. El paquete estable que contiene ese adaptador es `v2.2.0`.
