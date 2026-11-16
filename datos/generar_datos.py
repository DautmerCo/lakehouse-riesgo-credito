"""Genera los archivos diarios en una carpeta local, para explorarlos sin Databricks.

Uso:  python datos/generar_datos.py --hasta 2026-10-31
      (los escribe en datos/salida/, que no se versiona)

En Databricks no hace falta: el notebook 00_aterrizaje llama al mismo simulador y
escribe en el Volume.
"""
import argparse
import sys
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from riesgo_credito.simulador import HORIZONTE, escribir_archivos, generar_historial  # noqa: E402

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--hasta", type=date.fromisoformat, default=min(date.today(), HORIZONTE))
    p.add_argument("--destino", type=Path, default=RAIZ / "datos" / "salida")
    args = p.parse_args()
    historial = generar_historial()
    n = escribir_archivos(historial, args.destino, args.hasta)
    print(f"{n} archivos nuevos en {args.destino} (hasta {args.hasta})")
    for entidad, df in historial.items():
        print(f"  {entidad}: {len(df):,} registros simulados en todo el historial")
