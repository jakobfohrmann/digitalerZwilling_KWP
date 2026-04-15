"""
Klimaszenarien: Auswahl von HDD/RHDD und Neuberechnung der Energiewerte.
"""

from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from energie_ref_berechnung import create_energie_instanzen
from paths import PARAMS_KLIMA_GEB
from gebaeudetypologie_loader import load_gebaeudetypologie
from helpers import (
    baujahr_to_baualtersklasse,
    find_matching_referenz_and_gebaeude,
    scale_energie_values,
    ENERGIE_SPALTEN,
)


def load_climate_solar_scenarios(csv_path: Optional[str] = None) -> pd.DataFrame:
    """Lädt erweiterte Klima+Solar-Szenarien aus CSV."""
    if csv_path is None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            str(PARAMS_KLIMA_GEB / "annual_climate_solar_projections_2100.csv"),
            os.path.join(script_dir, "annual_climate_solar_projections_2100.csv"),
            "annual_climate_solar_projections_2100.csv",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break

    if csv_path is None or not os.path.exists(csv_path):
        raise FileNotFoundError("annual_climate_solar_projections_2100.csv nicht gefunden.")

    df = pd.read_csv(csv_path)
    required = {
        "year",
        "scenario",
        "HDD",
        "HD",
        "RHDD",
        "G_Hor",
        "G_Hor_HD",
        "G_E_HD",
        "G_S_HD",
        "G_W_HD",
        "G_N_HD",
    }
    if not required.issubset(df.columns):
        raise ValueError(
            "CSV enthält nicht die benötigten Spalten: year, scenario, HDD, HD, RHDD, G_Hor, "
            "G_Hor_HD, G_E_HD, G_S_HD, G_W_HD, G_N_HD"
        )
    return df


def normalize_scenario_name(scenario: str) -> str:
    """Normalisiert Szenarionamen (rcp45/rcp85)."""
    scenario_clean = str(scenario).strip().lower().replace(' ', '')
    if scenario_clean.startswith('rcp') and '_' in scenario_clean:
        return scenario_clean.split('_')[0]
    return scenario_clean


def get_climate_values_for_scenario(
    year: int,
    scenario: str,
    csv_path: Optional[str] = None
) -> Dict[str, float]:
    """Gibt Klima-/Strahlungswerte für ein Jahr und Szenario zurück."""
    df = load_climate_solar_scenarios(csv_path)
    scenario_key = normalize_scenario_name(scenario)

    try:
        year_int = int(year)
    except (TypeError, ValueError):
        raise ValueError('Ungültiges Jahr für Klimaszenario.')

    match = df[(df['year'] == year_int) & (df['scenario'] == scenario_key)]
    if match.empty:
        raise ValueError(f'Keine Klimadaten für {scenario_key} im Jahr {year_int} gefunden.')

    row = match.iloc[0]
    return {
        "year": float(row["year"]),
        "HDD": float(row["HDD"]),
        "HD": float(row["HD"]),
        "RHDD": float(row["RHDD"]),
        "G_Hor": float(row["G_Hor"]),
        "G_Hor_HD": float(row["G_Hor_HD"]),
        "G_E_HD": float(row["G_E_HD"]),
        "G_S_HD": float(row["G_S_HD"]),
        "G_W_HD": float(row["G_W_HD"]),
        "G_N_HD": float(row["G_N_HD"]),
    }


def get_hdd_rhdd_for_scenario(
    year: int,
    scenario: str,
    csv_path: Optional[str] = None
) -> Tuple[float, float]:
    """Kompatibilitätsfunktion: Gibt HDD/RHDD zurück."""
    climate_values = get_climate_values_for_scenario(year, scenario, csv_path)
    return climate_values["HDD"], climate_values["RHDD"]




