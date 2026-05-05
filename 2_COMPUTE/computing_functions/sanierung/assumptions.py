"""CRUD für Sanierungsannahmen (JSON-Persistenz)."""

import json
import os
from typing import Dict, List, Optional, Tuple

import pandas as pd

from paths import PARAMS_KLIMA_GEB, SIMULATION_ASSUMPTIONS_DIR, VISUALIZE_DIR
from sanierung.constants import SANIERUNG_DEPTHS, SANIERUNG_PARTS

_PARAMS_FILE = 'sanierung_assumptions.json'


def get_assumptions_path() -> str:
    os.makedirs(SIMULATION_ASSUMPTIONS_DIR, exist_ok=True)
    return os.path.join(str(SIMULATION_ASSUMPTIONS_DIR), _PARAMS_FILE)


def load_sanierung_assumptions() -> List[Dict]:
    primary = get_assumptions_path()
    legacy = os.path.join(str(VISUALIZE_DIR), _PARAMS_FILE)
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


def save_sanierung_assumptions(assumptions: List[Dict]) -> bool:
    try:
        with open(get_assumptions_path(), 'w', encoding='utf-8') as f:
            json.dump(assumptions, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Fehler: {e}")
        return False


def parse_sanierungszyklus_start(cycle: str) -> Optional[int]:
    """Extrahiert Startjahr aus Zyklus-String (z.B. '2002-2009' → 2002)."""
    if not cycle:
        return None
    s = str(cycle).strip().lower()
    if s.startswith('vor'):
        return 1919
    if s.startswith('nach'):
        return 2009
    if '-' in s:
        try:
            return int(s.split('-')[0])
        except ValueError:
            return None
    try:
        return int(s)
    except ValueError:
        return None


def get_available_sanierungszyklen() -> List[str]:
    """Liest verfügbare Sanierungszyklen aus der Typologie-CSV."""
    from sanierung.u_values import load_sanierungs_typologie
    csv_path = str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")
    df = load_sanierungs_typologie(csv_path=csv_path)
    if len(df.columns) < 15:
        return []

    values = []
    for val in df[df.columns[14]].dropna():
        try:
            values.append(str(int(float(str(val).strip()))))
        except ValueError:
            values.append(str(val).strip())

    return sorted(set(v for v in values if v), key=lambda x: parse_sanierungszyklus_start(x) or 0)


def normalize_sanierung_assumption(data: Dict) -> Tuple[Optional[Dict], Optional[str]]:
    """Validiert und normalisiert Sanierungsannahmen."""
    if not isinstance(data, dict):
        return None, 'Ungültige Datenstruktur'

    try:
        density = float(data.get('density', 0))
    except (ValueError, TypeError):
        return None, 'Ungültiger Wert für Sanierungsdichte'
    if not (0 <= density <= 100):
        return None, 'Sanierungsdichte muss zwischen 0 und 100 liegen'

    try:
        baujahr_from = int(data['baujahr_from']) if data.get('baujahr_from') not in (None, '') else None
        baujahr_to = int(data['baujahr_to']) if data.get('baujahr_to') not in (None, '') else None
    except (ValueError, TypeError):
        return None, 'Ungültiger Baujahrbereich'

    building_types = data.get('building_types') or []
    if isinstance(building_types, str):
        building_types = [building_types]
    building_types = [t for t in building_types if t]

    custom_parts = data.get('custom_parts') or []
    depth = str(data.get('depth', 'vollsaniert')).strip() or 'vollsaniert'

    return {
        'id': data.get('id'),
        'name': str(data.get('name', '')).strip() or 'Sanierungsannahme',
        'density': density,
        'cycle': str(data.get('cycle', '')).strip(),
        'depth': depth,
        'building_types': building_types,
        'baujahr_from': baujahr_from,
        'baujahr_to': baujahr_to,
        'custom_parts': custom_parts if isinstance(custom_parts, list) else [],
    }, None
