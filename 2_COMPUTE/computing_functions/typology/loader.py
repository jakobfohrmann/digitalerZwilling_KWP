"""Lädt die Gebäudetypologie aus CSV."""

import os
from typing import List, Optional

import pandas as pd

from paths import PARAMS_KLIMA_GEB
from typology.models import Gebaeude


def parse_float_value(val) -> float:
    """Konvertiert Wert zu float; behandelt Komma als Dezimaltrenner, Punkt als Tausendertrenner."""
    if pd.isna(val):
        return 0.0
    try:
        if isinstance(val, (int, float)):
            return float(val)
        val_str = str(val).strip()
        if not val_str or val_str == 'nan':
            return 0.0
        if '.' in val_str and ',' in val_str:
            val_str = val_str.replace('.', '').replace(',', '.')
        elif ',' in val_str:
            val_str = val_str.replace(',', '.')
        return float(val_str)
    except (ValueError, TypeError):
        return 0.0


def convert_row_to_building(row: pd.Series) -> Gebaeude:
    """Konvertiert eine DataFrame-Zeile in eine Gebaeude-Instanz."""
    def s(idx, default=""): return str(row.iloc[idx]) if idx < len(row) and pd.notna(row.iloc[idx]) else default
    def f(idx): return parse_float_value(row.iloc[idx]) if idx < len(row) else 0.0

    a_dach, a_ogd, a_aw = f(8), f(9), f(10)
    a_kd, a_fen, a_tuer = f(11), f(12), f(13)
    u_dach, u_ogd, u_aw = f(15), f(16), f(17)
    u_kd, u_fen, u_tuer = f(18), f(19), f(20)

    return Gebaeude(
        reference=s(0), typ=s(1), bal=s(2),
        NGF=f(4), WFL=f(5), AN=f(6), V=f(7),
        A_dach=a_dach, A_ogd=a_ogd, A_aw=a_aw,
        A_kd=a_kd, A_fen=a_fen, A_tuer=a_tuer,
        A_summe=round(a_dach + a_ogd + a_aw + a_kd + a_fen + a_tuer, 2),
        U_dach=u_dach, U_ogd=u_ogd, U_aw=u_aw,
        U_kd=u_kd, U_fen=u_fen, U_tuer=u_tuer,
        U_summe=round(u_dach + u_ogd + u_aw + u_kd + u_fen + u_tuer, 2),
        U_wb=f(21),
        f_dach=f(22), f_ogd=f(23), f_aw=f(24),
        f_kd=f(25), f_fen=f(26), f_tuer=f(27),
        n_f=f(28), n_x=f(29),
        A_hor=f(30), A_ost=f(31), A_sued=f(32), A_west=f(33), A_nord=f(34),
        g_F=f(35), f_NA=f(36),
    )


def load_gebaeudetypologie(csv_path: Optional[str] = None) -> List[Gebaeude]:
    """Lädt die Gebäudetypologie aus CSV und gibt eine Liste von Gebaeude-Instanzen zurück."""
    if csv_path is None:
        candidates = [
            str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv"),
            "gebaeudetypologie.csv",
            "2_COMPUTE/gebaeudetypologie.csv",
        ]
        csv_path = next((p for p in candidates if os.path.exists(p)), None)
        if csv_path is None:
            raise FileNotFoundError(f"gebaeudetypologie.csv nicht gefunden. Gesuchte Pfade: {candidates}")

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV nicht gefunden: {csv_path}")

    df = None
    for enc in ['utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-8']:
        try:
            df = pd.read_csv(csv_path, sep=';', encoding=enc, skiprows=1, header=0,
                             on_bad_lines='skip', engine='python')
            if len(df.columns) > 1:
                break
        except Exception:
            continue

    if df is None or len(df.columns) <= 1:
        raise Exception(f"Konnte CSV nicht einlesen: {csv_path}")

    buildings = [
        convert_row_to_building(row)
        for _, row in df.iterrows()
        if str(row.iloc[0]).strip() not in ('', 'nan') and str(row.iloc[1]).strip() not in ('', 'nan')
    ]

    return [b for b in buildings if b.reference.startswith('Sub_')] + \
           [b for b in buildings if not b.reference.startswith('Sub_')]
