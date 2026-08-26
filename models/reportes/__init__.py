"""
Capa de modelos de los reportes de la Fase 2.

Cada módulo cubre una pieza del expediente:

    folios      consecutivo por serie, atómico
    base        ciclo de vida: abrir, guardar, liberar, cancelar
    lineas      refacciones, consumibles y costos
    adjuntos    fotos y archivos, con sus derivados
    notas       anotaciones del técnico

Todos siguen el patrón canónico del proyecto (el de ModelBLE): @classmethod con
`db` como primer parámetro, `?` para los valores y f-string solo para TABLE y
COLS, cursor en try/finally, y nunca abren ni cierran la conexión — eso lo hace
la ruta.
"""
