# Equipos gestionados

Algunos despliegues pueden activar `managedHosts`. El descriptor experimental de Valheim lo activa; Palworld v2.2.2 estable no.

El acceso gestionado separa a la **persona** del **PC físico**:

- Authentik autentica el username;
- Save Sync guarda si ese usuario está activo y su rol;
- cada PC aprobado se registra con un `ClientId` estable;
- cada PC recibe su propio token API vinculado a ese equipo;
- el lock y las publicaciones guardan la procedencia del equipo.

Crear un usuario en el panel de Save Sync **no** crea la cuenta correspondiente en Authentik. Authentik sigue siendo quien autentica; Save Sync solo autoriza el username ya autenticado.

## Flujo del administrador

1. Abre `/games/<gameKey>` como administrador.
2. Crea/habilita el usuario de Save Sync si hace falta.
3. Registra el PC físico y su `ClientId` estable.
4. Crea un token para ese equipo.
5. Copia el token en claro una sola vez a ese PC y configura localmente el mismo `ClientId`.

Los tokens vinculados a un equipo sirven solo para sincronizar. No pueden usar endpoints administrativos aunque su propietario tenga rol `admin`.

Los tokens antiguos sin equipo pueden seguir visibles para migración/administración, pero no pueden adquirir ni continuar una sesión sincronizada con `managedHosts`.

## Desactivar o revocar

- desactivar el usuario o el equipo bloquea actividad de sesión de confianza;
- revocar el token exacto también lo bloquea;
- un token no puede hacerse pasar por otro `ClientId` registrado;
- un lock activo se conserva deliberadamente en vez de borrarse al instante, para no liberar a otro host mientras el anterior podría seguir apagándose;
- tras un incidente, fuerza el unlock únicamente cuando hayas comprobado que el servidor anterior ya no puede escribir el mundo autoritativo.

Provisiona un token y un fichero de secretos DPAPI distinto en cada PC autorizado. No uses una copia del mismo fichero de secretos como mecanismo de autorización de máquina.

[[Managed-Computers|Read in English]]
