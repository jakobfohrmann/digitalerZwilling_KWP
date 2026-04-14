"""
Berechnet Energie-Referenzwerte aus Gebäudetypologie-Daten.
"""

import math
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from gebaeudetypologie_loader import load_gebaeudetypologie, Gebaeude
from iwu_gradtage_loader import load_iwu_gradtage, Klima


# Standard-Parameter für Energieberechnungen (Bezeichnungen nach Berechnung.pdf)
DEFAULT_ENERGY_PARAMETERS = {
    # Lüftungswärmeverlust (HV): cp,L * rho_L / 3600
    'cp_rho_3600': 0.34,  # [Wh/(m³K)]
    'f_gebaeude_efh_rh': 0.76,  # f_Gebäude für EFH/RH [-]
    'f_gebaeude_sonstige': 0.8,  # f_Gebäude für sonstige [-]

    # Solare Wärmegewinne (Qs): As,i * I_Sol,i
    'f_s_verschattung': 0.7,  # FS Verschattung [-]
    'f_w_strahlung': 0.85,  # FW nicht senkrechter Strahlungseinfalls [-]
    'f_hor': 0.9,  # Faktor für horizontale Globalstrahlung [-]
    'f_orientierung': 0.7,  # Faktor für Ost/Süd/West/Nord [-]

    # Interne Wärmegewinne (Qi)
    'qi_umrechnung_watt_zu_kwh_tag': 0.024,  # 0.024 kWh/(W·d)
    'qi_flaechenfaktor_ve': 0.32,  # Nutzflächenfaktor zu Ve [-]
    'phi_wm2': 5.0,  # nutzflächenspezifische Leistung [W/m²]

    # Zeitlicher Reduktionsfaktor (fze)
    'fze_basis': 0.9,  # Basiswert 0.9 [-]
    'fze_zusatz': 0.1,  # Zusatzterm 0.1 [-]

    # Räumlicher Reduktionsfaktor (fre) und nre-Anteil
    'fre_h_faktor': 0.5,  # Faktor vor h [-]
    'nre_basis': 0.25,  # nre-Basis 0.25 [-]
    'nre_faktor_atan': 0.2,  # nre-Faktor 0.2 [-]
    'nre_ref_flaeche_efh_rh': 100.0,  # AWE-Referenz EFH/RH [m²]
    'nre_ref_flaeche_sonstige': 80.0,  # AWE-Referenz sonstige [m²]
    'nre_divisor_flaeche': 50.0,  # Divisor für arctan [m²]

    # Nutzungsfaktor (fn)
    'fn_basis': 0.5,  # Basiswert 0.5 [-]
    'fn_zaehler': 1.0,  # Zählerterm 1.0 [-]
    'fn_h_faktor': 0.5,  # Faktor vor h im Nenner [-]

    # Heizwärmebedarf
    'qh_umrechnung_watt_zu_kwh_tag': 0.024,  # 0.024 kWh/(W·d)
    'eta_p': 0.95,  # Nutzungsgrad Wärmegewinne [-]
}


@dataclass
class Energie:
    """Energiebilanz-Datenstruktur (vereinfacht für Referenzberechnung)"""
    a_Referenz: str = ""  # Referenz/Bezeichnung des Gebäudes
    b_Baualtersklasse: str = ""  # Baualtersklasse des Gebäudes (z.B. "1919-1948", "vor 1919")
    c_QT: float = 0.0  # Transmissionswärmebedarf [W/K] - Wärmeverlust durch Gebäudehülle (nach Sanierung)
    c0_QT: float = 0.0  # Transmissionswärmebedarf [W/K] - Wärmeverlust durch Gebäudehülle (vor Sanierung/Referenz)
    d_QL: float = 0.0  # Lüftungswärmebedarf [W/K] - Wärmeverlust durch Lüftung (nach Sanierung)
    d0_QL: float = 0.0  # Lüftungswärmebedarf [W/K] - Wärmeverlust durch Lüftung (vor Sanierung/Referenz)
    e_QS: float = 0.0  # Wärmegewinne aus solarer Strahlung [kWh/a] - solare Wärmegewinne durch Fenster
    f_QI: float = 0.0  # Wärmegewinne aus internen Quellen [kWh/a] - interne Wärmegewinne (Personen, Geräte)
    g_QH: float = 0.0  # Heizwärmebedarf [kWh/a] - jährlicher Heizwärmebedarf (absolut)
    ga_qH: float = 0.0  # Spezifischer Heizwärmebedarf [kWh/m²a] - bezogen auf Nutzfläche (nach Sanierung)
    ga0_qH: float = 0.0  # Spezifischer Heizwärmebedarf [kWh/m²a] - bezogen auf Nutzfläche (vor Sanierung/Referenz)


