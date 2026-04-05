#!/usr/bin/env python3
"""
ETL-Schritt 2: Filtert ein Gebäude-GeoPackage nach Gebäudefunktionskatalog (GFK), Spalte typischerweise „GFK“.

Standard (ohne --codes / --prefix): Wohngebäude gemäß ALKIS-ähnlicher Kodierung
(31001_1000 reines Wohngebäude, 31001_1100 Wohngebäude mit sonstiger Nutzung).
Abweichungen je Datenstand möglich — mit --codes anpassen.

Beispiele:
  python etl_schritt2_filter_gebaeudefunktion.py output/output_step1/gebaeude_leipzig_schritt1.gpkg
  python etl_schritt2_filter_gebaeudefunktion.py --codes 31001_1000 31001_2000 -o output/output_step2/custom.gpkg
  python etl_schritt2_filter_gebaeudefunktion.py eingabe.gpkg --prefix 31001_30
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import geopandas as gpd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ALKIS/SN üblich: reines Wohngebäude + Wohngebäude mit sonstiger Nutzung (Anpassung mit --codes)
DEFAULT_WOHNGEBAEUDE_GFK: tuple[str, ...] = ("31001_1000", "31001_1100")


def _normalize_code_tokens(raw: list[str]) -> list[str]:
    out: list[str] = []
    for part in raw:
        for token in re.split(r"[\s,;]+", part.strip()):
            if token:
                out.append(token)
    return out


def _resolve_input_gpkg(path_arg: str | None) -> str | None:
    if path_arg:
        return path_arg if os.path.isfile(path_arg) else None
    step1 = os.path.join(SCRIPT_DIR, "output", "output_step1", "*_schritt1.gpkg")
    cands = sorted(glob.glob(step1))
    if not cands:
        cands = sorted(glob.glob(os.path.join(SCRIPT_DIR, "output", "output_step1", "*.gpkg")))
    if len(cands) > 1:
        print(
            f"Mehrere GPKG in output/output_step1/ — verwende: {cands[0]} (oder Eingabepfad angeben).",
            file=sys.stderr,
        )
    return cands[0] if cands else None


def _base_stem_from_step1_file(stem: str) -> str:
    """z. B. gebaeude_leipzig_schritt1 -> gebaeude_leipzig (Legacy: _mit_Lod1)."""
    for suf in ("_schritt1", "_mit_Lod1"):
        if stem.endswith(suf):
            return stem[: -len(suf)]
    return stem


def _default_output_path(input_path: str) -> str:
    stem = Path(input_path).stem
    base = _base_stem_from_step1_file(stem)
    return os.path.join(SCRIPT_DIR, "output", "output_step2", f"{base}_schritt2.gpkg")


def _pick_layer(gpkg_path: str, layer: str | None) -> str | None:
    if layer:
        return layer
    raw = gpd.list_layers(gpkg_path).name.values
    layers = [n for n in raw if not str(n).startswith(("gpkg_", "rtree_"))]
    return layers[0] if layers else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description="GeoPackage nach GFK (Gebäudefunktion) filtern",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "input_gpkg",
        nargs="?",
        default=None,
        help="Eingabe-GPKG (Standard: erste *.gpkg unter output/output_step1/)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: output/output_step2/<Basis>_schritt2.gpkg)",
    )
    ap.add_argument(
        "--column",
        default="GFK",
        metavar="NAME",
        help='Attributspalte mit dem GFK-Code (Standard: "GFK")',
    )
    ap.add_argument(
        "--codes",
        nargs="+",
        metavar="CODE",
        default=None,
        help="Exakte GFK-Werte (überschreibt das Wohngebäude-Standardset)",
    )
    ap.add_argument(
        "--prefix",
        action="append",
        default=None,
        metavar="PRÄFIX",
        help="GFK beginnt mit diesem Präfix (mehrfach möglich); Alternative zu --codes",
    )
    ap.add_argument("--layer", default=None, help="Layer-Name; Standard: erster sinnvoller Layer")
    ap.add_argument(
        "--layer-out",
        default=None,
        help="Layer-Name in der Ausgabe-GPKG (Standard: wie Eingabe-Layer)",
    )
    args = ap.parse_args()

    if args.codes and args.prefix:
        print("Bitte entweder --codes oder --prefix verwenden, nicht beides.", file=sys.stderr)
        return 1

    in_path = _resolve_input_gpkg(args.input_gpkg)
    if not in_path:
        print(
            "Keine Eingabe-GPKG: Pfad angeben oder eine *.gpkg unter output/output_step1/ ablegen.",
            file=sys.stderr,
        )
        return 1

    layer_in = _pick_layer(in_path, args.layer)
    if not layer_in:
        print("Kein lesbarer Layer in der GPKG.", file=sys.stderr)
        return 1

    gdf = gpd.read_file(in_path, layer=layer_in)
    if args.column not in gdf.columns:
        print(
            f'Spalte "{args.column}" nicht gefunden. Vorhanden: {list(gdf.columns)}',
            file=sys.stderr,
        )
        return 1

    s = gdf[args.column].astype(str).str.strip()

    if args.prefix:
        sel = s.str.startswith(args.prefix[0], na=False)
        for p in args.prefix[1:]:
            sel = sel | s.str.startswith(p, na=False)
    elif args.codes:
        values = set(_normalize_code_tokens(args.codes))
        sel = s.isin(values)
    else:
        values = set(DEFAULT_WOHNGEBAEUDE_GFK)
        sel = s.isin(values)

    filtered = gdf[sel].copy()
    if filtered.empty:
        print("Keine Zeilen nach GFK-Filter — Auswahl prüfen (--codes / --prefix).", file=sys.stderr)
        return 1

    out_path = args.output or _default_output_path(in_path)
    layer_out = args.layer_out or layer_in
    _ensure = os.path.dirname(os.path.abspath(out_path))
    if _ensure:
        os.makedirs(_ensure, exist_ok=True)

    filtered.to_file(out_path, driver="GPKG", layer=layer_out)

    n_in, n_out = len(gdf), len(filtered)
    print(
        f"GFK-Filter: {n_in} → {n_out} Gebäude | {out_path} (Layer: {layer_out})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
