"""Wendet Klimaszenarien auf Gebäudedaten an."""

from typing import Dict, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from climate.loader import get_climate_values_for_scenario, normalize_scenario_name
from energy.calculator import create_energie_instanzen
from typology.loader import load_gebaeudetypologie
from shared.helpers import baujahr_to_baualtersklasse, find_matching_referenz_and_gebaeude, scale_energie_values, ENERGIE_SPALTEN


def apply_klima_simulation(
    gdf: gpd.GeoDataFrame,
    scenario: str,
    year: int,
    energy_params: Optional[Dict[str, float]] = None,
    klima_csv_path: Optional[str] = None,
) -> Tuple[gpd.GeoDataFrame, Dict]:
    """Wendet Klimaszenario an und berechnet Energiewerte neu."""
    climate_values = get_climate_values_for_scenario(year, scenario, csv_path=klima_csv_path)
    energie_liste = create_energie_instanzen(energy_params=energy_params, climate_overrides=climate_values)
    gebaeude_liste = load_gebaeudetypologie()

    u_cols = ['U_dach', 'U_geschossdecke', 'U_wand', 'U_fenster', 'U_keller', 'U_tuer']

    for col in ENERGIE_SPALTEN:
        gdf[f"{col}_sim_klima"] = gdf.get(f"{col}_sim_klima", np.nan)

    matched, unmatched = 0, 0

    for idx, row in gdf.iterrows():
        gebaeudetyp = row.get('gebaeudetyp')
        bal = baujahr_to_baualtersklasse(row.get('baujahr'))
        bezugsflaeche = row.get('bezugsflaeche')

        energie_ref, ref_g = find_matching_referenz_and_gebaeude(gebaeudetyp, bal, energie_liste, gebaeude_liste)
        if energie_ref is None or ref_g is None:
            unmatched += 1
            continue

        energie_werte = scale_energie_values(energie_ref, bezugsflaeche, ref_g.AN)

        if any(pd.notna(row.get(c)) for c in u_cols if c in gdf.columns) and ref_g:
            sf = bezugsflaeche / ref_g.AN if ref_g.AN > 0 else 1.0
            qt_san = (ref_g.f_dach * (row.get('U_dach') if pd.notna(row.get('U_dach')) else ref_g.U_dach) * ref_g.A_dach +
                      ref_g.f_ogd * (row.get('U_geschossdecke') if pd.notna(row.get('U_geschossdecke')) else ref_g.U_ogd) * ref_g.A_ogd +
                      ref_g.f_aw * (row.get('U_wand') if pd.notna(row.get('U_wand')) else ref_g.U_aw) * ref_g.A_aw +
                      ref_g.f_kd * (row.get('U_keller') if pd.notna(row.get('U_keller')) else ref_g.U_kd) * ref_g.A_kd +
                      ref_g.f_fen * (row.get('U_fenster') if pd.notna(row.get('U_fenster')) else ref_g.U_fen) * ref_g.A_fen +
                      ref_g.f_tuer * (row.get('U_tuer') if pd.notna(row.get('U_tuer')) else ref_g.U_tuer) * ref_g.A_tuer +
                      ref_g.U_wb * ref_g.A_summe) * sf
            energie_werte['c_QT_saniert'] = qt_san
            denom = float(energie_werte.get('c_QT', 0)) + float(energie_werte.get('d_QL', 0))
            if denom > 0:
                k = float(energie_werte.get('g_QH', 0)) / denom
                qh_s = k * (qt_san + float(energie_werte.get('d_QL', 0)))
                energie_werte['g_QH_saniert'] = qh_s
                energie_werte['ga_qH_saniert'] = qh_s / bezugsflaeche if pd.notna(bezugsflaeche) and bezugsflaeche > 0 else np.nan

        for col, wert in energie_werte.items():
            gdf.loc[idx, f"{col}_sim_klima"] = wert
        matched += 1

    stats = {
        'total_buildings': len(gdf), 'matched': matched, 'unmatched': unmatched,
        'scenario': normalize_scenario_name(scenario), 'year': int(year),
        'hdd': climate_values['HDD'], 'hd': climate_values['HD'], 'rhdd': climate_values['RHDD'],
        'g_hor': climate_values['G_Hor'], 'g_hor_hd': climate_values['G_Hor_HD'],
        'g_e_hd': climate_values['G_E_HD'], 'g_s_hd': climate_values['G_S_HD'],
        'g_w_hd': climate_values['G_W_HD'], 'g_n_hd': climate_values['G_N_HD'],
    }
    return gdf, stats
