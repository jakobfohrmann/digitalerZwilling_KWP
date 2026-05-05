"""Farbzuordnungen und GeoJSON-Layer-Aufbereitung."""

import json
from typing import Dict, List, Optional

import geopandas as gpd
import pandas as pd

from shared.helpers import baujahr_to_baualtersklasse
from services.data_service import get_preferred_sim_value

SPEZ_SCENARIO_COLUMN_MAP = {
    'unsaniert':      'ga_qH',
    'groeger_saniert':'ga_qH_saniert',
    'sim_saniert':    'ga_qH_sim_saniert',
    'sim_klima':      'ga_qH_sim_klima',
}

SPEZ_SCENARIO_LABELS = {
    'unsaniert':      'Unsaniert',
    'groeger_saniert':'Saniert nach Groeger-Annahme',
    'sim_saniert':    'Simulation Sanierung',
    'sim_klima':      'Simulation Klima',
}


def normalize_spez_scenario(scenario: Optional[str]) -> str:
    key = str(scenario or '').strip().lower()
    return key if key in SPEZ_SCENARIO_COLUMN_MAP else 'unsaniert'


def get_spez_waermebedarf_value(record: dict, scenario: Optional[str]):
    col = SPEZ_SCENARIO_COLUMN_MAP[normalize_spez_scenario(scenario)]
    v = record.get(col)
    return v if pd.notna(v) else None


def get_spez_scenario_availability(gdf: gpd.GeoDataFrame) -> List[Dict]:
    return [
        {
            'id': sid,
            'label': SPEZ_SCENARIO_LABELS[sid],
            'column': col,
            'available': bool(col in gdf.columns and gdf[col].notna().any()),
            'reason': None if (col in gdf.columns and gdf[col].notna().any()) else f'Spalte {col} fehlt oder leer',
        }
        for sid, col in SPEZ_SCENARIO_COLUMN_MAP.items()
    ]


def get_color_for_waermebedarf(value: float, is_spezific: bool = True) -> str:
    if pd.isna(value) or value == 0:
        return '#95a5a6'
    if is_spezific:
        thresholds = [(250, '#a50026'), (200, '#d73027'), (160, '#f46d43'), (130, '#fdae61'),
                      (100, '#fee08b'), (75, '#d9ef8b'), (50, '#a6d96a'), (30, '#66bd63')]
        for t, c in thresholds:
            if value > t:
                return c
        return '#1a9850'
    else:
        n = value / 1000
        for t, c in [(200, '#e74c3c'), (150, '#e67e22'), (120, '#f39c12'), (80, '#f1c40f'), (50, '#52be80')]:
            if n > t:
                return c
        return '#2ecc71'


def get_color_for_gebaeudetyp(gebaeudetyp: str) -> str:
    return {'EFH': '#3498db', 'RH': '#9b59b6', 'MFH': '#e74c3c', 'GMH': '#f39c12', 'HH': '#1abc9c'}.get(gebaeudetyp, '#95a5a6')


def get_color_for_baualtersklasse(baualtersklasse: str) -> str:
    return {
        'vor 1919': '#1e3a5f', '1919-1948': '#2c5f8f', '1949-1957': '#3d7ab8',
        '1958-1968': '#4a8fc7', '1969-1978': '#5a9fd4', '1979-1983': '#6eb0e0',
        '1984-1994': '#8bc4e8', '1995-2001': '#a8d4f0', '2002-2009': '#c5e3f5',
        'nach 2009': '#e8f4f8',
    }.get(baualtersklasse, '#95a5a6')


def prepare_geojson_for_layer(
    gdf: gpd.GeoDataFrame,
    layer_type: str,
    spez_scenario: str = 'unsaniert',
) -> Dict:
    """Bereitet GeoJSON für einen Layer vor und fügt _layer_color/_layer_value hinzu."""
    gdf_web = gdf.copy()
    if gdf_web.crs and gdf_web.crs.to_epsg() != 4326:
        gdf_web = gdf_web.to_crs('EPSG:4326')

    geojson = json.loads(gdf_web.to_json())

    for feature in geojson['features']:
        props = feature['properties']

        if layer_type == 'waermebedarf':
            v = get_preferred_sim_value(props, 'g_QH') or 0
            props['_layer_value'] = v
            props['_layer_color'] = get_color_for_waermebedarf(v, is_spezific=False)

        elif layer_type == 'spez_waermebedarf':
            v = get_spez_waermebedarf_value(props, spez_scenario) or 0
            props['_layer_value'] = v
            props['_layer_color'] = get_color_for_waermebedarf(v, is_spezific=True)

        elif layer_type == 'gebaeudetyp':
            t = props.get('gebaeudetyp', 'Unbekannt')
            props['_layer_value'] = t
            props['_layer_color'] = get_color_for_gebaeudetyp(t)

        elif layer_type == 'baualtersklasse':
            bal = props.get('baualtersklasse') or baujahr_to_baualtersklasse(props.get('baujahr'))
            props['_layer_value'] = bal or 'Unbekannt'
            props['_layer_color'] = get_color_for_baualtersklasse(bal) if bal else '#95a5a6'

    return geojson
