"""Batch-Verarbeitung von Sanierungsgebieten (nicht die interaktive API)."""

import os
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd

from paths import COMPUTE_INPUTS, COMPUTE_OUTPUTS, PARAMS_KLIMA_GEB
from sanierung.u_values import _parse_float, find_matching_typologie_row, load_sanierungs_typologie


def process_sanierung(
    input_gpkg: str,
    sanierungsgebiete_gpkg: Optional[str] = None,
    csv_path: Optional[str] = None,
    csv_start_row: int = 49,
) -> gpd.GeoDataFrame:
    """
    Weist Sanierungsjahr und U-Werte für Gebäude in Sanierungsgebieten zu.
    Nutzt räumlichen Join zwischen Gebäudepolygonen und Sanierungsgebietspolygonen.
    """
    sanierungsgebiete_gpkg = sanierungsgebiete_gpkg or str(COMPUTE_INPUTS / "Sanierungsgebiete.gpkg")
    csv_path = csv_path or str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")

    for path, label in [(input_gpkg, "Gebäude"), (sanierungsgebiete_gpkg, "Sanierungsgebiete"), (csv_path, "CSV")]:
        if not os.path.exists(path):
            raise FileNotFoundError(f"{label}-Datei nicht gefunden: {path}")

    gdf_gebaeude = gpd.read_file(input_gpkg)
    gdf_sanierung = gpd.read_file(sanierungsgebiete_gpkg)
    print(f"✓ {len(gdf_gebaeude)} Gebäude, {len(gdf_sanierung)} Sanierungsgebiete geladen")

    df_typ = load_sanierungs_typologie(csv_path=csv_path, csv_start_row=csv_start_row)
    bool_cols = [c for c in ['Dach', 'Geschossdecke', 'Wand', 'Fenster', 'Keller', 'Tür', 'gF'] if c in gdf_sanierung.columns]

    if gdf_gebaeude.crs != gdf_sanierung.crs:
        gdf_gebaeude = gdf_gebaeude.to_crs(gdf_sanierung.crs)

    gdf_joined = gpd.sjoin(
        gdf_gebaeude,
        gdf_sanierung[['Sanierungsjahr'] + bool_cols + ['geometry']],
        how='left', predicate='within',
    )

    gdf_gebaeude['sanierungsjahr'] = np.nan
    u_cols = ['U_dach', 'U_geschossdecke', 'U_wand', 'U_fenster', 'U_keller', 'U_tuer']
    for col in u_cols:
        gdf_gebaeude[col] = np.nan

    u_idx = {'dach': 15, 'geschossdecke': 16, 'wand': 17, 'keller': 18, 'fenster': 19, 'tuer': 20}
    u_col_names = {k: df_typ.columns[v] if v < len(df_typ.columns) else None for k, v in u_idx.items()}

    bool_map = {'Dach': 'dach', 'Geschossdecke': 'geschossdecke', 'Wand': 'wand',
                'Fenster': 'fenster', 'Keller': 'keller', 'Tür': 'tuer'}

    assigned, u_count = 0, 0
    for idx in gdf_gebaeude.index:
        rows = gdf_joined[gdf_joined.index == idx]
        if rows.empty:
            continue
        row = rows.iloc[0]
        san_jahr = row.get('Sanierungsjahr')
        if pd.isna(san_jahr):
            continue
        try:
            san_int = int(float(san_jahr))
        except (ValueError, TypeError):
            continue

        gdf_gebaeude.loc[idx, 'sanierungsjahr'] = san_int
        assigned += 1

        typ_row = find_matching_typologie_row(df_typ, gdf_gebaeude.loc[idx].get('gebaeudetyp'), san_int)
        if typ_row is None:
            continue

        for bool_col, key in bool_map.items():
            if bool_col in bool_cols and row.get(bool_col) is True:
                col_name = u_col_names.get(key)
                if col_name and col_name in typ_row.index:
                    v = _parse_float(typ_row[col_name])
                    if v > 0:
                        gdf_gebaeude.loc[idx, f'U_{key}'] = v
                        u_count += 1

    print(f"✓ {assigned} Gebäude mit Sanierungsjahr, {u_count} U-Werte zugewiesen")

    base = os.path.splitext(os.path.basename(input_gpkg))[0]
    os.makedirs(COMPUTE_OUTPUTS, exist_ok=True)
    out = str(COMPUTE_OUTPUTS / f"{base}_mit_sanierung.gpkg")
    gdf_gebaeude.to_file(out, driver="GPKG")
    print(f"✓ GeoPackage gespeichert: {out}")
    return gdf_gebaeude
