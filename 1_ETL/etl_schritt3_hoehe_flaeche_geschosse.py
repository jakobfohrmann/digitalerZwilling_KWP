#!/usr/bin/env python3
"""
ETL-Schritt 3: Schätzt Dachhöhe und Traufhöhe aus LOD1-Attributen und Gebäudefußabdruck.

Annahmen (vereinfachtes Satteldach-Modell, EPSG:25833 = Meter):
- lod1_measuredHeight_m = Höhe bis zur First / Gebäudemaximum (typisch LOD1).
- lod1_Dachneigung = Neigungswinkel in Grad.
- Kürzere Seite des minimum rotated bounding rectangle = Traufbreite; First parallel zur längeren Seite.
  Dachhöhe (First über Traufe) = (Traufbreite/2) * tan(α).
- trauf_hoehe_m = measuredHeight_m - dach_hoehe_m.
- Klassifikation **zuerst** über numerischen ``lod1_roofType``-Code (wenn parsebar): 1000 = Flachdach → dach_hoehe_m = 0, trauf_hoehe_m = Höhe (Neigung wird ignoriert).
- Anderer bekannter Code (≠ 1000) → geneigtes Dachmodell aus Neigung + MBR (der Code hat Vorrang vor Neigungs-Heuristik).
- Ohne parsebaren ``lod1_roofType``-Code: nur noch Neigung < 0,5° als Flachdach-Näherung → dach_hoehe_m = 0, trauf_hoehe_m = Höhe; sonst Satteldach-Formel.
- anzahl_geschosse — geschätzte **Anzahl oberirdischer Geschosse** aus ``trauf_hoehe_m`` (Annahme ~3 m Geschosshöhe: ``round(trauf/3)``, mindestens 1 bei trauf > 0).
- bezugsflaeche = **georeferenzierte Fußabdruckfläche** (größtes Polygon, m²) × **anzahl_geschosse** × 0.85 (Kenngröße für Folge-Rechnungen).

Ausgabe: output/output_step3/<Basis>_schritt3.gpkg

Beispiele:
  python etl_schritt3_hoehe_flaeche_geschosse.py
  python etl_schritt3_hoehe_flaeche_geschosse.py output/output_step2/gebaeude_leipzig_schritt2.gpkg
"""

from __future__ import annotations

import argparse
import glob
import math
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry.base import BaseGeometry

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

COL_H = "lod1_measuredHeight_m"
COL_RT = "lod1_roofType"
COL_DN = "lod1_Dachneigung"
COL_BEZUGS = "bezugsflaeche"
COL_ANZAHL_GESCHOSSE = "anzahl_geschosse"
# AdV/ALKIS u. ä.: 1000 = Flachdach (vgl. lod1_roofType)
ROOFTYPE_FLACHDACH = 1000
# Dachhöhen-Plausibilisierung
MAX_DACHHOEHE_M = 10.0
MAX_DACHANTEIL = 1.0 / 3.0
# Schätzung der Geschosszahl aus Traufhöhe
GESCHOSS_HOEHE_ANNAHME_M = 3.0


def _ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _base_stem_from_step2(stem: str) -> str:
    if stem.endswith("_schritt2"):
        return stem[: -len("_schritt2")]
    return stem


def _resolve_input_gpkg(path_arg: str | None) -> str | None:
    if path_arg:
        return path_arg if os.path.isfile(path_arg) else None
    step2 = os.path.join(SCRIPT_DIR, "output", "output_step2", "*_schritt2.gpkg")
    cands = sorted(glob.glob(step2))
    if not cands:
        fallback = os.path.join(SCRIPT_DIR, "output", "output_step2", "*.gpkg")
        cands = sorted(glob.glob(fallback))
    if len(cands) > 1:
        print(
            f"Mehrere GPKG in output/output_step2/ — verwende: {cands[0]} (oder Eingabepfad angeben).",
            file=sys.stderr,
        )
    return cands[0] if cands else None


def _default_output_path(input_path: str) -> str:
    stem = Path(input_path).stem
    base = _base_stem_from_step2(stem)
    return os.path.join(SCRIPT_DIR, "output", "output_step3", f"{base}_schritt3.gpkg")