def apply_klima_simulation(
    gdf: gpd.GeoDataFrame,
    scenario: str,
    year: int,
    energy_params: Optional[Dict[str, float]] = None,
    klima_csv_path: Optional[str] = None
) -> Tuple[gpd.GeoDataFrame, Dict]:
    """Wendet Klimaszenario an und berechnet Energiewerte neu."""
    climate_values = get_climate_values_for_scenario(year, scenario, csv_path=klima_csv_path)
    energie_liste = create_energie_instanzen(
        energy_params=energy_params,
        climate_overrides=climate_values
    )
    gebaeude_liste = load_gebaeudetypologie()

    # Spalten für Simulation
    for col in ENERGIE_SPALTEN:
        sim_col = f"{col}_sim_klima"
        if sim_col not in gdf.columns:
            gdf[sim_col] = np.nan

    matched_count = 0
    unmatched_count = 0

    u_cols = ['U_dach', 'U_geschossdecke', 'U_wand', 'U_fenster', 'U_keller', 'U_tuer']

    for idx, row in gdf.iterrows():
        gebaeudetyp = row.get('gebaeudetyp')
        baujahr = row.get('baujahr')
        bezugsflaeche = row.get("bezugsflaeche")

        # Konvertiere Baujahr zu Baualtersklasse
        bal = baujahr_to_baualtersklasse(baujahr)

        energie_ref, ref_gebaeude = find_matching_referenz_and_gebaeude(gebaeudetyp, bal, energie_liste, gebaeude_liste)

        if energie_ref is None:
            unmatched_count += 1
            continue

        bezugsflaeche_ref = ref_gebaeude.AN if ref_gebaeude is not None else None

        if bezugsflaeche_ref is None:
            unmatched_count += 1
            continue

        energie_werte = scale_energie_values(energie_ref, bezugsflaeche, bezugsflaeche_ref)

        # Wenn sanierte U-Werte vorhanden sind, sanierten QT und daraus sanierten QH approximieren
        has_sanierung = any(pd.notna(row.get(col)) for col in u_cols if col in gdf.columns)
        if has_sanierung and ref_gebaeude:
            scale_factor = bezugsflaeche / bezugsflaeche_ref if bezugsflaeche_ref > 0 else 1.0
            c_qt_saniert = 0.0

            u_dach = row.get('U_dach') if 'U_dach' in gdf.columns else None
            c_qt_saniert += ref_gebaeude.f_dach * (u_dach if pd.notna(u_dach) else ref_gebaeude.U_dach) * ref_gebaeude.A_dach * scale_factor

            u_ogd = row.get('U_geschossdecke') if 'U_geschossdecke' in gdf.columns else None
            c_qt_saniert += ref_gebaeude.f_ogd * (u_ogd if pd.notna(u_ogd) else ref_gebaeude.U_ogd) * ref_gebaeude.A_ogd * scale_factor

            u_wand = row.get('U_wand') if 'U_wand' in gdf.columns else None
            c_qt_saniert += ref_gebaeude.f_aw * (u_wand if pd.notna(u_wand) else ref_gebaeude.U_aw) * ref_gebaeude.A_aw * scale_factor

            u_keller = row.get('U_keller') if 'U_keller' in gdf.columns else None
            c_qt_saniert += ref_gebaeude.f_kd * (u_keller if pd.notna(u_keller) else ref_gebaeude.U_kd) * ref_gebaeude.A_kd * scale_factor

            u_fenster = row.get('U_fenster') if 'U_fenster' in gdf.columns else None
            c_qt_saniert += ref_gebaeude.f_fen * (u_fenster if pd.notna(u_fenster) else ref_gebaeude.U_fen) * ref_gebaeude.A_fen * scale_factor

            u_tuer = row.get('U_tuer') if 'U_tuer' in gdf.columns else None
            c_qt_saniert += ref_gebaeude.f_tuer * (u_tuer if pd.notna(u_tuer) else ref_gebaeude.U_tuer) * ref_gebaeude.A_tuer * scale_factor

            c_qt_saniert += ref_gebaeude.U_wb * ref_gebaeude.A_summe * scale_factor
            energie_werte['c_QT_saniert'] = c_qt_saniert

            transmission_unsaniert = float(energie_werte.get('c_QT', 0.0))
            lueftung = float(energie_werte.get('d_QL', 0.0))
            qh_unsaniert = float(energie_werte.get('g_QH', 0.0))
            denom = transmission_unsaniert + lueftung
            if denom > 0:
                k_eff = qh_unsaniert / denom
                qh_saniert = k_eff * (c_qt_saniert + lueftung)
                energie_werte['g_QH_saniert'] = qh_saniert
                energie_werte['ga_qH_saniert'] = qh_saniert / bezugsflaeche if pd.notna(bezugsflaeche) and bezugsflaeche > 0 else np.nan

        for col, wert in energie_werte.items():
            gdf.loc[idx, f"{col}_sim_klima"] = wert

        matched_count += 1

    stats = {
        'total_buildings': len(gdf),
        'matched': matched_count,
        'unmatched': unmatched_count,
        'hdd': climate_values["HDD"],
        'hd': climate_values["HD"],
        'rhdd': climate_values["RHDD"],
        'g_hor': climate_values["G_Hor"],
        'g_hor_hd': climate_values["G_Hor_HD"],
        'g_e_hd': climate_values["G_E_HD"],
        'g_s_hd': climate_values["G_S_HD"],
        'g_w_hd': climate_values["G_W_HD"],
        'g_n_hd': climate_values["G_N_HD"],
        'scenario': normalize_scenario_name(scenario),
        'year': int(year)
    }
    return gdf, stats
