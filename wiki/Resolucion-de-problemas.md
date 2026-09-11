# Resolución de problemas

## No adquiere el lock

Comprueba `/status` y confirma que no existe otra sesión viva. No fuerces el unlock salvo que sepas que el otro PalServer ya no puede estar ejecutándose.

## Detecta otro mundo

No fuerces el upload. Comprueba la carpeta configurada y el `worldGuid`. Este rechazo evita que un mundo sobrescriba otro por error.

## Queda un ZIP pendiente

No lo borres. El cliente conserva publicaciones no confirmadas para poder reconciliarlas de forma segura.

## Valheim indica que el equipo/token está desactivado o no coincide

Revisa el panel de Valheim: usuario, equipo registrado y token deben estar activos, y `config.json` debe usar exactamente el `ClientId` estable asignado a ese token. No reutilices el token de un PC en otro.

## Valheim se detiene al degradarse el heartbeat/lease

Es un comportamiento deliberado de fallo seguro. El cliente reserva TTL suficiente para un apagado controlado en vez de permitir que el lock caduque mientras `valheim_server.exe` podría seguir escribiendo. No fuerces el unlock hasta confirmar que el proceso anterior se ha detenido.

Aunque el lock termine caducando de forma natural, eso **no demuestra** que un servidor antiguo fallido/bloqueado haya desaparecido. Confirma el proceso escritor anterior y el estado de sesión pendiente antes de iniciar otro host.

## El backup aparece como `unknown` o `stalePending`

El supervisor puede haberse caído o la fila de cola puede llevar más tiempo del esperado. Esos estados no equivalen a éxito ni autorizan a borrar la versión protegida. Revisa los logs de `backup-supervisor` y el destino externo.

## ¿Qué puedo pegar en una issue?

Redacta tokens, contraseñas, rutas privadas, GUID, IP, dominios y nombres personales. Nunca adjuntes un save real, ZIP o base SQLite a una incidencia pública.

[[Troubleshooting|Read in English]]
