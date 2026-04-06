#!/usr/bin/env python3
"""
ETL-Schritt 4: Baujahr und Denkmalschutz aus Flächendenkmal (optional) und Zensus-Gitter (Baualtersklassen).

Datenquellen (Standardpfade relativ zum Projektroot):
- input/flaechendenkmal/*.gpkg — erstes GPKG alphabetisch; fehlt die Datei oder der Ordner ist leer → Flächendenkmal wird übersprungen
- input/zensus_baualtersklassen/ — bevorzugt zensus_baualter.gpkg, sonst erstes *.gpkg

Priorität: Flächendenkmal (ext_dat → Jahr, denkmalschutz), danach Zensus-Gitter-Häufigkeiten; verbleibende baujahr bleiben leer.

Eingabe: Standard erste *_schritt3.gpkg unter output/output_step3/
Ausgabe: Standard output/output_step4/<Basis>_schritt4.gpkg

Beispiele:
  python etl_schritt4_baujahr.py
  python etl_schritt4_baujahr.py output/output_step3/gebaeude_leipzig_schritt3.gpkg
  python etl_schritt4_baujahr.py --no-gitter
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

DIR_FLAECHENDENKMAL = os.path.join(SCRIPT_DIR, "input", "flaechendenkmal")
DIR_ZENSUS_BAUALT = os.path.join(SCRIPT_DIR, "input", "zensus_baualtersklassen")


def _list_gpkg_sorted(directory: str) -> list[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(glob.glob(os.path.join(directory, "*.gpkg")))


def resolve_flaechendenkmal_gpkg(directory: str | None = None) -> str | None:
    """Erstes *.gpkg im Ordner, oder None wenn Ordner fehlt/leer."""
    d = directory if directory is not None else DIR_FLAECHENDENKMAL
    files = _list_gpkg_sorted(d)
    return files[0] if files else None


def resolve_zensus_gitter_gpkg(directory: str | None = None) -> str | None:
    """Bevorzugt zensus_baualter.gpkg, sonst erstes *.gpkg im Ordner."""
    d = directory if directory is not None else DIR_ZENSUS_BAUALT
    preferred = os.path.join(d, "zensus_baualter.gpkg")
    if os.path.isfile(preferred):
        return preferred
    files = _list_gpkg_sorted(d)
    return files[0] if files else None


def _resolve_input_schritt3(path_arg: str | None) -> str | None:
    if path_arg:
        return path_arg if os.path.isfile(path_arg) else None
    step3 = os.path.join(SCRIPT_DIR, "output", "output_step3", "*_schritt3.gpkg")
    cands = sorted(glob.glob(step3))
    if not cands:
        cands = sorted(glob.glob(os.path.join(SCRIPT_DIR, "output", "output_step3", "*.gpkg")))
    if len(cands) > 1:
        print(
            f"Mehrere GPKG in output/output_step3/ — verwende: {cands[0]} (oder Eingabepfad angeben).",
            file=sys.stderr,
        )
    return cands[0] if cands else None


def _base_stem_from_step3(stem: str) -> str:
    if stem.endswith("_schritt3"):
        return stem[: -len("_schritt3")]
    return stem


def _default_output_path(input_path: str) -> str:
    stem = Path(input_path).stem
    base = _base_stem_from_step3(stem)
    return os.path.join(SCRIPT_DIR, "output", "output_step4", f"{base}_schritt4.gpkg")


def _ensure_parent_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _pick_layer(gpkg_path: str, layer: str | None) -> str | None:
    if layer:
        return layer
    raw = gpd.list_layers(gpkg_path).name.values
    layers = [n for n in raw if not str(n).startswith(("gpkg_", "rtree_"))]
    return layers[0] if layers else None


# Zensus-Baualtersklassen: zwei übliche Destatis-/CSV-Schemata (Spaltennamen müssen exakt passen)
_BAUJAHR_LEGACY_ORDER: tuple[str, ...] = (
    "Vor1919",
    "a1919bis1948",
    "a1949bis1978",
    "a1979bis1990",
    "a1991bis2000",
    "a2001bis2010",
    "a2011bis2019",
    "a2020undspaeter",
)
_BAUJAHR_LEGACY_MITTEL: dict[str, int] = {
    "Vor1919": 1900,
    "a1919bis1948": 1933,
    "a1949bis1978": 1963,
    "a1979bis1990": 1984,
    "a1991bis2000": 1995,
    "a2001bis2010": 2005,
    "a2011bis2019": 2015,
    "a2020undspaeter": 2022,
}

# 100-m-Gitter (feinere Klassen), typisch bei aktuellen CSV-Exporten
_BAUJAHR_DESTATIS100M_ORDER: tuple[str, ...] = (
    "Vor1919",
    "a1919bis1949",
    "a1950bis1959",
    "a1960bis1969",
    "a1970bis1979",
    "a1980bis1989",
    "a1990bis1999",
    "a2000bis2009",
    "a2010bis2015",
    "a2016undspaeter",
)
# Repräsentatives Baujahr je Zensus-Klasse (ganze Jahre; Mittel der Spanne gerundet)
_BAUJAHR_DESTATIS100M_MITTEL: dict[str, int] = {
    "Vor1919": 1900,
    "a1919bis1949": 1934,
    "a1950bis1959": 1955,
    "a1960bis1969": 1965,
    "a1970bis1979": 1975,
    "a1980bis1989": 1985,
    "a1990bis1999": 1995,
    "a2000bis2009": 2005,
    "a2010bis2015": 2013,
    "a2016undspaeter": 2020,
}


def _detect_baujahr_klassen_schema(
    columns: pd.Index,
) -> tuple[list[str], dict[str, int], str] | None:
    """
    Erkennt bekanntes Spalten-Schema für Baualters-Häufigkeiten.
    Returns (Spaltenliste in fester Reihenfolge, Mittelwerte je Klasse, Kurzname) oder None.
    """
    c = set(columns)
    if all(name in c for name in _BAUJAHR_DESTATIS100M_ORDER):
        return (
            list(_BAUJAHR_DESTATIS100M_ORDER),
            dict(_BAUJAHR_DESTATIS100M_MITTEL),
            "Destatis 100m-Gitter (10 Klassen)",
        )
    if all(name in c for name in _BAUJAHR_LEGACY_ORDER):
        return (
            list(_BAUJAHR_LEGACY_ORDER),
            dict(_BAUJAHR_LEGACY_MITTEL),
            "8 Baualtersklassen (Legacy)",
        )
    return None


def extract_year_from_text(text):
    """Extrahiert das Jahr aus einem Text wie 'vor 1930 (Mietshaus)' -> 1930. Nimmt den ersten gefundenen Wert."""
    if pd.isna(text) or text == "":
        return None

    text_str = str(text).strip()
    year_matches = re.findall(r"\b(1[89]\d{2}|20[0-2]\d)\b", text_str)
    if year_matches:
        try:
            year = int(year_matches[0])
            if 1800 <= year <= 2025:
                return year
        except (ValueError, IndexError):
            pass

    return None


def assign_baujahr_and_denkmalschutz(gdf_gebaeude, gdf_flaechen):
    """Weist Baujahr und Denkmalschutz basierend auf Flächendenkmal zu."""
    if "baujahr" not in gdf_gebaeude.columns:
        gdf_gebaeude["baujahr"] = np.nan
        print("Spalte 'baujahr' erstellt", file=sys.stderr)
    if "denkmalschutz" not in gdf_gebaeude.columns:
        gdf_gebaeude["denkmalschutz"] = False
        print("Spalte 'denkmalschutz' erstellt", file=sys.stderr)

    print("Extrahiere Jahre aus Flächendenkmal-Daten …", file=sys.stderr)
    gdf_flaechen = gdf_flaechen.copy()
    gdf_flaechen["extracted_year"] = gdf_flaechen["ext_dat"].apply(extract_year_from_text)

    print("Erstelle räumlichen Index …", file=sys.stderr)
    gdf_flaechen.sindex

    denkmal_count = 0

    print("Prüfe Gebäude gegen Flächendenkmal …", file=sys.stderr)
    for idx, gebaeude_row in gdf_gebaeude.iterrows():
        gebaeude_geom = gebaeude_row.geometry
        current_baujahr = gebaeude_row.get("baujahr")
        has_baujahr = pd.notna(current_baujahr)
        extracted_year = None

        possible_matches = list(gdf_flaechen.sindex.intersection(gebaeude_geom.bounds))

        for match_idx in possible_matches:
            flaeche_geom = gdf_flaechen.iloc[match_idx].geometry
            if gebaeude_geom.within(flaeche_geom) or gebaeude_geom.intersects(flaeche_geom):
                extracted_year = gdf_flaechen.iloc[match_idx]["extracted_year"]
                if extracted_year is not None:
                    gdf_gebaeude.loc[idx, "denkmalschutz"] = True
                    if not has_baujahr:
                        gdf_gebaeude.loc[idx, "baujahr"] = extracted_year
                        denkmal_count += 1
                    break

    print(
        f"{denkmal_count} Gebäude: Denkmal mit Baujahr aus Flächendenkmal",
        file=sys.stderr,
    )
    return gdf_gebaeude


def assign_baujahr_from_gitter(gdf_gebaeude, gpkg_gitter_path: str | None = None):
    """
    Weist Baujahr basierend auf Gitterzellen-Häufigkeiten zu (Zensus Baualtersklassen).
    """
    if gpkg_gitter_path is None:
        gpkg_gitter_path = resolve_zensus_gitter_gpkg()

    if "baujahr" not in gdf_gebaeude.columns:
        gdf_gebaeude["baujahr"] = np.nan
        print("Spalte 'baujahr' erstellt", file=sys.stderr)

    if not gpkg_gitter_path or not os.path.isfile(gpkg_gitter_path):
        print(
            f"Zensus-Gitter: keine Datei in {DIR_ZENSUS_BAUALT} — überspringe.",
            file=sys.stderr,
        )
        return gdf_gebaeude

    print(f"Lade Zensus-Gitter: {gpkg_gitter_path} …", file=sys.stderr)
    try:
        gdf_gitter = gpd.read_file(gpkg_gitter_path)
        print(f"{len(gdf_gitter)} Gitterzellen geladen", file=sys.stderr)
    except Exception as e:
        print(f"Fehler beim Einlesen der Gitter-Datei: {e}", file=sys.stderr)
        return gdf_gebaeude

    gdf_gebaeude_work = gdf_gebaeude.copy()
    if gdf_gebaeude_work.crs != gdf_gitter.crs:
        print(
            f"Konvertiere CRS: Gebäude {gdf_gebaeude_work.crs} -> Gitter {gdf_gitter.crs}",
            file=sys.stderr,
        )
        gdf_gebaeude_work = gdf_gebaeude_work.to_crs(gdf_gitter.crs)

    schema = _detect_baujahr_klassen_schema(gdf_gitter.columns)
    if schema is None:
        print(
            "Warnung: Kein bekanntes Baualtersklassen-Schema. Erwartet werden alle Spalten eines der beiden Sätze:\n"
            f"  • 100m-Gitter: {list(_BAUJAHR_DESTATIS100M_ORDER)}\n"
            f"  • Legacy: {list(_BAUJAHR_LEGACY_ORDER)}\n"
            f"Vorhandene Spalten: {list(gdf_gitter.columns)}",
            file=sys.stderr,
        )
        return gdf_gebaeude

    baujahr_spalten, baujahr_mittelwerte, schema_name = schema
    print(f"Zensus Baualtersklassen: {schema_name}", file=sys.stderr)

    if "Insgesamt_Gebaeude" not in gdf_gitter.columns:
        print(
            "Warnung: Spalte 'Insgesamt_Gebaeude' nicht gefunden in Gitter-Datei",
            file=sys.stderr,
        )
        return gdf_gebaeude

    for col in baujahr_spalten:
        if col in gdf_gitter.columns:
            gdf_gitter[col] = pd.to_numeric(gdf_gitter[col], errors="coerce").fillna(0)

    gdf_gitter["Insgesamt_Gebaeude"] = pd.to_numeric(
        gdf_gitter["Insgesamt_Gebaeude"], errors="coerce"
    ).fillna(0)

    print("Räumlicher Join Gebäude ↔ Gitter …", file=sys.stderr)
    gdf_joined = gpd.sjoin(
        gdf_gebaeude_work[["geometry", "baujahr"]],
        gdf_gitter[["geometry"] + baujahr_spalten + ["Insgesamt_Gebaeude"]],
        how="left",
        predicate="intersects",
    )

    gitter_count = 0
    gitter_eindeutig_count = 0
    gitter_mehrdeutig_count = 0
    keine_gitter_count = 0
    mehrfach_gitter_count = 0

    print("Weise Baujahre aus Gitter-Häufigkeiten zu …", file=sys.stderr)

    for idx in gdf_gebaeude.index:
        if pd.notna(gdf_gebaeude.loc[idx, "baujahr"]):
            continue

        joined_rows = gdf_joined[gdf_joined.index == idx]
        if len(joined_rows) == 0:
            keine_gitter_count += 1
            continue

        if len(joined_rows) > 1:
            mehrfach_gitter_count += 1
            gebaeude_geom = gdf_gebaeude_work.loc[idx, "geometry"]
            gebaeude_flaeche = gebaeude_geom.area
            max_overlap_ratio = 0
            best_gitter_idx = 0

            for i, gitter_row in joined_rows.iterrows():
                gitter_geom = gitter_row.geometry
                intersection = gebaeude_geom.intersection(gitter_geom)
                if intersection.is_empty:
                    overlap_ratio = 0
                else:
                    overlap_ratio = intersection.area / gebaeude_flaeche

                if overlap_ratio > max_overlap_ratio:
                    max_overlap_ratio = overlap_ratio
                    best_gitter_idx = i

            gitter_row = joined_rows.loc[best_gitter_idx]
            if isinstance(gitter_row, pd.Series):
                gitter_row = gitter_row.to_dict()
        else:
            gitter_row = joined_rows.iloc[0]
            if isinstance(gitter_row, pd.Series):
                gitter_row = gitter_row.to_dict()

        total_gebaeude = gitter_row["Insgesamt_Gebaeude"]
        if isinstance(total_gebaeude, pd.Series):
            total_gebaeude = total_gebaeude.iloc[0] if len(total_gebaeude) > 0 else np.nan
        try:
            total_gebaeude = float(total_gebaeude)
        except (ValueError, TypeError):
            total_gebaeude = np.nan

        if pd.isna(total_gebaeude) or total_gebaeude == 0:
            keine_gitter_count += 1
            continue

        probs = []
        klassen = []

        for klasse in baujahr_spalten:
            anzahl = gitter_row[klasse]
            if isinstance(anzahl, pd.Series):
                anzahl = anzahl.iloc[0] if len(anzahl) > 0 else 0
            try:
                anzahl = float(anzahl) if pd.notna(anzahl) else 0
            except (ValueError, TypeError):
                anzahl = 0
            if pd.notna(anzahl) and anzahl > 0:
                wahrscheinlichkeit = anzahl / total_gebaeude
                if wahrscheinlichkeit > 1:
                    wahrscheinlichkeit = 1
                probs.append(wahrscheinlichkeit)
                klassen.append(klasse)

        if len(klassen) == 0:
            keine_gitter_count += 1
            continue

        max_prob = max(probs)
        ist_eindeutig = max_prob == 1.0

        probs = np.array(probs)
        probs = probs / probs.sum()

        gewaehlte_klasse = np.random.choice(klassen, p=probs)
        baujahr = baujahr_mittelwerte[gewaehlte_klasse]
        gdf_gebaeude.loc[idx, "baujahr"] = baujahr
        gitter_count += 1

        if ist_eindeutig:
            gitter_eindeutig_count += 1
        else:
            gitter_mehrdeutig_count += 1

    print(
        f"{gitter_count} Gebäude: Baujahr aus Zensus-Gitter "
        f"({gitter_eindeutig_count} eindeutig, {gitter_mehrdeutig_count} mehrdeutig)",
        file=sys.stderr,
    )
    if mehrfach_gitter_count > 0:
        print(
            f"  {mehrfach_gitter_count} Gebäude in mehreren Gitterzellen (größte Überlappung)",
            file=sys.stderr,
        )
    if keine_gitter_count > 0:
        print(
            f"  {keine_gitter_count} Gebäude ohne Gitterzuordnung / leere Zelle",
            file=sys.stderr,
        )

    return gdf_gebaeude


def create_baujahr(
    gdf,
    gpkg_flaechen_path: str | None = None,
    gpkg_gitter_path: str | None = None,
    use_gitter: bool = True,
):
    """
    Priorität: Flächendenkmal, dann Gitter, verbleibend leer.

    gpkg_flaechen_path None: kein Flächendenkmal (Ordner leer oder nicht angegeben) — still übersprungen.
    """
    if "baujahr" not in gdf.columns:
        gdf["baujahr"] = np.nan
        print("Spalte 'baujahr' erstellt", file=sys.stderr)
    if "denkmalschutz" not in gdf.columns:
        gdf["denkmalschutz"] = False
        print("Spalte 'denkmalschutz' erstellt", file=sys.stderr)

    gdf_flaechen = gpd.GeoDataFrame()

    if gpkg_flaechen_path is None:
        pass  # z. B. Ordner leer — still überspringen
    elif not os.path.isfile(gpkg_flaechen_path):
        print(
            f"Warnung: Flächendenkmal nicht gefunden: {gpkg_flaechen_path}",
            file=sys.stderr,
        )
    else:
        print(f"Lade Flächendenkmal: {gpkg_flaechen_path} …", file=sys.stderr)
        try:
            gdf_flaechen = gpd.read_file(gpkg_flaechen_path)
            print(f"{len(gdf_flaechen)} Flächendenkmal-Polygone", file=sys.stderr)
            if "ext_dat" not in gdf_flaechen.columns:
                print(
                    "Warnung: Spalte 'ext_dat' fehlt — Flächendenkmal wird ignoriert.",
                    file=sys.stderr,
                )
                gdf_flaechen = gpd.GeoDataFrame()
        except Exception as e:
            print(f"Fehler beim Einlesen Flächendenkmal: {e}", file=sys.stderr)
            gdf_flaechen = gpd.GeoDataFrame()

    if len(gdf_flaechen) > 0:
        gdf = assign_baujahr_and_denkmalschutz(gdf, gdf_flaechen)

    if use_gitter:
        gdf = assign_baujahr_from_gitter(gdf, gpkg_gitter_path)

    missing_mask = gdf["baujahr"].isna()
    missing_count = int(missing_mask.sum())
    if missing_count > 0:
        print(
            f"{missing_count} Gebäude ohne Baujahr (unverändert leer)",
            file=sys.stderr,
        )

    # Ganzzahlige Baujahre (ältere Läufe: .5 aus Zensus-Mittel der Spanne)
    bj = pd.to_numeric(gdf["baujahr"], errors="coerce")
    gdf["baujahr"] = bj.round()

    print("baujahr / denkmalschutz fertig", file=sys.stderr)
    return gdf


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Baujahr und Denkmalschutz (Flächendenkmal + Zensus-Gitter)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "input_gpkg",
        nargs="?",
        default=None,
        help="Eingabe-GPKG (Standard: erste *_schritt3.gpkg unter output/output_step3/)",
    )
    ap.add_argument(
        "-o",
        "--output",
        default=None,
        help="Ausgabe-GPKG (Standard: output/output_step4/<Basis>_schritt4.gpkg)",
    )
    ap.add_argument(
        "--layer-in",
        default=None,
        help="Layer der Eingabe-GPKG (Standard: erster sinnvoller Layer)",
    )
    ap.add_argument(
        "--layer-out",
        default=None,
        help="Layer in der Ausgabe-GPKG (Standard: wie Eingabe)",
    )
    ap.add_argument(
        "--flaechen",
        default=None,
        metavar="PFAD",
        help=f"Flächendenkmal-GPKG (Standard: erstes *.gpkg unter {DIR_FLAECHENDENKMAL}/)",
    )
    ap.add_argument(
        "--flaechen-dir",
        default=DIR_FLAECHENDENKMAL,
        help="Ordner für Flächendenkmal-*.gpkg (Standard: input/flaechendenkmal)",
    )
    ap.add_argument(
        "--zensus",
        default=None,
        metavar="PFAD",
        help="Zensus-Gitter-GPKG (Standard: zensus_baualter.gpkg oder erstes *.gpkg unter input/zensus_baualtersklassen/)",
    )
    ap.add_argument(
        "--zensus-dir",
        default=DIR_ZENSUS_BAUALT,
        help="Ordner für Zensus-*.gpkg (Standard: input/zensus_baualtersklassen)",
    )
    ap.add_argument(
        "--no-gitter",
        action="store_true",
        help="Keine Baujahrschätzung aus Zensus-Gitter",
    )
    args = ap.parse_args()

    in_path = _resolve_input_schritt3(args.input_gpkg)
    if not in_path:
        print(
            "Keine Eingabe-GPKG: Pfad angeben oder *_schritt3.gpkg unter output/output_step3/ ablegen.",
            file=sys.stderr,
        )
        return 1

    layer_in = _pick_layer(in_path, args.layer_in)
    if not layer_in:
        print("Kein lesbarer Layer in der GPKG.", file=sys.stderr)
        return 1

    gdf = gpd.read_file(in_path, layer=layer_in)

    if args.flaechen:
        if os.path.isfile(args.flaechen):
            flaechen_path = os.path.abspath(args.flaechen)
        else:
            print(
                f"Warnung: --flaechen nicht gefunden: {args.flaechen} — überspringe Flächendenkmal.",
                file=sys.stderr,
            )
            flaechen_path = None
    else:
        flaechen_path = resolve_flaechendenkmal_gpkg(args.flaechen_dir)

    zensus_path = args.zensus
    if not zensus_path:
        preferred = os.path.join(args.zensus_dir, "zensus_baualter.gpkg")
        if os.path.isfile(preferred):
            zensus_path = preferred
        else:
            files = _list_gpkg_sorted(args.zensus_dir)
            zensus_path = files[0] if files else None

    gdf = create_baujahr(
        gdf,
        gpkg_flaechen_path=flaechen_path,
        gpkg_gitter_path=zensus_path,
        use_gitter=not args.no_gitter,
    )

    out_path = args.output or _default_output_path(in_path)
    layer_out = args.layer_out or layer_in
    _ensure_parent_dir(out_path)

    gdf.to_file(out_path, driver="GPKG", layer=layer_out)
    print(
        f"Baujahr/Denkmal: {len(gdf)} Gebäude | {out_path} (Layer: {layer_out})",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
