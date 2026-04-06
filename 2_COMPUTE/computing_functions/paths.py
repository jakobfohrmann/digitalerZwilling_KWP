"""Zentrale Pfadkonstanten relativ zum Projektroot."""
from pathlib import Path

# computing_functions/ -> 2_COMPUTE -> Projektroot
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]

COMPUTE_INPUTS: Path = PROJECT_ROOT / "2_COMPUTE" / "computing_inputs"
# Ergebnisse (Energiebilanz, Sanierung, Klima) — getrennt von Eingaben/ETL-Kopien
COMPUTE_OUTPUTS: Path = PROJECT_ROOT / "2_COMPUTE" / "computing_outputs"
PARAMS_KLIMA_GEB: Path = COMPUTE_INPUTS / "params_klima_gebäudetypologie"

VISUALIZE_DIR: Path = PROJECT_ROOT / "3_VISUALIZE"
SIMULATION_ASSUMPTIONS_DIR: Path = VISUALIZE_DIR / "simulation_assumptions"
