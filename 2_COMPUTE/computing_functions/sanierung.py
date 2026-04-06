"""
Weist Sanierungsjahr und U-Werte für Gebäude in Sanierungsgebieten zu.
"""

import geopandas as gpd
import pandas as pd
import numpy as np
import os
import json
import random
from dataclasses import replace
from typing import Optional, Dict, Set, List, Tuple
from gebaeudetypologie_loader import Gebaeude
from energie_ref_berechnung import create_energie_instanzen, create_energie_instanzen_for_gebaeude
from gebaeudetypologie_loader import load_gebaeudetypologie
from helpers import ENERGIE_SPALTEN, baujahr_to_baualtersklasse, scale_energie_values
from paths import COMPUTE_INPUTS, COMPUTE_OUTPUTS, PARAMS_KLIMA_GEB, SIMULATION_ASSUMPTIONS_DIR, VISUALIZE_DIR


SANIERUNG_PARAMS_FILE = 'sanierung_assumptions.json'

SANIERUNG_DEPTHS = {
    'vollsaniert': {'dach', 'geschossdecke', 'wand', 'keller', 'fenster', 'tuer'},
    'teilsaniert': {'dach', 'wand', 'fenster'},
    'huelle': {'dach', 'geschossdecke', 'wand', 'keller', 'fenster', 'tuer'},
    'fenster': {'fenster'},
    'dach': {'dach'},
    'wand': {'wand'},
    'keller': {'keller'},
    'tuer': {'tuer'}
}

SANIERUNG_PARTS = ['dach', 'geschossdecke', 'wand', 'keller', 'fenster', 'tuer']


def get_sanierung_assumptions_path() -> str:
    """Zielpfad für Sanierungsannahmen (3_VISUALIZE/simulation_assumptions/)."""
    os.makedirs(SIMULATION_ASSUMPTIONS_DIR, exist_ok=True)
    return os.path.join(str(SIMULATION_ASSUMPTIONS_DIR), SANIERUNG_PARAMS_FILE)


def load_sanierung_assumptions() -> List[Dict]:
    """Lädt gespeicherte Sanierungsannahmen."""
    data_path = get_sanierung_assumptions_path()
    legacy_path = os.path.join(str(VISUALIZE_DIR), SANIERUNG_PARAMS_FILE)
    file_path = data_path if os.path.exists(data_path) else legacy_path

    if not os.path.exists(file_path):
        return []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Warnung: Fehler beim Laden der Sanierungsannahmen: {e}")
        return []


