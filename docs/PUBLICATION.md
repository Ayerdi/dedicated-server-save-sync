# Checklist para hacer público el repositorio

La visibilidad no debe cambiar hasta completar todos los puntos.

## Código y seguridad

- [x] `LICENSE` Apache-2.0 incluido desde la fuente oficial.
- [x] Derechos sobre el código confirmados por el propietario al elegir Apache-2.0.
- [ ] CI verde en el commit candidato de licencia.
- [x] `pip-audit`, Gitleaks, cobertura y E2E sin hallazgos.
- [ ] Prueba manual real con PalServer en Windows documentada.
- [x] Historial Git revisado sin secretos, saves ni datos personales.
- [x] Artefacto candidato y checksum generados dos veces con resultado idéntico.
- [ ] Tag firmado y release estable creados después de la aceptación manual.

La aceptación manual con PalServer se ha pospuesto conscientemente. Mientras
permanezca pendiente se puede generar un artefacto candidato para verificar su
reproducibilidad, pero no crear el tag ni el release público.

## Comunidad

- [x] README, soporte, contribución, conducta y política de seguridad revisados.
- [x] Disclaimer de marcas visible.
- [x] Issues y Discussions preparados.
- [ ] Respuesta privada de vulnerabilidades asignada a un mantenedor.

## Cambio de visibilidad

1. Crear un backup o mirror privado del repositorio.
2. Cambiar manualmente la visibilidad en GitHub Settings.
3. Ejecutar inmediatamente:

   ```bash
   bash scripts/configure-public-repository.sh --apply
   ```

   El script se niega a operar mientras el repositorio sea privado y nunca
   cambia la visibilidad por sí mismo.

4. Verificar protección de `main`, Dependabot, reporte privado, topics y CI.
5. Abrir una incidencia de prueba sin datos sensibles y cerrarla.

## Rollback

Si aparece información privada, volver a privado de inmediato, revocar cualquier
secreto, retirar artefactos y limpiar el historial antes de considerar otra
apertura. Borrar un archivo en un commit posterior no elimina su historial.
