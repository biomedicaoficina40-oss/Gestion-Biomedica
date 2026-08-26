"""
Arma el contexto que reciben las plantillas de PDF.

Vive aparte de reporte_pdf.py a propósito: aquel es el motor (maqueta, pagina,
escribe) y no debe saber qué es un "reporte de mantenimiento". Aquí se junta lo
que cada tipo necesita, leyendo de varios modelos, y se entrega un diccionario
plano que la plantilla solo tiene que pintar.

La regla que se repite en todo el archivo: la plantilla no resuelve rutas, no
formatea fechas y no traduce claves a etiquetas. Todo eso pasa aquí, para que
maquetar un tipo nuevo sea escribir HTML y nada más.
"""

from models.reportes.adjuntos import ETIQUETAS as ETIQUETAS_ADJUNTO
from models.reportes.adjuntos import ModelAdjuntos
from models.reportes.lineas import ETIQUETAS as ETIQUETAS_LINEA
from models.reportes.lineas import ModelLineas
from models.reportes.mantenimiento import ModelMantenimiento
from models.reportes.movimiento import ModelMovimiento
from models.reportes.notas import ModelNotas
from models.reportes.tecnovigilancia import ModelTecnovigilancia
from models.ModelFirmas import ModelFirmas
from services import reporte_pdf

# Firmas que lleva cada tipo: (rol, etiqueta impresa, texto fijo del bloque).
# El texto fijo se imprime siempre; el nombre de quien firma sale de la firma.
FIRMAS_POR_TIPO = {
    'preventivo': [
        ('biomedico',        'Realizó el servicio',   'Ingeniería Biomédica'),
        ('responsable_area', 'Responsable del área',  ''),
    ],
    'correctivo': [
        ('biomedico',        'Realizó el servicio',   'Ingeniería Biomédica'),
        ('responsable_area', 'Recibe de conformidad', ''),
    ],
    'tecnovigilancia': [
        ('biomedico',        'Reporta',               'Ingeniería Biomédica'),
        ('responsable_area', 'Responsable del área',  ''),
    ],
}


def _firmas_para_pdf(db, reporte_id):
    """Firmas con la URI del trazo y la fecha ya formateadas."""
    resueltas = {}
    for rol, firma in (ModelFirmas.get_por_reporte(db, reporte_id) or {}).items():
        url = reporte_pdf.uri_subida(firma.get('imagen'))
        if not url:
            continue
        resueltas[rol] = {
            'nombre':    firma.get('nombre'),
            'cargo':     firma.get('cargo'),
            'url':       url,
            'fecha_txt': reporte_pdf.fecha_es(firma.get('fecha')),
        }
    return resueltas


def _fotos_para_anexo(db, reporte_id):
    """
    Fotos que entran al anexo, en orden y con su etiqueta de etapa.

    Solo las marcadas incluir_en_pdf. Las del proceso vienen apagadas por
    omisión: son las más numerosas y las que menos le dicen a quien lee el
    documento, pero son justo las que le sirven al técnico que abra ese equipo
    dentro de seis meses. Su lugar es el expediente, no el papel.
    """
    fotos = []
    for adjunto in ModelAdjuntos.get_por_reporte(db, reporte_id, solo_pdf=True):
        if not str(adjunto.get('clase', '')).startswith('foto_'):
            continue
        # El derivado 'pdf' es el reducido a 900px: meter el de 1200 haría que
        # WeasyPrint decodifique una imagen grande en cada una de sus cuatro
        # pasadas de maquetado.
        url = reporte_pdf.uri_subida(adjunto.get('archivo_pdf') or adjunto.get('archivo'))
        if not url:
            continue
        fotos.append({
            'url':         url,
            'descripcion': adjunto.get('descripcion'),
            'etapa':       ETIQUETAS_ADJUNTO.get(adjunto.get('clase'), ''),
        })
    return fotos