def create_energie_instanzen_for_gebaeude(
    gebaeude_liste: List[Gebaeude],
    klima_csv_path: Optional[str] = None,
    energy_params: Optional[Dict[str, float]] = None,
    climate_hdd_rhdd: Optional[Tuple[float, float]] = None,
    climate_overrides: Optional[Dict[str, float]] = None
) -> List[Energie]:
    """
    Erstellt Energie-Instanzen aus einer Liste von Gebaeude-Objekten und berechnet Referenzwerte.
    """
    # Verwende übergebene Parameter oder Standardwerte
    params = {**DEFAULT_ENERGY_PARAMETERS}
    if energy_params:
        params.update(energy_params)

    klima = load_iwu_gradtage(klima_csv_path)
    if climate_hdd_rhdd is not None:
        klima.HDD = float(climate_hdd_rhdd[0])
        klima.RHDD = float(climate_hdd_rhdd[1])
    if climate_overrides is not None:
        for key, value in climate_overrides.items():
            if hasattr(klima, key):
                setattr(klima, key, float(value))
    energie_instanzen = []

    for gebaeude in gebaeude_liste:
        energie = Energie(
            a_Referenz=gebaeude.reference,
            b_Baualtersklasse=gebaeude.bal
        )
        
        # Transmissionswärmebedarf QT (nach Sanierung = vor Sanierung für Referenz)
        energie.c_QT = (gebaeude.f_dach * gebaeude.U_dach * gebaeude.A_dach +
                       gebaeude.f_ogd * gebaeude.U_ogd * gebaeude.A_ogd +
                       gebaeude.f_aw * gebaeude.U_aw * gebaeude.A_aw +
                       gebaeude.f_kd * gebaeude.U_kd * gebaeude.A_kd +
                       gebaeude.f_fen * gebaeude.U_fen * gebaeude.A_fen +
                       gebaeude.f_tuer * gebaeude.U_tuer * gebaeude.A_tuer + gebaeude.U_wb * gebaeude.A_summe)
        
        # Für Referenz: c0_QT = c_QT (gleiche Werte)
        # Wenn saniert, wird c0_QT in compute_main.py mit sanierten U-Werten überschrieben
        energie.c0_QT = energie.c_QT
        
        # Lüftungswärmebedarf QL
        if gebaeude.typ == "EFH" or gebaeude.typ == "RH":
            luftfaktor = params['f_gebaeude_efh_rh']
        else:
            luftfaktor = params['f_gebaeude_sonstige']
        energie.d_QL = params['cp_rho_3600'] * luftfaktor * gebaeude.V * (gebaeude.n_f + gebaeude.n_x)
        
        # Für Referenz: d0_QL = d_QL (gleiche Werte)
        energie.d0_QL = energie.d_QL
        
        # Wärmegewinne aus solarer Strahlung (Werte aus IWU-Gradtage-Daten)
        energie.e_QS = (params['f_s_verschattung'] * params['f_w_strahlung'] * gebaeude.g_F * 
                       (params['f_hor'] * gebaeude.A_hor * klima.G_Hor_HD +
                        params['f_orientierung'] * gebaeude.A_ost * klima.G_E_HD +
                        params['f_orientierung'] * gebaeude.A_sued * klima.G_S_HD +
                        params['f_orientierung'] * gebaeude.A_west * klima.G_W_HD +
                        params['f_orientierung'] * gebaeude.A_nord * klima.G_N_HD))
        
        # Wärmegewinne aus internen Quellen (Heizperiodenlänge aus IWU Modell)
        energie.f_QI = (params['qi_flaechenfaktor_ve'] * 
                       params['qi_umrechnung_watt_zu_kwh_tag'] * 
                       klima.HD * 
                       gebaeude.V * 
                       params['phi_wm2'])
        
        # Berücksichtigung Nutzerverhalten
        # Spezifischer Wärmeverlustkoeffizient h = Summe Transmissionswärmebedarf und Lüftungswärmebedarf / Gebäudenutzfläche
        h = (energie.c_QT + energie.d_QL) / gebaeude.AN if gebaeude.AN > 0 else 0.0
        
        # Reduktionsfaktor für zeitlich eingeschränkter Beheizung bewegt sich zwischen 0.9 und 1.0
        fze = params['fze_basis'] + params['fze_zusatz'] / (1 + h) if h > 0 else params['fze_basis']
        
        # Reduktionsfaktor für räumlich eingeschränkter Beheizung
        if gebaeude.typ == "EFH" or gebaeude.typ == "RH":
            referenz_nutzflaeche = params['nre_ref_flaeche_efh_rh']
        else:
            referenz_nutzflaeche = params['nre_ref_flaeche_sonstige']
        
        if h > 0:
            fre = 1 / (params['fre_h_faktor'] * math.sqrt(h) * 
                       (params['nre_basis'] + 
                        params['nre_faktor_atan'] * math.atan((gebaeude.AN - referenz_nutzflaeche) / params['nre_divisor_flaeche'])) ** 2 + 1)
        else:
            fre = 1.0
        
        # Faktor Nutzung
        fn = params['fn_basis'] + params['fn_zaehler'] / (1 + params['fn_h_faktor'] * h) if h > 0 else params['fn_basis']
        
        # Heizwärmebedarf
        energie.g_QH = (params['qh_umrechnung_watt_zu_kwh_tag'] * klima.RHDD * fze * fre * fn * 
                       (energie.c_QT + energie.d_QL) - 
                       params['eta_p'] * (energie.e_QS + energie.f_QI))
        
        # Spezifischer Heizwärmebedarf
        energie.ga_qH = energie.g_QH / gebaeude.AN if gebaeude.AN > 0 else 0.0
        
        # Für Referenz: ga0_qH = ga_qH (gleiche Werte)
        energie.ga0_qH = energie.ga_qH
        
        energie_instanzen.append(energie)

    return energie_instanzen


def create_energie_instanzen(
    csv_path: Optional[str] = None,
    klima_csv_path: Optional[str] = None,
    energy_params: Optional[Dict[str, float]] = None,
    climate_hdd_rhdd: Optional[Tuple[float, float]] = None,
    climate_overrides: Optional[Dict[str, float]] = None
) -> List[Energie]:
    """
    Erstellt Energie-Instanzen aus den Gebäudetypologie-Daten und berechnet die Referenzwerte.
    """
    gebaeude_liste = load_gebaeudetypologie(csv_path)
    return create_energie_instanzen_for_gebaeude(
        gebaeude_liste=gebaeude_liste,
        klima_csv_path=klima_csv_path,
        energy_params=energy_params,
        climate_hdd_rhdd=climate_hdd_rhdd,
        climate_overrides=climate_overrides
    )


def get_default_energy_parameters() -> Dict[str, float]:
    """
    Gibt die Standard-Parameter für Energieberechnungen zurück.
    
    Returns:
    --------
    Dict[str, float]
        Dictionary mit Standard-Parametern
    """
    return DEFAULT_ENERGY_PARAMETERS.copy()
