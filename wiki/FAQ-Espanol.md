# Preguntas frecuentes

## ¿Es una alternativa a Steam Cloud?

No exactamente. Save Sync coordina un servidor dedicado: versiona el save, bloquea sesiones y transporta un único mundo autoritativo entre hosts autorizados.

El proyecto sucesor podrá explorar sincronización entre dispositivos/cloud como un modo distinto, pero queda deliberadamente fuera de este repositorio de referencia para Palworld.

## ¿Necesito un servidor Palworld 24/7?

No. El servicio web Save Sync debe estar disponible cuando los hosts intercambian el save, pero PalServer solo necesita ejecutarse en el PC que aloja la sesión actual.

## ¿Fusiona dos versiones distintas del mundo?

No. Rechaza publicaciones conflictivas para evitar pérdida silenciosa, pero no puede fusionar semánticamente progreso divergente de Palworld.

## ¿Debo desplegar desde `main`?

No en producción. Usa el tag estable actual, `v2.2.2`, y el cliente de esa misma release. `main` puede contener cambios aún no publicados.

## ¿Por qué el producto dice v2.2.2 y el cliente muestra 1.2.0?

`v2.2.2` es la release completa del producto. `clientVersion=1.2.0` es la versión interna del adaptador/componente Windows registrada en manifests y diagnóstico.

## ¿Puedo usar este repositorio con otros juegos?

El backend conserva primitivas genéricas, pero este repositorio se mantiene como referencia estable de Palworld. El soporte multi-juego amplio pertenece al proyecto sucesor separado.

## ¿Hay documentación en inglés?

Sí. Empieza en [[Home]].
