# Resolución de problemas

## No adquiere el lock

Comprueba `/status` y confirma que no existe otra sesión viva. No fuerces el unlock salvo que sepas que el otro PalServer ya no puede estar ejecutándose.

## Detecta otro mundo

No fuerces el upload. Comprueba la carpeta configurada y el `worldGuid`. Este rechazo evita que un mundo sobrescriba otro por error.

## Queda un ZIP pendiente

No lo borres. El cliente conserva publicaciones no confirmadas para poder reconciliarlas de forma segura.

## El backup aparece como `unknown` o `stalePending`

El supervisor puede haberse caído o la fila de cola puede llevar más tiempo del esperado. Esos estados no equivalen a éxito ni autorizan a borrar la versión protegida. Revisa los logs de `backup-supervisor` y el destino externo.

## ¿Qué puedo pegar en una issue?

Redacta tokens, contraseñas, rutas privadas, GUID, IP, dominios y nombres personales. Nunca adjuntes un save real, ZIP o base SQLite a una incidencia pública.

[[Troubleshooting|Read in English]]
