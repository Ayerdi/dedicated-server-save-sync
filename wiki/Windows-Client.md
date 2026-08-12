# Windows Client

1. Download `dedicated-server-save-sync-client-v2.2.1.zip` and its `.sha256`
   file from release `v2.2.1`.
2. Verify SHA-256 before extracting the archive.
3. Copy `client/config.example.json` to `client/config.json`.
4. Configure the URL, PalServer path and `Adapter=palworld`.
5. Run `Configurar-secretos.cmd`.
6. Run `Probar-conexion.cmd`.
7. Start sessions with `Iniciar-PalworldSync.cmd`.

PowerShell verification example:

```powershell
$zip = 'dedicated-server-save-sync-client-v2.2.1.zip'
$expected = ((Get-Content "$zip.sha256") -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Client SHA-256 mismatch.' }
```

The API token and local REST password are protected with Windows DPAPI.

Palworld's REST API must listen on localhost only. Do not expose that port
through your router.

> The Palworld adapter currently identifies itself internally as
> `clientVersion=1.2.0`. That is the Windows adapter/component version, not the
> product release number. The stable product bundle containing it is `v2.2.1`.
