# Windows client

1. Download `dedicated-server-save-sync-client-v2.2.2.zip` and its `.sha256` file from release `v2.2.2`.
2. Verify SHA-256 before extracting the archive.
3. Copy `client/config.example.json` to `client/config.json`.
4. Configure the public URL, PalServer path and `Adapter=palworld`.
5. Run `Configure-Secrets.cmd`.
6. Run `Test-Connection.cmd`.
7. Start sessions with `Start-PalworldSync.cmd`.

PowerShell verification example:

```powershell
$zip = 'dedicated-server-save-sync-client-v2.2.2.zip'
$expected = ((Get-Content "$zip.sha256") -split '\s+')[0].ToLowerInvariant()
$actual = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actual -ne $expected) { throw 'Client SHA-256 mismatch.' }
```

The older Spanish command filenames remain in the package as compatibility aliases for existing users.

The API token and Palworld REST password are stored using Windows DPAPI. Do not copy `data/secrets.json` between machines.

Palworld's REST API must listen on localhost only. Do not expose that port through your router.

## Experimental Valheim client

The development tree also contains `config.valheim.example.json`, `Start-ValheimSync.cmd` and `client/adapters/valheim/`. Valheim credentials are stored separately under `data/valheim/`, and each PC must use its own token registered through [[Managed-Computers]]. See [[Valheim-Experimental]] before testing it.

> `clientVersion=1.2.0` is the internal Palworld adapter/client component version. It is independent from the product release number `v2.2.2`.

[[Cliente-Windows|Leer en español]]