def save_sanierung_assumptions(assumptions: List[Dict]) -> bool:
    """Speichert Sanierungsannahmen in eine JSON-Datei."""
    file_path = get_sanierung_assumptions_path()
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(assumptions, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Fehler beim Speichern der Sanierungsannahmen: {e}")
        return False


def parse_sanierungszyklus_start(cycle: str) -> Optional[int]:
    """Extrahiert Startjahr aus einem Zyklus-String (z.B. '2002-2009')."""
    if not cycle:
        return None

    cycle_str = str(cycle).strip().lower()
    if cycle_str.startswith('vor'):
        return 1919
    if cycle_str.startswith('nach'):
        return 2009
    if '-' in cycle_str:
        try:
            return int(cycle_str.split('-')[0])
        except ValueError:
            return None
    try:
        return int(cycle_str)
    except ValueError:
        return None


def get_available_sanierungszyklen() -> List[str]:
    """Liest verfügbare Sanierungszyklen aus der Typologie."""
    csv_path = str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")
    df_typologie = load_sanierungs_typologie(csv_path=csv_path)

    if len(df_typologie.columns) < 15:
        return []

    cycle_col = df_typologie.columns[14]
    values = []
    for val in df_typologie[cycle_col].tolist():
        if pd.isna(val):
            continue
        if isinstance(val, (int, float)) and not pd.isna(val):
            values.append(str(int(val)))
            continue
        val_str = str(val).strip()
        if not val_str:
            continue
        # Normalisiere "1977.0" -> "1977"
        try:
            values.append(str(int(float(val_str))))
        except ValueError:
            values.append(val_str)

    unique_vals = sorted(set(values), key=lambda x: parse_sanierungszyklus_start(x) or 0)
    return unique_vals


def get_sanierung_parts(depth: str, custom_parts: Optional[List[str]] = None) -> Set[str]:
    """Ermittelt Gebäudeteile anhand Sanierungstiefe oder Custom-Auswahl."""
    if depth and depth in SANIERUNG_DEPTHS:
        return set(SANIERUNG_DEPTHS[depth])
    if depth == 'custom' and custom_parts:
        return {p for p in custom_parts if p in SANIERUNG_PARTS}
    return set()


def normalize_sanierung_assumption(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Validiert und normalisiert Sanierungsannahmen."""
    if not isinstance(data, dict):
        return None, 'Ungültige Datenstruktur'

    name = str(data.get('name', '')).strip() or 'Sanierungsannahme'
    cycle = str(data.get('cycle', '')).strip()
    depth = str(data.get('depth', '')).strip() or 'vollsaniert'
    building_types = data.get('building_types', [])
    custom_parts = data.get('custom_parts', [])

    density_raw = data.get('density', 0)
    try:
        density = float(density_raw)
    except (ValueError, TypeError):
        return None, 'Ungültiger Wert für Sanierungsdichte'
    if density < 0 or density > 100:
        return None, 'Sanierungsdichte muss zwischen 0 und 100 liegen'

    try:
        baujahr_from = int(data['baujahr_from']) if data.get('baujahr_from') not in [None, ''] else None
        baujahr_to = int(data['baujahr_to']) if data.get('baujahr_to') not in [None, ''] else None
    except (ValueError, TypeError):
        return None, 'Ungültiger Baujahrbereich'

    if building_types in [None, '']:
        building_types = []
    if isinstance(building_types, str):
        building_types = [building_types]
    building_types = [t for t in building_types if t]

    return {
        'id': data.get('id'),
        'name': name,
        'density': density,
        'cycle': cycle,
        'depth': depth,
        'building_types': building_types,
        'baujahr_from': baujahr_from,
        'baujahr_to': baujahr_to,
        'custom_parts': custom_parts if isinstance(custom_parts, list) else []
    }, None


def parse_float_value(val):
    """Konvertiert einen Wert zu float, behandelt Komma als Dezimaltrennzeichen."""
    if pd.isna(val):
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        val_str = str(val).strip().replace(',', '.')
        return float(val_str) if val_str and val_str != 'nan' else 0.0
    except (ValueError, TypeError):
        return 0.0


def load_sanierungs_typologie(csv_path: str = 'gebaeudetypologie.csv', csv_start_row: int = 49) -> pd.DataFrame:
    """Lädt den Sanierungs-Teil der Gebäudetypologie ab einer Startzeile."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV-Datei nicht gefunden: {csv_path}")

    encodings = ['utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-8']
    df_typologie = None

    for encoding in encodings:
        try:
            df = pd.read_csv(csv_path, sep=';', encoding=encoding, skiprows=1, header=0, on_bad_lines='skip', engine='python')
            if len(df.columns) > 1:
                df_typologie = df.iloc[max(0, csv_start_row - 2):].copy()
                break
        except Exception:
            continue

    if df_typologie is None:
        raise Exception(f"Konnte CSV-Datei nicht einlesen: {csv_path}")

    return df_typologie


def get_sanierungs_u_values(
    df_typologie: pd.DataFrame,
    gebaeudetyp: str,
    sanierungsjahr: int
) -> Optional[Dict[str, float]]:
    """
    Holt U-Werte aus der Typologie für einen Gebäudetyp und Sanierungsjahr.
    """
    typologie_row = find_matching_typologie_row(df_typologie, gebaeudetyp, sanierungsjahr)
    if typologie_row is None:
        return None

    u_col_indices = {'dach': 15, 'geschossdecke': 16, 'wand': 17, 'keller': 18, 'fenster': 19, 'tuer': 20}
    u_values = {}

    for key, idx in u_col_indices.items():
        if idx < len(df_typologie.columns):
            col_name = df_typologie.columns[idx]
            if col_name in typologie_row.index:
                val = parse_float_value(typologie_row[col_name])
                if val > 0:
                    u_values[key] = val

    return u_values or None


def apply_sanierungs_u_values_to_gebaeude(
    gebaeude: Gebaeude,
    u_values: Optional[Dict[str, float]],
    parts: Set[str]
) -> Gebaeude:
    """
    Ersetzt U-Werte am Gebaeude anhand der Sanierungswerte und Sanierungstiefe.
    """
    if not u_values or not parts:
        return gebaeude

    updated = gebaeude

    if 'dach' in parts and 'dach' in u_values:
        updated = replace(updated, U_dach=u_values['dach'])
    if 'geschossdecke' in parts and 'geschossdecke' in u_values:
        updated = replace(updated, U_ogd=u_values['geschossdecke'])
    if 'wand' in parts and 'wand' in u_values:
        updated = replace(updated, U_aw=u_values['wand'])
    if 'keller' in parts and 'keller' in u_values:
        updated = replace(updated, U_kd=u_values['keller'])
    if 'fenster' in parts and 'fenster' in u_values:
        updated = replace(updated, U_fen=u_values['fenster'])
    if 'tuer' in parts and 'tuer' in u_values:
        updated = replace(updated, U_tuer=u_values['tuer'])

    u_summe = round(
        updated.U_dach + updated.U_ogd + updated.U_aw + updated.U_kd + updated.U_fen + updated.U_tuer,
        2
    )
    updated = replace(updated, U_summe=u_summe)
    return updated


def find_matching_typologie_row(df_typologie: pd.DataFrame, gebaeudetyp: str, sanierungsjahr: int) -> Optional[pd.Series]:
    """
    Findet passende Sanierungszyklus-Zeile (generisch, ohne Gebäudetyp).

    Logik: Findet den größten Sanierungszyklus-Start (Spalte O) der <= dem Sanierungsjahr ist.
    Beispiel: Sanierungsjahr 2003, Zyklen 2002 und 2009 -> nimmt Zyklus 2002.
    """
    if len(df_typologie.columns) < 15:
        return None
    
    typ_col = df_typologie.columns[1]  # Gebäudetyp (Spalte B)
    sanierungsjahr_col = df_typologie.columns[14]  # Sanierungsjahr (Spalte O, Index 14)
    
    def parse_year(value) -> Optional[int]:
        if pd.isna(value):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def select_latest_row(frame: pd.DataFrame) -> Optional[pd.Series]:
        if frame.empty:
            return None
        san_jahre = frame[sanierungsjahr_col].apply(parse_year)
        valid_mask = san_jahre.notna() & (san_jahre <= sanierungsjahr)
        if not valid_mask.any():
            return None
        max_san_jahr = san_jahre[valid_mask].max()
        result = frame[san_jahre == max_san_jahr]
        return result.iloc[0] if len(result) > 0 else None

    try:
        # Sanierungszyklen sind generisch: ohne Gebäudetyp filtern
        typ_values = df_typologie[typ_col].astype(str).str.strip()
        mask_generic = typ_values.isna() | (typ_values == '') | (typ_values.str.lower() == 'nan')
        return select_latest_row(df_typologie[mask_generic].copy())
    except Exception:
        return None


def apply_sanierung_simulation(
    gdf: gpd.GeoDataFrame,
    assumption: Dict,
    energy_params: Optional[Dict[str, float]] = None
) -> Tuple[gpd.GeoDataFrame, Dict]:
    """Wendet Sanierungsannahmen auf Gebäude an und berechnet Energiewerte neu."""
    density = assumption['density'] / 100.0
    cycle = assumption['cycle']
    depth = assumption['depth']
    building_types = {str(t).strip().upper() for t in (assumption.get('building_types') or []) if t}
    baujahr_from = assumption.get('baujahr_from')
    baujahr_to = assumption.get('baujahr_to')
    custom_parts = assumption.get('custom_parts') or []

    cycle_start = parse_sanierungszyklus_start(cycle)
    if cycle_start is None:
        raise ValueError('Sanierungszyklus ist ungültig')

    parts = get_sanierung_parts(depth, custom_parts)
    if not parts:
        raise ValueError('Sanierungstiefe enthält keine Gebäudeteile')

    # Lade Referenzgebäude und Energie-Referenzwerte
    default_gebaeude = load_gebaeudetypologie()
    default_energie = create_energie_instanzen(energy_params=energy_params)

    default_energie_map = {(g.typ.strip().upper(), g.bal): e for g, e in zip(default_gebaeude, default_energie)}
    default_gebaeude_map = {(g.typ.strip().upper(), g.bal): g for g in default_gebaeude}

    # Lade Sanierungstypologie und bestimme U-Werte je Gebäudetyp
    csv_path = str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")
    df_typologie = load_sanierungs_typologie(csv_path=csv_path)

    u_values_by_type = {}
    for g in default_gebaeude:
        g_typ = g.typ.strip().upper()
        if building_types and g_typ not in building_types:
            continue
        u_values_by_type[g_typ] = get_sanierungs_u_values(df_typologie, g_typ, cycle_start)

    # Erzeuge renovierte Referenzgebäude
    renovated_gebaeude = []
    for g in default_gebaeude:
        g_typ = g.typ.strip().upper()
        if building_types and g_typ not in building_types:
            renovated_gebaeude.append(g)
            continue
        u_values = u_values_by_type.get(g_typ)
        renovated_gebaeude.append(apply_sanierungs_u_values_to_gebaeude(g, u_values, parts))

    renovated_energie = create_energie_instanzen_for_gebaeude(
        renovated_gebaeude,
        energy_params=energy_params
    )
    renovated_energie_map = {(g.typ.strip().upper(), g.bal): e for g, e in zip(renovated_gebaeude, renovated_energie)}

    # Spalten für Simulation
    for col in ENERGIE_SPALTEN:
        sim_col = f"{col}_sim"
        if sim_col not in gdf.columns:
            gdf[sim_col] = np.nan
        base_col = f"{col}_base"
        if base_col not in gdf.columns and col in gdf.columns:
            gdf[base_col] = gdf[col]

    if 'sanierung_kandidat' not in gdf.columns:
        gdf['sanierung_kandidat'] = False
    if 'sanierung_angewandt' not in gdf.columns:
        gdf['sanierung_angewandt'] = False

    rng = random.Random(assumption.get('seed'))
    matched_count = 0
    applied_count = 0
    unmatched_count = 0

    for idx, row in gdf.iterrows():
        gebaeudetyp = row.get('gebaeudetyp')
        if pd.notna(gebaeudetyp):
            gebaeudetyp = str(gebaeudetyp).strip().upper()
        else:
            gebaeudetyp = None
        baujahr = row.get('baujahr')
        bezugsflaeche = row.get("bezugsflaeche")

        # Filterung
        matches_type = True if not building_types else (gebaeudetyp in building_types)
        matches_baujahr = True

        if baujahr_from is not None:
            matches_baujahr = matches_baujahr and pd.notna(baujahr) and float(baujahr) >= baujahr_from
        if baujahr_to is not None:
            matches_baujahr = matches_baujahr and pd.notna(baujahr) and float(baujahr) <= baujahr_to

        is_candidate = matches_type and matches_baujahr
        gdf.loc[idx, 'sanierung_kandidat'] = bool(is_candidate)

        bal = baujahr_to_baualtersklasse(baujahr)
        energie_default = default_energie_map.get((gebaeudetyp, bal))
        energie_renov = renovated_energie_map.get((gebaeudetyp, bal))
        ref_gebaeude = default_gebaeude_map.get((gebaeudetyp, bal))

        if energie_default is None or ref_gebaeude is None:
            unmatched_count += 1
            continue

        use_renov = False
        if is_candidate and energie_renov is not None:
            if rng.random() <= density:
                use_renov = True

        energie_ref = energie_renov if use_renov else energie_default
        energie_werte = scale_energie_values(energie_ref, bezugsflaeche, ref_gebaeude.AN)

        for col, wert in energie_werte.items():
            gdf.loc[idx, f"{col}_sim"] = wert

        if is_candidate:
            matched_count += 1
        if use_renov:
            applied_count += 1
        gdf.loc[idx, 'sanierung_angewandt'] = bool(use_renov)

    stats = {
        'total_buildings': len(gdf),
        'candidates': matched_count,
        'applied': applied_count,
        'unmatched': unmatched_count
    }
    return gdf, stats


def process_sanierung(
    input_gpkg: str,
    sanierungsgebiete_gpkg: Optional[str] = None,
    csv_path: Optional[str] = None,
    csv_start_row: int = 49,
) -> gpd.GeoDataFrame:
    """
    Batch-Vorverarbeitung (nicht die interaktive „Sanierung simulieren“-API in app.py).

    Vorgehen:
    - Lädt Gebäudepolygone (input_gpkg) und ein Polygon-Layer „Sanierungsgebiete“
      (Standard: computing_inputs/Sanierungsgebiete.gpkg).
    - Räumlicher Join (Gebäude liegen *within* Sanierungsgebiets-Polygonen).
    - Pro Treffer: ``sanierungsjahr`` aus dem Gebiets-Layer; anhand Gebäudetyp,
      Sanierungsjahr und Spalten in der Gebäudetypologie-CSV werden U-Werte
      (U_dach, U_wand, …) gesetzt, sofern die Gebiets-Polygone die zugehörigen
      Boolean-Spalten (Dach, Wand, …) gesetzt haben.

    Ausgabe: GPKG unter computing_outputs/ mit Suffix ``_mit_sanierung.gpkg``.

    Die Web-App nutzt stattdessen ``apply_sanierung_simulation`` mit in
    ``SIMULATION_ASSUMPTIONS_DIR`` gespeicherten JSON-Szenarien und schreibt
    ebenfalls nach ``computing_outputs/``.
    """
    if sanierungsgebiete_gpkg is None:
        sanierungsgebiete_gpkg = str(COMPUTE_INPUTS / "Sanierungsgebiete.gpkg")
    if csv_path is None:
        csv_path = str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")

    # Lade Dateien
    if not os.path.exists(input_gpkg):
        raise FileNotFoundError(f"Gebäude-Datei nicht gefunden: {input_gpkg}")
    if not os.path.exists(sanierungsgebiete_gpkg):
        raise FileNotFoundError(f"Sanierungsgebiete-Datei nicht gefunden: {sanierungsgebiete_gpkg}")
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV-Datei nicht gefunden: {csv_path}")
    
    gdf_gebaeude = gpd.read_file(input_gpkg)
    gdf_sanierung = gpd.read_file(sanierungsgebiete_gpkg)
    
    print(f"✓ {len(gdf_gebaeude)} Gebäude geladen")
    print(f"✓ {len(gdf_sanierung)} Sanierungsgebiete geladen")
    
    # Lade CSV ab Startzeile
    df_typologie = load_sanierungs_typologie(csv_path=csv_path, csv_start_row=csv_start_row)
    
    print(f"✓ {len(df_typologie)} Zeilen aus CSV geladen")
    
    
    # Boolean-Spalten für U-Werte
    boolean_cols = ['Dach', 'Geschossdecke', 'Wand', 'Fenster', 'Keller', 'Tür', 'gF']
    available_boolean_cols = [col for col in boolean_cols if col in gdf_sanierung.columns]
    
    # CRS angleichen
    if gdf_gebaeude.crs != gdf_sanierung.crs:
        gdf_gebaeude = gdf_gebaeude.to_crs(gdf_sanierung.crs)
    
    # Räumlicher Join
    gdf_joined = gpd.sjoin(gdf_gebaeude, gdf_sanierung[['Sanierungsjahr'] + available_boolean_cols + ['geometry']], 
                           how='left', predicate='within')
    
    # Initialisiere Spalten
    gdf_gebaeude['sanierungsjahr'] = np.nan
    u_value_cols = ['U_dach', 'U_geschossdecke', 'U_wand', 'U_fenster', 'U_keller', 'U_tuer']
    for col in u_value_cols:
        gdf_gebaeude[col] = np.nan
    
    # U-Wert-Spaltenindizes (basierend auf gebaeudetypologie_loader.py)
    u_col_indices = {'dach': 15, 'geschossdecke': 16, 'wand': 17, 'keller': 18, 'fenster': 19, 'tuer': 20}
    u_col_names = {k: df_typologie.columns[v] if v < len(df_typologie.columns) else None for k, v in u_col_indices.items()}
    
    # Weise Sanierungsjahr und U-Werte zu
    assigned_count = 0
    u_value_count = 0
    
    for idx in gdf_gebaeude.index:
        joined_rows = gdf_joined[gdf_joined.index == idx]
        if len(joined_rows) == 0:
            continue
        
        sanierung_row = joined_rows.iloc[0]
        sanierungsjahr = sanierung_row.get('Sanierungsjahr')
        if pd.isna(sanierungsjahr):
            continue
        
        try:
            sanierungsjahr_int = int(float(sanierungsjahr))
        except (ValueError, TypeError):
            continue
        
        gdf_gebaeude.loc[idx, 'sanierungsjahr'] = sanierungsjahr_int
        assigned_count += 1
        
        # Finde Gebäudetyp
        gebaeudetyp = gdf_gebaeude.loc[idx, 'gebaeudetyp'] if 'gebaeudetyp' in gdf_gebaeude.columns else None
        
        # Finde passende Typologie-Zeile basierend auf Gebäudetyp und Sanierungsjahr (aus Spalte O)
        typologie_row = find_matching_typologie_row(df_typologie, gebaeudetyp, sanierungsjahr_int)
        if typologie_row is None:
            continue
        
        # Weise U-Werte zu, nur wenn Boolean True ist
        boolean_mapping = {'Dach': 'dach', 'Geschossdecke': 'geschossdecke', 'Wand': 'wand', 
                          'Fenster': 'fenster', 'Keller': 'keller', 'Tür': 'tuer'}
        
        for bool_col, u_key in boolean_mapping.items():
            if bool_col in available_boolean_cols and sanierung_row.get(bool_col) == True:
                u_col_name = u_col_names.get(u_key)
                if u_col_name and u_col_name in typologie_row.index:
                    val = typologie_row[u_col_name]
                    if pd.notna(val):
                        u_val = parse_float_value(val)
                        if u_val > 0:
                            gdf_gebaeude.loc[idx, f'U_{u_key}'] = u_val
                            u_value_count += 1
    
    print(f"✓ {assigned_count} Gebäude mit Sanierungsjahr versehen")
    print(f"✓ {u_value_count} U-Werte zugewiesen")
    
    # Speichere Ergebnis
    base_name = os.path.splitext(os.path.basename(input_gpkg))[0]
    os.makedirs(COMPUTE_OUTPUTS, exist_ok=True)
    output_path = str(COMPUTE_OUTPUTS / f"{base_name}_mit_sanierung.gpkg")
    gdf_gebaeude.to_file(output_path, driver="GPKG")
    print(f"✓ GeoPackage gespeichert: {output_path}")
    
    return gdf_gebaeude