def contexto_mantenimiento(db, reporte, equipo=None, ver_costos=True):
    """
    Contexto del PDF de un mantenimiento preventivo, predictivo o correctivo.

    `ver_costos` gobierna si la tabla de refacciones lleva importes. Se decide
    en la ruta según el rol y se pasa hasta aquí, porque ocultar la columna en
    pantalla no sirve de nada si el PDF descargado la trae.
    """
    reporte_id = reporte['id']
    detalle = ModelMantenimiento.get(db, reporte_id) or {}

    # El snapshot manda: el documento debe decir lo que decía el día del
    # trabajo, aunque el equipo haya cambiado de área desde entonces. `equipo`
    # solo rellena huecos de reportes viejos cuyo snapshot no traía todo.
    datos = reporte.get('datos') or {}
    eq = {**(equipo or {}), **datos}
    for campo in ('fecha_adquisicion', 'fecha_fabricacion', 'fecha_fin_garantia'):
        if eq.get(campo):
            eq[campo] = reporte_pdf.fecha_es(eq.get(campo))

    lineas = ModelLineas.get_por_reporte(db, reporte_id)
    for linea in lineas:
        linea['clase_txt'] = ETIQUETAS_LINEA.get(linea.get('clase'), linea.get('clase'))

    # La fecha impresa es la de liberación: un preventivo que empezó el lunes y
    # terminó el miércoles documenta el miércoles. Mientras no se libere se
    # muestra la de hoy, que es lo que se está previsualizando.
    fecha = reporte.get('fecha_liberacion') or reporte.get('fecha')

    # Diagnóstico y tiempo de atención — solo tiene sentido en un correctivo;
    # un preventivo no falla, se anticipa. La plantilla decide si imprime la
    # sección según si `fecha_falla_txt` viene o no, no según el tipo: así un
    # predictivo que sí registró una falla también la mostraría.
    horas_paro = detalle.get('horas_paro')

    return dict(
        eq                  = eq,
        folio               = reporte.get('folio'),
        fecha_txt           = reporte_pdf.fecha_larga_es(fecha),
        anio                = fecha.year if hasattr(fecha, 'year') else None,
        area_nombre         = reporte.get('area_nombre'),
        logo_url            = reporte_pdf.uri_estatica('img', 'Logo-Galenia.png'),

        descripcion_trabajo = detalle.get('descripcion_trabajo'),
        observaciones       = detalle.get('observaciones'),
        tipo_servicio_txt   = detalle.get('tipo_servicio_txt'),
        resultado_txt       = detalle.get('resultado_txt'),

        fecha_falla_txt     = reporte_pdf.fecha_es(detalle.get('fecha_falla'),
                                                    formato='%d/%m/%Y %H:%M'),
        tipo_falla_nombre   = detalle.get('tipo_falla_nombre'),
        causa_demora_nombre = detalle.get('causa_demora_nombre'),
        horas_paro_txt      = (f"{horas_paro:g} h" if horas_paro is not None else None),

        lineas              = lineas,
        totales             = ModelLineas.total(db, reporte_id),
        ver_costos          = ver_costos,
        notas_pdf           = ModelNotas.get_por_reporte(db, reporte_id, solo_pdf=True),

        firmas              = _firmas_para_pdf(db, reporte_id),
        firmas_requeridas   = FIRMAS_POR_TIPO.get(reporte.get('tipo'), []),
        fotos_anexo         = _fotos_para_anexo(db, reporte_id),

        # Guion cuando el dato se capturó y no existe. El acta de alta usa ''
        # para las regularizaciones, que se llenan a mano; aquí no aplica.
        ph                  = '—',
    )


def _firmas_requeridas_movimiento(firmas):
    """
    A diferencia de mantenimiento, aquí no hay una lista fija de roles.

    El biomédico es el único obligatorio (se imprime su recuadro aunque siga
    pendiente); responsable de área y proveedor son independientes entre sí y
    solo se imprimen si de verdad se capturaron — mostrar un recuadro vacío
    "Pendiente de firma" para un rol que nadie pensaba usar en ese movimiento
    se leería como un requisito que no es.
    """
    requeridas = [('biomedico', 'Ingeniería Biomédica', '')]
    if 'responsable_area' in firmas:
        requeridas.append(('responsable_area', 'Responsable del área', ''))
    if 'proveedor' in firmas:
        requeridas.append(('proveedor', 'Proveedor', ''))
    return requeridas


