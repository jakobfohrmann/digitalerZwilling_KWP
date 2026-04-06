"""
Flask-App für interaktive Gebäudevisualisierung mit mehreren Layern.
Lädt Daten aus GPKG-Dateien und stellt REST API für verschiedene Visualisierungen bereit.
"""

from flask import Flask, render_template, request, jsonify
import geopandas as gpd
import pandas as pd
import numpy as np
import json
import os
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import sys

# Füge computing_functions zum Python-Pfad hinzu (Module + paths.py)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "2_COMPUTE", "computing_functions"))
from paths import COMPUTE_OUTPUTS, SIMULATION_ASSUMPTIONS_DIR, VISUALIZE_DIR
from energie_ref_berechnung import get_default_energy_parameters, create_energie_instanzen, create_energie_instanzen_for_gebaeude
from gebaeudetypologie_loader import load_gebaeudetypologie
from sanierung import (
    load_sanierung_assumptions,
    save_sanierung_assumptions,
    get_available_sanierungszyklen,
    normalize_sanierung_assumption,
    apply_sanierung_simulation,
)
from klima import apply_klima_simulation
from helpers import (
    baujahr_to_baualtersklasse,
    find_matching_referenz,
    scale_energie_values,
    ENERGIE_SPALTEN,
)

# ============================================================================
# KONFIGURATION
# ============================================================================

# Gebäude-GPKG: automatisch das (bei mehreren: zuletzt geänderte) *.gpkg unter
# 2_COMPUTE/computing_outputs/ — kein fester Dateiname nötig.

# Gespeicherte Szenario-Listen (JSON): nur unter SIMULATION_ASSUMPTIONS_DIR
KLIMA_PARAMS_FILE = "klima_assumptions.json"
# Globale Variable für Energie-Parameter (nur Standardwerte)
energy_parameters = get_default_energy_parameters()

# Sanierungstiefen (Zuordnung zu Gebäudeteilen)
# ============================================================================
# HILFSFUNKTIONEN
# ============================================================================


