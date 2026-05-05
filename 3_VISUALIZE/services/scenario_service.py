"""Verwaltung von Klima- und Sanierungsannahmen sowie Simulationsdateinamen."""

import json
import os
import uuid
from typing import Dict, List, Optional, Tuple

from shared.paths import SIMULATION_ASSUMPTIONS_DIR, VISUALIZE_DIR
from climate.loader import load_climate_solar_scenarios

_KLIMA_FILE = 'klima_assumptions.json'

SIM_FILENAME_SUFFIXES = [
    ('_mit_klima', 'klima'),
    ('_mit_sanierung', 'sanierung'),
    ('_mit_energiebilanz', None),
]
SIM_FILENAME_ORDER = ['klima', 'sanierung']


# --- Klima-Annahmen ---

def get_klima_assumptions_path() -> str:
    os.makedirs(SIMULATION_ASSUMPTIONS_DIR, exist_ok=True)
    return os.path.join(str(SIMULATION_ASSUMPTIONS_DIR), _KLIMA_FILE)


def load_klima_assumptions() -> List[Dict]:
    primary = get_klima_assumptions_path()
    legacy = os.path.join(str(VISUALIZE_DIR), _KLIMA_FILE)
    path = primary if os.path.exists(primary) else legacy
    if not os.path.exists(path):
        return []
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"Warnung: {e}")
        return []


def save_klima_assumptions(assumptions: List[Dict]) -> bool:
    try:
        with open(get_klima_assumptions_path(), 'w', encoding='utf-8') as f:
            json.dump(assumptions, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Fehler: {e}")
        return False


def normalize_klima_assumption(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    if not isinstance(data, dict):
        return None, 'Ungültige Datenstruktur'

    scenario = str(data.get('scenario', '')).strip().lower()
    try:
        climate_df = load_climate_solar_scenarios()
    except Exception as e:
        return None, f'Klimadaten konnten nicht geladen werden: {e}'

    available = sorted(climate_df['scenario'].astype(str).str.lower().unique().tolist())
    if scenario not in available:
        return None, f'Klimaszenario ungültig. Verfügbar: {", ".join(available)}'

    try:
        year = int(data.get('year'))
    except (ValueError, TypeError):
        return None, 'Jahr ist ungültig'

    years = climate_df[climate_df['scenario'].astype(str).str.lower() == scenario]['year'].astype(int).unique().tolist()
    if year not in years:
        mn, mx = (min(years), max(years)) if years else (None, None)
        return None, f'Jahr für {scenario} muss zwischen {mn} und {mx} liegen' if mn else f'Jahr für {scenario} nicht verfügbar'

    return {'id': data.get('id'), 'name': str(data.get('name', '')).strip() or f"Klima {scenario.upper()} {year}",
            'scenario': scenario, 'year': year}, None


# --- Gemeinsame Hilfsfunktionen ---

def assumption_payload_without_id(a: Dict) -> Dict:
    return {k: a.get(k) for k in sorted(a) if k != 'id'}


def find_exact_duplicate(assumptions: List[Dict], candidate: Dict, exclude_id: Optional[str] = None) -> Optional[Dict]:
    payload = assumption_payload_without_id(candidate)
    for item in assumptions:
        if exclude_id and item.get('id') == exclude_id:
            continue
        if assumption_payload_without_id(item) == payload:
            return item
    return None


def upsert_assumption(assumptions: List[Dict], candidate: Dict) -> Tuple[List[Dict], Dict]:
    """Fügt Annahme ein oder aktualisiert sie; entfernt Duplikate. Gibt (Liste, verwendete Annahme) zurück."""
    assumption_id = candidate.get('id') or str(uuid.uuid4())
    candidate['id'] = assumption_id
    duplicate = find_exact_duplicate(assumptions, candidate, exclude_id=assumption_id)
    assumptions = [a for a in assumptions if a.get('id') != assumption_id]
    if duplicate is None:
        assumptions.append(candidate)
        return assumptions, candidate
    return assumptions, duplicate


def build_simulation_output_filename(input_filename: str, simulation_tag: str) -> str:
    """Baut stabilen Ausgabedateinamen für Simulationsergebnisse."""
    base = os.path.splitext(input_filename)[0]
    tags = set()
    while True:
        matched = False
        for suffix, tag in SIM_FILENAME_SUFFIXES:
            if base.endswith(suffix):
                base = base[:-len(suffix)]
                if tag is not None:
                    tags.add(tag)
                matched = True
                break
        if not matched:
            break

    if simulation_tag in SIM_FILENAME_ORDER:
        tags.add(simulation_tag)

    combined = ''.join(f"_mit_{t}" for t in SIM_FILENAME_ORDER if t in tags)
    return f"{base}{combined}.gpkg"
