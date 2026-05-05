"""Zentrale Pfadkonstanten für das gesamte Projekt."""
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# 1_ETL
ETL_DIR: Path = PROJECT_ROOT / "1_ETL"
ETL_INPUT: Path = ETL_DIR / "input"
ETL_OUTPUT: Path = ETL_DIR / "output"

# 2_COMPUTE
COMPUTE_INPUTS: Path = PROJECT_ROOT / "2_COMPUTE" / "computing_inputs"
COMPUTE_OUTPUTS: Path = PROJECT_ROOT / "2_COMPUTE" / "computing_outputs"
PARAMS_KLIMA_GEB: Path = COMPUTE_INPUTS / "params_klima_gebäudetypologie"

# 3_VISUALIZE
VISUALIZE_DIR: Path = PROJECT_ROOT / "3_VISUALIZE"
SIMULATION_ASSUMPTIONS_DIR: Path = VISUALIZE_DIR / "simulation_assumptions"
