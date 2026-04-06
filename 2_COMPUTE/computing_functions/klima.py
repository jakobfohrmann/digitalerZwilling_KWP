"""
Klimaszenarien: Auswahl von HDD/RHDD und Neuberechnung der Energiewerte.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from energie_ref_berechnung import Energie, create_energie_instanzen
from paths import PARAMS_KLIMA_GEB
from gebaeudetypologie_loader import load_gebaeudetypologie
from helpers import baujahr_to_baualtersklasse, find_matching_referenz, scale_energie_values, ENERGIE_SPALTEN


def load_climate_scenarios(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Lädt HDD/RHDD-Szenarien aus CSV."""
    if csv_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            str(PARAMS_KLIMA_GEB / "annual_hdd_rhdd_all_scenarios.csv"),
            os.path.join(script_dir, "annual_hdd_rhdd_all_scenarios.csv"),
            "annual_hdd_rhdd_all_scenarios.csv",
            "2_COMPUTE/annual_hdd_rhdd_all_scenarios.csv",
            "data/annual_hdd_rhdd_all_scenarios.csv",
            "../data/annual_hdd_rhdd_all_scenarios.csv",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break

    if csv_path is None or not os.path.exists(csv_path):
        raise FileNotFoundError('annual_hdd_rhdd_all_scenarios.csv nicht gefunden.')

    df = pd.read_csv(csv_path)
    if not {'year', 'scenario', 'HDD', 'RHDD'}.issubset(df.columns):
        raise ValueError('CSV enthält nicht die benötigten Spalten: year, scenario, HDD, RHDD')

    return df


def normalize_scenario_name(scenario: str) -> str:
    """Normalisiert Szenarionamen (rcp26/rcp45/rcp85)."""
    scenario_clean = str(scenario).strip().lower().replace(' ', '')
    if scenario_clean.startswith('rcp') and '_' not in scenario_clean:
        return f"{scenario_clean}_2024_2050"
    return scenario_clean


def get_hdd_rhdd_for_scenario(
    year: int,
    scenario: str,
    csv_path: Optional[str] = None
) -> Tuple[float, float]:
    """Gibt HDD/RHDD für ein Jahr und Szenario zurück."""
    df = load_climate_scenarios(csv_path)
    scenario_key = normalize_scenario_name(scenario)

    try:
        year_int = int(year)
    except (TypeError, ValueError):
        raise ValueError('Ungültiges Jahr für Klimaszenario.')

    match = df[(df['year'] == year_int) & (df['scenario'] == scenario_key)]
    if match.empty:
        raise ValueError(f'Keine Klimadaten für {scenario_key} im Jahr {year_int} gefunden.')

    row = match.iloc[0]
    return float(row['HDD']), float(row['RHDD'])




def apply_klima_simulation(
    gdf: gpd.GeoDataFrame,
    scenario: str,
    year: int,
    energy_params: Optional[Dict[str, float]] = None,
    klima_csv_path: Optional[str] = None
) -> Tuple[gpd.GeoDataFrame, Dict]:
    """Wendet Klimaszenario an und berechnet Energiewerte neu."""
    hdd, rhdd = get_hdd_rhdd_for_scenario(year, scenario, csv_path=klima_csv_path)
    energie_liste = create_energie_instanzen(energy_params=energy_params, climate_hdd_rhdd=(hdd, rhdd))
    gebaeude_liste = load_gebaeudetypologie()

    # Spalten für Simulation
    for col in ENERGIE_SPALTEN:
        sim_col = f"{col}_sim"
        if sim_col not in gdf.columns:
            gdf[sim_col] = np.nan
        base_col = f"{col}_base"
        if base_col not in gdf.columns and col in gdf.columns:
            gdf[base_col] = gdf[col]

    matched_count = 0
    unmatched_count = 0

    u_cols = ['U_dach', 'U_geschossdecke', 'U_wand', 'U_fenster', 'U_keller', 'U_tuer']

    for idx, row in gdf.iterrows():
        gebaeudetyp = row.get('gebaeudetyp')
        baujahr = row.get('baujahr')
        bezugsflaeche = row.get("bezugsflaeche")

        # Konvertiere Baujahr zu Baualtersklasse
        bal = baujahr_to_baualtersklasse(baujahr)

        energie_ref = find_matching_referenz(gebaeudetyp, bal, energie_liste, gebaeude_liste)

        if energie_ref is None:
            unmatched_count += 1
            continue

        bezugsflaeche_ref = None
        ref_gebaeude = None
        for gebaeude in gebaeude_liste:
            if gebaeude.typ == gebaeudetyp and gebaeude.bal == bal:
                bezugsflaeche_ref = gebaeude.AN
                ref_gebaeude = gebaeude
                break

        if bezugsflaeche_ref is None:
            unmatched_count += 1
            continue

        energie_werte = scale_energie_values(energie_ref, bezugsflaeche, bezugsflaeche_ref)

        # Wenn sanierte U-Werte vorhanden sind, c0_QT entsprechend anpassen
        has_sanierung = any(pd.notna(row.get(col)) for col in u_cols if col in gdf.columns)
        if has_sanierung and ref_gebaeude:
            scale_factor = bezugsflaeche / bezugsflaeche_ref if bezugsflaeche_ref > 0 else 1.0
            c0_QT_saniert = 0.0

            u_dach = row.get('U_dach') if 'U_dach' in gdf.columns else None
            c0_QT_saniert += ref_gebaeude.f_dach * (u_dach if pd.notna(u_dach) else ref_gebaeude.U_dach) * ref_gebaeude.A_dach * scale_factor

            u_ogd = row.get('U_geschossdecke') if 'U_geschossdecke' in gdf.columns else None
            c0_QT_saniert += ref_gebaeude.f_ogd * (u_ogd if pd.notna(u_ogd) else ref_gebaeude.U_ogd) * ref_gebaeude.A_ogd * scale_factor

            u_wand = row.get('U_wand') if 'U_wand' in gdf.columns else None
            c0_QT_saniert += ref_gebaeude.f_aw * (u_wand if pd.notna(u_wand) else ref_gebaeude.U_aw) * ref_gebaeude.A_aw * scale_factor

            u_keller = row.get('U_keller') if 'U_keller' in gdf.columns else None
            c0_QT_saniert += ref_gebaeude.f_kd * (u_keller if pd.notna(u_keller) else ref_gebaeude.U_kd) * ref_gebaeude.A_kd * scale_factor

            u_fenster = row.get('U_fenster') if 'U_fenster' in gdf.columns else None
            c0_QT_saniert += ref_gebaeude.f_fen * (u_fenster if pd.notna(u_fenster) else ref_gebaeude.U_fen) * ref_gebaeude.A_fen * scale_factor

            u_tuer = row.get('U_tuer') if 'U_tuer' in gdf.columns else None
            c0_QT_saniert += ref_gebaeude.f_tuer * (u_tuer if pd.notna(u_tuer) else ref_gebaeude.U_tuer) * ref_gebaeude.A_tuer * scale_factor

            c0_QT_saniert += ref_gebaeude.U_wb * ref_gebaeude.A_summe * scale_factor
            energie_werte['c0_QT'] = c0_QT_saniert

        for col, wert in energie_werte.items():
            gdf.loc[idx, f"{col}_sim"] = wert

        matched_count += 1

    stats = {
        'total_buildings': len(gdf),
        'matched': matched_count,
        'unmatched': unmatched_count,
        'hdd': hdd,
        'rhdd': rhdd,
        'scenario': normalize_scenario_name(scenario),
        'year': int(year)
    }
    return gdf, stats
