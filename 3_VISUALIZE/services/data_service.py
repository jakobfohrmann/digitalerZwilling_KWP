"""Gebäudedaten laden, cachen und Energiebilanz berechnen."""

from pathlib import Path
from typing import Optional, Tuple, List

import geopandas as gpd
import numpy as np
import pandas as pd

from paths import COMPUTE_OUTPUTS
from energy.calculator import create_energie_instanzen, get_default_energy_parameters
from typology.loader import load_gebaeudetypologie
from helpers import baujahr_to_baualtersklasse, find_matching_referenz_and_gebaeude, scale_energie_values, ENERGIE_SPALTEN

# --- Globaler Zustand ---
buildings_data: Optional[gpd.GeoDataFrame] = None
current_data_filename: Optional[str] = None
energy_parameters = get_default_energy_parameters()


def pick_gpkg_from_outputs(explicit_basename: Optional[str] = None) -> Tuple[str, str]:
    """Wählt eine GeoPackage-Datei aus COMPUTE_OUTPUTS (neueste, falls mehrere)."""
    out_dir = Path(COMPUTE_OUTPUTS)
    out_dir.mkdir(parents=True, exist_ok=True)

    if explicit_basename:
        path = out_dir / explicit_basename
        if not path.is_file():
            raise FileNotFoundError(f"GeoPackage nicht gefunden: {path}")
        return str(path.resolve()), explicit_basename

    candidates = sorted(out_dir.glob("*.gpkg"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(f"Kein .gpkg in {out_dir}. Bitte compute_main ausführen.")
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates[:5])
        print(f"[INFO] Mehrere GPKG gefunden ({names}) — verwende: {candidates[0].name}")
    return str(candidates[0].resolve()), candidates[0].name


def list_gpkg_in_outputs() -> List[str]:
    """Gibt alle .gpkg-Dateien aus COMPUTE_OUTPUTS zurück (neueste zuerst)."""
    out_dir = Path(COMPUTE_OUTPUTS)
    out_dir.mkdir(parents=True, exist_ok=True)
    return [p.name for p in sorted(out_dir.glob("*.gpkg"), key=lambda p: p.stat().st_mtime, reverse=True)]


def load_data(input_filename: Optional[str] = None) -> gpd.GeoDataFrame:
    """Lädt Gebäude-GPKG und aktualisiert den globalen Cache."""
    global buildings_data, current_data_filename

    gpkg_path, basename = pick_gpkg_from_outputs(explicit_basename=input_filename)
    gdf = gpd.read_file(gpkg_path)
    print(f"[OK] {len(gdf)} Gebäude geladen: {gpkg_path}")

    if 'baujahr' in gdf.columns and 'baualtersklasse' not in gdf.columns:
        gdf['baualtersklasse'] = gdf['baujahr'].apply(baujahr_to_baualtersklasse)

    buildings_data = gdf
    current_data_filename = basename
    return gdf


def add_energiebilanz_to_gebaeude(
    gdf: gpd.GeoDataFrame,
    params: Optional[dict] = None,
) -> gpd.GeoDataFrame:
    """Fügt Energiebilanzwerte zu Gebäuden hinzu basierend auf Referenzgebäuden."""
    energie_liste = create_energie_instanzen(energy_params=params)
    gebaeude_liste = load_gebaeudetypologie()

    for col in ENERGIE_SPALTEN:
        if col not in gdf.columns:
            gdf[col] = np.nan

    matched, unmatched = 0, 0
    for idx, row in gdf.iterrows():
        bal = baujahr_to_baualtersklasse(row.get('baujahr'))
        e_ref, ref_g = find_matching_referenz_and_gebaeude(
            row.get('gebaeudetyp'), bal, energie_liste, gebaeude_liste
        )
        if e_ref is None or ref_g is None:
            unmatched += 1
            continue
        for col, wert in scale_energie_values(e_ref, row.get('bezugsflaeche'), ref_g.AN).items():
            gdf.loc[idx, col] = wert
        matched += 1

    print(f"✓ {matched} Gebäude mit Energiebilanz, {unmatched} nicht zugeordnet")
    return gdf


def get_preferred_sim_value(record: dict, base_col: str):
    """Gibt bevorzugten Simulationswert zurück: Klima > Sanierung > Basis."""
    for suffix in ('_sim_klima', '_sim_saniert'):
        v = record.get(f"{base_col}{suffix}")
        if pd.notna(v):
            return v
    return record.get(base_col)
