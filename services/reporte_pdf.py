"""
Motor de PDF de los reportes.

Esto vivía como funciones privadas dentro de routes/admin_routes.py, atado al
acta de alta. Se extrajo aquí sin tocar el algoritmo para que los demás tipos de
reporte (preventivo, correctivo, entrada/salida, tecnovigilancia) lo reusen en
vez de reimplementarlo cinco veces.

Qué SÍ hace este módulo: maquetar, decidir cortes de página, anclar las firmas al
pie, escribir el archivo y calcular su hash.

Qué NO hace: tocar la base de datos ni saber qué es un "reporte de alta". El
contexto de cada tipo lo arma quien llama; aquí solo se recibe una plantilla y un
diccionario. Esa separación es la que permite que el mismo motor sirva para todos.

Restricción de fondo: WeasyPrint 52.5. `display:grid` cae a `block` en silencio,
así que todo el maquetado va con tablas e inline-block, y las decisiones de
paginación se toman midiendo el documento ya renderizado en vez de con CSS.
"""

import hashlib
import os
from datetime import datetime
from io import BytesIO
from pathlib import Path

from flask import render_template
from weasyprint import HTML as WeasyHTML
from werkzeug.utils import secure_filename

# Carpetas de trabajo. Los PDF viven junto al resto de archivos subidos
# (static/uploads), que .gitignore ya excluye del repositorio.
STATIC_DIR   = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'static'))
UPLOADS_DIR  = os.path.join(STATIC_DIR, 'uploads')
REPORTES_DIR = os.path.join(UPLOADS_DIR, 'reportes')


# ── Rutas y archivos ───────────────────────────────────────────

def uri_estatica(*partes):
    """
    URI absoluta de un archivo de static, o None si no existe.

    WeasyPrint no resuelve `url_for('static', ...)`, y el proyecto vive en
    una carpeta con espacios, así que as_uri() se encarga de escaparla.
    """
    ruta = os.path.join(STATIC_DIR, *partes)
    return Path(ruta).as_uri() if os.path.exists(ruta) else None


def uri_subida(ruta_relativa):
    """URI absoluta de un archivo bajo static/uploads ('equipos/x.jpg')."""
    if not ruta_relativa:
        return None
    return uri_estatica('uploads', *str(ruta_relativa).split('/'))


def ruta_pdf(folio, sufijo=''):
    """
    Ruta absoluta en disco donde vive el PDF de un folio.

    `sufijo` distingue las variantes del mismo reporte: '' es el documento
    completo con anexos y '-reporte' es solo la hoja principal, que es la que
    se imprime cuando no se quieren las fotos.
    """
    return os.path.join(REPORTES_DIR, f"{secure_filename(folio)}{sufijo}.pdf")


# ── Fechas y texto ─────────────────────────────────────────────

MESES_ES = ('Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun',
            'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic')


def fecha_es(valor, formato='%d/%m/%Y'):
    """
    Formatea una fecha que puede llegar como date, datetime o texto.

    Hace falta porque conviven tres orígenes: el snapshot del reporte
    guarda las fechas como 'YYYY-MM-DD', la columna fecha_fabricacion es
    varchar en la BD, y fecha_adquisicion sí es date.
    """
    if not valor:
        return None
    if hasattr(valor, 'strftime'):
        return valor.strftime(formato)
    texto = str(valor).strip()
    for patron, corte in (('%Y-%m-%d %H:%M:%S', 19), ('%Y-%m-%d', 10), ('%d/%m/%Y', 10)):
        try:
            return datetime.strptime(texto[:corte], patron).strftime(formato)
        except ValueError:
            continue
    # Un valor que no es fecha (fecha_fabricacion es varchar y a veces trae
    # solo el año) se imprime tal cual en lugar de perderse.
    return texto


def fecha_larga_es(valor):
    """Fecha de registro en formato '11 / Ago / 2026', con el mes en español."""
    if valor is None:
        return None
    if not hasattr(valor, 'strftime'):
        return fecha_es(valor)
    return f"{valor.day:02d} / {MESES_ES[valor.month - 1]} / {valor.year}"