def _parse_float_maybe(val) -> float | None:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return None
    if isinstance(val, (int, float)):
        return float(val)
    t = str(val).strip().replace(",", ".")
    if not t or t.lower() in ("nan", "none", ""):
        return None
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", t)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def _parse_roof_type_code(rt) -> int | None:
    """Numerischen Dachform-Code aus lod1_roofType; bei reinem Text ohne führende Zahl None."""
    if rt is None or (isinstance(rt, float) and pd.isna(rt)):
        return None
    if isinstance(rt, bool):
        return None
    if isinstance(rt, (int, float)):
        try:
            return int(rt)
        except (ValueError, OverflowError):
            return None
    t = str(rt).strip()
    m = re.match(r"^[-+]?\d+", t)
    if not m:
        return None
    try:
        return int(m.group())
    except ValueError:
        return None


def _flat_roof_fallback_no_code(alpha_deg: float | None) -> bool:
    """Nur wenn kein numerischer roofType-Code: sehr kleine Neigung wie praktisch flach."""
    return alpha_deg is not None and alpha_deg < 0.5


def _largest_polygon(geom: BaseGeometry) -> BaseGeometry:
    if geom is None or geom.is_empty:
        return geom
    if geom.geom_type == "MultiPolygon":
        return max(geom.geoms, key=lambda g: g.area)
    return geom


def _mbr_short_side_m(geom: BaseGeometry) -> float:
    """Kürzere Kantenlänge des minimum rotated rectangle (Meter)."""
    g = _largest_polygon(geom)
    if g is None or g.is_empty:
        return float("nan")
    try:
        mrr = g.minimum_rotated_rectangle
    except Exception:
        return float("nan")
    coords = list(mrr.exterior.coords)
    if len(coords) < 4:
        return float("nan")
    dists: list[float] = []
    for i in range(4):
        ax, ay = coords[i]
        bx, by = coords[i + 1]
        dists.append(math.hypot(bx - ax, by - ay))
    return min(dists) if dists else float("nan")


def _pitched_dach_trauf(
    geom: BaseGeometry, h_m: float, alpha_deg: float
) -> tuple[float | None, float | None]:
    """Satteldach-Näherung: Dachhöhe aus Traufbreite (MBR) und Neigungswinkel."""
    W = _mbr_short_side_m(geom)
    if W is None or (isinstance(W, float) and (math.isnan(W) or W <= 0)):
        return None, None
    rad = math.radians(alpha_deg)
    dach = (W / 2.0) * math.tan(rad)
    trauf = float(h_m) - dach
    return dach, trauf


def _is_null_roof_type(rt) -> bool:
    return rt is None or pd.isna(rt)


def _apply_dach_plausibility(
    dach: float | None, trauf: float | None, gesamt_hoehe: float
) -> tuple[float | None, float | None]:
    if dach is None or (isinstance(dach, float) and math.isnan(dach)):
        return dach, trauf
    if dach > MAX_DACHHOEHE_M or dach > (gesamt_hoehe * MAX_DACHANTEIL):
        return 0.0, float(gesamt_hoehe)
    return dach, trauf


def _row_dach_trauf(geom: BaseGeometry, h_m: float | None, rt, dn_raw) -> tuple[float | None, float | None]:
    """Rückgabe (dach_hoehe_m, trauf_hoehe_m). Zuerst lod1_roofType-Code, sonst Heuristik."""
    if h_m is None or (isinstance(h_m, float) and math.isnan(h_m)):
        return None, None

    hf = float(h_m)
    if _is_null_roof_type(rt):
        return 0.0, hf

    code = _parse_roof_type_code(rt)
    if code == ROOFTYPE_FLACHDACH:
        return 0.0, hf

    alpha = _parse_float_maybe(dn_raw)

    if code is not None:
        if alpha is None:
            return None, None
        dach, trauf = _pitched_dach_trauf(geom, hf, alpha)
        return _apply_dach_plausibility(dach, trauf, hf)

    if _flat_roof_fallback_no_code(alpha):
        return 0.0, hf

    if alpha is None:
        return None, None
    dach, trauf = _pitched_dach_trauf(geom, hf, alpha)
    return _apply_dach_plausibility(dach, trauf, hf)