def contexto_movimiento(db, reporte, equipo=None, ver_costos=True):
    """
    Contexto del PDF de una entrada o salida de equipo.

    Sin refacciones ni costos: el plan no los contempla para este tipo, es un
    documento de logística, no de servicio. `equipo` (el snapshot resuelto de
    la ruta) se ignora a propósito — la lista real sale de ReporteEquipos,
    porque puede ser más de uno.
    """
    reporte_id = reporte['id']
    detalle = ModelMovimiento.get(db, reporte_id) or {}
    equipos = ModelMovimiento.get_equipos(db, reporte_id)

    # El anexo fotográfico (en _base_pdf.html) encabeza cada hoja con el
    # nombre del equipo; con varios, un rótulo agregado dice más que el
    # primero de la lista solo.
    if len(equipos) == 1:
        eq = equipos[0]
    else:
        eq = {'equipo_unidad': f"{len(equipos)} equipos" if equipos else None,
             'numero_inventario': None}

    fecha = reporte.get('fecha_liberacion') or reporte.get('fecha')
    firmas = _firmas_para_pdf(db, reporte_id)

    return dict(
        eq                  = eq,
        equipos             = equipos,
        folio               = reporte.get('folio'),
        fecha_txt           = reporte_pdf.fecha_larga_es(fecha),
        anio                = fecha.year if hasattr(fecha, 'year') else None,
        area_nombre         = reporte.get('area_nombre'),
        logo_url            = reporte_pdf.uri_estatica('img', 'Logo-Galenia.png'),

        sentido_txt         = detalle.get('sentido_txt'),
        motivo              = detalle.get('motivo'),
        accesorios          = detalle.get('accesorios'),
        destino_externo     = detalle.get('destino_externo'),
        proveedor_nombre    = detalle.get('proveedor_nombre'),
        fecha_retorno_prevista_txt = reporte_pdf.fecha_es(detalle.get('fecha_retorno_prevista')),
        fecha_retorno_real_txt     = reporte_pdf.fecha_es(detalle.get('fecha_retorno_real')),
        padre_folio         = detalle.get('padre_folio'),

        lineas              = [],
        totales             = None,
        ver_costos          = False,
        notas_pdf           = ModelNotas.get_por_reporte(db, reporte_id, solo_pdf=True),

        firmas              = firmas,
        firmas_requeridas   = _firmas_requeridas_movimiento(firmas),
        fotos_anexo         = _fotos_para_anexo(db, reporte_id),

        ph                  = '—',
    )


def contexto_tecnovigilancia(db, reporte, equipo=None, ver_costos=True):
    """
    Contexto del PDF de tecnovigilancia: un documento de redacción, no de
    servicio. Sin refacciones, sin costos, sin anexo fotográfico esperado
    —nadie sube fotos aquí hoy, pero si alguna vez se suben con otra clase de
    adjunto, `_fotos_para_anexo` las tomaría igual, sin cambiar este código.
    """
    reporte_id = reporte['id']
    detalle = ModelTecnovigilancia.get(db, reporte_id) or {}

    datos = reporte.get('datos') or {}
    eq = {**(equipo or {}), **datos}

    fecha = reporte.get('fecha_liberacion') or reporte.get('fecha')

    return dict(
        eq                  = eq,
        folio               = reporte.get('folio'),
        fecha_txt           = reporte_pdf.fecha_larga_es(fecha),
        anio                = fecha.year if hasattr(fecha, 'year') else None,
        area_nombre         = reporte.get('area_nombre'),
        logo_url            = reporte_pdf.uri_estatica('img', 'Logo-Galenia.png'),

        fecha_evento_txt    = reporte_pdf.fecha_es(detalle.get('fecha_evento'),
                                                    formato='%d/%m/%Y %H:%M'),
        fecha_deteccion_txt = reporte_pdf.fecha_es(detalle.get('fecha_deteccion'),
                                                    formato='%d/%m/%Y %H:%M'),
        clasificacion_txt   = detalle.get('clasificacion_txt'),
        descripcion         = detalle.get('descripcion'),
        involucrados        = detalle.get('involucrados'),
        acciones_inmediatas = detalle.get('acciones_inmediatas'),

        lineas              = [],
        totales             = None,
        ver_costos          = False,
        notas_pdf           = ModelNotas.get_por_reporte(db, reporte_id, solo_pdf=True),

        firmas              = _firmas_para_pdf(db, reporte_id),
        firmas_requeridas   = FIRMAS_POR_TIPO.get(reporte.get('tipo'), []),
        fotos_anexo         = _fotos_para_anexo(db, reporte_id),

        ph                  = '—',
    )


PLANTILLAS = {
    'preventivo':      'reportes/pdf/preventivo.html',
    'correctivo':      'reportes/pdf/correctivo.html',
    'entrada':         'reportes/pdf/movimiento.html',
    'salida':          'reportes/pdf/movimiento.html',
    'tecnovigilancia': 'reportes/pdf/tecnovigilancia.html',
}

CONSTRUCTORES = {
    'preventivo':      contexto_mantenimiento,
    'correctivo':      contexto_mantenimiento,
    'entrada':         contexto_movimiento,
    'salida':          contexto_movimiento,
    'tecnovigilancia': contexto_tecnovigilancia,
}


def para(db, reporte, equipo=None, ver_costos=True):
    """
    (plantilla, contexto) para un reporte, según su tipo.

    Devuelve (None, None) si el tipo todavía no tiene plantilla; quien llama
    decide si eso es un 404 o un mensaje.
    """
    tipo = reporte.get('tipo')
    plantilla = PLANTILLAS.get(tipo)
    constructor = CONSTRUCTORES.get(tipo)
    if not plantilla or not constructor:
        return None, None
    return plantilla, constructor(db, reporte, equipo, ver_costos)