def limitar(texto, maximo):
    """
    Recorta un campo de texto al límite acordado con el formulario.

    El `maxlength` del HTML solo cubre al navegador; sin esto, un POST
    armado a mano metería textos de cualquier largo y reventaría el
    formato del PDF.
    """
    if not texto:
        return texto
    texto = texto.strip()
    return texto[:maximo] if len(texto) > maximo else texto


# ── Medición del documento maquetado ───────────────────────────

def bloques_por_pagina(documento):
    """
    Secciones .blq agrupadas por página, como [[(indice, alto), …], …].

    El índice es el mismo con el que las numera el template, así que sirve
    para pedir un corte. Una sección que se parte entre dos páginas (la
    tabla de accesorios larga) aparece en ambas con el MISMO índice: si se
    contaran como dos, los índices se recorrerían y el corte apuntaría a un
    bloque que no existe.
    """
    vistos  = {}
    paginas = []
    for pagina in documento.pages:
        bloques = []

        def recorrer(caja):
            elemento = caja.element
            if elemento is not None and 'blq' in (elemento.get('class') or ''):
                clave = id(elemento)
                if clave not in vistos:
                    vistos[clave] = len(vistos) + 1
                try:
                    bloques.append((vistos[clave], caja.margin_height()))
                except Exception:
                    pass
                return          # no hace falta bajar dentro del bloque
            for hija in getattr(caja, 'children', []):
                recorrer(hija)

        recorrer(pagina._page_box)
        paginas.append(bloques)
    return paginas


def corte_equilibrado(documento, minimo=2):
    """
    Antes de qué sección conviene cortar para repartir el contenido entre
    las hojas, o None si no hace falta.

    Cuando todo el cuerpo cabe en la primera página, las firmas —que van
    ancladas al pie— se quedan solas en la segunda y el acta parece
    incompleta. Aquí se elige el corte que deja las dos hojas lo más
    parejas posible.

    `minimo` evita cortar antes de la identificación: una primera hoja con
    solo el encabezado y la fila de datos generales se vería peor.
    """
    if len(documento.pages) != 2:
        return None

    por_pagina = bloques_por_pagina(documento)

    # Solo interesa el caso "la última hoja lleva poco o nada de contenido".
    # Si en la segunda hoja empieza alguna sección nueva, ya está repartido;
    # y si solo continúa una que venía partida, tampoco hay nada que mover.
    indices_p1 = {indice for indice, _ in por_pagina[0]}
    if any(indice not in indices_p1 for indice, _ in por_pagina[1]):
        return None

    bloques = por_pagina[0]
    total   = sum(alto for _, alto in bloques)
    if total <= 0 or len(bloques) <= minimo:
        return None

    # Primer bloque que hace que lo acumulado pase de la mitad: el siguiente
    # es el que debe arrancar la segunda hoja.
    mitad, acumulado = total / 2, 0
    for posicion, (indice, alto) in enumerate(bloques):
        acumulado += alto
        if acumulado >= mitad and posicion + 1 < len(bloques):
            return max(bloques[posicion + 1][0], minimo)
    return None


def hueco_ultima_pagina(documento):
    """
    Espacio libre al pie de la última página de un documento ya maquetado.

    Es lo que hay que insertar antes del bloque de firmas para que quede
    pegado al fondo de la hoja, sea el reporte de una o de dos páginas.
    """
    pagina = documento.pages[-1]
    caja   = pagina._page_box
    cuerpo = next(
        (c for c in caja.children if getattr(c, 'element_tag', None) == 'html'),
        None
    )
    if cuerpo is None:
        return 0
    fondo_contenido = cuerpo.content_box_y() + cuerpo.height
    limite_pagina   = caja.content_box_y() + caja.height
    return max(limite_pagina - fondo_contenido, 0)


# ── Generación ─────────────────────────────────────────────────

