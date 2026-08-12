# Windows Client

1. Download `dedicated-server-save-sync-client-v2.2.0.zip`.
2. Verify the `.sha256` file.
3. Copy `client/config.example.json` to `client/config.json`.
4. Configure the URL, PalServer path and `Adapter=palworld`.
5. Run `Configurar-secretos.cmd`.
6. Run `Probar-conexion.cmd`.
7. Start sessions with `Iniciar-PalworldSync.cmd`.

The API token and local REST password are protected with Windows DPAPI.

Palworld's REST API must listen on localhost only. Do not expose that port
through your router.
