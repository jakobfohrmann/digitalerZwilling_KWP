"""ETL-Pipeline: führt alle 5 Schritte der Reihe nach aus.

Verwendung:
    python 1_ETL/run_etl.py --gpkg input/gpkg_filtered/gebaeude_borsdorf.gpkg --lod1 input/lod1/lod1_borsdorf
"""

from __future__ import annotations
import argparse
import subprocess
import sys
from pathlib import Path

ETL_DIR = Path(__file__).resolve().parent

STEPS = [
    "etl_schritt1_spatial_join.py",
    "etl_schritt2_filter_gebaeudefunktion.py",
    "etl_schritt3_hoehe_flaeche_geschosse.py",
    "etl_schritt4_baujahr.py",
    "etl_schritt5_gebaeudetyp.py",
]


def run_step(script: str, step_num: int, extra_args: list[str] = []) -> None:
    print(f"\n{'='*60}\nSchritt {step_num}/5: {script}\n{'='*60}")
    result = subprocess.run([sys.executable, str(ETL_DIR / script), *extra_args], cwd=str(ETL_DIR))
    if result.returncode != 0:
        sys.exit(f"[FEHLER] Schritt {step_num} fehlgeschlagen (exit code {result.returncode})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ETL-Pipeline (5 Schritte).")
    parser.add_argument("--gpkg", required=True, help="Pfad zur GPKG-Datei (z.B. gebaeude_borsdorf.gpkg)")
    parser.add_argument("--lod1", required=True, help="Ordner mit *.gml LOD1-Dateien")
    args = parser.parse_args()

    gpkg = Path(args.gpkg).resolve()
    lod1_dir = Path(args.lod1).resolve()
    gmls = sorted(lod1_dir.glob("*.gml"))

    if not gpkg.is_file():
        sys.exit(f"[FEHLER] GPKG fehlt: {gpkg}")
    if not gmls:
        sys.exit(f"[FEHLER] Keine *.gml in {lod1_dir}")

    base = gpkg.stem  # z.B. "gebaeude_borsdorf"
    outputs = [ETL_DIR / "output" / f"output_step{i}" / f"{base}_schritt{i}.gpkg" for i in range(1, 5)]

    run_step(STEPS[0], 1, [*[str(g) for g in gmls], "--gpkg", str(gpkg)])
    for i, (script, prev_out) in enumerate(zip(STEPS[1:], outputs), start=2):
        run_step(script, i, [str(prev_out)])

    print(f"\n{'='*60}\nETL-Pipeline abgeschlossen.\nAusgabe liegt in 2_COMPUTE/computing_inputs/\n{'='*60}")
