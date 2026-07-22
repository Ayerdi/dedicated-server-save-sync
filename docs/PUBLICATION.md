# Checklist para hacer público el repositorio

La visibilidad no debe cambiar hasta completar todos los puntos.

## Código y seguridad

- [ ] `LICENSE` elegido por el propietario y derechos sobre el código confirmados.
- [ ] CI verde en el commit candidato.
- [ ] `pip-audit`, Gitleaks, cobertura y E2E sin hallazgos.
- [ ] Prueba manual real con PalServer en Windows documentada.
- [ ] Historial Git revisado sin secretos, saves ni datos personales.
- [ ] Release y checksums reproducibles creados.

## Comunidad

- [ ] README, soporte, contribución, conducta y política de seguridad revisados.
- [ ] Disclaimer de marcas visible.
- [ ] Issues y Discussions preparados.
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
