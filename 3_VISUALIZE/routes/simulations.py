"""Routen für Klima- und Sanierungssimulationen."""

import os
import traceback

import geopandas as gpd
from flask import Blueprint, jsonify, request

from shared.paths import COMPUTE_OUTPUTS
from sanierung import (
    load_sanierung_assumptions, save_sanierung_assumptions,
    normalize_sanierung_assumption, apply_sanierung_simulation,
    get_available_sanierungszyklen,
)
from climate.simulator import apply_klima_simulation
from services.data_service import pick_gpkg_from_outputs
from services.scenario_service import (
    load_klima_assumptions, save_klima_assumptions, normalize_klima_assumption,
    upsert_assumption, build_simulation_output_filename,
)

import services.data_service as ds

simulations_bp = Blueprint('simulations', __name__)


@simulations_bp.route('/api/sanierung-zyklen', methods=['GET'])
def sanierung_zyklen():
    try:
        return jsonify(get_available_sanierungszyklen())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@simulations_bp.route('/api/sanierung-assumptions', methods=['GET', 'POST'])
def sanierung_assumptions():
    if request.method == 'GET':
        return jsonify(load_sanierung_assumptions())

    normalized, error = normalize_sanierung_assumption(request.json or {})
    if error:
        return jsonify({'error': error}), 400

    assumptions, _ = upsert_assumption(load_sanierung_assumptions(), normalized)
    if not save_sanierung_assumptions(assumptions):
        return jsonify({'error': 'Konnte nicht gespeichert werden'}), 500
    return jsonify(assumptions)


@simulations_bp.route('/api/klima-assumptions', methods=['GET', 'POST'])
def klima_assumptions():
    if request.method == 'GET':
        return jsonify(load_klima_assumptions())

    normalized, error = normalize_klima_assumption(request.json or {})
    if error:
        return jsonify({'error': error}), 400

    assumptions, _ = upsert_assumption(load_klima_assumptions(), normalized)
    if not save_klima_assumptions(assumptions):
        return jsonify({'error': 'Konnte nicht gespeichert werden'}), 500
    return jsonify(assumptions)


@simulations_bp.route('/api/sanierung-simulate', methods=['POST'])
def sanierung_simulate():
    try:
        data = request.json or {}
        input_filename = data.get('input_filename') or ds.current_data_filename
        if not input_filename:
            _, input_filename = pick_gpkg_from_outputs()

        gpkg_path = os.path.join(str(COMPUTE_OUTPUTS), input_filename)
        if not os.path.isfile(gpkg_path):
            return jsonify({'error': f'GeoPackage nicht in computing_outputs: {input_filename}'}), 404

        assumption = _resolve_sanierung_assumption(data)
        if isinstance(assumption, tuple):
            return assumption

        gdf = gpd.read_file(gpkg_path)
        gdf, stats = apply_sanierung_simulation(gdf, assumption, energy_params=ds.energy_parameters)

        output_filename = build_simulation_output_filename(input_filename, 'sanierung')
        os.makedirs(COMPUTE_OUTPUTS, exist_ok=True)
        out_path = os.path.join(str(COMPUTE_OUTPUTS), output_filename)
        gdf.to_file(out_path, driver='GPKG')

        ds.buildings_data = gdf
        ds.current_data_filename = output_filename

        return jsonify({'message': 'Sanierungssimulation abgeschlossen', 'input_file': input_filename,
                        'output_file': output_filename, 'statistics': stats, 'assumption_used': assumption})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


@simulations_bp.route('/api/klima-simulate', methods=['POST'])
def klima_simulate():
    try:
        data = request.json or {}
        input_filename = data.get('input_filename') or ds.current_data_filename
        if not input_filename:
            _, input_filename = pick_gpkg_from_outputs()

        gpkg_path = os.path.join(str(COMPUTE_OUTPUTS), input_filename)
        if not os.path.isfile(gpkg_path):
            return jsonify({'error': f'GeoPackage nicht in computing_outputs: {input_filename}'}), 404

        assumption = _resolve_klima_assumption(data)
        if isinstance(assumption, tuple):
            return assumption

        gdf = gpd.read_file(gpkg_path)
        gdf, stats = apply_klima_simulation(gdf, scenario=assumption['scenario'],
                                             year=assumption['year'], energy_params=ds.energy_parameters)

        output_filename = build_simulation_output_filename(input_filename, 'klima')
        os.makedirs(COMPUTE_OUTPUTS, exist_ok=True)
        out_path = os.path.join(str(COMPUTE_OUTPUTS), output_filename)
        gdf.to_file(out_path, driver='GPKG')

        ds.buildings_data = gdf
        ds.current_data_filename = output_filename

        return jsonify({'message': 'Klima-Simulation abgeschlossen', 'input_file': input_filename,
                        'output_file': output_filename, 'statistics': stats, 'assumption_used': assumption})
    except Exception as e:
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500


def _resolve_sanierung_assumption(data: dict):
    """Lädt oder normalisiert + persistiert eine Sanierungsannahme."""
    if data.get('assumption_id'):
        for item in load_sanierung_assumptions():
            if item.get('id') == data['assumption_id']:
                return item

    normalized, error = normalize_sanierung_assumption(data.get('assumption', {}))
    if error:
        return jsonify({'error': error}), 400

    assumptions, used = upsert_assumption(load_sanierung_assumptions(), normalized)
    save_sanierung_assumptions(assumptions)
    return used


def _resolve_klima_assumption(data: dict):
    """Lädt oder normalisiert + persistiert eine Klimaannahme."""
    if data.get('assumption_id'):
        for item in load_klima_assumptions():
            if item.get('id') == data['assumption_id']:
                return item

    normalized, error = normalize_klima_assumption(data.get('assumption', {}))
    if error:
        return jsonify({'error': error}), 400

    assumptions, used = upsert_assumption(load_klima_assumptions(), normalized)
    save_klima_assumptions(assumptions)
    return used
