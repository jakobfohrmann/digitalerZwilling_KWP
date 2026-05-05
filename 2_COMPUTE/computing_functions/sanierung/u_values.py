"""U-Wert-Zuordnung aus Sanierungstypologie."""

import os
from dataclasses import replace
from typing import Dict, List, Optional, Set

import pandas as pd

from paths import PARAMS_KLIMA_GEB
from sanierung.constants import SANIERUNG_DEPTHS, SANIERUNG_PARTS
from typology.models import Gebaeude


def _parse_float(val) -> float:
    if pd.isna(val):
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(',', '.')
        return float(s) if s and s != 'nan' else 0.0
    except (ValueError, TypeError):
        return 0.0


def load_sanierungs_typologie(csv_path: str = 'gebaeudetypologie.csv', csv_start_row: int = 49) -> pd.DataFrame:
    """Lädt den Sanierungsteil der Gebäudetypologie (ab Zeile csv_start_row)."""
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV nicht gefunden: {csv_path}")

    for enc in ['utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-8']:
        try:
            df = pd.read_csv(csv_path, sep=';', encoding=enc, skiprows=1, header=0,
                             on_bad_lines='skip', engine='python')
            if len(df.columns) > 1:
                return df.iloc[max(0, csv_start_row - 2):].copy()
        except Exception:
            continue
    raise Exception(f"Konnte CSV nicht einlesen: {csv_path}")


def find_matching_typologie_row(df: pd.DataFrame, gebaeudetyp: str, sanierungsjahr: int) -> Optional[pd.Series]:
    """Findet Sanierungszeile mit größtem Jahr <= sanierungsjahr."""
    if len(df.columns) < 15:
        return None

    san_col = df.columns[14]

    def parse_year(v) -> Optional[int]:
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    typ_values = df[df.columns[1]].astype(str).str.strip()
    generic = df[typ_values.isin(['', 'nan']) | typ_values.isna()]

    san_jahre = generic[san_col].apply(parse_year)
    valid = san_jahre.notna() & (san_jahre <= sanierungsjahr)
    if not valid.any():
        return None

    max_year = san_jahre[valid].max()
    result = generic[san_jahre == max_year]
    return result.iloc[0] if not result.empty else None


def get_sanierungs_u_values(
    df: pd.DataFrame, gebaeudetyp: str, sanierungsjahr: int
) -> Optional[Dict[str, float]]:
    """Holt U-Werte für Gebäudetyp und Sanierungsjahr aus der Typologie."""
    row = find_matching_typologie_row(df, gebaeudetyp, sanierungsjahr)
    if row is None:
        return None

    u_map = {}
    for key, idx in [('dach', 15), ('geschossdecke', 16), ('wand', 17), ('keller', 18), ('fenster', 19), ('tuer', 20)]:
        if idx < len(df.columns):
            col = df.columns[idx]
            if col in row.index:
                v = _parse_float(row[col])
                if v > 0:
                    u_map[key] = v
    return u_map or None


def get_sanierung_parts(depth: str, custom_parts: Optional[List[str]] = None) -> Set[str]:
    if depth in SANIERUNG_DEPTHS:
        return set(SANIERUNG_DEPTHS[depth])
    if depth == 'custom' and custom_parts:
        return {p for p in custom_parts if p in SANIERUNG_PARTS}
    return set()


def apply_u_values_to_gebaeude(
    gebaeude: Gebaeude,
    u_values: Optional[Dict[str, float]],
    parts: Set[str],
) -> Gebaeude:
    """Ersetzt U-Werte am Gebaeude entsprechend Sanierungstiefe."""
    if not u_values or not parts:
        return gebaeude

    g = gebaeude
    mapping = [
        ('dach', 'U_dach'), ('geschossdecke', 'U_ogd'), ('wand', 'U_aw'),
        ('keller', 'U_kd'), ('fenster', 'U_fen'), ('tuer', 'U_tuer'),
    ]
    for part, attr in mapping:
        if part in parts and part in u_values:
            g = replace(g, **{attr: u_values[part]})

    u_sum = round(g.U_dach + g.U_ogd + g.U_aw + g.U_kd + g.U_fen + g.U_tuer, 2)
    return replace(g, U_summe=u_sum)
