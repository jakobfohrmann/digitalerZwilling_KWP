"""Routen für Gebäudedaten, Layer und Statistiken."""

import pandas as pd
from flask import Blueprint, jsonify, request, render_template

from climate.loader import load_climate_solar_scenarios
from services.data_service import (
    buildings_data, current_data_filename,
    load_data, list_gpkg_in_outputs, get_preferred_sim_value,
)
from services.color_service import (
    prepare_geojson_for_layer, normalize_spez_scenario, get_spez_waermebedarf_value,
    get_spez_scenario_availability, get_color_for_waermebedarf, get_color_for_gebaeudetyp,
    get_color_for_baualtersklasse, SPEZ_SCENARIO_COLUMN_MAP,
)
from helpers import baujahr_to_baualtersklasse

import services.data_service as ds

buildings_bp = Blueprint('buildings', __name__)

_VALID_LAYERS = ['waermebedarf', 'spez_waermebedarf', 'gebaeudetyp', 'baualtersklasse']


@buildings_bp.route('/')
def index():
    return render_template("map.html")


@buildings_bp.route('/api/klima-options', methods=['GET'])
def klima_options():
    try:
        df = load_climate_solar_scenarios()
        scenarios = sorted(df['scenario'].astype(str).str.lower().unique().tolist())
        years_by_scenario = {
            s: sorted(df[df['scenario'].astype(str).str.lower() == s]['year'].astype(int).unique().tolist())
            for s in scenarios
        }
        return jsonify({'scenarios': scenarios, 'years': sorted(df['year'].astype(int).unique().tolist()),
                        'years_by_scenario': years_by_scenario})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/layer/<layer_type>')
