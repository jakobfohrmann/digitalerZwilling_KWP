#!/usr/bin/env python3
"""
ETL-Schritt 1: Räumlicher Abgleich GeoPackage (Gebäude-Polygone) mit LOD1 CityGML.

Standard: LEFT JOIN — alle GPKG-Zeilen bleiben erhalten; GML-Attribute werden
per größter Schnittfläche (intersects) ergänzt, wo ein LOD1-Fußabdruck passt.

Eingabe-GPKG ohne ``--gpkg``: zuerst ``input/gpkg_filtered/``, dann
``input/grundkarte_liegenschaftskataster/gpkg_filtered/``, sonst ``input/gpkg_raw/``.

Fußabdruck GML: horizontale Ringfläche mit min. Z in lod1Solid (wie zuvor).

CityGML-Attribute: bldg-Kinder von bldg:Building bzw. Generics (int/doubleAttribute).
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import xml.etree.ElementTree as ET

import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
from shapely.validation import make_valid

BLDG = "{http://www.opengis.net/citygml/building/1.0}"
GML = "{http://www.opengis.net/gml}"
GEN = "{http://www.opengis.net/citygml/generics/1.0}"
DEFAULT_CRS = "EPSG:25833"

GML_ATTR_PREFIX = "lod1_"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _bldg_text(elem: ET.Element, local: str) -> str | None:
    el = elem.find(f"{BLDG}{local}")
    if el is None:
        el = elem.find(f".//{BLDG}{local}")
    return (el.text or "").strip() if el is not None else None


def _gen_attribute_named(elem: ET.Element, name: str) -> str | None:
    """Erstes gen:intAttribute oder gen:doubleAttribute [@name] mit gen:value."""
    int_t = f"{GEN}intAttribute"
    dbl_t = f"{GEN}doubleAttribute"
    for node in elem.iter():
        if node.tag not in (int_t, dbl_t):
            continue
        if node.get("name") != name:
            continue
        v_el = node.find(f"{GEN}value")
        if v_el is not None and (v_el.text or "").strip():
            return (v_el.text or "").strip()
    return None


def _ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _list_gml_paths(gml_args: list[str]) -> list[str]:
    """Ohne Positionsargumente: alle *.gml direkt unter input/lod1/."""
    if gml_args:
        out: list[str] = []
        for p in gml_args:
            ap = os.path.abspath(p)
            if os.path.isfile(ap):
                out.append(ap)
            else:
                print(f"GML nicht gefunden, übersprungen: {p}", file=sys.stderr)
        return out
    cands = sorted(glob.glob(os.path.join(SCRIPT_DIR, "input", "lod1", "*.gml")))
    return cands


def _resolve_gpkg_path(explicit: str | None) -> str | None:
    """
    Bevorzugt gefilterte GPKG:
    1) input/gpkg_filtered/
    2) input/grundkarte_liegenschaftskataster/gpkg_filtered/
    Sonst: input/gpkg_raw/
    """
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    filtered_dirs = [
        os.path.join(SCRIPT_DIR, "input", "gpkg_filtered"),
        os.path.join(SCRIPT_DIR, "input", "grundkarte_liegenschaftskataster", "gpkg_filtered"),
    ]
    raw_dir = os.path.join(SCRIPT_DIR, "input", "gpkg_raw")
    for filtered_dir in filtered_dirs:
        cands = sorted(glob.glob(os.path.join(filtered_dir, "*.gpkg")))
        if len(cands) > 1:
            rel = os.path.relpath(filtered_dir, SCRIPT_DIR)
            print(
                f"Mehrere GPKG in {rel}/ — verwende: {cands[0]} (oder --gpkg setzen).",
                file=sys.stderr,
            )
        if cands:
            return cands[0]
    cands = sorted(glob.glob(os.path.join(raw_dir, "*.gpkg")))
    if len(cands) > 1:
        print(
            f"Mehrere GPKG in input/gpkg_raw/ — verwende: {cands[0]} (oder --gpkg setzen).",
            file=sys.stderr,
        )
    return cands[0] if cands else None


def _default_gpkg_output_path(gpkg_input_path: str) -> str:
    stem = os.path.splitext(os.path.basename(gpkg_input_path))[0]
    return os.path.join(SCRIPT_DIR, "output", "output_step1", f"{stem}_schritt1.gpkg")


def parse_poslist_ring(text: str) -> list[tuple[float, float, float]]:
    nums = [float(x) for x in text.split()]
    if len(nums) % 3 != 0:
        return []
    return [(nums[i], nums[i + 1], nums[i + 2]) for i in range(0, len(nums), 3)]


def footprint_polygon_from_lod1(lod1_el: ET.Element) -> Polygon | None:
    rings: list[list[tuple[float, float, float]]] = []
    for pl in lod1_el.iter():
        if pl.tag != f"{GML}posList" or not (pl.text and pl.text.strip()):
            continue
        ring = parse_poslist_ring(pl.text.strip())
        if len(ring) < 3:
            continue
        rings.append(ring)

    if not rings:
        return None

    z_min = min(p[2] for ring in rings for p in ring)
    tol = 1e-3
    candidates: list[list[tuple[float, float]]] = []
    for ring in rings:
        zs = [p[2] for p in ring]
        if not zs:
            continue
        if max(abs(z - z_min) for z in zs) > tol:
            continue
        xy = [(p[0], p[1]) for p in ring]
        if len(xy) >= 2 and xy[0] == xy[-1]:
            xy = xy[:-1]
        if len(xy) < 3:
            continue
        candidates.append(xy)

    if not candidates:
        return None

    def ring_area(xy: list[tuple[float, float]]) -> float:
        try:
            return Polygon(xy).area
        except Exception:
            return 0.0

    best_xy = max(candidates, key=ring_area)
    try:
        poly = Polygon(best_xy)
        if not poly.is_valid:
            poly = make_valid(poly)
        if poly.geom_type == "Polygon":
            return poly
        if poly.geom_type == "MultiPolygon":
            return max(poly.geoms, key=lambda p: p.area)
    except Exception:
        return None
    return None


def lod1_element_for_building(building_el: ET.Element) -> ET.Element | None:
    el = building_el.find(f"{BLDG}lod1Solid")
    if el is not None:
        return el
    return building_el.find(f".//{BLDG}lod1Solid")


def iter_gml_footprints_and_attrs(path: str):
    """Pro Building: Fußabdruck + Attribute aus CityGML."""
    for _event, elem in ET.iterparse(path, events=("end",)):
        if elem.tag != f"{BLDG}Building":
            continue
        gml_id = elem.get(f"{GML}id")
        height = _bldg_text(elem, "measuredHeight")
        roof_type = _bldg_text(elem, "roofType")
        qual_dach = _gen_attribute_named(elem, "QualitaetDacherkennung")
        dach_neig = _gen_attribute_named(elem, "Dachneigung")

        lod1 = lod1_element_for_building(elem)
        foot = footprint_polygon_from_lod1(lod1) if lod1 is not None else None

        yield gml_id, height, roof_type, qual_dach, dach_neig, foot
        elem.clear()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="GPKG (links) mit LOD1-GML per Geometrie verknüpfen (Standard: LEFT JOIN); Hauptausgabe GPKG."
    )
    ap.add_argument(
        "gml",
        nargs="*",
        default=[],
        help="LOD1-GML-Dateien (optional; Standard: alle *.gml unter input/lod1/)",
    )
    ap.add_argument(
        "--gpkg",
        default=None,
        help="Pfad zur Eingabe-GPKG (Standard: erste *.gpkg in input/gpkg_filtered/, sonst "
        "input/grundkarte_liegenschaftskataster/gpkg_filtered/, sonst input/gpkg_raw/)",
    )
    ap.add_argument("--gpkg-layer", default=None, help="Layer-Name der Eingabe-GPKG (optional)")
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: output/output_step1/<EingabeGPKG-Name>_schritt1.gpkg)",
    )
    ap.add_argument(
        "--csv",
        nargs="?",
        const="__AUTO__",
        default=None,
        metavar="PFAD",
        help="Optional CSV schreiben; ohne Pfad: gleicher Basisname wie die GPKG-Ausgabe (.csv)",
    )
    ap.add_argument(
        "--no-gpkg",
        action="store_true",
        help="Kein GPKG schreiben (nur sinnvoll mit --csv)",
    )
    ap.add_argument(
        "--gpkg-layer-out",
        default="lod1_join",
        help="Layer-Name in der Ausgabe-GPKG (Standard: lod1_join)",
    )
    ap.add_argument("--crs", default=DEFAULT_CRS, help=f"CRS GML (Standard: {DEFAULT_CRS})")
    ap.add_argument(
        "--join",
        choices=("left", "inner"),
        default="left",
        help="left = alle GPKG-Zeilen (Standard); inner = nur mit GML-Treffer",
    )
    args = ap.parse_args()

    gml_paths = _list_gml_paths(args.gml)
    if not gml_paths:
        print(
            "Keine GML: Dateien als Argument angeben oder *.gml unter input/lod1/ ablegen.",
            file=sys.stderr,
        )
        return 1

    gpkg_path = _resolve_gpkg_path(args.gpkg)
    if not gpkg_path:
        print(
            "Keine Eingabe-GPKG: --gpkg angeben oder eine *.gpkg unter input/gpkg_filtered/, "
            "input/grundkarte_liegenschaftskataster/gpkg_filtered/ oder input/gpkg_raw/.",
            file=sys.stderr,
        )
        return 1

    gpkg_out = args.output or _default_gpkg_output_path(gpkg_path)
    if args.no_gpkg and args.csv is None:
        print("Mit --no-gpkg bitte --csv angeben, sonst keine Ausgabe.", file=sys.stderr)
        return 1

    print(f"Eingabe-GPKG: {gpkg_path}", file=sys.stderr)
    for p in gml_paths:
        print(f"LOD1-GML: {p}", file=sys.stderr)

    rows: list[tuple] = []
    for path in gml_paths:
        rows.extend(iter_gml_footprints_and_attrs(path))
    if not rows:
        print("Keine Gebäude in den GML-Dateien.", file=sys.stderr)
        return 1

    cols = (
        "gml_id",
        "measuredHeight_m",
        "roofType",
        "QualitaetDacherkennung",
        "Dachneigung",
        "geometry",
    )
    data = {c: [] for c in cols}
    for row in rows:
        for i, c in enumerate(cols):
            data[c].append(row[i])

    gml_gdf = gpd.GeoDataFrame(data, crs=args.crs)
    gml_gdf = gml_gdf.rename(
        columns={c: f"{GML_ATTR_PREFIX}{c}" for c in cols if c != "geometry"}
    )
    gml_gdf = gml_gdf[gml_gdf.geometry.notna()].copy()

    layer = args.gpkg_layer
    if not layer:
        raw = gpd.list_layers(gpkg_path).name.values
        layers = [n for n in raw if not str(n).startswith(("gpkg_", "rtree_"))]
        layer = layers[0] if len(layers) else None
    bldg = gpd.read_file(gpkg_path, layer=layer)
    if bldg.crs is None:
        bldg.set_crs(args.crs, inplace=True)
    else:
        gml_gdf = gml_gdf.to_crs(bldg.crs)

    bldg = bldg.reset_index(drop=True)
    bldg["_gpkg_row"] = range(len(bldg))
    gml_gdf = gml_gdf.reset_index(drop=True)

    joined = gpd.sjoin(
        bldg,
        gml_gdf,
        how=args.join,
        predicate="intersects",
    )

    if args.join == "inner" and joined.empty:
        print("Keine Überschneidungen (inner join leer).", file=sys.stderr)
        return 1

    areas: list[float] = []
    for idx, row in joined.iterrows():
        if pd.isna(row.get("index_right")):
            areas.append(float("nan"))
            continue
        gr = int(row["index_right"])
        g0 = bldg.geometry.iloc[int(row["_gpkg_row"])]
        g1 = gml_gdf.geometry.iloc[gr]
        try:
            areas.append(g0.intersection(g1).area)
        except Exception:
            areas.append(float("nan"))
    joined = joined.assign(_ia=areas)

    ia_col = f"{GML_ATTR_PREFIX}intersection_area_m2"
    joined = joined.rename(columns={"_ia": ia_col})
    best = joined.sort_values(ia_col, ascending=False, na_position="last").drop_duplicates(
        subset=["_gpkg_row"],
        keep="first",
    )

    join_cols_drop = [
        c for c in ("index_right", "index_left", "_gpkg_row") if c in best.columns
    ]
    gpkg_gdf = best.drop(columns=join_cols_drop, errors="ignore").copy()
    for c in list(gpkg_gdf.columns):
        if c.startswith("geometry_") and c != "geometry":
            gpkg_gdf = gpkg_gdf.drop(columns=[c], errors="ignore")
    if not isinstance(gpkg_gdf, gpd.GeoDataFrame):
        gpkg_gdf = gpd.GeoDataFrame(gpkg_gdf, geometry="geometry", crs=bldg.crs)
    else:
        gpkg_gdf.set_crs(bldg.crs, allow_override=True, inplace=True)

    sort_key = next((c for c in ("fid", "id") if c in gpkg_gdf.columns), None)
    if sort_key:
        gpkg_gdf = gpkg_gdf.sort_values(sort_key, kind="mergesort")

    out_tabular = gpkg_gdf.drop(columns=["geometry"], errors="ignore")

    if not args.no_gpkg:
        _ensure_parent_dir(gpkg_out)
        gpkg_gdf.to_file(gpkg_out, driver="GPKG", layer=args.gpkg_layer_out)

    csv_path: str | None = None
    if args.csv is not None:
        csv_path = (
            os.path.splitext(gpkg_out)[0] + ".csv"
            if args.csv == "__AUTO__"
            else args.csv
        )
        _ensure_parent_dir(csv_path)
        out_tabular.to_csv(csv_path, index=False, encoding="utf-8")

    n_gpkg = len(bldg)
    n_hit = int(gpkg_gdf[ia_col].notna().sum()) if ia_col in gpkg_gdf.columns else 0
    print(
        f"GPKG-Zeilen: {n_gpkg} | mit LOD1-Treffer: {n_hit} | ohne Treffer: {n_gpkg - n_hit}",
        file=sys.stderr,
    )
    if not args.no_gpkg:
        print(f"Ausgabe-GPKG: {gpkg_out} (Layer: {args.gpkg_layer_out})", file=sys.stderr)
    if csv_path:
        print(f"CSV: {csv_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
