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
7. liberar el lock y confirmar SQLite;
8. reconciliar la retención por slot.

Una excepción antes del commit mantiene la versión anterior. Los ZIP huérfanos
se reconcilian al arrancar o tras otra publicación.

## Concurrencia

- SQLite usa WAL y `busy_timeout`.
- La creación/migración del esquema se protege con `flock` multiproceso.
- `PRAGMA user_version=2` permite detectar upgrades y rechazar downgrades.
- Dos adquisiciones simultáneas producen un único ganador.
- Dos uploads sobre la misma base no pueden publicar la misma versión.
- La limpieza física permanece bajo el mismo lock de escritura que el snapshot
  de referencias, evitando borrar un ZIP recién publicado.

Cada despliegue gestiona un único `gameKey` y requiere una sola instancia del
servicio sobre filesystem Linux local. Otro juego usa otro proyecto Compose,
base y volumen. Esta separación es también el aislamiento entre juegos.

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

## Retención

Cada usuario se asocia a un `slot` mediante
`SAVE_SYNC_USER_IDENTITIES_JSON`. Se conserva la última versión física de cada
slot. Los alias del mismo anfitrión deben compartir slot. La versión vigente
nunca se elimina durante una publicación fallida.
