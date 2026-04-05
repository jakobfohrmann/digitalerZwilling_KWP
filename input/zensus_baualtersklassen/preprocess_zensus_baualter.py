#!/usr/bin/env python3
"""
Zensus-Gitter (z. B. Baualtersklassen) aus CSV nach GeoPackage — **Polygon-Layer** aus Zellmittelpunkten.

Erwartung: Die ersten drei Spalten sind Gitter-ID und X-/Y-Koordinaten des Mittelpunkts
(typisch ETRS89-LAEA **EPSG:3035** bei Destatis — Koordinaten in **Metern**). Pro Zelle wird ein
**Quadrat** erzeugt, das den Mittelpunkt zentriert (Standard: **100 m × 100 m** Kantenlänge), damit
räumliche Zuordnungen (z. B. Schnitt mit Gebäuden, Baualtersklassen) möglich sind.

**Hinweis:** ``--cell-size-m`` bezieht sich auf Längen in den Einheiten des CRS. Bei EPSG:3035 sind
das Meter. Bei geografischen CRS (z. B. EPSG:4326) wäre die Kantenlänge in **Grad** — für 100 m
Zellen daher immer ein projiziertes Meter-CRS verwenden.

-------------------------------------------------------------------------------
Räumliche Eingrenzung (eine der beiden Varianten)
-------------------------------------------------------------------------------

1) Rechteck in WGS84 (einfach): Option ``--bbox``

   Vier Zahlen in der Reihenfolge: min_lon min_lat max_lon max_lat
   (westlicher/südlicher Rand, östlicher/nördlicher Rand), wie bei üblichen GIS-Bounds.

   Beispiel:
     --bbox 12.26 51.27 12.51 51.44

   Koordinaten z. B. aus QGIS/OSM ablesen: Rechteck zeichnen oder Layer-Extent,
   in EPSG:4326 (WGS 84) anzeigen und die vier Werte übernehmen.

2) Beliebiges Polygon (exakt): Option ``--boundary``

   Pfad zu einer Vektordatei (GeoPackage, GeoJSON, Shapefile, …) mit der
   gewünschten Fläche (eine oder mehrere Polygone; mehrere werden vereinigt).
   CRS wird ggf. als WGS84 angenommen und ins CRS der Punkte transformiert.

   Ohne ``--bbox`` und ohne ``--boundary`` nutzt das Skript eine eingebaute
   **Beispiel-Bounding-Box** (aktuell grob Stadt Leipzig) — für andere Regionen
   unbedingt ``--bbox`` oder ``--boundary`` setzen.

-------------------------------------------------------------------------------
Beispiele (Skript und CSV liegen typischerweise in input/zensus_baualtersklassen/)
-------------------------------------------------------------------------------

  python preprocess_zensus_baualter.py
  python preprocess_zensus_baualter.py --bbox 6.8 50.9 7.2 51.2 -o zensus_baualter.gpkg
  python preprocess_zensus_baualter.py --boundary path/zu/region_umriss.gpkg --crs EPSG:3035
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Fallback, wenn weder --bbox noch --boundary gesetzt: grobe Box in WGS84 (Beispielregion)
DEFAULT_BBOX_WGS84 = (12.26, 51.27, 12.51, 51.44)  # min_lon, min_lat, max_lon, max_lat


def _ensure_parent(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _read_csv_flexible(path: str, encoding: str, sep: str | None) -> pd.DataFrame:
    if sep:
        return pd.read_csv(path, sep=sep, encoding=encoding, dtype=str, low_memory=False)
    for s in (";", ",", "\t"):
        try:
            return pd.read_csv(path, sep=s, encoding=encoding, dtype=str, low_memory=False)
        except Exception:
            continue
    return pd.read_csv(path, sep=None, engine="python", encoding=encoding, dtype=str, low_memory=False)


def _pick_columns(df: pd.DataFrame, id_col: str | None, x_col: str | None, y_col: str | None) -> tuple[str, str, str]:
    if id_col and x_col and y_col:
        for c in (id_col, x_col, y_col):
            if c not in df.columns:
                raise ValueError(f"Spalte {c!r} nicht gefunden. Vorhanden: {list(df.columns)}")
        return id_col, x_col, y_col
    if len(df.columns) < 3:
        raise ValueError(f"Mindestens drei Spalten nötig, haben: {list(df.columns)}")
    c0, c1, c2 = df.columns[0], df.columns[1], df.columns[2]
    return c0, c1, c2


def _to_float_series(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def _squares_around_centers(
    xs: pd.Series,
    ys: pd.Series,
    cell_size_m: float,
) -> list[Polygon]:
    """Quadrat-Polygone (Achsenparallel), Mittelpunkt = (x,y), Kantenlänge = cell_size_m."""
    half = cell_size_m / 2.0
    out = []
    for x, y in zip(xs, ys):
        xf, yf = float(x), float(y)
        out.append(box(xf - half, yf - half, xf + half, yf + half))
    return out


def _clip_mask(
    gdf: gpd.GeoDataFrame,
    boundary: str | None,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoSeries:
    """True = Zellmittelpunkt liegt innerhalb der gewählten Auswahl (in CRS von gdf)."""
    if boundary:
        b = gpd.read_file(boundary)
        if b.crs is None:
            b = b.set_crs("EPSG:4326")
        b = b.to_crs(gdf.crs)
        geom = unary_union(b.geometry.values)
        return gdf.geometry.within(geom)

    min_lon, min_lat, max_lon, max_lat = bbox_wgs84
    bbox_poly = box(min_lon, min_lat, max_lon, max_lat)
    bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_poly], crs="EPSG:4326").to_crs(gdf.crs)
    return gdf.geometry.within(bbox_gdf.geometry.iloc[0])


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Zensus-Gitter-CSV → GPKG (Quadrat-Polygone um Zellmittelpunkte), räumlich gefiltert",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--input-dir",
        default=SCRIPT_DIR,
        help="Ordner mit CSV-Dateien (Standard: gleicher Ordner wie dieses Skript)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: zensus_baualter.gpkg im selben Ordner wie das Skript)",
    )
    ap.add_argument(
        "--crs",
        default="EPSG:3035",
        help="CRS der X/Y-Spalten (Destatis-Gitter meist EPSG:3035; Standard: EPSG:3035)",
    )
    ap.add_argument(
        "--cell-size-m",
        type=float,
        default=100.0,
        metavar="METER",
        help="Kantenlänge der Quadrate um jeden Mittelpunkt in CRS-Einheiten (Standard: 100 = 100 m bei EPSG:3035)",
    )
    ap.add_argument("--id-col", default=None, help="Spalte Gitter-ID (Standard: 1. Spalte)")
    ap.add_argument("--x-col", default=None, help="Spalte X Mittelpunkt (Standard: 2. Spalte)")
    ap.add_argument("--y-col", default=None, help="Spalte Y Mittelpunkt (Standard: 3. Spalte)")
    ap.add_argument("--sep", default=None, help="CSV-Trennzeichen (Standard: automatisch ; ,)")
    ap.add_argument("--encoding", default="utf-8-sig", help="Dateikodierung (Standard: utf-8-sig)")
    ap.add_argument(
        "--boundary",
        default=None,
        help="Polygon (GPKG/GeoJSON/SHP …) für räumliche Begrenzung statt Rechteck",
    )
    ap.add_argument(
        "--bbox",
        nargs=4,
        type=float,
        metavar=("MIN_LON", "MIN_LAT", "MAX_LON", "MAX_LAT"),
        default=None,
        help="WGS84-Rechteck: min_lon min_lat max_lon max_lat (statt Standard-Box / statt --boundary)",
    )
    ap.add_argument("--layer", default="zensus_gitter", help="Layer-Name in der GPKG (Standard: zensus_gitter)")
    args = ap.parse_args()

    in_dir = os.path.abspath(args.input_dir)
    if not os.path.isdir(in_dir):
        print(f"Ordner nicht gefunden: {in_dir}", file=sys.stderr)
        return 1

    paths = sorted(glob.glob(os.path.join(in_dir, "*.csv")))
    if not paths:
        print(f"Keine *.csv in {in_dir}", file=sys.stderr)
        return 1

    frames: list[pd.DataFrame] = []
    for p in paths:
        print(f"Lese {p} …", file=sys.stderr)
        frames.append(_read_csv_flexible(p, args.encoding, args.sep))

    df = pd.concat(frames, ignore_index=True)

    try:
        id_c, x_c, y_c = _pick_columns(df, args.id_col, args.x_col, args.y_col)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1

    xs = _to_float_series(df[x_c])
    ys = _to_float_series(df[y_c])
    valid = xs.notna() & ys.notna()
    n_drop = int((~valid).sum())
    if n_drop:
        print(f"Hinweis: {n_drop} Zeilen ohne gültige Koordinaten verworfen.", file=sys.stderr)
    df = df.loc[valid].copy()
    xs = xs.loc[valid]
    ys = ys.loc[valid]

    if args.cell_size_m <= 0:
        print("--cell-size-m muss positiv sein.", file=sys.stderr)
        return 1

    # Filter über Mittelpunkte (Punkte), danach Quadrat-Polygone für Ausgabe
    geometry_pts = [Point(float(x), float(y)) for x, y in zip(xs, ys)]
    gdf = gpd.GeoDataFrame(df, geometry=geometry_pts, crs=args.crs)

    try:
        crs_obj = gdf.crs
        if crs_obj is not None and getattr(crs_obj, "is_geographic", False):
            print(
                "Hinweis: CRS ist geografisch (Grad). --cell-size-m gilt dann in Grad, nicht in Metern — "
                "für 100 m-Kanten typischerweise --crs EPSG:3035 nutzen.",
                file=sys.stderr,
            )
    except Exception:
        pass

    bbox = tuple(args.bbox) if args.bbox else DEFAULT_BBOX_WGS84
    mask = _clip_mask(gdf, args.boundary, bbox)
    n_vor = len(gdf)
    gdf = gdf.loc[mask].copy()
    n_nach = len(gdf)
    print(f"Räumlicher Filter (Zentren): {n_vor} → {n_nach} Gitterzellen", file=sys.stderr)

    if gdf.empty:
        print("Keine Zellen in der gewählten Region — CRS, --bbox oder --boundary prüfen.", file=sys.stderr)
        return 1

    xc = _to_float_series(gdf[x_c])
    yc = _to_float_series(gdf[y_c])
    gdf.geometry = _squares_around_centers(xc, yc, args.cell_size_m)
    print(
        f"Geometrie: Quadrate {args.cell_size_m:g}×{args.cell_size_m:g} (CRS-Einheiten), {len(gdf)} Polygone",
        file=sys.stderr,
    )

    out = args.output or os.path.join(SCRIPT_DIR, "zensus_baualter.gpkg")
    _ensure_parent(out)
    gdf.to_file(out, driver="GPKG", layer=args.layer)
    print(f"Geschrieben: {out} (Layer: {args.layer})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
