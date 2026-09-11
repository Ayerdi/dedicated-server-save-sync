# Soporte experimental de Valheim

> **No forma parte de la versión estable v2.2.2.** El adaptador para Valheim 1.0 está disponible en la rama de desarrollo `main`. Pruébalo con un mundo aislado y con backup independiente antes de plantearte usarlo con un mundo real.

Valheim reutiliza el mismo modelo de versión autoritativa, lock, heartbeat, historial y recuperación que el backend estable de Palworld, pero el adaptador Windows controla un ciclo de servidor/save diferente.

## Qué cambia

- los saves están bajo `worlds_local/<WorldName>`;
- Save Sync trata la carpeta completa del mundo configurado como una unidad;
- la identidad autoritativa es el `worldUid` intrínseco de 64 bits con signo leído de los metadatos `.fwl2` confirmados;
- el adaptador inicia directamente `valheim_server.exe`;
- solicita el apagado limpio mediante CTRL+C;
- solo publica cuando el proceso ha terminado y existe una generación final completa;
- Valheim activa [[Equipos-Gestionados]] y por tanto exige un token vinculado al PC físico registrado.

## Configuración segura

1. Despliega Valheim con su propio `gameKey=valheim`, base SQLite y almacenamiento. Nunca compartas base o storage con Palworld.
2. Registra todos los PCs que puedan alojar la partida con un `ClientId` estable y distinto.
3. Crea un token vinculado a cada equipo.
4. En cada PC, copia `client/config.valheim.example.json` como `client/config.json` y configura su `ClientId`, rutas, mundo y servidor.
5. Ejecuta `Configure-Secrets.cmd`/`Configurar-secretos.cmd` e introduce el token de ese PC y la contraseña del servidor Valheim.
6. Ejecuta `Test-Connection.cmd`/`Probar-conexion.cmd`.
7. Para una sesión sincronizada, inicia únicamente con `Start-ValheimSync.cmd`/`Iniciar-ValheimSync.cmd`.

Valheim no está incluido en el paquete estable del cliente v2.2.2. Usa backend y cliente procedentes del mismo commit/artefacto de desarrollo probado.

## Seguridad de sesión

El cliente adquiere el lock remoto antes de tocar el save autoritativo, mantiene heartbeats mientras Valheim está activo y reserva suficiente TTL para un apagado controlado. Si el lease deja de ser fiable, falla de forma segura e intenta detener Valheim mientras el otro host sigue excluido.

Una salida inesperada del servidor **no** se publica automáticamente.

Si no puede confirmar un upload, conserva el ZIP final en `data/valheim/pending-uploads` y mantiene el estado pendiente para recuperación.

Si el apagado falló o quedó una sesión pendiente, **que caduque el TTL no demuestra que el antiguo `valheim_server.exe` se haya detenido**. Antes de arrancar otro host, confirma que el proceso escritor anterior ya no existe y revisa el estado pendiente.

## Antes de usar un mundo real

Ejecuta el [checklist real de cuatro hosts A → B → C → D → A](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/client/MANUAL-ACCEPTANCE-VALHEIM.md). Comprueba exclusión por lock, reemplazo remoto, apagado limpio, desactivación de equipos y recuperación de errores.

No uses la única copia válida de un mundo real como entrada de esa prueba.

## Más información

- [Guía técnica completa de Valheim](https://github.com/Ayerdi/dedicated-server-save-sync/blob/main/docs/VALHEIM.md)
- [[Equipos-Gestionados]]
- [[Arquitectura]]
- [[Resolucion-de-problemas]]
- [[Home|English]]
