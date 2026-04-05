#!/usr/bin/env python3
"""
Preprocessing: Filtert ein Vektor-GeoPackage nach Amtlichem Gemeindeschlüssel (AGS).

Typische Spaltennamen: AGS, gemeindeschluessel (Groß/Kleinschreibung über --column).
Ausgabe sinnvoll nach ``input/gpkg_filtered/`` oder
``input/grundkarte_liegenschaftskataster/gpkg_filtered/``, damit ``etl_schritt1_spatial_join.py``
die Datei automatisch vor Rohdaten aus ``input/gpkg_raw/`` verwendet.

Modi:
  --ags CODE [CODE ...]   exakter Vergleich (ein oder mehrere Schlüssel)
  --prefix PRÄFIX         Spaltenwert beginnt mit PRÄFIX (z. B. Kreis 5-stellig)

Beispiele (vom Projektroot aus):
  python input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py input/gpkg_raw/hu_sn_gebaeude.gpkg --ags 14713000 -o input/gpkg_filtered/gebaeude_leipzig.gpkg
  python input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py input/gpkg_raw/hu_sn_gebaeude.gpkg --ags 14713000 14523380 -o input/gpkg_filtered/gebaeude_auswahl.gpkg
  python input/grundkarte_liegenschaftskataster/preprocess_filter_gemeinde.py input/gpkg_raw/hu_sn_gebaeude.gpkg --prefix 14713 -o input/grundkarte_liegenschaftskataster/gpkg_filtered/region_14713.gpkg
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd


def _normalize_ags_tokens(raw: list[str]) -> list[str]:
    out: list[str] = []
    for part in raw:
        for token in re.split(r"[\s,;]+", part.strip()):
            if token:
                out.append(token)
    return out


def _filter_exact(gdf: gpd.GeoDataFrame, col: str, values: set[str]) -> gpd.GeoDataFrame:
    s = gdf[col].astype(str).str.strip()
    return gdf[s.isin(values)].copy()


def _filter_prefix(gdf: gpd.GeoDataFrame, col: str, prefix: str) -> gpd.GeoDataFrame:
    s = gdf[col].astype(str).str.strip()
    return gdf[s.str.startswith(prefix, na=False)].copy()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="GeoPackage nach AGS (Amtlicher Gemeindeschlüssel) filtern",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "input_gpkg",
        help="Pfad zur Quell-GeoPackage-Datei (.gpkg)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: <Eingabe>_ags_filter.gpkg im gleichen Ordner)",
    )
    ap.add_argument(
        "--column",
        default="AGS",
        metavar="NAME",
        help='Attributspalte mit dem AGS (Standard: "AGS")',
    )
    ap.add_argument(
        "--layer",
        default=None,
        help="Layer-Name; Standard: erster Layer in der Datei",
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--ags",
        nargs="+",
        metavar="CODE",
        help="Einer oder mehrere AGS-Werte (exakt), z. B. 14713000 oder 14713000 14523380",
    )
    mode.add_argument(
        "--prefix",
        metavar="PRÄFIX",
        help="Alle Datensätze, deren AGS mit diesem Text beginnt (z. B. 14713 oder 14523)",
    )
    args = ap.parse_args()

    inp = Path(args.input_gpkg)
    if not inp.is_file():
        print(f"Datei nicht gefunden: {inp}", file=sys.stderr)
        return 1

    out_path = args.output
    if not out_path:
        out_path = str(inp.with_name(f"{inp.stem}_ags_filter.gpkg"))

    layer = args.layer
    if not layer:
        layers = gpd.list_layers(str(inp))
        layer = str(layers.name.iloc[0])

    col = args.column
    where: str | None = None

    if args.prefix is not None:
        prefix = args.prefix.strip()
        if not prefix:
            print("--prefix darf nicht leer sein.", file=sys.stderr)
            return 1
        col_sql = f'"{col}"' if not col.isalnum() else col
        where = f"{col_sql} LIKE '{prefix}%'"
        label = f"Präfix {prefix!r}"
    else:
        codes = _normalize_ags_tokens(args.ags)
        if not codes:
            print("Mindestens einen --ags CODE angeben.", file=sys.stderr)
            return 1
        col_sql = f'"{col}"' if not col.isalnum() else col
        if len(codes) == 1:
            where = f"{col_sql} = '{codes[0]}'"
        else:
            inner = ", ".join(f"'{c}'" for c in codes)
            where = f"{col_sql} IN ({inner})"
        label = f"AGS in {{{', '.join(codes)}}}"

    gdf: gpd.GeoDataFrame | None = None
    err: Exception | None = None
    if where is not None:
        try:
            gdf = gpd.read_file(str(inp), layer=layer, where=where)
        except Exception as e:
            err = e

    if gdf is None:
        if err:
            print(f"Hinweis: SQL-Filter nicht nutzbar ({err}); lade Layer und filtere lokal.", file=sys.stderr)
        gdf = gpd.read_file(str(inp), layer=layer)
        if col not in gdf.columns:
            print(
                f"Spalte {col!r} fehlt. Vorhanden: {list(gdf.columns)}",
                file=sys.stderr,
            )
            return 1
        if args.prefix is not None:
            gdf = _filter_prefix(gdf, col, args.prefix.strip())
        else:
            codes = _normalize_ags_tokens(args.ags)
            gdf = _filter_exact(gdf, col, set(codes))

    if gdf.crs is None:
        gdf.set_crs("EPSG:25833", inplace=True)

    out_layer = Path(out_path).stem
    gdf.to_file(out_path, driver="GPKG", layer=out_layer)

    print(
        f"{label}: {len(gdf)} Features -> {out_path} (Layer: {out_layer})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
