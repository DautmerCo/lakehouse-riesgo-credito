"""Simulador del sistema fuente de una cartera de préstamos de consumo.

Genera un historial sintético y reproducible (solicitudes, préstamos, pagos y cambios de
clientes) y lo entrega como archivos diarios, igual que lo haría un sistema transaccional:
cada día aparece un archivo nuevo por entidad con lo ocurrido ese día.

El historial completo se simula siempre hasta HORIZONTE con la misma semilla; `hasta`
solo decide qué archivos se entregan. Así, volver a ejecutar con una fecha posterior
agrega archivos nuevos sin cambiar los que ya existían.

Los archivos traen a propósito los problemas típicos de una fuente real: registros
duplicados, reenvíos al día siguiente, pagos que llegan tarde, montos vacíos o negativos,
códigos inválidos y pagos de préstamos inexistentes.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEMILLA = 20250101
INICIO = date(2025, 1, 1)
HORIZONTE = date(2026, 12, 31)

# código: (participación, monto mediano, tasa mensual base, plazos en meses, factor de riesgo)
PRODUCTOS = {
    "LI": (0.55, 8_000_000, 0.021, (12, 18, 24, 36), 1.00),   # Libre inversión
    "CC": (0.25, 15_000_000, 0.017, (24, 36, 48), 0.85),      # Compra de cartera
    "MC": (0.20, 2_000_000, 0.026, (6, 12), 1.30),            # Microcrédito
}
# canal: (participación, factor de riesgo)
CANALES = {"APP": (0.55, 1.15), "WEB": (0.25, 1.00), "ALIADO": (0.12, 1.25), "REFERIDO": (0.08, 0.70)}
CIUDADES = (["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga", "Pereira"],
            [0.38, 0.20, 0.15, 0.12, 0.08, 0.07])
OCUPACIONES = (["EMPLEADO", "INDEPENDIENTE", "PENSIONADO"], [0.62, 0.30, 0.08])
MEDIOS_PAGO = (["PSE", "DEBITO_AUTOMATICO", "EFECTIVO", "TRANSFERENCIA"], [0.45, 0.30, 0.15, 0.10])

# Entre estas fechas la política de crédito se relajó para crecer: se aprobaron puntajes
# más bajos. Es la historia que el análisis de cohortes debe dejar ver.
RELAJACION = (date(2025, 7, 1), date(2025, 10, 31))
CORTE_SCORE_NORMAL, CORTE_SCORE_RELAJADO = 600, 560

FORMATOS = {"solicitudes": "json", "clientes": "json", "prestamos": "csv", "pagos": "csv"}


def sumar_meses(d: date, n: int) -> date:
    """Suma meses como add_months de Spark: si el día no existe, usa el último del mes."""
    y, m = divmod(d.month - 1 + n, 12)
    y, m = d.year + y, m + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def riesgo_por_score(score: float) -> float:
    """Entre 0 y 1: crece cuando el puntaje de buró baja."""
    return 1.0 / (1.0 + np.exp((score - 610) / 45))


def generar_historial(semilla: int = SEMILLA) -> dict[str, pd.DataFrame]:
    """Simula el negocio día a día y devuelve una tabla por entidad.

    Cada tabla incluye `_fecha_archivo`: el día en que el registro aparece en un archivo.
    """
    rng = np.random.default_rng(semilla)
    prod_cod = list(PRODUCTOS)
    prod_p = [PRODUCTOS[p][0] for p in prod_cod]
    canal_cod = list(CANALES)
    canal_p = [CANALES[c][0] for c in canal_cod]

    clientes: list[dict] = []          # estado vigente; la posición es el número de cliente
    cambios, solicitudes, prestamos, pagos = [], [], [], []

    def registrar_cambio(c: dict, dia: date) -> None:
        cambios.append({**c, "fecha_actualizacion": dia, "_fecha_archivo": dia})

    dia = INICIO
    while dia <= HORIZONTE:
        # Actualización mensual de datos de clientes (alimenta la dimensión histórica).
        if dia.day == 1 and clientes:
            for i in np.flatnonzero(rng.random(len(clientes)) < 0.03):
                c = clientes[i]
                c["score_buro"] = int(np.clip(c["score_buro"] + rng.normal(0, 25), 300, 850))
                c["ingreso_mensual"] = int(round(c["ingreso_mensual"] * (1 + rng.normal(0.03, 0.05)), -4))
                if rng.random() < 0.3:
                    c["ciudad"] = str(rng.choice(CIUDADES[0], p=CIUDADES[1]))
                registrar_cambio(c, dia)

        meses = (dia.year - INICIO.year) * 12 + dia.month - 1
        demanda = 45 * 1.02 ** meses
        demanda *= 0.5 if dia.weekday() >= 5 else 1.0
        demanda *= 1.25 if dia.month in (11, 12) else 1.0

        for _ in range(rng.poisson(demanda)):
            if clientes and rng.random() < 0.25:
                c = clientes[int(rng.integers(0, len(clientes)))]
            else:
                c = {
                    "cliente_id": f"C{len(clientes) + 1:06d}",
                    "ciudad": str(rng.choice(CIUDADES[0], p=CIUDADES[1])),
                    "ocupacion": str(rng.choice(OCUPACIONES[0], p=OCUPACIONES[1])),
                    "ingreso_mensual": int(round(float(np.clip(rng.lognormal(np.log(3_200_000), 0.5),
                                                               1_300_000, 30_000_000)), -4)),
                    "score_buro": int(np.clip(rng.normal(620, 90), 300, 850)),
                }
                clientes.append(c)
                registrar_cambio(c, dia)

            producto = str(rng.choice(prod_cod, p=prod_p))
            canal = str(rng.choice(canal_cod, p=canal_p))
            _, mediana, tasa_base, plazos, f_producto = PRODUCTOS[producto]
            monto = int(max(500_000, round(rng.lognormal(np.log(mediana), 0.5), -5)))
            plazo = int(rng.choice(plazos))
            riesgo = riesgo_por_score(c["score_buro"])
            tasa = round(tasa_base + 0.004 * riesgo, 4)
            cuota = int(round(monto * tasa / (1 - (1 + tasa) ** -plazo)))

            relajada = RELAJACION[0] <= dia <= RELAJACION[1]
            corte = CORTE_SCORE_RELAJADO if relajada else CORTE_SCORE_NORMAL
            if c["score_buro"] + rng.normal(0, 15) < corte:
                estado, motivo = "RECHAZADA", "SCORE"
            elif cuota > 0.35 * c["ingreso_mensual"]:
                estado, motivo = "RECHAZADA", "CAPACIDAD_PAGO"
            else:
                estado, motivo = "APROBADA", None

            solicitud_id = f"S{len(solicitudes) + 1:07d}"
            solicitudes.append({
                "solicitud_id": solicitud_id, "cliente_id": c["cliente_id"], "fecha_solicitud": dia,
                "producto": producto, "canal": canal, "monto_solicitado": monto, "plazo_meses": plazo,
                "score_buro": c["score_buro"], "estado": estado, "motivo_rechazo": motivo,
                "_fecha_archivo": dia,
            })
            if estado != "APROBADA" or rng.random() > 0.85:   # 15% de los aprobados desiste
                continue

            desembolso = dia + timedelta(days=int(rng.integers(0, 5)))
            prestamo_id = f"L{len(prestamos) + 1:07d}"
            prestamos.append({
                "prestamo_id": prestamo_id, "solicitud_id": solicitud_id, "cliente_id": c["cliente_id"],
                "producto": producto, "fecha_desembolso": desembolso, "monto_desembolsado": monto,
                "tasa_mensual": tasa, "plazo_meses": plazo, "cuota_mensual": cuota,
                "_fecha_archivo": desembolso,
            })

            # Comportamiento de pago, cuota a cuota.
            p_fallo_base = (0.01 + 0.12 * riesgo) * CANALES[canal][1] * f_producto
            pagadas = fallos_seguidos = 0
            castigado = False
            for m in range(1, plazo + 1):
                vence = sumar_meses(desembolso, m)
                if vence > HORIZONTE:
                    break
                atraso = (m - 1) - pagadas
                p_fallo = min(0.95, p_fallo_base * (2.5 if atraso > 0 else 1.0))
                if castigado or rng.random() < p_fallo:
                    fallos_seguidos += 1
                    castigado = castigado or fallos_seguidos >= 4
                    continue
                fallos_seguidos = 0
                # Quien viene atrasado a veces se pone al día pagando dos cuotas.
                for _ in range(2 if atraso > 0 and rng.random() < 0.35 else 1):
                    demora = int(rng.integers(0, 21)) if atraso > 0 else int(rng.integers(-3, 3))
                    fecha_pago = max(desembolso + timedelta(days=1), vence + timedelta(days=demora))
                    pagadas += 1
                    pagos.append({
                        "pago_id": f"P{len(pagos) + 1:08d}", "prestamo_id": prestamo_id,
                        "numero_cuota": pagadas, "fecha_pago": fecha_pago, "monto_pagado": cuota,
                        "medio_pago": str(rng.choice(MEDIOS_PAGO[0], p=MEDIOS_PAGO[1])),
                        "_fecha_archivo": fecha_pago,
                    })
        dia += timedelta(days=1)

    historial = {
        "clientes": pd.DataFrame(cambios),
        "solicitudes": pd.DataFrame(solicitudes),
        "prestamos": pd.DataFrame(prestamos),
        "pagos": pd.DataFrame(pagos),
    }
    return _ensuciar(historial, np.random.default_rng(semilla + 1))


def _ensuciar(h: dict[str, pd.DataFrame], rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    """Agrega los defectos de calidad. Ninguno altera la verdad del negocio: son filas
    de más (duplicados, basura) o filas reales con formato sucio o entregadas tarde."""
    un_dia = pd.Timedelta(days=1)

    def muestra(df: pd.DataFrame, fraccion: float) -> pd.DataFrame:
        return df.sample(frac=fraccion, random_state=int(rng.integers(0, 2**31))).copy()

    for nombre in h:
        h[nombre]["_fecha_archivo"] = pd.to_datetime(h[nombre]["_fecha_archivo"])

    # --- pagos
    pagos = h["pagos"]
    tarde = pagos.sample(frac=0.01, random_state=int(rng.integers(0, 2**31))).index
    pagos.loc[tarde, "_fecha_archivo"] += pd.to_timedelta(rng.integers(1, 4, len(tarde)), unit="D")
    reenviados = muestra(pagos, 0.01)                      # el mismo pago llega otra vez al día siguiente
    reenviados["_fecha_archivo"] += un_dia
    sin_monto = muestra(pagos, 0.003)                      # registros basura con otro identificador
    sin_monto["pago_id"] = "PX" + sin_monto["pago_id"].str[1:]
    sin_monto["monto_pagado"] = np.where(rng.random(len(sin_monto)) < 0.5, np.nan, -sin_monto["monto_pagado"])
    huerfanos = muestra(pagos, 0.001)                      # pagos de préstamos que no existen
    huerfanos["pago_id"] = "PH" + huerfanos["pago_id"].str[1:]
    huerfanos["prestamo_id"] = "L9" + huerfanos["prestamo_id"].str[2:]
    h["pagos"] = pd.concat([pagos, reenviados, sin_monto, huerfanos], ignore_index=True)
    h["pagos"]["monto_pagado"] = h["pagos"]["monto_pagado"].astype("Int64")

    # --- solicitudes
    sol = h["solicitudes"]
    sucias = sol.sample(frac=0.03, random_state=int(rng.integers(0, 2**31))).index
    estilos = rng.integers(0, 3, len(sucias))
    canal = sol.loc[sucias, "canal"]
    sol.loc[sucias, "canal"] = np.select(
        [estilos == 0, estilos == 1], [canal.str.lower(), " " + canal.str.title() + " "], canal.str.lower() + " ")
    duplicadas = muestra(sol, 0.005)                       # duplicado dentro del mismo archivo
    invalidas = muestra(sol, 0.002)
    invalidas["solicitud_id"] = "SX" + invalidas["solicitud_id"].str[1:]
    invalidas["producto"] = "XX"
    h["solicitudes"] = pd.concat([sol, duplicadas, invalidas], ignore_index=True)

    # --- préstamos y clientes
    pre = h["prestamos"]
    en_cero = muestra(pre, 0.002)
    en_cero["prestamo_id"] = "LX" + en_cero["prestamo_id"].str[1:]
    en_cero["monto_desembolsado"] = 0
    h["prestamos"] = pd.concat([pre, en_cero], ignore_index=True)

    cli = h["clientes"]
    score_malo = muestra(cli, 0.002)                       # una segunda versión del mismo día, corrupta
    score_malo["score_buro"] = 9999
    h["clientes"] = pd.concat([cli, score_malo], ignore_index=True)
    return h


def escribir_archivos(historial: dict[str, pd.DataFrame], destino: str | Path, hasta: date,
                      desde: date = INICIO) -> int:
    """Entrega un archivo por entidad y día en `destino/<entidad>/`. No reescribe los que ya existen.

    Devuelve cuántos archivos nuevos escribió.
    """
    destino = Path(destino)
    nuevos = 0
    for entidad, df in historial.items():
        carpeta = destino / entidad
        carpeta.mkdir(parents=True, exist_ok=True)
        formato = FORMATOS[entidad]
        en_rango = df[(df["_fecha_archivo"] >= pd.Timestamp(desde)) & (df["_fecha_archivo"] <= pd.Timestamp(hasta))]
        for fecha, lote in en_rango.groupby("_fecha_archivo"):
            ruta = carpeta / f"{entidad}_{fecha:%Y%m%d}.{formato}"
            if ruta.exists():
                continue
            lote = lote.drop(columns="_fecha_archivo")
            for col in lote.columns[lote.columns.str.startswith("fecha_")]:
                lote[col] = lote[col].astype(str)
            if formato == "csv":
                lote.to_csv(ruta, index=False, encoding="utf-8")
            else:
                lote.to_json(ruta, orient="records", lines=True, force_ascii=False)
            nuevos += 1
    return nuevos
