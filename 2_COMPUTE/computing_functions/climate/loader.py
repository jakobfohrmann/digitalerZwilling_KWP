"""Lädt Klima- und Solardaten aus CSV."""

import os
from typing import Dict, Optional, Tuple

import pandas as pd

from paths import PARAMS_KLIMA_GEB

_REQUIRED_COLUMNS = {'year', 'scenario', 'HDD', 'HD', 'RHDD', 'G_Hor', 'G_Hor_HD', 'G_E_HD', 'G_S_HD', 'G_W_HD', 'G_N_HD'}


def load_climate_solar_scenarios(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Lädt Klima+Solar-Szenarien aus CSV."""
    if csv_path is None:
        candidates = [
            str(PARAMS_KLIMA_GEB / "annual_climate_solar_projections_2100.csv"),
            "annual_climate_solar_projections_2100.csv",
        ]
        csv_path = next((p for p in candidates if os.path.exists(p)), None)

    if csv_path is None or not os.path.exists(csv_path):
        raise FileNotFoundError("annual_climate_solar_projections_2100.csv nicht gefunden.")

    df = pd.read_csv(csv_path)
    if not _REQUIRED_COLUMNS.issubset(df.columns):
        raise ValueError(f"CSV fehlen Spalten: {_REQUIRED_COLUMNS - set(df.columns)}")
    return df


def normalize_scenario_name(scenario: str) -> str:
    s = str(scenario).strip().lower().replace(' ', '')
    return s.split('_')[0] if s.startswith('rcp') and '_' in s else s


def get_climate_values_for_scenario(
    year: int, scenario: str, csv_path: Optional[str] = None
) -> Dict[str, float]:
    """Gibt Klima-/Strahlungswerte für Jahr und Szenario zurück."""
    df = load_climate_solar_scenarios(csv_path)
    key = normalize_scenario_name(scenario)
    try:
        year_int = int(year)
    except (TypeError, ValueError):
        raise ValueError('Ungültiges Jahr.')

    match = df[(df['year'] == year_int) & (df['scenario'] == key)]
    if match.empty:
        raise ValueError(f'Keine Klimadaten für {key} im Jahr {year_int}.')

    row = match.iloc[0]
    return {col: float(row[col]) for col in ['year', 'HDD', 'HD', 'RHDD', 'G_Hor', 'G_Hor_HD', 'G_E_HD', 'G_S_HD', 'G_W_HD', 'G_N_HD']}


def get_hdd_rhdd_for_scenario(year: int, scenario: str, csv_path: Optional[str] = None) -> Tuple[float, float]:
    vals = get_climate_values_for_scenario(year, scenario, csv_path)
    return vals['HDD'], vals['RHDD']
