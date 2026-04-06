"""
Gemeinsame Hilfsfunktionen für Compute/Visualize.
"""

from typing import Optional, Dict, List

import numpy as np
import pandas as pd


ENERGIE_SPALTEN: List[str] = [
    'c_QT',
    'c0_QT',
    'd_QL',
    'd0_QL',
    'e_QS',
    'f_QI',
    'g_QH',
    'ga_qH',
    'ga0_qH',
]


def baujahr_to_baualtersklasse(baujahr: float) -> Optional[str]:
    """Konvertiert Baujahr in Baualtersklasse."""
    if pd.isna(baujahr):
        return None
    try:
        baujahr_int = int(float(baujahr))
    except (ValueError, TypeError):
        return None

    if baujahr_int < 1919:
        return "vor 1919"
    if 1919 <= baujahr_int <= 1948:
        return "1919-1948"
    if 1949 <= baujahr_int <= 1957:
        return "1949-1957"
    if 1958 <= baujahr_int <= 1968:
        return "1958-1968"
    if 1969 <= baujahr_int <= 1978:
        return "1969-1978"
    if 1979 <= baujahr_int <= 1983:
        return "1979-1983"
    if 1984 <= baujahr_int <= 1994:
        return "1984-1994"
    if 1995 <= baujahr_int <= 2001:
        return "1995-2001"
    if 2002 <= baujahr_int <= 2009:
        return "2002-2009"
    # ab 2010 = nach 2009
    return "nach 2009"


def find_matching_referenz(gebaeudetyp: str, bal: str, energie_liste: list, gebaeude_liste: list):
    """Findet passende Referenz-Energiebilanz basierend auf Gebäudetyp und Baualtersklasse."""
    if pd.isna(gebaeudetyp) or bal is None:
        return None

    for energie, gebaeude in zip(energie_liste, gebaeude_liste):
        if gebaeude.typ == gebaeudetyp and gebaeude.bal == bal:
            return energie

    return None


def scale_energie_values(
    energie_ref,
    bezugsflaeche_gebaeude: float,
    bezugsflaeche_referenz: float,
) -> Dict[str, float]:
    """Skaliert Energiebilanzwerte basierend auf Bezugsfläche (GPKG) vs. Referenz AN (Typologie)."""
    if bezugsflaeche_referenz == 0 or pd.isna(bezugsflaeche_gebaeude) or pd.isna(bezugsflaeche_referenz):
        return {col: np.nan for col in ENERGIE_SPALTEN}

    scale_factor = bezugsflaeche_gebaeude / bezugsflaeche_referenz

    return {
        'c_QT': energie_ref.c_QT * scale_factor,
        'c0_QT': energie_ref.c0_QT * scale_factor,
        'd_QL': energie_ref.d_QL * scale_factor,
        'd0_QL': energie_ref.d0_QL * scale_factor,
        'e_QS': energie_ref.e_QS * scale_factor,
        'f_QI': energie_ref.f_QI * scale_factor,
        'g_QH': energie_ref.g_QH * scale_factor,
        'ga_qH': energie_ref.ga_qH,
        'ga0_qH': energie_ref.ga0_qH,
    }