def pick_gpkg_from_outputs(explicit_basename: Optional[str] = None) -> Tuple[str, str]:
    """
    Wählt eine GeoPackage-Datei unter COMPUTE_OUTPUTS.

    Ohne ``explicit_basename``: alle ``*.gpkg``, bei mehreren die zuletzt geänderte.
    Gibt (voller Pfad, Dateiname) zurück.
    """
    out_dir = Path(COMPUTE_OUTPUTS)
    out_dir.mkdir(parents=True, exist_ok=True)

    if explicit_basename:
        path = out_dir / explicit_basename
        if not path.is_file():
            raise FileNotFoundError(f"GeoPackage nicht gefunden: {path}")
        return str(path.resolve()), explicit_basename

    candidates = sorted(out_dir.glob("*.gpkg"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not candidates:
        raise FileNotFoundError(
            f"Kein .gpkg in {out_dir}. Bitte compute_main ausführen oder eine GPKG nach computing_outputs legen."
        )
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates[:5])
        more = f" (+{len(candidates) - 5} weitere)" if len(candidates) > 5 else ""
        print(
            f"[INFO] Mehrere GPKG in computing_outputs ({names}{more}) — "
            f"verwende zuletzt geändert: {candidates[0].name}"
        )
    chosen = candidates[0]
    return str(chosen.resolve()), chosen.name


def get_klima_assumptions_path() -> str:
    """Zielpfad für Klimaannahmen (simulation_assumptions/)."""
    os.makedirs(SIMULATION_ASSUMPTIONS_DIR, exist_ok=True)
    return os.path.join(str(SIMULATION_ASSUMPTIONS_DIR), KLIMA_PARAMS_FILE)


def load_klima_assumptions() -> List[Dict]:
    """Lädt gespeicherte Klimaannahmen."""
    data_path = get_klima_assumptions_path()
    legacy_path = os.path.join(str(VISUALIZE_DIR), KLIMA_PARAMS_FILE)
    file_path = data_path if os.path.exists(data_path) else legacy_path

    if not os.path.exists(file_path):
        return []

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Warnung: Fehler beim Laden der Klimaannahmen: {e}")
        return []


def save_klima_assumptions(assumptions: List[Dict]) -> bool:
    """Speichert Klimaannahmen in eine JSON-Datei."""
    file_path = get_klima_assumptions_path()
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(assumptions, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Fehler beim Speichern der Klimaannahmen: {e}")
        return False


def normalize_klima_assumption(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Validiert und normalisiert Klimaannahmen."""
    if not isinstance(data, dict):
        return None, 'Ungültige Datenstruktur'

    scenario = str(data.get('scenario', '')).strip().lower()
    if scenario not in ['rcp26', 'rcp45', 'rcp85']:
        return None, 'Klimaszenario ist ungültig'

    try:
        year = int(data.get('year'))
    except (ValueError, TypeError):
        return None, 'Jahr ist ungültig'

    if year < 2024 or year > 2050:
        return None, 'Jahr muss zwischen 2024 und 2050 liegen'

    name = str(data.get('name', '')).strip() or f"Klima {scenario.upper()} {year}"

    return {
        'id': data.get('id'),
        'name': name,
        'scenario': scenario,
        'year': year
    }, None


def add_energiebilanz_to_gebaeude(gdf: gpd.GeoDataFrame, energy_params: Optional[Dict[str, float]] = None) -> gpd.GeoDataFrame:
    """Fügt Energiebilanzwerte zu Gebäuden hinzu basierend auf Referenzgebäuden."""
    print("Lade Referenz-Energiebilanzwerte...")
    energie_liste = create_energie_instanzen(energy_params=energy_params)
    gebaeude_liste = load_gebaeudetypologie()
    
    print(f"✓ {len(energie_liste)} Referenz-Energiebilanzen geladen")
    
    # Initialisiere neue Spalten
    for col in ENERGIE_SPALTEN:
        if col not in gdf.columns:
            gdf[col] = np.nan
    
    print("\nBerechne Energiebilanzwerte für Gebäude...")
    matched_count = 0
    unmatched_count = 0
    
    for idx, row in gdf.iterrows():
        gebaeudetyp = row.get('gebaeudetyp')
        baujahr = row.get('baujahr')
        bezugsflaeche = row.get("bezugsflaeche")

        # Konvertiere Baujahr zu Baualtersklasse
        bal = baujahr_to_baualtersklasse(baujahr)

        # Finde passende Referenz
        energie_ref = find_matching_referenz(gebaeudetyp, bal, energie_liste, gebaeude_liste)

        if energie_ref is None:
            unmatched_count += 1
            continue

        # Referenzfläche AN aus Typologie
        bezugsflaeche_ref = None
        for gebaeude in gebaeude_liste:
            if gebaeude.typ == gebaeudetyp and gebaeude.bal == bal:
                bezugsflaeche_ref = gebaeude.AN
                break

        if bezugsflaeche_ref is None:
            unmatched_count += 1
            continue

        # Skaliere Werte
        energie_werte = scale_energie_values(energie_ref, bezugsflaeche, bezugsflaeche_ref)
        
        # Füge Werte zum GeoDataFrame hinzu
        for col, wert in energie_werte.items():
            gdf.loc[idx, col] = wert
        
        matched_count += 1
    
    print(f"✓ {matched_count} Gebäude mit Energiebilanzwerten versehen")
    if unmatched_count > 0:
        print(f"⚠ {unmatched_count} Gebäude konnten nicht zugeordnet werden")
    
    return gdf


def get_color_for_waermebedarf(value: float, is_spezific: bool = True) -> str:
    """
    Gibt Farbe für Wärmebedarf zurück.
    
    Args:
        value: Wärmebedarf-Wert
        is_spezific: True für spezifischen Wärmebedarf [kWh/m²a], False für absoluten [kWh/a]
    """
    if pd.isna(value) or value == 0:
        return '#95a5a6'  # Grau für fehlende Werte
    
    if is_spezific:
        # Spezifischer Wärmebedarf [kWh/m²a]
        if value > 200:
            return '#e74c3c'  # Rot - sehr hoch
        elif value > 150:
            return '#e67e22'  # Orange - hoch
        elif value > 120:
            return '#f39c12'  # Orange-Gelb
        elif value > 80:
            return '#f1c40f'  # Gelb - mittel
        elif value > 50:
            return '#52be80'  # Hellgrün - niedrig
        else:
            return '#2ecc71'  # Grün - sehr niedrig
    else:
        # Absoluter Wärmebedarf [kWh/a] - andere Skalierung
        # Normalisiere auf 1000 kWh/a Schritte
        normalized = value / 1000
        if normalized > 200:
            return '#e74c3c'  # Rot - sehr hoch
        elif normalized > 150:
            return '#e67e22'  # Orange - hoch
        elif normalized > 120:
            return '#f39c12'  # Orange-Gelb
        elif normalized > 80:
            return '#f1c40f'  # Gelb - mittel
        elif normalized > 50:
            return '#52be80'  # Hellgrün - niedrig
        else:
            return '#2ecc71'  # Grün - sehr niedrig


def get_color_for_gebaeudetyp(gebaeudetyp: str) -> str:
    """Gibt Farbe für Gebäudetyp zurück."""
    colors = {
        'EFH': '#3498db',      # Blau
        'RH': '#9b59b6',       # Lila
        'MFH': '#e74c3c',      # Rot
        'GMH': '#f39c12',      # Orange
        'HH': '#1abc9c',       # Türkis
    }
    return colors.get(gebaeudetyp, '#95a5a6')  # Grau als Fallback


def get_color_for_baualtersklasse(baualtersklasse: str) -> str:
    """
    Gibt Farbe für Baualtersklasse zurück.
    Farbverlauf von dunkel (alt) zu hell (neu) mit unterschiedlichen Helligkeitstönen.
    """
    colors = {
        'vor 1919': '#1e3a5f',        # Sehr dunkles Blau - Baualtersklasse A/B
        '1919-1948': '#2c5f8f',      # Dunkles Blau - Baualtersklasse C
        '1949-1957': '#3d7ab8',       # Mittel-dunkles Blau - Baualtersklasse D
        '1958-1968': '#4a8fc7',      # Mittel-Blau - Baualtersklasse E
        '1969-1978': '#5a9fd4',      # Helles Blau - Baualtersklasse F
        '1979-1983': '#6eb0e0',      # Sehr helles Blau - Baualtersklasse G
        '1984-1994': '#8bc4e8',      # Sehr helles Blau - Baualtersklasse H
        '1995-2001': '#a8d4f0',      # Sehr helles Blau - Baualtersklasse I
        '2002-2009': '#c5e3f5',      # Sehr helles Blau - Baualtersklasse J 
        'nach 2009': '#e8f4f8',      # Sehr helles Blau-Weiß - Baualtersklasse K
    }
    return colors.get(baualtersklasse, '#95a5a6')  # Grau als Fallback


# ============================================================================
# FLASK APP
# ============================================================================

app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))

# Globale Variable für Gebäudedaten
buildings_data = None
current_data_filename: Optional[str] = None


def load_data(input_filename: Optional[str] = None) -> gpd.GeoDataFrame:
    """Lädt Gebäude-GPKG aus 2_COMPUTE/computing_outputs/ (Ordnerinhalt, kein fester Name)."""
    global buildings_data, current_data_filename

    gpkg_path, basename = pick_gpkg_from_outputs(explicit_basename=input_filename)

    gdf = gpd.read_file(gpkg_path)
    print(f"[OK] Gebäudedaten geladen: {gpkg_path}")
    
    # Füge Baualtersklasse hinzu, falls nicht vorhanden
    if 'baujahr' in gdf.columns and 'baualtersklasse' not in gdf.columns:
        gdf['baualtersklasse'] = gdf['baujahr'].apply(baujahr_to_baualtersklasse)
        print("[OK] Baualtersklasse berechnet")
    
    print(f"[OK] Anzahl Gebäude: {len(gdf)}")
    print(f"[OK] Verfügbare Spalten: {list(gdf.columns)}")
    
    buildings_data = gdf
    current_data_filename = basename
    return gdf


def prepare_geojson_for_layer(gdf: gpd.GeoDataFrame, layer_type: str) -> Dict:
    """
    Bereitet GeoJSON für einen bestimmten Layer vor.
    
    Args:
        gdf: GeoDataFrame mit Gebäudedaten
        layer_type: 'waermebedarf', 'spez_waermebedarf', 'gebaeudetyp', 'baualtersklasse'
    
    Returns:
        GeoJSON-Dictionary mit Style-Informationen
    """
    # Konvertiere zu WGS84 für Web-Darstellung
    gdf_web = gdf.copy()
    if gdf_web.crs != 'EPSG:4326':
        gdf_web = gdf_web.to_crs('EPSG:4326')
    
    # Konvertiere zu GeoJSON
    geojson = json.loads(gdf_web.to_json())
    
    # Füge Style-Informationen hinzu
    for feature in geojson['features']:
        props = feature['properties']
        
        if layer_type == 'waermebedarf':
            # Wärmebedarf [kWh/a]
            value = props.get('g_QH_sim')
            if value is None:
                value = props.get('g_QH') or 0
            feature['properties']['_layer_value'] = value
            feature['properties']['_layer_color'] = get_color_for_waermebedarf(value, is_spezific=False)
        
        elif layer_type == 'spez_waermebedarf':
            # Spezifischer Wärmebedarf [kWh/m²a]
            value = props.get('ga_qH_sim')
            if value is None:
                value = props.get('ga_qH') or 0
            feature['properties']['_layer_value'] = value
            feature['properties']['_layer_color'] = get_color_for_waermebedarf(value, is_spezific=True)
        
        elif layer_type == 'gebaeudetyp':
            # Gebäudetyp
            gebaeudetyp = props.get('gebaeudetyp', 'Unbekannt')
            feature['properties']['_layer_value'] = gebaeudetyp
            feature['properties']['_layer_color'] = get_color_for_gebaeudetyp(gebaeudetyp)
        
        elif layer_type == 'baualtersklasse':
            # Baualtersklasse
            baualtersklasse = props.get('baualtersklasse')
            if not baualtersklasse and 'baujahr' in props:
                baualtersklasse = baujahr_to_baualtersklasse(props['baujahr'])
            feature['properties']['_layer_value'] = baualtersklasse or 'Unbekannt'
            feature['properties']['_layer_color'] = get_color_for_baualtersklasse(baualtersklasse) if baualtersklasse else '#95a5a6'
    
    return geojson


# ============================================================================
# ROUTES
# ============================================================================

@app.route('/')
def index():
    """Hauptseite mit interaktiver Karte"""
    return render_template("map.html")


@app.route('/api/layer/<layer_type>')
def get_layer(layer_type: str):
    """
    API Endpoint für verschiedene Layer.
    
    Layer-Typen:
    - waermebedarf: Wärmebedarf [kWh/a]
    - spez_waermebedarf: Spezifischer Wärmebedarf [kWh/m²a]
    - gebaeudetyp: Gebäudetyp
    - baualtersklasse: Baualtersklasse
    """
    try:
        if buildings_data is None:
            load_data()
        
        valid_layers = ['waermebedarf', 'spez_waermebedarf', 'gebaeudetyp', 'baualtersklasse']
        if layer_type not in valid_layers:
            return jsonify({'error': f'Ungültiger Layer-Typ. Erlaubt: {valid_layers}'}), 400
        
        geojson = prepare_geojson_for_layer(buildings_data, layer_type)
        return jsonify(geojson)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/building/<building_id>')
def get_building(building_id: str):
    """
    API Endpoint für Details eines einzelnen Gebäudes.
    
    Args:
        building_id: ID des Gebäudes (z.B. identifikator)
    """
    try:
        if buildings_data is None:
            load_data()
        
        # Suche nach ID-Spalte
        id_cols = ["lod1_gml_id", "identifikator", "id", "fid", "objectid"]
        id_col = None
        for col in id_cols:
            if col in buildings_data.columns:
                id_col = col
                break
        
        if id_col is None:
            return jsonify({'error': 'Keine ID-Spalte gefunden'}), 400
        
        # Finde Gebäude
        try:
            # Versuche zuerst als String
            building = buildings_data[buildings_data[id_col].astype(str) == str(building_id)]
            if len(building) == 0:
                # Versuche als Integer
                building = buildings_data[buildings_data[id_col] == int(building_id)]
        except (ValueError, TypeError):
            building = buildings_data[buildings_data[id_col].astype(str) == str(building_id)]
        
        if len(building) == 0:
            return jsonify({'error': f'Gebäude mit ID {building_id} nicht gefunden'}), 404
        
        # Konvertiere zu Dictionary
        building_row = building.iloc[0]
        ga_qh_sim = building_row.get('ga_qH_sim') if 'ga_qH_sim' in building_row else None
        g_qh_sim = building_row.get('g_QH_sim') if 'g_QH_sim' in building_row else None

        building_dict = {
            'id': str(building_row.get(id_col, '')),
            'baujahr': int(building_row['baujahr']) if pd.notna(building_row.get('baujahr')) else None,
            'gebaeudetyp': str(building_row['gebaeudetyp']) if pd.notna(building_row.get('gebaeudetyp')) else None,
            'bezugsflaeche': float(building_row['bezugsflaeche']) if pd.notna(building_row.get('bezugsflaeche')) else None,
            'spez_waermebedarf': float(ga_qh_sim) if pd.notna(ga_qh_sim) else (
                float(building_row['ga_qH']) if pd.notna(building_row.get('ga_qH')) else None
            ),
            'waermebedarf': float(g_qh_sim) if pd.notna(g_qh_sim) else (
                float(building_row['g_QH']) if pd.notna(building_row.get('g_QH')) else None
            ),
            'baualtersklasse': str(building_row['baualtersklasse']) if pd.notna(building_row.get('baualtersklasse')) else None,
        }
        
        return jsonify(building_dict)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/legend-colors')
def get_legend_colors():
    """API Endpoint für Farbzuordnungen der Legenden für alle Layer"""
    try:
        # Baualtersklassen-Farben
        baualtersklassen_colors = {}
        classes = ['vor 1919', '1919-1948', '1949-1957', '1958-1968', '1969-1978', 
                   '1979-1983', '1984-1994', '1995-2001', '2002-2009', 'nach 2009']
        for cls in classes:
            baualtersklassen_colors[cls] = get_color_for_baualtersklasse(cls)
        
        # Gebäudetyp-Farben
        gebaeudetypen_colors = {}
        typen = ['EFH', 'RH', 'MFH', 'GMH', 'HH']
        for typ in typen:
            gebaeudetypen_colors[typ] = get_color_for_gebaeudetyp(typ)
        
        # Wärmebedarf-Klassen (basierend auf Schwellenwerten)
        waermebedarf_classes = {
            'sehr_niedrig': {'min': 0, 'max': 50000, 'color': get_color_for_waermebedarf(25000, is_spezific=False)},
            'niedrig': {'min': 50000, 'max': 80000, 'color': get_color_for_waermebedarf(65000, is_spezific=False)},
            'mittel': {'min': 80000, 'max': 120000, 'color': get_color_for_waermebedarf(100000, is_spezific=False)},
            'mittel_hoch': {'min': 120000, 'max': 150000, 'color': get_color_for_waermebedarf(135000, is_spezific=False)},
            'hoch': {'min': 150000, 'max': 200000, 'color': get_color_for_waermebedarf(175000, is_spezific=False)},
            'sehr_hoch': {'min': 200000, 'max': None, 'color': get_color_for_waermebedarf(250000, is_spezific=False)}  # None = unbegrenzt
        }
        
        # Spezifischer Wärmebedarf-Klassen
        spez_waermebedarf_classes = {
            'sehr_niedrig': {'min': 0, 'max': 50, 'color': get_color_for_waermebedarf(25, is_spezific=True)},
            'niedrig': {'min': 50, 'max': 80, 'color': get_color_for_waermebedarf(65, is_spezific=True)},
            'mittel': {'min': 80, 'max': 120, 'color': get_color_for_waermebedarf(100, is_spezific=True)},
            'mittel_hoch': {'min': 120, 'max': 150, 'color': get_color_for_waermebedarf(135, is_spezific=True)},
            'hoch': {'min': 150, 'max': 200, 'color': get_color_for_waermebedarf(175, is_spezific=True)},
            'sehr_hoch': {'min': 200, 'max': None, 'color': get_color_for_waermebedarf(250, is_spezific=True)}  # None = unbegrenzt
        }
        
        return jsonify({
            'baualtersklasse': baualtersklassen_colors,
            'gebaeudetyp': gebaeudetypen_colors,
            'waermebedarf': waermebedarf_classes,
            'spez_waermebedarf': spez_waermebedarf_classes
        })
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/stats')
def get_stats():
    """API Endpoint für statistische Übersicht"""
    try:
        if buildings_data is None:
            load_data()
        
        stats = {
            'total_buildings': len(buildings_data),
        }
        
        # Bezugsfläche
        if 'bezugsflaeche' in buildings_data.columns:
            stats['total_area'] = float(buildings_data['bezugsflaeche'].sum())
        
        # Wärmebedarf
        if 'g_QH_sim' in buildings_data.columns and buildings_data['g_QH_sim'].notna().any():
            stats['waermebedarf_total'] = float(buildings_data['g_QH_sim'].sum())
            stats['waermebedarf_mean'] = float(buildings_data['g_QH_sim'].mean())
        elif 'g_QH' in buildings_data.columns:
            stats['waermebedarf_total'] = float(buildings_data['g_QH'].sum())
            stats['waermebedarf_mean'] = float(buildings_data['g_QH'].mean())
        
        # Spezifischer Wärmebedarf
        if 'ga_qH_sim' in buildings_data.columns and buildings_data['ga_qH_sim'].notna().any():
            stats['spez_waermebedarf_mean'] = float(buildings_data['ga_qH_sim'].mean())
        elif 'ga_qH' in buildings_data.columns:
            stats['spez_waermebedarf_mean'] = float(buildings_data['ga_qH'].mean())
        
        # Gebäudetypen
        if 'gebaeudetyp' in buildings_data.columns:
            stats['building_types'] = buildings_data['gebaeudetyp'].value_counts().to_dict()
        
        # Baualtersklassen
        if 'baualtersklasse' in buildings_data.columns:
            stats['baualtersklassen'] = buildings_data['baualtersklasse'].value_counts().to_dict()
        
        return jsonify(stats)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sanierung-assumptions', methods=['GET', 'POST'])
def sanierung_assumptions():
    """API Endpoint zum Laden/Speichern von Sanierungsannahmen."""
    if request.method == 'GET':
        return jsonify(load_sanierung_assumptions())

    data = request.json or {}
    normalized, error = normalize_sanierung_assumption(data)
    if error:
        return jsonify({'error': error}), 400

    assumptions = load_sanierung_assumptions()

    assumption_id = normalized.get('id') or str(uuid.uuid4())
    normalized['id'] = assumption_id

    assumptions = [a for a in assumptions if a.get('id') != assumption_id]
    assumptions.append(normalized)

    if not save_sanierung_assumptions(assumptions):
        return jsonify({'error': 'Sanierungsannahme konnte nicht gespeichert werden'}), 500

    return jsonify(assumptions)


@app.route('/api/klima-assumptions', methods=['GET', 'POST'])
def klima_assumptions():
    """API Endpoint zum Laden/Speichern von Klimaannahmen."""
    if request.method == 'GET':
        return jsonify(load_klima_assumptions())

    data = request.json or {}
    normalized, error = normalize_klima_assumption(data)
    if error:
        return jsonify({'error': error}), 400

    assumptions = load_klima_assumptions()

    assumption_id = normalized.get('id') or str(uuid.uuid4())
    normalized['id'] = assumption_id

    assumptions = [a for a in assumptions if a.get('id') != assumption_id]
    assumptions.append(normalized)

    if not save_klima_assumptions(assumptions):
        return jsonify({'error': 'Klimaannahme konnte nicht gespeichert werden'}), 500

    return jsonify(assumptions)


@app.route('/api/sanierung-zyklen', methods=['GET'])
def sanierung_zyklen():
    """API Endpoint für verfügbare Sanierungszyklen aus der Typologie."""
    try:
        return jsonify(get_available_sanierungszyklen())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/sanierung-simulate', methods=['POST'])
def sanierung_simulate():
    """
    Eingabe-GPKG nur aus computing_outputs. Gespeicherte Szenario-JSONs: simulation_assumptions/.
    Ergebnis-GPKG wieder nach computing_outputs.
    """
    global buildings_data, energy_parameters, current_data_filename
    try:
        data = request.json or {}
        input_filename = data.get('input_filename', None)

        if input_filename is None:
            if current_data_filename:
                input_filename = current_data_filename
            else:
                _, input_filename = pick_gpkg_from_outputs()

        gpkg_path = os.path.join(str(COMPUTE_OUTPUTS), input_filename)
        if not os.path.isfile(gpkg_path):
            return jsonify({'error': f'GeoPackage nicht in computing_outputs: {input_filename}'}), 404

        gdf = gpd.read_file(gpkg_path)

        # Sanierungsannahme bestimmen
        assumption = None
        assumption_id = data.get('assumption_id')
        if assumption_id:
            assumptions = load_sanierung_assumptions()
            for item in assumptions:
                if item.get('id') == assumption_id:
                    assumption = item
                    break

        if assumption is None:
            normalized, error = normalize_sanierung_assumption(data.get('assumption', {}))
            if error:
                return jsonify({'error': error}), 400
            assumption = normalized

            # Persistiere Annahme automatisch
            assumptions = load_sanierung_assumptions()
            assumption_id = assumption.get('id') or str(uuid.uuid4())
            assumption['id'] = assumption_id
            assumptions = [a for a in assumptions if a.get('id') != assumption_id]
            assumptions.append(assumption)
            save_sanierung_assumptions(assumptions)

        # Sanierung anwenden
        gdf, stats = apply_sanierung_simulation(gdf, assumption, energy_params=energy_parameters)

        # Speichere Ergebnis
        base_name = os.path.splitext(input_filename)[0]
        if base_name.endswith('_mit_energiebilanz'):
            base_name = base_name.replace('_mit_energiebilanz', '')
        output_filename = f'{base_name}_mit_sanierung.gpkg'
        os.makedirs(COMPUTE_OUTPUTS, exist_ok=True)
        output_path = os.path.join(str(COMPUTE_OUTPUTS), output_filename)
        gdf.to_file(output_path, driver='GPKG')

        buildings_data = gdf
        current_data_filename = output_filename

        return jsonify({
            'message': 'Sanierungssimulation erfolgreich durchgeführt',
            'input_file': input_filename,
            'output_file': output_filename,
            'output_path': output_path,
            'statistics': stats,
            'assumption_used': assumption
        })

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Fehler bei Sanierungssimulation: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


@app.route('/api/klima-simulate', methods=['POST'])
def klima_simulate():
    """
    Eingabe-GPKG nur aus computing_outputs. Gespeicherte Szenario-JSONs: simulation_assumptions/.
    Ergebnis-GPKG nach computing_outputs.
    """
    global buildings_data, energy_parameters, current_data_filename
    try:
        data = request.json or {}
        input_filename = data.get('input_filename', None)

        if input_filename is None:
            if current_data_filename:
                input_filename = current_data_filename
            else:
                _, input_filename = pick_gpkg_from_outputs()

        gpkg_path = os.path.join(str(COMPUTE_OUTPUTS), input_filename)
        if not os.path.isfile(gpkg_path):
            return jsonify({'error': f'GeoPackage nicht in computing_outputs: {input_filename}'}), 404

        gdf = gpd.read_file(gpkg_path)

        # Klimaannahme bestimmen
        assumption = None
        assumption_id = data.get('assumption_id')
        if assumption_id:
            assumptions = load_klima_assumptions()
            for item in assumptions:
                if item.get('id') == assumption_id:
                    assumption = item
                    break

        if assumption is None:
            normalized, error = normalize_klima_assumption(data.get('assumption', {}))
            if error:
                return jsonify({'error': error}), 400
            assumption = normalized

            # Persistiere Annahme automatisch
            assumptions = load_klima_assumptions()
            assumption_id = assumption.get('id') or str(uuid.uuid4())
            assumption['id'] = assumption_id
            assumptions = [a for a in assumptions if a.get('id') != assumption_id]
            assumptions.append(assumption)
            save_klima_assumptions(assumptions)

        # Klima anwenden
        gdf, stats = apply_klima_simulation(
            gdf,
            scenario=assumption['scenario'],
            year=assumption['year'],
            energy_params=energy_parameters
        )

        # Speichere Ergebnis
        base_name = os.path.splitext(input_filename)[0]
        for suffix in ['_mit_energiebilanz', '_mit_sanierung', '_mit_klima']:
            if base_name.endswith(suffix):
                base_name = base_name.replace(suffix, '')
        output_filename = f'{base_name}_mit_klima.gpkg'
        os.makedirs(COMPUTE_OUTPUTS, exist_ok=True)
        output_path = os.path.join(str(COMPUTE_OUTPUTS), output_filename)
        gdf.to_file(output_path, driver='GPKG')

        buildings_data = gdf
        current_data_filename = output_filename

        return jsonify({
            'message': 'Klima-Simulation erfolgreich durchgeführt',
            'input_file': input_filename,
            'output_file': output_filename,
            'output_path': output_path,
            'statistics': stats,
            'assumption_used': assumption
        })

    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        print(f"Fehler bei Klima-Simulation: {error_trace}")
        return jsonify({'error': str(e), 'traceback': error_trace}), 500


if __name__ == '__main__':
    # Lade Daten beim Start
    load_data()
    
    print("\n" + "="*60)
    print("🌍 Web-App gestartet!")
    print("📊 Öffne http://127.0.0.1:5001 im Browser")
    print(f"💾 Energie-Parameter: {len(energy_parameters)} Parameter (Standardwerte)")
    print("="*60 + "\n")
    
    app.run(debug=True, port=5001)

