"""
Lädt die IWU-Gradtage-Daten aus CSV.
"""

import os
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from paths import PARAMS_KLIMA_GEB


@dataclass
class Klima:
    """Klimadaten-Struktur aus IWU-Gradtage-Daten"""
    year_start: int = 0  # Startjahr
    year_end: int = 0  # Endjahr
    month_start: int = 0  # Startmonat
    D: float = 0.0  # Tage
    TA: float = 0.0  # Mittlere Außentemperatur [°C]
    HD: float = 0.0  # Heiztage
    TA_HD: float = 0.0  # Mittlere Außentemperatur während Heizperiode [°C]
    HDD: float = 0.0  # Heating Degree Days
    RHDD: float = 0.0  # Relative Heating Degree Days
    CT: float = 0.0  # Korrekturfaktor
    G_Hor: float = 0.0  # Globale Strahlung horizontal [kWh/m²]
    G_Hor_HD: float = 0.0  # Globale Strahlung horizontal während Heizperiode [kWh/m²]
    G_E_HD: float = 0.0  # Globale Strahlung Ost während Heizperiode [kWh/m²]
    G_S_HD: float = 0.0  # Globale Strahlung Süd während Heizperiode [kWh/m²]
    G_W_HD: float = 0.0  # Globale Strahlung West während Heizperiode [kWh/m²]
    G_N_HD: float = 0.0  # Globale Strahlung Nord während Heizperiode [kWh/m²]


def parse_float_value(val):
    """Konvertiert einen Wert zu float, behandelt Komma als Dezimaltrennzeichen."""
    if pd.isna(val):
        return 0.0
    
    try:
        if isinstance(val, (int, float)):
            return float(val)
        
        val_str = str(val).strip()
        if not val_str or val_str == 'nan':
            return 0.0
        
        # Entferne Anführungszeichen falls vorhanden
        val_str = val_str.replace('"', '').replace("'", "")
        
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


def load_iwu_gradtage(csv_path: Optional[str] = None, klima_column: str = "Klima.2") -> Klima:
    """
    Lädt die IWU-Gradtage-Daten aus CSV.
    
    Parameters:
    -----------
    csv_path : Optional[str]
        Pfad zur CSV-Datei. Wenn None, wird nach IWU-gradtage.csv gesucht.
    klima_column : str
        Name der Klima-Spalte zu verwenden (Standard: "Klima.2")
    
    Returns:
    --------
    Klima
        Klima-Instanz mit geladenen Werten
    """
    # Suche nach CSV-Datei
    if csv_path is None:
        # Suche in verschiedenen Verzeichnissen
        script_dir = os.path.dirname(os.path.abspath(__file__))
        possible_paths = [
            str(PARAMS_KLIMA_GEB / "IWU-gradtage.csv"),
            os.path.join(script_dir, "IWU-gradtage.csv"),
            "IWU-gradtage.csv",
            "2_COMPUTE/IWU-gradtage.csv",
            "data/IWU-gradtage.csv",
            "../data/IWU-gradtage.csv",
        ]
        
        csv_path = None
        for path in possible_paths:
            if os.path.exists(path):
                csv_path = path
                break
        
        if csv_path is None:
            raise FileNotFoundError("IWU-gradtage.csv nicht gefunden. Bitte Pfad angeben.")
    
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"IWU-gradtage.csv nicht gefunden: {csv_path}")
    
    # Die CSV hat eine spezielle Struktur: jede Zeile ist komplett in Anführungszeichen
    # Format: "Parameter,""Wert1"",""Wert2"""
    klima_dict = {}
    
    with open(csv_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
        # Erste Zeile ist Header - finde Index der gewünschten Klima-Spalte
        header_line = lines[0].strip()
        klima_col_index = None
        
        # Parse Header: ",""Klima.1"",""Klima.2"""
        parts = header_line.split(',')
        for i, part in enumerate(parts):
            if klima_column in part:
                klima_col_index = i
                break
        
        if klima_col_index is None:
            raise ValueError(f"Klima-Spalte '{klima_column}' nicht in Header gefunden")
        
        # Parse Datenzeilen
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            
            # Entferne äußere Anführungszeichen
            if line.startswith('"') and line.endswith('"'):
                line = line[1:-1]
            
            # Split nach Komma, aber beachte doppelte Anführungszeichen
            parts = []
            current_part = ""
            in_quotes = False
            
            for char in line:
                if char == '"':
                    if in_quotes:
                        # Doppelte Anführungszeichen = escaped quote
                        current_part += '"'
                        in_quotes = False
                    else:
                        in_quotes = True
                elif char == ',' and not in_quotes:
                    parts.append(current_part)
                    current_part = ""
                else:
                    current_part += char
            
            if current_part:
                parts.append(current_part)
            
            if len(parts) <= klima_col_index:
                continue
            
            # Erste Spalte ist Parameter-Name, klima_col_index-te Spalte ist der Wert
            param_name = parts[0].strip().replace('"', '')
            klima_value_str = parts[klima_col_index].strip().replace('"', '')
            
            # Parse den Wert
            value = parse_float_value(klima_value_str)
            
            # Mappe Parameter-Namen zu Attributen
            if param_name == "Year_Start":
                klima_dict['year_start'] = int(value)
            elif param_name == "Year_End":
                klima_dict['year_end'] = int(value)
            elif param_name == "Month_Start":
                klima_dict['month_start'] = int(value)
            elif param_name == "D":
                klima_dict['D'] = value
            elif param_name == "TA":
                klima_dict['TA'] = value
            elif param_name == "HD":
                klima_dict['HD'] = value
            elif param_name == "TA_HD":
                klima_dict['TA_HD'] = value
            elif param_name == "HDD":
                klima_dict['HDD'] = value
            elif param_name == "RHDD":
                klima_dict['RHDD'] = value
            elif param_name == "CT":
                klima_dict['CT'] = value
            elif param_name == "G_Hor":
                klima_dict['G_Hor'] = value
            elif param_name == "G_Hor_HD":
                klima_dict['G_Hor_HD'] = value
            elif param_name == "G_E_HD":
                klima_dict['G_E_HD'] = value
            elif param_name == "G_S_HD":
                klima_dict['G_S_HD'] = value
            elif param_name == "G_W_HD":
                klima_dict['G_W_HD'] = value
            elif param_name == "G_N_HD":
                klima_dict['G_N_HD'] = value
    
    # Erstelle Klima-Instanz
    klima = Klima(**klima_dict)
    
    return klima
