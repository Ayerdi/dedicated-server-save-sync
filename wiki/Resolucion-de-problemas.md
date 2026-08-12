# Resolución de problemas

## No adquiere el lock

Comprueba `/status`, que no exista otra sesión viva y que el reloj del host sea
razonable. No fuerces un unlock salvo que conozcas el estado del servidor.

## Detecta otro mundo

No fuerces el upload. Comprueba la carpeta configurada y el `worldGuid`. Esta
protección evita sobrescribir otro mundo.

## Queda un ZIP pendiente

No lo borres. El cliente conserva el pendiente cuando no puede confirmar la
publicación para permitir reconciliación posterior.

## Backup en `unknown`

Puede indicar un supervisor perdido o un marker vencido. No equivale a éxito ni
a fallo confirmado. Comprueba el repositorio externo antes de actuar.

No pegues logs completos en una issue: redacta tokens, rutas, GUID, IP y dominios.
