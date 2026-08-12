# Cliente Windows

1. Descarga `dedicated-server-save-sync-client-v2.2.0.zip`.
2. Verifica el `.sha256`.
3. Copia `client/config.example.json` como `client/config.json`.
4. Configura URL, PalServer y `Adapter=palworld`.
5. Ejecuta `Configurar-secretos.cmd`.
6. Ejecuta `Probar-conexion.cmd`.
7. Inicia sesiones con `Iniciar-PalworldSync.cmd`.

El token y la contraseña REST se guardan cifrados con DPAPI.

La REST de Palworld debe escuchar únicamente en localhost. No abras su puerto
en el router.
