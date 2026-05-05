"""Gemeinsame Hilfsfunktionen für Compute und Visualize."""
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


ENERGIE_SPALTEN: List[str] = [
    'c_QT', 'c_QT_saniert', 'd_QL', 'e_QS', 'f_QI',
    'g_QH', 'g_QH_saniert', 'ga_qH', 'ga_qH_saniert',
]


def baujahr_to_baualtersklasse(baujahr: float) -> Optional[str]:
    if pd.isna(baujahr):
        return None
    try:
        y = int(float(baujahr))
    except (ValueError, TypeError):
        return None
    if y < 1919:        return "vor 1919"
    if y <= 1948:       return "1919-1948"
    if y <= 1957:       return "1949-1957"
    if y <= 1968:       return "1958-1968"
    if y <= 1978:       return "1969-1978"
    if y <= 1983:       return "1979-1983"
    if y <= 1994:       return "1984-1994"
    if y <= 2001:       return "1995-2001"
    if y <= 2009:       return "2002-2009"
    return "nach 2009"


def get_gebaeudetyp_fallback_chain(gebaeudetyp: str) -> List[str]:
    if pd.isna(gebaeudetyp):
        return []
    typ = str(gebaeudetyp).strip().upper()
    if typ == "HH":  return ["HH", "GMH", "MFH"]
    if typ == "GMH": return ["GMH", "MFH"]
    return [typ]


def find_matching_referenz_and_gebaeude(
    gebaeudetyp: str, bal: str, energie_liste: list, gebaeude_liste: list,
) -> Tuple[Optional[Any], Optional[Any]]:
    if pd.isna(gebaeudetyp) or bal is None:
        return None, None
    for typ in get_gebaeudetyp_fallback_chain(gebaeudetyp):
        for energie, gebaeude in zip(energie_liste, gebaeude_liste):
            if str(gebaeude.typ).strip().upper() == typ and gebaeude.bal == bal:
                return energie, gebaeude
    return None, None


def find_matching_referenz(gebaeudetyp: str, bal: str, energie_liste: list, gebaeude_liste: list):
    energie, _ = find_matching_referenz_and_gebaeude(gebaeudetyp, bal, energie_liste, gebaeude_liste)
    return energie


def scale_energie_values(
    energie_ref, bezugsflaeche_gebaeude: float, bezugsflaeche_referenz: float,
) -> Dict[str, float]:
    if bezugsflaeche_referenz == 0 or pd.isna(bezugsflaeche_gebaeude) or pd.isna(bezugsflaeche_referenz):
        return {col: np.nan for col in ENERGIE_SPALTEN}
    sf = bezugsflaeche_gebaeude / bezugsflaeche_referenz
    return {
        'c_QT':           energie_ref.c_QT * sf,
        'c_QT_saniert':   energie_ref.c_QT_saniert * sf,
        'd_QL':           energie_ref.d_QL * sf,
        'e_QS':           energie_ref.e_QS * sf,
        'f_QI':           energie_ref.f_QI * sf,
        'g_QH':           energie_ref.g_QH * sf,
        'g_QH_saniert':   energie_ref.g_QH_saniert * sf,
        'ga_qH':          energie_ref.ga_qH,
        'ga_qH_saniert':  energie_ref.ga_qH_saniert,
    }