def get_layer(layer_type: str):
    try:
        if ds.buildings_data is None:
            load_data()
        if layer_type not in _VALID_LAYERS:
            return jsonify({'error': f'Ungültiger Layer. Erlaubt: {_VALID_LAYERS}'}), 400
        spez_scenario = normalize_spez_scenario(request.args.get('spez_scenario'))
        return jsonify(prepare_geojson_for_layer(ds.buildings_data, layer_type, spez_scenario=spez_scenario))
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/spez-waermebedarf-scenarios', methods=['GET'])
def get_spez_waermebedarf_scenarios():
    try:
        if ds.buildings_data is None:
            load_data()
        return jsonify({'options': get_spez_scenario_availability(ds.buildings_data), 'default': 'unsaniert'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/data-files', methods=['GET'])
def get_data_files():
    try:
        files = list_gpkg_in_outputs()
        if not files:
            return jsonify({'files': [], 'current_file': ds.current_data_filename,
                            'error': 'Keine .gpkg in computing_outputs gefunden'}), 404
        return jsonify({'files': files, 'current_file': ds.current_data_filename or files[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/data-select', methods=['POST'])
def select_data_file():
    try:
        filename = str((request.json or {}).get('filename', '')).strip()
        if not filename:
            return jsonify({'error': 'Dateiname fehlt'}), 400
        load_data(input_filename=filename)
        return jsonify({'message': 'Datensatz geladen', 'current_file': ds.current_data_filename})
    except FileNotFoundError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/building/<building_id>')
def get_building(building_id: str):
    try:
        if ds.buildings_data is None:
            load_data()
        gdf = ds.buildings_data

        id_col = next((c for c in ['lod1_gml_id', 'identifikator', 'id', 'fid', 'objectid'] if c in gdf.columns), None)
        if id_col is None:
            return jsonify({'error': 'Keine ID-Spalte gefunden'}), 400

        building = gdf[gdf[id_col].astype(str) == str(building_id)]
        if building.empty:
            try:
                building = gdf[gdf[id_col] == int(building_id)]
            except (ValueError, TypeError):
                pass
        if building.empty:
            return jsonify({'error': f'Gebäude {building_id} nicht gefunden'}), 404

        row = building.iloc[0]
        spez_scenario = normalize_spez_scenario(request.args.get('spez_scenario'))
        ga_qh_sim = get_spez_waermebedarf_value(row, spez_scenario)
        g_qh_sim = get_preferred_sim_value(row, 'g_QH')

        geschossanzahl = None
        for col in ['anzahl_geschosse', 'anzahlDOberirdischenGeschosse', 'anzahl_oberirdische_geschosse']:
            if col in row and pd.notna(row.get(col)):
                try:
                    v = float(row[col])
                    geschossanzahl = int(round(v)) if abs(v - round(v)) < 1e-6 else v
                    break
                except (TypeError, ValueError):
                    continue

        return jsonify({
            'id': str(row.get(id_col, '')),
            'baujahr': int(row['baujahr']) if pd.notna(row.get('baujahr')) else None,
            'gebaeudetyp': str(row['gebaeudetyp']) if pd.notna(row.get('gebaeudetyp')) else None,
            'bezugsflaeche': float(row['bezugsflaeche']) if pd.notna(row.get('bezugsflaeche')) else None,
            'geschossanzahl': geschossanzahl,
            'baualtersklasse': str(row['baualtersklasse']) if pd.notna(row.get('baualtersklasse')) else None,
            'spez_waermebedarf_unsaniert': float(row['ga_qH']) if pd.notna(row.get('ga_qH')) else None,
            'spez_waermebedarf_saniert': float(row['ga_qH_saniert']) if pd.notna(row.get('ga_qH_saniert')) else None,
            'spez_waermebedarf': float(ga_qh_sim) if pd.notna(ga_qh_sim) else (float(row['ga_qH']) if pd.notna(row.get('ga_qH')) else None),
            'waermebedarf': float(g_qh_sim) if pd.notna(g_qh_sim) else (float(row['g_QH']) if pd.notna(row.get('g_QH')) else None),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/legend-colors')
def get_legend_colors():
    try:
        bal_classes = ['vor 1919', '1919-1948', '1949-1957', '1958-1968', '1969-1978',
                       '1979-1983', '1984-1994', '1995-2001', '2002-2009', 'nach 2009']
        wb_samples = [(250, None), (200, 250), (160, 200), (130, 160), (100, 130),
                      (75, 100), (50, 75), (30, 50), (0, 30)]
        spez_samples = [(250, None), (200, 250), (160, 200), (130, 160), (100, 130),
                        (75, 100), (50, 75), (30, 50), (0, 30)]

        return jsonify({
            'baualtersklasse': {c: get_color_for_baualtersklasse(c) for c in bal_classes},
            'gebaeudetyp': {t: get_color_for_gebaeudetyp(t) for t in ['EFH', 'RH', 'MFH', 'GMH', 'HH']},
            'waermebedarf': {
                f"klasse_{i}": {'min': mn * 1000, 'max': mx * 1000 if mx else None,
                                'color': get_color_for_waermebedarf((mn + (mx or mn + 50)) / 2 * 1000, is_spezific=False)}
                for i, (mn, mx) in enumerate([(0, 50), (50, 80), (80, 120), (120, 150), (150, 200), (200, None)])
            },
            'spez_waermebedarf': {
                f"klasse_{name}": {'min': mn, 'max': mx,
                                   'color': get_color_for_waermebedarf((mn + (mx or mn + 50)) / 2, is_spezific=True)}
                for name, mn, mx in [
                    ('a_plus', 0, 30), ('a', 30, 50), ('b', 50, 75), ('c', 75, 100),
                    ('d', 100, 130), ('e', 130, 160), ('f', 160, 200), ('g', 200, 250), ('h', 250, None),
                ]
            },
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@buildings_bp.route('/api/stats')
def get_stats():
    try:
        if ds.buildings_data is None:
            load_data()
        gdf = ds.buildings_data
        stats = {'total_buildings': len(gdf)}

        if 'bezugsflaeche' in gdf.columns:
            stats['total_area'] = float(gdf['bezugsflaeche'].sum())

        for col in ['g_QH_sim_klima', 'g_QH_sim_saniert', 'g_QH']:
            if col in gdf.columns and gdf[col].notna().any():
                stats['waermebedarf_total'] = float(gdf[col].sum())
                stats['waermebedarf_mean'] = float(gdf[col].mean())
                break

        spez_col = SPEZ_SCENARIO_COLUMN_MAP[normalize_spez_scenario(request.args.get('spez_scenario'))]
        src_col = spez_col if (spez_col in gdf.columns and gdf[spez_col].notna().any()) else 'ga_qH'
        if src_col in gdf.columns and gdf[src_col].notna().any():
            stats['spez_waermebedarf_mean'] = float(gdf[src_col].mean())

        if 'gebaeudetyp' in gdf.columns:
            stats['building_types'] = gdf['gebaeudetyp'].value_counts().to_dict()
        if 'baualtersklasse' in gdf.columns:
            stats['baualtersklassen'] = gdf['baualtersklasse'].value_counts().to_dict()

        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
