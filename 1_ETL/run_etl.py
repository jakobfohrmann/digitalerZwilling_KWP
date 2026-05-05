"""ETL-Pipeline: führt alle 5 Schritte der Reihe nach aus.

Verwendung:
    python 1_ETL/run_etl.py

Die Schritte erkennen ihre Eingabedaten automatisch aus den vorherigen
Ausgabe-Ordnern. Das Ergebnis (Schritt 5) wird zusätzlich nach
2_COMPUTE/computing_inputs/ kopiert.
"""

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


def run_step(script: str, step_num: int) -> bool:
    print(f"\n{'='*60}")
    print(f"Schritt {step_num}/5: {script}")
    print('='*60)
    result = subprocess.run(
        [sys.executable, str(ETL_DIR / script)],
        cwd=str(ETL_DIR),
    )
    if result.returncode != 0:
        print(f"\n[FEHLER] Schritt {step_num} fehlgeschlagen (exit code {result.returncode})")
        return False
    return True


if __name__ == "__main__":
    print("ETL-Pipeline gestartet")
    for i, script in enumerate(STEPS, start=1):
        if not run_step(script, i):
            print("\nPipeline abgebrochen.")
            sys.exit(1)
    print(f"\n{'='*60}")
    print("ETL-Pipeline abgeschlossen.")
    print("Ausgabe liegt in 2_COMPUTE/computing_inputs/")
    print('='*60)
