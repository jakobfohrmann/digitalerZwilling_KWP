#!/usr/bin/env python3
"""
ETL-Schritt 5: Gebäudetyp (Wohn: EFH, RH, MFH, GMH, HH).

Nutzt ausschließlich die in **Schritt 3** berechneten Spalten (plus Geometrie für die Fußabdruckfläche):

- ``trauf_hoehe_m``, ``dach_hoehe_m``
- ``bezugsflaeche`` (Fußabdruckfläche × ``geschoss_hoehe_m``-Kennzahl, m³)
- ``anzahl_geschosse`` (geschätzte oberirdische Geschosse aus Schritt 3)

Die Höhen-Regeln (MFH/GMH/HH) verwenden ``trauf_hoehe_m + dach_hoehe_m`` als Objekthöhen-Proxy;
EFH/RH: Fußabdruckfläche (m²) und ``anzahl_geschosse``.

Eingabe: Standard erste ``*_schritt4.gpkg`` unter ``output/output_step4/``
Ausgabe: ``output/output_step5/<Basis>_schritt5.gpkg``

Beispiele:
  python etl_schritt5_gebaeudetyp.py
  python etl_schritt5_gebaeudetyp.py output/output_step4/gebaeude_leipzig_schritt4.gpkg
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Spalten aus etl_schritt3_hoehe_flaeche_geschosse.py
COL_TRAUF = "trauf_hoehe_m"
COL_DACH = "dach_hoehe_m"
COL_BEZUGS = "bezugsflaeche"
COL_ANZAHL_GESCHOSSE = "anzahl_geschosse"

EFH_MAX_FOOTPRINT_M2 = 400.0


def _ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _base_stem_from_step4(stem: str) -> str:
    if stem.endswith("_schritt4"):
        return stem[: -len("_schritt4")]
    return stem


def _resolve_input_schritt4(path_arg: str | None) -> str | None:
    if path_arg:
        return path_arg if os.path.isfile(path_arg) else None
    step4 = os.path.join(SCRIPT_DIR, "output", "output_step4", "*_schritt4.gpkg")
    cands = sorted(glob.glob(step4))
    if not cands:
        cands = sorted(glob.glob(os.path.join(SCRIPT_DIR, "output", "output_step4", "*.gpkg")))
    if len(cands) > 1:
        print(
            f"Mehrere GPKG in output/output_step4/ — verwende: {cands[0]} (oder Eingabepfad angeben).",
            file=sys.stderr,
        )
    return cands[0] if cands else None


def _default_output_path(input_path: str) -> str:
    stem = Path(input_path).stem
    base = _base_stem_from_step4(stem)
    return os.path.join(SCRIPT_DIR, "output", "output_step5", f"{base}_schritt5.gpkg")


def _pick_layer(gpkg_path: str, layer: str | None) -> str | None:
    if layer:
        return layer
    raw = gpd.list_layers(gpkg_path).name.values
    layers = [n for n in raw if not str(n).startswith(("gpkg_", "rtree_"))]
    return layers[0] if layers else None


def _index_pos(gdf: gpd.GeoDataFrame, idx) -> int | None:
    loc = gdf.index.get_loc(idx)
    if isinstance(loc, (slice, np.ndarray)):
        return None
    return int(loc)


def _footprint_area_m2(geom) -> float:
    """Größtes Polygon — Fläche in Karteneinheiten (m² bei EPSG:25833)."""
    if geom is None or geom.is_empty:
        return float("nan")
    if geom.geom_type == "MultiPolygon":
        return float(max(geom.geoms, key=lambda g: g.area).area)
    return float(geom.area)


def _float_or_nan(val) -> float:
    if val is None or pd.isna(val):
        return float("nan")
    try:
        x = float(val)
        if np.isnan(x):
            return float("nan")
        return x
    except (TypeError, ValueError):
        return float("nan")


def count_touching_neighbors(gdf: gpd.GeoDataFrame, idx) -> int:
    """Benachbarte Gebäude mit ähnlicher Fläche (±5 %), die die Geometrie berühren."""
    pos_self = _index_pos(gdf, idx)
    if pos_self is None:
        return 0
    current_geom = gdf.geometry.iloc[pos_self]
    current_area = current_geom.area
    if current_area <= 0:
        return 0
    possible_matches = list(gdf.sindex.intersection(current_geom.bounds))
    touching_count = 0
    for match_idx in possible_matches:
        if match_idx == pos_self:
            continue
        other_geom = gdf.geometry.iloc[match_idx]
        other_area = other_geom.area
        area_ratio = other_area / current_area if current_area > 0 else 0
        if current_geom.touches(other_geom) and (0.95 <= area_ratio <= 1.05):
            touching_count += 1
    return touching_count


def determine_gebaeudetyp(row, gdf: gpd.GeoDataFrame, idx) -> float | str:
    """Gebäudetyp aus Schritt-3-Spalten (trauf, dach, anzahl_geschosse) + Fußabdruck."""
    anzahl_oberirdische_geschosse = _float_or_nan(row.get(COL_ANZAHL_GESCHOSSE))
    trauf_m = _float_or_nan(row.get(COL_TRAUF))
    dach_m = _float_or_nan(row.get(COL_DACH))

    if pd.isna(trauf_m) or pd.isna(anzahl_oberirdische_geschosse):
        return np.nan

    if pd.notna(dach_m):
        objekthoehe_m = trauf_m + dach_m
    else:
        objekthoehe_m = trauf_m

    footprint_m2 = _footprint_area_m2(row.geometry)

    # EFH/RH
    if (
        pd.notna(footprint_m2)
        and (footprint_m2 <= EFH_MAX_FOOTPRINT_M2)
        and (anzahl_oberirdische_geschosse < 3)
    ):
        if count_touching_neighbors(gdf, idx) >= 1:
            return "RH"
        return "EFH"

    if (objekthoehe_m <= 13) or (2 < anzahl_oberirdische_geschosse <= 4):
        return "MFH"

    if (13 < objekthoehe_m < 22) and (anzahl_oberirdische_geschosse > 4):
        return "GMH"

    if objekthoehe_m >= 22:
        return "HH"

    return "fällt nicht in eine der Kategorien"


def create_gebaeudetyp(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Erstellt die Spalte ``gebaeudetyp``."""
    print("Berechne Gebäudetypen …", file=sys.stderr)
    gdf = gdf.copy()
    gdf["gebaeudetyp"] = gdf.apply(
        lambda row: determine_gebaeudetyp(row, gdf, row.name),
        axis=1,
    )
    print("Spalte gebaeudetyp erstellt", file=sys.stderr)
    typ_counts = gdf["gebaeudetyp"].value_counts(dropna=False)
    print("Verteilung gebaeudetyp:", file=sys.stderr)
    for typ, count in typ_counts.items():
        typ_name = typ if pd.notna(typ) else "NaN/Leer"
        print(f"  {typ_name}: {count}", file=sys.stderr)
    return gdf


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Gebäudetyp (Wohn) aus Schritt-4-GPKG berechnen und nach Schritt 5 schreiben",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "input_gpkg",
        nargs="?",
        default=None,
        help="Eingabe-GPKG (Standard: erste *_schritt4.gpkg unter output/output_step4/)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: output/output_step5/<Basis>_schritt5.gpkg)",
    )
    ap.add_argument("--layer-in", default=None, help="Layer der Eingabe (Standard: erster sinnvoller Layer)")
    ap.add_argument(
        "--layer-out",
        default=None,
        help="Layer in der Ausgabe-GPKG (Standard: wie Eingabe)",
    )
    args = ap.parse_args()

    in_path = _resolve_input_schritt4(args.input_gpkg)
    if not in_path:
        print(
            "Keine Eingabe-GPKG: Pfad angeben oder *_schritt4.gpkg unter output/output_step4/ ablegen.",
            file=sys.stderr,
        )
        return 1

    layer_in = _pick_layer(in_path, args.layer_in)
    if not layer_in:
        print("Kein lesbarer Layer in der GPKG.", file=sys.stderr)
        return 1

    gdf = gpd.read_file(in_path, layer=layer_in)
    required = (COL_TRAUF, COL_DACH, COL_BEZUGS, COL_ANZAHL_GESCHOSSE)
    missing = [c for c in required if c not in gdf.columns]
    if missing:
        print(
            f"Erwartete Spalten aus Schritt 3 fehlen: {missing}. "
            f"Benötigt: {list(required)}. Vorhanden: {list(gdf.columns)}",
            file=sys.stderr,
        )
        return 1

    gdf = create_gebaeudetyp(gdf)

    out_path = args.output or _default_output_path(in_path)
    layer_out = args.layer_out or layer_in
    _ensure_parent_dir(out_path)
    gdf.to_file(out_path, driver="GPKG", layer=layer_out)

    print(
        f"Gebäudetyp: {len(gdf)} Gebäude | {out_path} (Layer: {layer_out})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
