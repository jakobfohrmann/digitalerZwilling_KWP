"""
Lädt die Gebäudetypologie aus CSV und erstellt Gebaeude Instanzen.
"""

import os
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from paths import PARAMS_KLIMA_GEB


@dataclass
class Gebaeude:
    """Gebäude-Datenstruktur aus der Gebäudetypologie"""
    reference: str = ""  # Referenz/ID des Gebäudes (z.B. "EFH_01_Bestand")
    typ: str = ""  # Gebäudetyp (z.B. "EFH", "MFH", "RH")
    bal: str = ""  # Baualtersklasse (z.B. "vor 1919", "1919-1948")
    NGF: float = 0.0  # Netto-Grundfläche [m²]
    WFL: float = 0.0  # Wohnfläche [m²]
    AN: float = 0.0  # Gebäudenutzfläche nach EnEV [m²]
    V: float = 0.0  # beheiztes Gebäudevolumen [m³]
    A_dach: float = 0.0  # Außenbauteil Dach [m²]
    A_ogd: float = 0.0  # Außenbauteil oberste Geschossdecke [m²]
    A_aw: float = 0.0  # Außenbauteil Außenwand [m²]
    A_kd: float = 0.0  # Außenbauteil Kellerdecke [m²]
    A_fen: float = 0.0  # Außenbauteil Fenster [m²]
    A_tuer: float = 0.0  # Außenbauteil Außentür [m²]
    A_summe: float = 0.0  # Summe aller Außenbauteile [m²]
    U_dach: float = 0.0  # U-Wert Dach [W/m²K]
    U_ogd: float = 0.0  # U-Wert oberste Geschossdecke [W/m²K]
    U_aw: float = 0.0  # U-Wert Außenwand [W/m²K]
    U_kd: float = 0.0  # U-Wert Kellerdecke [W/m²K]
    U_fen: float = 0.0  # U-Wert Fenster [W/m²K]
    U_tuer: float = 0.0  # U-Wert Außentür [W/m²K]
    U_wb: float = 0.0  # U-Wert Wärmebrücke [W/m²K]
    U_summe: float = 0.0  # Summe aller U-Werte [W/m²K]
    f_dach: float = 0.0  # Faktor Dach [-]
    f_ogd: float = 0.0  # Faktor Geschossdecke [-]
    f_aw: float = 0.0  # Faktor Außenwand [-]
    f_kd: float = 0.0  # Faktor Kellerdecke [-]
    f_fen: float = 0.0  # Faktor Fenster [-]
    f_tuer: float = 0.0  # Faktor Außentür [-]
    n_f: float = 0.0  # minimale Luftwechselrate nmin,F [1/h]
    n_x: float = 0.0  # minimale Luftwechselrate nmin,x [1/h]
    A_hor: float = 0.0  # Außenfläche horizontal [m²]
    A_ost: float = 0.0  # Außenfläche Ost [m²]
    A_sued: float = 0.0  # Außenfläche Süd [m²]
    A_west: float = 0.0  # Außenfläche West [m²]
    A_nord: float = 0.0  # Außenfläche Nord [m²]
    g_F: float = 0.0  # Gesamtenergiedurchlassgrad Fenster [-]
    f_NA: float = 0.0  # Faktor Nachtabsenkung [-]
    


def parse_float_value(val):
    """Konvertiert einen Wert zu float, behandelt Komma als Dezimaltrennzeichen und Punkt als Tausendertrennzeichen."""
    if pd.isna(val):
        return 0.0
    
    try:
        if isinstance(val, (int, float)):
            return float(val)
        
        val_str = str(val).strip()
        if not val_str or val_str == 'nan':
            return 0.0
        
        # Wenn sowohl Punkt als auch Komma vorhanden sind, ist Punkt wahrscheinlich Tausendertrennzeichen
        if '.' in val_str and ',' in val_str:
            # Entferne Punkt (Tausendertrennzeichen) und ersetze Komma durch Punkt (Dezimaltrennzeichen)
            val_str = val_str.replace('.', '').replace(',', '.')
        elif ',' in val_str:
            # Nur Komma vorhanden -> Komma ist Dezimaltrennzeichen
            val_str = val_str.replace(',', '.')
        
        return float(val_str)
    except (ValueError, TypeError):
        return 0.0


