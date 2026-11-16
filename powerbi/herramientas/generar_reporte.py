"""Genera las páginas del reporte "Riesgo Credito" en formato PBIR, más el fondo y el tema.

Uso (con Power BI Desktop CERRADO):
    python powerbi/herramientas/generar_reporte.py "powerbi/Riesgo Credito.Report"

Reescribe definition/pages, registra el tema y la imagen de fondo en report.json.
No toca el modelo semántico (medidas y relaciones viven en Riesgo Credito.SemanticModel).
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

VC = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/visualContainer/2.4.0/schema.json"
PAGE = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/page/2.1.0/schema.json"
PAGES = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition/pagesMetadata/1.1.0/schema.json"
W, H = 1920, 1080
M, G = 40, 20                      # margen y separación entre visuales
BANDA = 136                        # alto de la franja superior del fondo

# Tinta y superficies
INK, INK2, MUTED, GRID = "#0B0B0B", "#52514E", "#898781", "#E1E0D9"
PLANE, WHITE = "#F3F4F6", "#FFFFFF"
NAVY_1, NAVY_2 = "#0B2540", "#17446E"
TEXTO_BANDA = "#C9D6E3"

# Datos (validados con la skill dataviz)
AZUL = "#2A78D6"                   # serie única
NARANJA = "#EB6834"                # resaltado: cohortes con política relajada
NEUTRO = "#C3C2B7"                 # "Al día": ausencia de mora
MORA = {"1-30": "#F2A36B", "31-60": "#E0702F", "61-90": "#B4471C", "Más de 90": "#7A2812"}  # rampa ordinal
VINTAGE_MIN, VINTAGE_MAX = "#FFF4EC", "#E0702F"

TEMA = "TemaRiesgoCredito.json"
FONDO = "FondoRiesgoCredito.png"

SOL, PRE, CAR = "fact_solicitudes", "fact_prestamos", "fact_cartera_mensual"


# ------------------------------------------------------------------ fondo
def generar_fondo(destino: Path) -> None:
    """Franja superior con degradado azul marino, formas suaves y una línea de acento."""
    k = 2                                                     # se dibuja al doble y se reduce (bordes suaves)
    img = Image.new("RGB", (W * k, H * k), PLANE)
    d = ImageDraw.Draw(img)
    a, b = (int(NAVY_1[i:i + 2], 16) for i in (1, 3, 5)), (int(NAVY_2[i:i + 2], 16) for i in (1, 3, 5))
    a, b = list(a), list(b)
    for x in range(W * k):
        t = x / (W * k - 1)
        d.line([(x, 0), (x, BANDA * k)], fill=tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))

    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    c = ImageDraw.Draw(capa)
    for cx, cy, r, alfa in [(1700, -40, 260, 18), (1880, 120, 180, 14), (1180, 150, 120, 10)]:
        c.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=(255, 255, 255, alfa))
    for i in range(6):                                        # líneas diagonales finas
        x0 = (980 + i * 46) * k
        c.line([(x0, BANDA * k), (x0 + 120 * k, 0)], fill=(255, 255, 255, 16), width=2 * k)
    recorte = Image.new("L", img.size, 0)
    ImageDraw.Draw(recorte).rectangle([0, 0, W * k, BANDA * k], fill=255)
    capa.putalpha(Image.composite(capa.getchannel("A"), Image.new("L", img.size, 0), recorte))
    img = Image.alpha_composite(img.convert("RGBA"), capa)

    d = ImageDraw.Draw(img)
    d.rectangle([0, BANDA * k, W * k, (BANDA + 3) * k], fill="#3987E5")          # acento bajo la franja
    sombra = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sombra).rectangle([0, (BANDA + 3) * k, W * k, (BANDA + 12) * k], fill=(11, 37, 64, 22))
    img = Image.alpha_composite(img, sombra.filter(ImageFilter.GaussianBlur(6 * k)))
    d = ImageDraw.Draw(img)
    d.line([(M * k, (H - 40) * k), ((W - M) * k, (H - 40) * k)], fill=GRID, width=k)  # línea del pie
    img.convert("RGB").resize((W, H), Image.LANCZOS).save(destino, optimize=True)


# ------------------------------------------------------------------ expresiones PBIR
def uid(*parts) -> str:
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:20]


def lit(v):
    if isinstance(v, bool):
        s = "true" if v else "false"
    elif isinstance(v, (int, float)):
        s = f"{v}D"
    else:
        s = "'" + str(v).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": s}}}


def color(hexa):
    return {"solid": {"color": lit(hexa)}}


def col(entity, prop):
    return {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def meas(entity, prop):
    return {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}}


def proj(field, display=None):
    kind = "Measure" if "Measure" in field else "Column"
    ent, prop = field[kind]["Expression"]["SourceRef"]["Entity"], field[kind]["Property"]
    p = {"field": field, "queryRef": f"{ent}.{prop}", "nativeQueryRef": prop}
    if display:
        p["displayName"] = display
    return p


def props(**kw):
    return [{"properties": kw}]


def valor_literal(v):
    return f"{v}L" if isinstance(v, int) else "'" + str(v).replace("'", "''") + "'"


def filtro_in(entity, prop, valores):
    vals = [[{"Literal": {"Value": valor_literal(v)}}] for v in valores]
    return {"name": uid("f", entity, prop, *valores), "field": col(entity, prop), "type": "Categorical",
            "filter": {"Version": 2, "From": [{"Name": "t", "Entity": entity, "Type": 0}],
                       "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "t"}}, "Property": prop}}],
                                                       "Values": vals}}}]},
            "howCreated": "User"}


def orden(field, desc=False):
    return {"sort": [{"field": field, "direction": "Descending" if desc else "Ascending"}], "isDefaultSort": False}


# ------------------------------------------------------------------ contenedores y visuales
def contenedor(titulo=None, subtitulo=None, fondo=WHITE, sombra=True):
    o = {"background": props(show=lit(True), color=color(fondo), transparency=lit(0)),
         "border": props(show=lit(False), radius=lit(12)),
         "dropShadow": props(show=lit(sombra)),
         "visualHeader": props(show=lit(False)),
         "padding": props(top=lit(12), bottom=lit(10), left=lit(16), right=lit(16))}
    o["title"] = (props(show=lit(True), text=lit(titulo), fontSize=lit(13), fontColor=color(INK), bold=lit(True))
                  if titulo else props(show=lit(False)))
    if subtitulo:
        o["subTitle"] = props(show=lit(True), text=lit(subtitulo), fontSize=lit(10), fontColor=color(MUTED))
    return o


def sin_contenedor():
    return {"background": props(show=lit(False)), "border": props(show=lit(False)),
            "dropShadow": props(show=lit(False)), "visualHeader": props(show=lit(False)),
            "title": props(show=lit(False))}


def texto(parrafos, en_tarjeta=False):
    pars = []
    for p in parrafos:
        runs = p if isinstance(p, list) else [p]
        pars.append({"textRuns": [{"value": r[0], "textStyle": r[1]} if isinstance(r, tuple)
                                  else {"value": r, "textStyle": {"fontSize": "11pt", "color": INK2}} for r in runs]})
    return {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": pars}}]},
            "visualContainerObjects": contenedor() if en_tarjeta else sin_contenedor()}


def tarjeta(entity, medida, titulo, millones=False):
    labels = dict(fontSize=lit(30), color=color(INK))
    if millones:
        labels.update(labelDisplayUnits=lit(1000000), labelPrecision=lit(0))
    return {"visualType": "card",
            "query": {"queryState": {"Values": {"projections": [proj(meas(entity, medida))]}}},
            "objects": {"labels": props(**labels), "categoryLabels": props(show=lit(False))},
            "visualContainerObjects": contenedor(titulo)}


def segmentador(entity, columna, titulo, grupo):
    return {"visualType": "slicer",
            "query": {"queryState": {"Values": {"projections": [proj(col(entity, columna))]}}},
            "objects": {"data": props(mode=lit("Dropdown")),
                        "header": props(show=lit(True), text=lit(titulo), fontColor=color(INK2), textSize=lit(10)),
                        "items": props(fontColor=color(INK), textSize=lit(11))},
            "visualContainerObjects": {**contenedor(sombra=False), "padding": props(top=lit(6), bottom=lit(6), left=lit(12), right=lit(12))},
            "syncGroup": {"groupName": grupo, "fieldChanges": True, "filterChanges": True}}


def ejes(millones=False, leyenda=False, pct=False):
    va = props(labelColor=color(MUTED), fontSize=lit(10), gridlineColor=color(GRID), gridlineStyle=lit("dotted"),
               showAxisTitle=lit(False))
    if millones:
        va[0]["properties"]["labelDisplayUnits"] = lit(1000000)
    return {"categoryAxis": props(labelColor=color(MUTED), fontSize=lit(10), showAxisTitle=lit(False)),
            "valueAxis": va,
            "legend": props(show=lit(leyenda), position=lit("Top"), labelColor=color(INK2), fontSize=lit(10))}


def relleno(hexa):
    return {"properties": {"fill": color(hexa)}}


def relleno_categoria(entity, columna, valor, hexa):
    scope = {"Comparison": {"ComparisonKind": 0, "Left": col(entity, columna), "Right": {"Literal": {"Value": valor_literal(valor)}}}}
    return {"selector": {"data": [{"scopeId": scope}]}, "properties": {"fill": color(hexa)}}


def etiquetas(millones=False):
    p = dict(show=lit(True), color=color(INK2), fontSize=lit(10))
    if millones:
        p.update(labelDisplayUnits=lit(1000000), labelPrecision=lit(0))
    return props(**p)


def columnas(categoria, entity, medida, titulo, subtitulo, color_barras=AZUL, millones=False, con_etiquetas=False):
    obj = {**ejes(millones), "dataPoint": [relleno(color_barras)]}
    if con_etiquetas:
        obj["labels"] = etiquetas(millones)
    return {"visualType": "clusteredColumnChart",
            "query": {"queryState": {"Category": {"projections": [proj(categoria)]},
                                     "Y": {"projections": [proj(meas(entity, medida))]}},
                      "sortDefinition": orden(categoria)},
            "objects": obj, "visualContainerObjects": contenedor(titulo, subtitulo)}


def linea(categoria, entity, medida, titulo, subtitulo):
    return {"visualType": "lineChart",
            "query": {"queryState": {"Category": {"projections": [proj(categoria)]},
                                     "Y": {"projections": [proj(meas(entity, medida))]}},
                      "sortDefinition": orden(categoria)},
            "objects": {**ejes(), "dataPoint": [relleno(AZUL)],
                        "lineStyles": props(strokeWidth=lit(2), showMarker=lit(True), markerSize=lit(4))},
            "visualContainerObjects": contenedor(titulo, subtitulo)}


def barras(categoria, entity, medida, titulo, subtitulo, ordenar_por_valor=False, colores=None):
    campo = meas(entity, medida)
    obj = {**ejes(), "labels": etiquetas(), "dataPoint": [relleno(AZUL)] + (colores or [])}
    return {"visualType": "clusteredBarChart",
            "query": {"queryState": {"Category": {"projections": [proj(categoria)]},
                                     "Y": {"projections": [proj(campo)]}},
                      "sortDefinition": orden(campo, desc=True) if ordenar_por_valor else orden(categoria)},
            "objects": obj, "visualContainerObjects": contenedor(titulo, subtitulo)}


class Pagina:
    def __init__(self, clave, nombre, titulo, subtitulo):
        self.id, self.nombre, self.visuales, self.z = uid("page", clave), nombre, [], 0
        self.add("titulo", M, 20, 1100, 58, texto([[(titulo, {"fontSize": "26pt", "fontWeight": "bold", "color": WHITE})]]))
        self.add("subtitulo", M, 76, 1200, 40, texto([[(subtitulo, {"fontSize": "11pt", "color": TEXTO_BANDA})]]))
        self.add("slicer_producto", 1380, 32, 240, 72, segmentador("dim_producto", "nombre_producto", "Producto", "producto"))
        self.add("slicer_canal", 1640, 32, 240, 72, segmentador("dim_canal", "nombre_canal", "Canal", "canal"))
        self.add("pie", M, H - 36, 1600, 30, texto([[(
            "Datos sintéticos generados para el proyecto · Pipeline: Databricks (bronze → silver → gold) → Power BI · "
            "Saldos medidos al último cierre de mes del periodo filtrado", {"fontSize": "9pt", "color": MUTED})]]))

    def add(self, clave, x, y, w, h, visual, filtros=None):
        self.z += 1
        v = {"$schema": VC, "name": uid(self.id, clave),
             "position": {"x": x, "y": y, "z": self.z * 1000, "width": w, "height": h, "tabOrder": self.z * 1000},
             "visual": visual}
        if filtros:
            v["filterConfig"] = {"filters": filtros}
        self.visuales.append(v)


def fila(n, ancho_total=W - 2 * M):
    """Posiciones x y ancho para n visuales iguales en una fila."""
    w = (ancho_total - (n - 1) * G) / n
    return [(round(M + i * (w + G)), round(w)) for i in range(n)]


MES = col("dim_fecha", "anio_mes")


# ------------------------------------------------------------------ páginas
def pagina_originacion():
    p = Pagina("originacion", "Originación", "Originación",
               "Solicitudes, aprobación y desembolsos por mes · enero 2025 a octubre 2026")
    kpis = [(SOL, "Solicitudes", "Solicitudes", False), (SOL, "% Aprobación", "% de aprobación", False),
            (SOL, "% Desembolso", "% de desembolso", False), (PRE, "Monto desembolsado", "Monto desembolsado", False),
            (PRE, "Ticket promedio", "Ticket promedio", False)]
    for (x, w), (e, m, t, mill) in zip(fila(5), kpis):
        p.add(f"kpi_{m}", x, 160, w, 120, tarjeta(e, m, t, mill))

    (x1, w1), (x2, w2) = fila(2)
    p.add("col_solicitudes", x1, 300, w1, 360,
          columnas(MES, SOL, "Solicitudes", "Solicitudes por mes", "Crecimiento de la demanda"))
    p.add("lin_aprobacion", x2, 300, w2, 360,
          linea(MES, SOL, "% Aprobación", "Tasa de aprobación por mes",
                "Entre julio y octubre de 2025 la política de crédito se relajó: la aprobación sube de ~51% a ~65%"))

    (x1, w1), (x2, w2), (x3, w3) = fila(3)
    p.add("bar_canal", x1, 680, w1, 336,
          barras(col("dim_canal", "nombre_canal"), SOL, "% Aprobación", "Aprobación por canal",
                 "Solicitudes aprobadas sobre recibidas", ordenar_por_valor=True))
    p.add("col_producto", x2, 680, w2, 336,
          columnas(col("dim_producto", "nombre_producto"), PRE, "Monto desembolsado", "Monto desembolsado por producto",
                   "Millones de pesos", millones=True, con_etiquetas=True))
    p.add("nota", x3, 680, w3, 336, texto([
        [("Cómo leer esta página", {"fontSize": "13pt", "fontWeight": "bold", "color": INK})],
        [(" ", {"fontSize": "6pt"})],
        "• Una solicitud se aprueba si pasa el puntaje mínimo de buró y la capacidad de pago (cuota ≤ 35% del ingreso).",
        "• El % de desembolso es menor que el de aprobación: parte de los clientes aprobados no toma el crédito.",
        "• El salto de aprobación de mediados de 2025 no es más demanda de calidad: es una política más laxa. "
        "Su efecto aparece meses después, en la página de cohortes.",
    ], en_tarjeta=True))
    return p


def pagina_cohortes():
    p = Pagina("cohortes", "Cohortes", "Cohortes de desembolso",
               "Cómo envejece cada grupo de préstamos desembolsados en el mismo mes (análisis vintage)")
    cohorte, vida = col(CAR, "cohorte"), col(CAR, "meses_de_vida")
    medida = meas(CAR, "% Mora 30+")
    regla = {"FillRule": {"Input": medida, "FillRule": {"linearGradient2": {
        "min": {"color": {"Literal": {"Value": f"'{VINTAGE_MIN}'"}}},
        "max": {"color": {"Literal": {"Value": f"'{VINTAGE_MAX}'"}}},
        "nullColoringStrategy": {"strategy": {"Literal": {"Value": "'asZero'"}}}}}}}
    matriz = {"visualType": "pivotTable",
              "query": {"queryState": {"Rows": {"projections": [proj(cohorte, "Cohorte")]},
                                       "Columns": {"projections": [proj(vida, "Meses de vida")]},
                                       "Values": {"projections": [proj(medida)]}},
                        "sortDefinition": orden(cohorte)},
              "objects": {"subTotals": props(rowSubtotals=lit(False), columnSubtotals=lit(False)),
                          "columnHeaders": props(fontColor=color(INK2), fontSize=lit(11), bold=lit(True)),
                          "rowHeaders": props(fontColor=color(INK2), fontSize=lit(11)),
                          "values": [{"properties": {"fontSize": lit(11), "fontColorPrimary": color(INK)}},
                                     {"selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}],
                                                   "metadata": f"{CAR}.% Mora 30+"},
                                      "properties": {"backColor": {"solid": {"color": {"expr": regla}}}}}],
                          "grid": props(gridHorizontal=lit(True), gridHorizontalColor=color(WHITE),
                                        gridVertical=lit(True), gridVerticalColor=color(WHITE), rowPadding=lit(5))},
              "visualContainerObjects": contenedor("% de saldo en mora 30+ por cohorte y edad",
                                                   "Filas: mes de desembolso · columnas: meses de vida del préstamo")}
    ancho_matriz = 760
    p.add("matriz_vintage", M, 160, ancho_matriz, 860, matriz, filtros=[filtro_in(CAR, "meses_de_vida", list(range(1, 13)))])
    x_der, w_der = M + ancho_matriz + G, W - 2 * M - ancho_matriz - G

    destacadas = ["2025-07", "2025-08", "2025-09", "2025-10", "2025-11"]
    seis = columnas(cohorte, CAR, "% Mora 30+", "Mora 30+ a los 6 meses de vida, por cohorte",
                    "Naranja: cohortes originadas con la política relajada (jul–nov 2025)", con_etiquetas=True)
    seis["objects"]["dataPoint"] += [relleno_categoria(CAR, "cohorte", c, NARANJA) for c in destacadas]
    p.add("col_seis_meses", x_der, 160, w_der, 540, seis, filtros=[filtro_in(CAR, "meses_de_vida", [6])])

    p.add("hallazgo", x_der, 720, w_der, 300, texto([
        [("Hallazgo", {"fontSize": "13pt", "fontWeight": "bold", "color": INK})],
        [(" ", {"fontSize": "6pt"})],
        "Las cohortes desembolsadas entre julio y noviembre de 2025 llegan a 7–10% de mora 30+ a los 6 meses, "
        "frente a 3–6% del resto.",
        [(" ", {"fontSize": "6pt"})],
        "Es el costo de haber relajado el puntaje mínimo de aprobación para crecer. "
        "La cartera total lo diluye; solo el análisis por cohorte lo hace visible.",
    ], en_tarjeta=True))
    return p


def pagina_cartera():
    p = Pagina("cartera", "Cartera", "Calidad de cartera",
               "Saldo de capital por bucket de mora en cada cierre de mes")
    kpis = [("Saldo cartera", "Saldo de cartera", False), ("% Mora 30+", "% de cartera en mora 30+", False),
            ("Préstamos en cartera", "Préstamos vigentes", False), ("Fecha último cierre", "Último cierre", False)]
    for (x, w), (m, t, mill) in zip(fila(4), kpis):
        p.add(f"kpi_{m}", x, 160, w, 120, tarjeta(CAR, m, t, mill))

    bucket = col(CAR, "bucket_mora")
    apilado = {"visualType": "columnChart",
               "query": {"queryState": {"Category": {"projections": [proj(MES)]},
                                        "Series": {"projections": [proj(bucket, "Bucket")]},
                                        "Y": {"projections": [proj(meas(CAR, "Saldo cartera"))]}},
                         "sortDefinition": orden(MES)},
               "objects": {**ejes(millones=True, leyenda=True),
                           "dataPoint": [relleno_categoria(CAR, "bucket_mora", b, c) for b, c in MORA.items()]},
               "visualContainerObjects": contenedor("Saldo en mora por bucket", "Millones de pesos al cierre de cada mes · sin la cartera al día")}
    p.add("col_buckets", M, 300, 1220, 360, apilado, filtros=[filtro_in(CAR, "bucket_mora", list(MORA))])

    p.add("bar_distribucion", M + 1240, 300, W - 2 * M - 1240, 360,
          barras(bucket, CAR, "% Saldo", "Distribución del saldo", "Último cierre del periodo",
                 colores=[relleno_categoria(CAR, "bucket_mora", "Al día", NEUTRO)] +
                         [relleno_categoria(CAR, "bucket_mora", b, c) for b, c in MORA.items()]))

    (x1, w1), (x2, w2) = fila(2)
    p.add("lin_mora", x1, 680, w1, 336,
          linea(MES, CAR, "% Mora 30+", "% de cartera en mora 30+ por mes",
                "Sube a medida que maduran las cohortes de la política relajada"))
    p.add("bar_score", x2, 680, w2, 336,
          barras(col("dim_cliente", "banda_score"), CAR, "% Mora 30+", "Mora 30+ por puntaje de buró al desembolso",
                 "Usa la versión del cliente vigente al desembolsar (dimensión histórica)"))
    return p


# ------------------------------------------------------------------ escritura
def page_json(p):
    imagen = {"image": {"name": lit("Fondo"),
                        "url": {"expr": {"ResourcePackageItem": {"PackageName": "RegisteredResources", "PackageType": 1, "ItemName": FONDO}}},
                        "scaling": lit("Fit")}}
    return {"$schema": PAGE, "name": p.id, "displayName": p.nombre, "displayOption": "FitToPage", "height": H, "width": W,
            "objects": {"background": props(image=imagen, transparency=lit(0)),
                        "outspace": props(color=color(PLANE), transparency=lit(0))}}


def main(report_dir: Path) -> None:
    defn = report_dir / "definition"
    pages_dir = defn / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for hijo in pages_dir.iterdir():
        shutil.rmtree(hijo) if hijo.is_dir() else hijo.unlink()

    paginas = [pagina_originacion(), pagina_cohortes(), pagina_cartera()]
    for p in paginas:
        d = pages_dir / p.id
        (d / "visuals").mkdir(parents=True)
        (d / "page.json").write_text(json.dumps(page_json(p), ensure_ascii=False, indent=2), encoding="utf-8")
        for v in p.visuales:
            vd = d / "visuals" / v["name"]
            vd.mkdir()
            (vd / "visual.json").write_text(json.dumps(v, ensure_ascii=False, indent=2), encoding="utf-8")
    (pages_dir / "pages.json").write_text(json.dumps(
        {"$schema": PAGES, "pageOrder": [p.id for p in paginas], "activePageName": paginas[0].id}, indent=2), encoding="utf-8")

    rr = report_dir / "StaticResources" / "RegisteredResources"
    rr.mkdir(parents=True, exist_ok=True)
    generar_fondo(rr / FONDO)
    tema = {
        "name": "Riesgo de crédito",
        "dataColors": ["#2A78D6", "#EB6834", "#1BAF7A", "#EDA100", "#E87BA4", "#008300", "#6250D6", "#E34948"],
        "foreground": INK, "foregroundNeutralSecondary": INK2, "foregroundNeutralTertiary": MUTED,
        "background": WHITE, "backgroundLight": "#FAFAF8", "backgroundNeutral": GRID, "tableAccent": AZUL,
        "textClasses": {"callout": {"fontSize": 30, "fontFace": "Segoe UI Semibold", "color": INK},
                        "title": {"fontSize": 13, "fontFace": "Segoe UI Semibold", "color": INK},
                        "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": INK},
                        "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": INK2}},
    }
    (rr / TEMA).write_text(json.dumps(tema, ensure_ascii=False, indent=2), encoding="utf-8")

    rep_path = defn / "report.json"
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    base = rep["themeCollection"]["baseTheme"]
    rep["themeCollection"]["customTheme"] = {"name": TEMA, "reportVersionAtImport": base["reportVersionAtImport"],
                                            "type": "RegisteredResources"}
    rep["resourcePackages"] = [r for r in rep["resourcePackages"] if r["type"] != "RegisteredResources"] + [
        {"name": "RegisteredResources", "type": "RegisteredResources",
         "items": [{"name": TEMA, "path": TEMA, "type": "CustomTheme"},
                   {"name": FONDO, "path": FONDO, "type": "Image"}]}]
    rep_path.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Páginas: {len(paginas)} | visuales: {sum(len(p.visuales) for p in paginas)} | fondo: {rr / FONDO}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