def _pick_layer(gpkg_path: str, layer: str | None) -> str | None:
    if layer:
        return layer
    raw = gpd.list_layers(gpkg_path).name.values
    layers = [n for n in raw if not str(n).startswith(("gpkg_", "rtree_"))]
    return layers[0] if layers else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Dachhöhe / Traufhöhe aus LOD1 + Fußabdruck schätzen -> Schritt 3 GPKG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "input_gpkg",
        nargs="?",
        default=None,
        help="Eingabe-GPKG (Standard: erste *_schritt2.gpkg unter output/output_step2/)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: output/output_step3/<Basis>_schritt3.gpkg)",
    )
    ap.add_argument("--layer", default=None, help="Layer-Name; Standard: erster sinnvoller Layer")
    ap.add_argument(
        "--layer-out",
        default=None,
        help="Layer-Name in der Ausgabe-GPKG (Standard: wie Eingabe-Layer)",
    )
    args = ap.parse_args()

    in_path = _resolve_input_gpkg(args.input_gpkg)
    if not in_path:
        print(
            "Keine Eingabe-GPKG: Pfad angeben oder *_schritt2.gpkg unter output/output_step2/ ablegen.",
            file=sys.stderr,
        )
        return 1

    layer_in = _pick_layer(in_path, args.layer)
    if not layer_in:
        print("Kein lesbarer Layer in der GPKG.", file=sys.stderr)
        return 1

    gdf = gpd.read_file(in_path, layer=layer_in)
    for req in (COL_H, COL_DN):
        if req not in gdf.columns:
            print(
                f"Erwartete Spalte {req!r} fehlt. Vorhanden: {list(gdf.columns)}",
                file=sys.stderr,
            )
            return 1

    dach_list: list[float | None] = []
    trauf_list: list[float | None] = []
    anzahl_geschosse_list: list[float | None] = []
    bezugs_list: list[float | None] = []

    for _, row in gdf.iterrows():
        h = _parse_float_maybe(row.get(COL_H))
        rt = row.get(COL_RT) if COL_RT in gdf.columns else None
        dn = row.get(COL_DN)
        geom = row.geometry
        dach, trauf = _row_dach_trauf(geom, h, rt, dn)
        dach_list.append(dach)
        trauf_list.append(trauf)
        if trauf is None or (isinstance(trauf, float) and math.isnan(trauf)):
            anzahl_g = None
        else:
            tf = float(trauf)
            if tf > 0:
                # -1 Korrektur: Traufhöhe schließt Erdgeschoss ein, das im
                # Heizwärmebedarf-Modell als Keller/Sockel gilt (vgl. Scanergy-Vergleich)
                anzahl_g = max(1, int(round(tf / GESCHOSS_HOEHE_ANNAHME_M)) - 1)
            else:
                anzahl_g = 0
        anzahl_geschosse_list.append(float(anzahl_g) if anzahl_g is not None else float("nan"))

        g_fp = _largest_polygon(geom)
        if anzahl_g is not None and g_fp is not None and not g_fp.is_empty:
            bezugs_list.append(float(g_fp.area) * float(anzahl_g) * 0.85)
        else:
            bezugs_list.append(float("nan"))

    gdf = gdf.copy()
    gdf["dach_hoehe_m"] = dach_list
    gdf["trauf_hoehe_m"] = trauf_list
    gdf[COL_ANZAHL_GESCHOSSE] = anzahl_geschosse_list
    gdf[COL_BEZUGS] = bezugs_list

    out_path = args.output or _default_output_path(in_path)
    layer_out = args.layer_out or layer_in
    _ensure_parent_dir(out_path)

    gdf.to_file(out_path, driver="GPKG", layer=layer_out)

    n_ok = sum(
        1
        for t in trauf_list
        if t is not None and not (isinstance(t, float) and math.isnan(t))
    )
    print(
        f"Traufhöhe: {len(gdf)} Gebäude, {n_ok} mit geschätzter trauf_hoehe_m | {out_path} (Layer: {layer_out})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