def convert_row_to_building(row: pd.Series) -> Gebaeude:
    """Konvertiert eine DataFrame-Zeile in eine Gebaeude Instanz."""
    def safe_get_str(idx, default=""):
        if idx < len(row):
            val = row.iloc[idx]
            return str(val) if pd.notna(val) else default
        return default
    
    def safe_get_float(idx, default=0.0):
        if idx < len(row):
            return parse_float_value(row.iloc[idx])
        return default
    
    # Lade Basiswerte
    a_dach = safe_get_float(8)  # ABT,Dach [m²]
    a_ogd = safe_get_float(9)  # ABT,o.Geschossdecke [m²]
    a_aw = safe_get_float(10)  # ABT,Außenwand [m²]
    a_kd = safe_get_float(11)  # ABT,Kellerdecke [m²]
    a_fen = safe_get_float(12)  # ABT,Fenster [m²]
    a_tuer = safe_get_float(13)  # ABT,Außentür [m²]
    
    u_dach = safe_get_float(15)  # UDach [W/m²K]
    u_ogd = safe_get_float(16)  # Uo.Geschossdecke [W/m²K]
    u_aw = safe_get_float(17)  # UAußenwand [W/m²K]
    u_kd = safe_get_float(18)  # UKellerdecke [W/m²K]
    u_fen = safe_get_float(19)  # UFenster [W/m²K]
    u_tuer = safe_get_float(20)  # UAußentür [W/m²K]
    
    # Berechne Summen (auf 2 Nachkommastellen gerundet)
    a_summe = round(a_dach + a_ogd + a_aw + a_kd + a_fen + a_tuer, 2)
    u_summe = round(u_dach + u_ogd + u_aw + u_kd + u_fen + u_tuer, 2)
    
    return Gebaeude(
        reference=safe_get_str(0),  # Referenz
        typ=safe_get_str(1),  # Gebäudetyp
        bal=safe_get_str(2),  # Baualtersklasse
        NGF=safe_get_float(4),  # Netto-grundfläche [m²]
        WFL=safe_get_float(5),  # Wohnfläche [m²]
        AN=safe_get_float(6),  # Gebäudenutzfläche nach EnEV [m²]
        V=safe_get_float(7),  # beheiztes Gebäudevolumen [m³]
        A_dach=a_dach,
        A_ogd=a_ogd,
        A_aw=a_aw,
        A_kd=a_kd,
        A_fen=a_fen,
        A_tuer=a_tuer,
        A_summe=a_summe,  # Summe aller Außenbauteile [m²]
        U_dach=u_dach,
        U_ogd=u_ogd,
        U_aw=u_aw,
        U_kd=u_kd,
        U_fen=u_fen,
        U_tuer=u_tuer,
        U_summe=u_summe,  # Summe aller U-Werte [W/m²K]
        U_wb=safe_get_float(21),  # U-Wert Wärmebrücke [W/m²K]
        f_dach=safe_get_float(22),  # fK,Dach
        f_ogd=safe_get_float(23),  # fK,Geschoßdecke
        f_aw=safe_get_float(24),  # fK,Außenwand
        f_kd=safe_get_float(25),  # fK,Kellerdecke
        f_fen=safe_get_float(26),  # fK,Fenster
        f_tuer=safe_get_float(27),  # fK,Außentür
        n_f=safe_get_float(28),  # nmin,F [1/h]
        n_x=safe_get_float(29),  # nmin,x [1/h]
        A_hor=safe_get_float(30),  # AFF,Horizontal [m²]
        A_ost=safe_get_float(31),  # AFF,Ost [m²]
        A_sued=safe_get_float(32),  # AFF,Süd [m²]
        A_west=safe_get_float(33),  # AFF,West [m²]
        A_nord=safe_get_float(34),  # AFF,Nord [m²]
        g_F=safe_get_float(35),  # gF (Gesamtenergiedurchlassgrad Fenster)
        f_NA=safe_get_float(36),  # fNA (Faktor Nachtabsenkung)
    )


def load_gebaeudetypologie(csv_path: Optional[str] = None) -> List[Gebaeude]:
    """Lädt die Gebäudetypologie aus CSV und erstellt Gebaeude Instanzen."""
    if csv_path is None:
        # Versuche verschiedene Pfade in dieser Reihenfolge:
        possible_paths = [
            str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv"),
            "gebaeudetypologie.csv",
            "2_COMPUTE/gebaeudetypologie.csv",
            "data/gebaeudetypologie.csv",
            "../data/gebaeudetypologie.csv",
            "../2_COMPUTE/gebaeudetypologie.csv",
        ]
        
        csv_path = None
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break
        
        if csv_path is None:
            raise FileNotFoundError(
                f"CSV-Datei nicht gefunden. Gesuchte Pfade: {', '.join(possible_paths)}"
            )
    
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"CSV-Datei nicht gefunden: {csv_path}")
    
    df = None
    encodings = ['utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-8']
    
    for encoding in encodings:
        try:
            df = pd.read_csv(csv_path, sep=';', encoding=encoding, skiprows=1, header=0, on_bad_lines='skip', engine='python')
            if len(df.columns) > 1:
                break
        except (UnicodeDecodeError, Exception):
            continue
    
    if df is None or len(df.columns) <= 1:
        raise Exception(f"Konnte CSV-Datei nicht einlesen: {csv_path}")
    
    df_filtered = df.iloc[0:36] if len(df) >= 36 else df.iloc[0:]
    buildings = [convert_row_to_building(row) for _, row in df_filtered.iterrows()]
    buildings = [b for b in buildings if b.reference and b.reference.strip() != ""]
    
    return buildings

