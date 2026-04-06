"""
Berechnet Energiebilanzwerte für tatsächliche Gebäude basierend auf Referenzgebäuden.
"""

import os
import sys
from pathlib import Path
from typing import Dict, Optional

_COMPUTE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_COMPUTE_DIR / "computing_functions"))

from paths import COMPUTE_INPUTS, COMPUTE_OUTPUTS

import geopandas as gpd
import numpy as np
import pandas as pd
from energie_ref_berechnung import Energie, create_energie_instanzen
from gebaeudetypologie_loader import load_gebaeudetypologie
from helpers import baujahr_to_baualtersklasse, find_matching_referenz, scale_energie_values, ENERGIE_SPALTEN


def add_energiebilanz_to_gebaeude(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Fügt Energiebilanzwerte zu Gebäuden hinzu basierend auf Referenzgebäuden."""
    print("Lade Referenz-Energiebilanzwerte...")
    energie_liste = create_energie_instanzen()
    gebaeude_liste = load_gebaeudetypologie()
    
    print(f"✓ {len(energie_liste)} Referenz-Energiebilanzen geladen")
    
    # Initialisiere neue Spalten
    for col in ENERGIE_SPALTEN:
        gdf[col] = np.nan
    
    print("\nBerechne Energiebilanzwerte für Gebäude...")
    matched_count = 0
    unmatched_count = 0
    
    for idx, row in gdf.iterrows():
        gebaeudetyp = row.get('gebaeudetyp')
        baujahr = row.get('baujahr')
        bezugsflaeche = row.get("bezugsflaeche")
        
        # Konvertiere Baujahr zu Baualtersklasse
        bal = baujahr_to_baualtersklasse(baujahr)
        
        # Finde passende Referenz
        energie_ref = find_matching_referenz(gebaeudetyp, bal, energie_liste, gebaeude_liste)
        
        if energie_ref is None:
            unmatched_count += 1
            continue
        
        # Referenzfläche AN aus Typologie
        bezugsflaeche_ref = None
        for gebaeude in gebaeude_liste:
            if gebaeude.typ == gebaeudetyp and gebaeude.bal == bal:
                bezugsflaeche_ref = gebaeude.AN
                break
        
        if bezugsflaeche_ref is None:
            unmatched_count += 1
            continue
        
        # Skaliere Werte
        energie_werte = scale_energie_values(energie_ref, bezugsflaeche, bezugsflaeche_ref)
        
        # Prüfe ob Gebäude saniert wurde (U-Werte aus sanierung.py vorhanden)
        u_cols = ['U_dach', 'U_geschossdecke', 'U_wand', 'U_fenster', 'U_keller', 'U_tuer']
        has_sanierung = any(pd.notna(row.get(col)) for col in u_cols if col in gdf.columns)
        
        if has_sanierung:
            # Berechne c0_QT mit sanierten U-Werten
            # Finde Referenzgebäude für Flächen und Faktoren
            ref_gebaeude = None
            for gebaeude in gebaeude_liste:
                if gebaeude.typ == gebaeudetyp and gebaeude.bal == bal:
                    ref_gebaeude = gebaeude
                    break
            
            if ref_gebaeude:
                # Skaliere Flächen basierend auf Bezugsfläche
                scale_factor = bezugsflaeche / bezugsflaeche_ref if bezugsflaeche_ref > 0 else 1.0
                
                # Berechne c0_QT mit sanierten U-Werten (nur wenn vorhanden, sonst Original)
                c0_QT_saniert = 0.0
                
                # Dach
                u_dach = row.get('U_dach') if 'U_dach' in gdf.columns else None
                if pd.notna(u_dach):
                    c0_QT_saniert += ref_gebaeude.f_dach * u_dach * ref_gebaeude.A_dach * scale_factor
                else:
                    c0_QT_saniert += ref_gebaeude.f_dach * ref_gebaeude.U_dach * ref_gebaeude.A_dach * scale_factor
                
                # Geschossdecke
                u_ogd = row.get('U_geschossdecke') if 'U_geschossdecke' in gdf.columns else None
                if pd.notna(u_ogd):
                    c0_QT_saniert += ref_gebaeude.f_ogd * u_ogd * ref_gebaeude.A_ogd * scale_factor
                else:
                    c0_QT_saniert += ref_gebaeude.f_ogd * ref_gebaeude.U_ogd * ref_gebaeude.A_ogd * scale_factor
                
                # Wand
                u_wand = row.get('U_wand') if 'U_wand' in gdf.columns else None
                if pd.notna(u_wand):
                    c0_QT_saniert += ref_gebaeude.f_aw * u_wand * ref_gebaeude.A_aw * scale_factor
                else:
                    c0_QT_saniert += ref_gebaeude.f_aw * ref_gebaeude.U_aw * ref_gebaeude.A_aw * scale_factor
                
                # Keller
                u_keller = row.get('U_keller') if 'U_keller' in gdf.columns else None
                if pd.notna(u_keller):
                    c0_QT_saniert += ref_gebaeude.f_kd * u_keller * ref_gebaeude.A_kd * scale_factor
                else:
                    c0_QT_saniert += ref_gebaeude.f_kd * ref_gebaeude.U_kd * ref_gebaeude.A_kd * scale_factor
                
                # Fenster
                u_fenster = row.get('U_fenster') if 'U_fenster' in gdf.columns else None
                if pd.notna(u_fenster):
                    c0_QT_saniert += ref_gebaeude.f_fen * u_fenster * ref_gebaeude.A_fen * scale_factor
                else:
                    c0_QT_saniert += ref_gebaeude.f_fen * ref_gebaeude.U_fen * ref_gebaeude.A_fen * scale_factor
                
                # Tür
                u_tuer = row.get('U_tuer') if 'U_tuer' in gdf.columns else None
                if pd.notna(u_tuer):
                    c0_QT_saniert += ref_gebaeude.f_tuer * u_tuer * ref_gebaeude.A_tuer * scale_factor
                else:
                    c0_QT_saniert += ref_gebaeude.f_tuer * ref_gebaeude.U_tuer * ref_gebaeude.A_tuer * scale_factor
                
                # Wärmebrücke
                c0_QT_saniert += ref_gebaeude.U_wb * ref_gebaeude.A_summe * scale_factor
                
                # Überschreibe c0_QT mit sanierten Werten
                energie_werte['c0_QT'] = c0_QT_saniert
        
        # Füge Werte zum GeoDataFrame hinzu
        for col, wert in energie_werte.items():
            gdf.loc[idx, col] = wert
        
        matched_count += 1
    
    print(f"✓ {matched_count} Gebäude mit Energiebilanzwerten versehen")
    if unmatched_count > 0:
        print(f"⚠ {unmatched_count} Gebäude konnten nicht zugeordnet werden")
    
    return gdf


def process_gebaeude_with_energiebilanz(input_filename: Optional[str] = None) -> Optional[gpd.GeoDataFrame]:
    """
    Lädt Gebäude aus ETL und fügt Energiebilanzwerte hinzu.
    
    Args:
        input_filename: Name der Eingabedatei (z.B. 'gebäude_mockau_erweitert.gpkg' oder 'mockau_Charlie_erweitert.gpkg')
                       Wenn None, wird 'gebäude_mockau_erweitert.gpkg' verwendet.
    """
    # Konfiguration: Hier einfach den Dateinamen ändern, um zwischen Datenquellen zu wechseln
    if input_filename is None:
        # ETL-Ausgabe: <Basis>_schritt5.gpkg in 2_COMPUTE/computing_inputs/
        input_filename = "gebaeude_leipzig_schritt5.gpkg"

    gpkg_path = COMPUTE_INPUTS / input_filename
    if not gpkg_path.is_file():
        print(f"Fehler: GeoPackage-Datei nicht gefunden: {gpkg_path}")
        return None

    print(f"Lade GeoPackage-Datei: {gpkg_path}")
    try:
        gdf = gpd.read_file(str(gpkg_path))
        print(f"✓ {len(gdf)} Gebäude geladen")
    except Exception as e:
        print(f"Fehler beim Einlesen der Datei: {e}")
        return None
    
    # Prüfe benötigte Spalten
    required_cols = ["gebaeudetyp", "baujahr", "bezugsflaeche"]
    missing_cols = [col for col in required_cols if col not in gdf.columns]
    if missing_cols:
        print(f"Fehler: Folgende Spalten fehlen: {missing_cols}")
        return None
    
    # Füge Energiebilanzwerte hinzu
    gdf = add_energiebilanz_to_gebaeude(gdf)
    
    # Speichere erweiterte Datei (basierend auf Input-Dateinamen)
    base_name = os.path.splitext(input_filename)[0]
    # Entferne "_erweitert" falls vorhanden, füge "_mit_energiebilanz" hinzu
    if base_name.endswith('_erweitert'):
        base_name = base_name[:-10]  # Entferne "_erweitert"
    output_filename = f'{base_name}_mit_energiebilanz.gpkg'

    COMPUTE_OUTPUTS.mkdir(parents=True, exist_ok=True)
    output_path = COMPUTE_OUTPUTS / output_filename
    gdf.to_file(str(output_path), driver="GPKG")
    print(f"\n✓ GeoPackage mit Energiebilanzwerten gespeichert: {output_path}")
    
    return gdf


if __name__ == "__main__":
    # Einfach den Dateinamen hier ändern, um zwischen Datenquellen zu wechseln
    # result = process_gebaeude_with_energiebilanz('gebäude_mockau_erweitert.gpkg')  # Standard-Datei
    result = process_gebaeude_with_energiebilanz("gebaeude_leipzig_schritt5.gpkg")
    
    if result is not None:
        print(f"\n{'='*80}")
        print("ZUSAMMENFASSUNG")
        print(f"{'='*80}")
        print(f"Gesamtanzahl Gebäude: {len(result)}")
        print(f"Gebäude mit Energiebilanzwerten: {result['g_QH'].notna().sum()}")
        print(f"Gebäude ohne Energiebilanzwerte: {result['g_QH'].isna().sum()}")
        
        if result['g_QH'].notna().any():
            print(f"\nStatistiken Heizwärmebedarf (g_QH):")
            print(f"  Mittelwert: {result['g_QH'].mean():.2f} kWh/a")
            print(f"  Median: {result['g_QH'].median():.2f} kWh/a")
            print(f"  Min: {result['g_QH'].min():.2f} kWh/a")
            print(f"  Max: {result['g_QH'].max():.2f} kWh/a")

