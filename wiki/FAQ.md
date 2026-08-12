# FAQ

## ¿Es una alternativa a Steam Cloud?

No exactamente. Es un coordinador self-hosted para un servidor dedicado:
versiona, bloquea sesiones y transporta el save entre hosts autorizados.

## ¿Necesito un servidor Palworld 24/7?

No. La web Save Sync sí debe estar disponible cuando quieras intercambiar el
save, pero PalServer puede ejecutarse solo en el PC que vaya a alojar la sesión.

## ¿Fusiona dos mundos distintos?

No. Rechaza conflictos para evitar pérdida silenciosa, pero no puede fusionar
progreso divergente.

## ¿Debo instalar el backend desde `main`?

Para producción, no. Usa el tag de la release estable, actualmente `v2.2.0`, y
el cliente de esa misma release. `main` puede contener documentación o fixes aún
no publicados como una nueva versión del producto.

## ¿Por qué el ZIP es v2.2.0 pero el cliente muestra 1.2.0?

`v2.2.0` es la versión de la release completa del producto. `clientVersion=1.2.0`
es la versión interna del adaptador/cliente Palworld. El backend no usa ese
campo para decidir compatibilidad.

## ¿Puedo usarlo con otros juegos?

El backend conserva abstracciones genéricas, pero `v2.2.0` se publica y mantiene
como referencia estable de Palworld. La expansión multi-juego de gran alcance
queda fuera del roadmap de este repositorio.

## Is English documentation available?

Yes. Start at [[Home-English]] or use the
[English website](https://ayerdi.github.io/dedicated-server-save-sync/en/).