def generar_documento(plantilla, contexto, rellenos=(5, 3, 2), minimo_corte=2):
    """
    Maqueta el reporte y devuelve el documento de WeasyPrint ya paginado.

    Se maqueta varias veces a propósito, porque nada de esto se resuelve
    con CSS en esta versión de WeasyPrint. La prioridad es que el reporte
    quepa en una sola hoja; solo se usan dos cuando el contenido ya no cabe:

      1. Se parte de la versión compacta: las secciones sin contenido (foto,
         accesorios, observaciones) ni siquiera se imprimen.
      2. Si sobró espacio, se reponen los recuadros en blanco para llenar a
         mano. Si eso empujaría a otra hoja, se descartan.
      3. Si aun así hacen falta dos hojas, se reparte el contenido entre
         ambas en vez de dejar la segunda casi vacía.
      4. Las firmas se anclan al pie de la última página (position:fixed las
         repetiría en todas): se mide el hueco y se rellena.

    `rellenos` permite que un tipo de reporte sin recuadros para llenar a
    mano se salte el paso 2 pasando una tupla vacía.
    """
    def maquetar(espaciador=0, corte_en=None, relleno=0):
        html_str = render_template(
            plantilla,
            espaciador=espaciador, corte_en=corte_en, relleno=relleno,
            **contexto
        )
        return WeasyHTML(string=html_str, base_url=STATIC_DIR).render()

    # 1 — Versión compacta: es la que decide cuántas hojas necesita el acta
    documento = maquetar()
    hojas     = len(documento.pages)

    # 2 — Reponer los recuadros para llenar a mano, pero solo si salen
    # gratis. Se prueba con menos renglones antes de rendirse: perder los
    # cinco por unos pocos píxeles dejaría el acta sin dónde anotar.
    relleno = 0
    for filas in rellenos:
        candidato = maquetar(relleno=filas)
        if len(candidato.pages) == hojas:
            documento, relleno = candidato, filas
            break

    # 3 — Repartir el contenido si la última hoja quedó casi vacía
    corte = corte_equilibrado(documento, minimo=minimo_corte)
    if corte:
        repartido = maquetar(corte_en=corte, relleno=relleno)
        # Solo se acepta si no agregó hojas: el objetivo es equilibrar, no
        # estirar el documento.
        if len(repartido.pages) == len(documento.pages):
            documento = repartido
        else:
            corte = None

    # 4 — Empujar las firmas al pie de la última hoja
    hueco = hueco_ultima_pagina(documento)
    if hueco > 1:
        empujado = maquetar(espaciador=round(hueco, 1), corte_en=corte,
                            relleno=relleno)
        # Si el espaciador desbordara a una hoja más, se prefiere el
        # documento sin empujar: mejor firmas a media hoja que una página
        # en blanco de más.
        if len(empujado.pages) == len(documento.pages):
            documento = empujado

    return documento


def escribir_pdf(documento, destino):
    """
    Escribe el documento en disco y devuelve (ruta, sha256).

    El hash es lo que vuelve verificable un reporte liberado: guardado en la
    BD, prueba que el archivo que se sirve hoy es el mismo que se firmó. Sin
    él, "el PDF está congelado" es una promesa de la aplicación, no un hecho
    comprobable.
    """
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    documento.write_pdf(destino)
    with open(destino, 'rb') as archivo:
        digest = hashlib.sha256(archivo.read()).hexdigest()
    return destino, digest


def generar_pdf(plantilla, contexto, destino, **opciones):
    """Maqueta y escribe en un paso. Devuelve (ruta, sha256)."""
    documento = generar_documento(plantilla, contexto, **opciones)
    return escribir_pdf(documento, destino)


def vista_previa(plantilla, contexto, **opciones):
    """
    Render al vuelo para revisar antes de liberar. Devuelve BytesIO.

    Nunca toca el disco, a propósito: un borrador escrito en
    static/uploads/reportes/ sería indistinguible de un reporte liberado al
    mirar la carpeta, y el respaldo acabaría lleno de documentos que nadie
    firmó.

    La marca de agua la pinta la plantilla al recibir `marca_agua`; hacerlo
    ahí y no post-procesando el PDF permite que salga detrás del texto en
    todas las hojas, incluidos los anexos.
    """
    contexto = {**contexto, 'marca_agua': 'BORRADOR — SIN VALIDEZ'}
    documento = generar_documento(plantilla, contexto, **opciones)
    return BytesIO(documento.write_pdf())
