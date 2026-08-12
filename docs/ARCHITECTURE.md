# Arquitectura e invariantes

## Autoridades

El orden de progreso lo determina `versions.version`, nunca la fecha de los
archivos. `current_save` referencia una versión inmutable. La primera publicación
establece `save_identity`; las siguientes deben coincidir.

Una publicación válida requiere simultáneamente:

- token activo del usuario que adquirió el lock;
- `sessionId` correspondiente al hash almacenado;
- lock no caducado;
- `baseVersion` igual a la versión vigente;
- identidad válida según el adaptador e igual a la partida autoritativa;
- ZIP e integridad SHA-256 válidos.

## Máquina de estados

```text
sin inicializar (v0, identidad null)
  └─ lock base0 + upload válido → inicializado (v1, identidad fijada)

disponible
  └─ lock → ocupado
       ├─ heartbeat → ocupado con nueva caducidad
       ├─ upload válido → nueva versión + disponible
       ├─ unlock propio → disponible
       └─ TTL agotado → disponible en el siguiente acceso transaccional
```

Solo se devuelve el `sessionId` al adquirir el lock. La API, el panel y la
auditoría no lo exponen posteriormente.

## Atomicidad

Los locks, uploads, restauraciones y limpieza usan `BEGIN IMMEDIATE`. El flujo
de publicación es:

1. recibir en temporal privado;
2. calcular SHA-256 y validar ZIP;
3. volver a comprobar lock, versión e identidad dentro de la transacción;
4. mover a un nombre histórico inmutable con `os.replace`;
5. sincronizar el directorio;
6. insertar versión y actualizar `current_save`;
7. si el backup externo está habilitado, insertar **en la misma transacción** la
   versión en `pending_backups`;
8. liberar el lock y confirmar SQLite;
9. reconciliar la retención por slot sin tocar versiones pendientes.

Una excepción antes del commit mantiene la versión anterior. Los ZIP huérfanos
se reconcilian al arrancar o tras otra publicación. Una fila de
`pending_backups` protege su ZIP aunque sea antigua: la retención no la purga
por edad.

## Supervisor durable de backup

Gunicorn no ejecuta comandos externos en producción. Un servicio Compose
separado, `backup-supervisor`, comparte SQLite y el volumen privado. Consume
`pending_backups`, refresca `started_at` al comenzar un intento, lanza el hook en
un process-group aislado y registra el resultado.

La finalización confirma bajo un único `BEGIN IMMEDIATE` la eliminación de la
fila pendiente, la auditoría de éxito/fallo y la **retención de metadata**. Si
esa transacción falla, rollback conserva el trabajo. La semántica es
**at-least-once**: un crash cuyo resultado no pudo registrarse puede repetir el
hook al arrancar de nuevo.

El borrado físico de ZIPs obsoletos ocurre después de ese commit y bajo un
segundo `BEGIN IMMEDIATE` que vuelve a comprobar qué rutas siguen referenciadas.
Así se cubren las dos carreras opuestas: un crash antes del primer commit nunca
puede dejar SQLite apuntando a un ZIP ya eliminado, y una publicación concurrente
no puede reutilizar un nombre huérfano entre el snapshot y el `unlink`. Si el
proceso cae en la segunda fase, el único residuo posible es un ZIP huérfano,
recuperable por la reconciliación posterior.

Una parada controlada del supervisor termina su grupo hijo pero conserva la
fila. Un crash de Gunicorn no afecta al proceso de backup porque vive en otro
contenedor. Un crash duro del propio supervisor deja la cola en SQLite y Docker
elimina el process namespace del contenedor; al reiniciar, la nueva instancia
reclama el trabajo. Un singleton `flock` impide dos consumidores simultáneos
sobre el mismo almacenamiento.

El timeout observado o un exit code distinto de cero se consideran un resultado
final conocido y se auditan como `backup_hook_failed`; no se reintentan
indefinidamente. El hook debe tolerar repetición para el caso incierto de crash.

## Concurrencia

- SQLite usa WAL y `busy_timeout`.
- La creación/migración del esquema se protege con `flock` multiproceso.
- `PRAGMA user_version=3` permite detectar upgrades y rechazar downgrades.
- Dos adquisiciones simultáneas producen un único ganador.
- Dos uploads sobre la misma base no pueden publicar la misma versión.
- La limpieza física toma un nuevo lock de escritura y revalida referencias
  después de que la retención de metadata ya esté confirmada.
- La cola de backup y la publicación nacen en el mismo commit SQLite: nunca
  existe una versión confirmada que debiera respaldarse pero no haya quedado
  encolada por muerte del worker entre dos transacciones.

Cada despliegue gestiona un único `gameKey` y requiere una sola instancia del
backend y un supervisor sobre filesystem Linux local. Otro juego usa otro
proyecto Compose, base y volumen. Esta separación es también el aislamiento
entre juegos.

La política de migración y backup está en [MIGRATIONS.md](MIGRATIONS.md).

## Identidad de la partida

El JSON `config/games/{gameKey}.json` declara el campo, etiqueta, regex y
normalización. El backend persiste el valor canónico en `save_identity` y lo
expone además con el nombre específico del adaptador.

Palworld usa `worldGuid`, `^[A-F0-9]{32}$` y uppercase. Su backend no analiza
`Level.sav`; la garantía depende de que el adaptador obtenga correctamente el
identificador real del juego.

La restauración histórica conserva la identidad y crea una versión nueva. No
existe un endpoint normal para cambiar de partida.

## Fronteras de confianza

- Traefik elimina cabeceras de identidad aportadas por el cliente.
- Authentik autentica el panel.
- El proxy inyecta una cabecera secreta solo después de ForwardAuth.
- Los scripts usan Bearer independiente de las cookies web.
- La REST local de Palworld usa otras credenciales y no debe exponerse fuera de
  localhost.
- El almacenamiento ZIP y SQLite no está servido por el frontend.
- `backup-supervisor` no se conecta a Traefik ni expone puerto HTTP; solo
  comparte el volumen privado y los secretos necesarios para el destino de
  backup.

## Retención

Cada usuario se asocia a un `slot` mediante
`SAVE_SYNC_USER_IDENTITIES_JSON`. Se conservan las últimas
`SAVE_SYNC_RETENTION_PER_SLOT` versiones físicas de cada slot. Los alias del
mismo anfitrión deben compartir slot. Las versiones en `pending_backups` se
conservan adicionalmente hasta que el supervisor registre un resultado final.

El comando `SAVE_SYNC_POST_PUBLISH_COMMAND` recibe versión, ruta e identidad
publicada. Su ejecución es asíncrona respecto a la petición HTTP porque la
realiza el supervisor independiente; nunca compromete la versión ya confirmada.
