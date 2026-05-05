"""Sanierungszyklus-Logik: U-Werte aus der Gebäudetypologie."""

import csv
from typing import Dict, List, Optional, Tuple

from paths import PARAMS_KLIMA_GEB


def _parse_float(value: str) -> Optional[float]:
    """Parst Float robust, gibt None bei Fehler zurück."""
    if value is None:
        return None
    s = str(value).strip().replace(',', '.')
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def baujahr_from_baualtersklasse(baualtersklasse: str) -> int:
    """Gibt repräsentatives Baujahr für eine Baualtersklasse zurück."""
    if not baualtersklasse:
        return 1919
    bal = str(baualtersklasse).strip().lower()
    if bal.startswith('vor'):
        return 1919
    if bal.startswith('nach'):
        return 2009
    if '-' in bal:
        try:
            return int(bal.split('-')[0].strip())
        except ValueError:
            return 1919
    try:
        return int(float(bal))
    except ValueError:
        return 1919


def load_sanierungszyklen_u_values(csv_path: Optional[str] = None) -> List[Tuple[int, Dict[str, float]]]:
    """
    Lädt Sanierungszyklen aus der Typologie-CSV.
    Gibt sortierte Liste von (Jahr, U-Wert-Dict) zurück.
    """
    target = csv_path or str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")
    for enc in ['utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-8']:
        try:
            with open(target, mode='r', encoding=enc, newline='') as f:
                reader = csv.reader(f, delimiter=';')
                cycles: List[Tuple[int, Dict[str, float]]] = []
                for row in reader:
                    if len(row) <= 20 or str(row[1]).strip() != "":
                        continue
                    year_val = _parse_float(row[14])
                    if year_val is None or not (1900 <= int(year_val) <= 2100):
                        continue
                    u_map = {}
                    for key, idx in [('dach', 15), ('wand', 17), ('fenster', 19), ('tuer', 20)]:
                        v = _parse_float(row[idx])
                        if v and v > 0:
                            u_map[key] = v
                    if u_map:
                        cycles.append((int(year_val), u_map))

                if cycles:
                    by_year: Dict[int, Dict[str, float]] = {}
                    for year, vals in cycles:
                        by_year[year] = vals
                    return sorted(by_year.items(), key=lambda x: x[0])
        except Exception:
            continue
    return []


def get_sanierungsjahr(baujahr: int, betrachtungsjahr: int, zyklus: int = 45) -> int:
    """Berechnet Sanierungsjahr nach 45-Jahres-Formel."""
    n = round((betrachtungsjahr - baujahr) / zyklus - 0.5)
    return baujahr + n * zyklus


def select_u_values_for_year(
    cycle_u_values: List[Tuple[int, Dict[str, float]]],
    sanierungsjahr: int,
) -> Dict[str, float]:
    """Wählt U-Werte passend zum Sanierungsjahr (größtes Jahr <= Sanierungsjahr)."""
    candidates = [entry for entry in cycle_u_values if entry[0] <= sanierungsjahr]
    return max(candidates, key=lambda x: x[0])[1] if candidates else {}
