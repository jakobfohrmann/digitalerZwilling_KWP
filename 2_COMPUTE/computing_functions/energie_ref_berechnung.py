"""
Berechnet Energie-Referenzwerte aus Gebäudetypologie-Daten.
"""

import csv
import math
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
from gebaeudetypologie_loader import load_gebaeudetypologie, Gebaeude
from iwu_gradtage_loader import load_iwu_gradtage, Klima
from paths import PARAMS_KLIMA_GEB


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
    c_QT: float = 0.0  # Transmissionswärmebedarf [W/K] - unsaniert
    c_QT_saniert: float = 0.0  # Transmissionswärmebedarf [W/K] - saniert (Dach/Wand/Fenster/Tuer ersetzt)
    d_QL: float = 0.0  # Lüftungswärmebedarf [W/K]
    e_QS: float = 0.0  # Wärmegewinne aus solarer Strahlung [kWh/a] - solare Wärmegewinne durch Fenster
    f_QI: float = 0.0  # Wärmegewinne aus internen Quellen [kWh/a] - interne Wärmegewinne (Personen, Geräte)
    g_QH: float = 0.0  # Heizwärmebedarf [kWh/a] - unsaniert
    g_QH_saniert: float = 0.0  # Heizwärmebedarf [kWh/a] - saniert
    ga_qH: float = 0.0  # Spezifischer Heizwärmebedarf [kWh/m²a] - unsaniert
    ga_qH_saniert: float = 0.0  # Spezifischer Heizwärmebedarf [kWh/m²a] - saniert


def _baualtersklasse_to_baujahr(baualtersklasse: str) -> int:
    """Leitet ein repräsentatives Baujahr aus der Baualtersklasse ab."""
    if not baualtersklasse:
        return 1919

    bal = str(baualtersklasse).strip().lower()
    if bal.startswith('vor'):
        return 1919
    if bal.startswith('nach'):
        return 2009
    if '-' in bal:
        first = bal.split('-')[0].strip()
        try:
            return int(first)
        except ValueError:
            return 1919
    try:
        return int(float(bal))
    except ValueError:
        return 1919


def _parse_float(value: str) -> Optional[float]:
    """Parst Float-Werte robust (inkl. Komma als Dezimaltrenner)."""
    if value is None:
        return None
    value_str = str(value).strip().replace(',', '.')
    if value_str == "":
        return None
    try:
        return float(value_str)
    except ValueError:
        return None


def _load_sanierungszyklen_u_values(csv_path: Optional[str] = None) -> List[Tuple[int, Dict[str, float]]]:
    """
    Lädt Sanierungszyklen aus der Typologie-CSV.
    Erwartet die Zyklusjahre in Spalte O (Index 14) und U-Werte in P/R/T/U.
    """
    target_csv = csv_path or str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")
    encodings = ['utf-8-sig', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-8']

    for encoding in encodings:
        try:
            with open(target_csv, mode='r', encoding=encoding, newline='') as file:
                reader = csv.reader(file, delimiter=';')
                cycles: List[Tuple[int, Dict[str, float]]] = []
                for row in reader:
                    if len(row) <= 20:
                        continue
                    # Sanierungsblock: kein Gebäudetyp in Spalte B und Jahr in Spalte O
                    if str(row[1]).strip() != "":
                        continue
                    year_val = _parse_float(row[14])
                    if year_val is None:
                        continue
                    year_int = int(year_val)
                    if year_int < 1900 or year_int > 2100:
                        continue

                    u_map: Dict[str, float] = {}
                    u_dach = _parse_float(row[15])
                    u_wand = _parse_float(row[17])
                    u_fenster = _parse_float(row[19])
                    u_tuer = _parse_float(row[20])
                    if u_dach and u_dach > 0:
                        u_map['dach'] = u_dach
                    if u_wand and u_wand > 0:
                        u_map['wand'] = u_wand
                    if u_fenster and u_fenster > 0:
                        u_map['fenster'] = u_fenster
                    if u_tuer and u_tuer > 0:
                        u_map['tuer'] = u_tuer

                    if u_map:
                        cycles.append((year_int, u_map))

                if cycles:
                    # Dedupliziere nach Jahr, späterer Treffer gewinnt
                    by_year: Dict[int, Dict[str, float]] = {}
                    for year, values in cycles:
                        by_year[year] = values
                    return sorted(by_year.items(), key=lambda item: item[0])
        except Exception:
            continue

    return []


def _get_sanierungsjahr_for_baujahr(baujahr: int, betrachtungsjahr: int, sanierungszyklus: int = 45) -> int:
    """Berechnet das Sanierungsjahr nach der vorgegebenen 45-Jahres-Formel."""
    n = int((betrachtungsjahr - baujahr) / sanierungszyklus - 0.5)
    return baujahr + n * sanierungszyklus


def _select_sanierungs_u_values(
    cycle_u_values: List[Tuple[int, Dict[str, float]]],
    sanierungsjahr: int
) -> Dict[str, float]:
    """Wählt U-Werte passend zum Sanierungsjahr (größtes Jahr <= Sanierungsjahr, sonst kleinstes Jahr)."""
    if not cycle_u_values:
        return {}

    candidates = [entry for entry in cycle_u_values if entry[0] <= sanierungsjahr]
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    return min(cycle_u_values, key=lambda item: item[0])[1]


def _compute_heating_reduction_factors(
    gebaeude: Gebaeude,
    params: Dict[str, float],
    h_value: float
) -> Tuple[float, float, float]:
    """Berechnet fze, fre und fn für einen gegebenen h-Wert."""
    fze = params['fze_basis'] + params['fze_zusatz'] / (1 + h_value) if h_value > 0 else params['fze_basis']

    if gebaeude.typ == "EFH" or gebaeude.typ == "RH":
        referenz_nutzflaeche = params['nre_ref_flaeche_efh_rh']
    else:
        referenz_nutzflaeche = params['nre_ref_flaeche_sonstige']

    if h_value > 0:
        fre = 1 / (
            params['fre_h_faktor'] * math.sqrt(h_value) *
            (params['nre_basis'] + params['nre_faktor_atan'] *
             math.atan((gebaeude.AN - referenz_nutzflaeche) / params['nre_divisor_flaeche'])) ** 2 + 1
        )
    else:
        fre = 1.0

    fn = params['fn_basis'] + params['fn_zaehler'] / (1 + params['fn_h_faktor'] * h_value) if h_value > 0 else params['fn_basis']
    return fze, fre, fn


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
    cycle_u_values = _load_sanierungszyklen_u_values()
    betrachtungsjahr = datetime.now().year

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
        
        # Sanierungs-QT: nur Dach, Außenwand, Fenster und Tür mit Zyklus-U-Werten ersetzen
        baujahr = _baualtersklasse_to_baujahr(gebaeude.bal)
        sanierungsjahr = _get_sanierungsjahr_for_baujahr(baujahr, betrachtungsjahr, sanierungszyklus=45)
        sanierungs_u = _select_sanierungs_u_values(cycle_u_values, sanierungsjahr)

        u_dach = sanierungs_u.get('dach', gebaeude.U_dach)
        u_aw = sanierungs_u.get('wand', gebaeude.U_aw)
        u_fen = sanierungs_u.get('fenster', gebaeude.U_fen)
        u_tuer = sanierungs_u.get('tuer', gebaeude.U_tuer)

        energie.c_QT_saniert = (
            gebaeude.f_dach * u_dach * gebaeude.A_dach +
            gebaeude.f_ogd * gebaeude.U_ogd * gebaeude.A_ogd +
            gebaeude.f_aw * u_aw * gebaeude.A_aw +
            gebaeude.f_kd * gebaeude.U_kd * gebaeude.A_kd +
            gebaeude.f_fen * u_fen * gebaeude.A_fen +
            gebaeude.f_tuer * u_tuer * gebaeude.A_tuer +
            gebaeude.U_wb * gebaeude.A_summe
        )
        
        # Lüftungswärmebedarf QL
        if gebaeude.typ == "EFH" or gebaeude.typ == "RH":
            luftfaktor = params['f_gebaeude_efh_rh']
        else:
            luftfaktor = params['f_gebaeude_sonstige']
        energie.d_QL = params['cp_rho_3600'] * luftfaktor * gebaeude.V * (gebaeude.n_f + gebaeude.n_x)
        
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
        h_unsaniert = (energie.c_QT + energie.d_QL) / gebaeude.AN if gebaeude.AN > 0 else 0.0
        h_saniert = (energie.c_QT_saniert + energie.d_QL) / gebaeude.AN if gebaeude.AN > 0 else 0.0

        fze_unsaniert, fre_unsaniert, fn_unsaniert = _compute_heating_reduction_factors(gebaeude, params, h_unsaniert)
        fze_saniert, fre_saniert, fn_saniert = _compute_heating_reduction_factors(gebaeude, params, h_saniert)

        energie.g_QH = (
            params['qh_umrechnung_watt_zu_kwh_tag'] * klima.RHDD * fze_unsaniert * fre_unsaniert * fn_unsaniert *
            (energie.c_QT + energie.d_QL) - params['eta_p'] * (energie.e_QS + energie.f_QI)
        )
        energie.g_QH_saniert = (
            params['qh_umrechnung_watt_zu_kwh_tag'] * klima.RHDD * fze_saniert * fre_saniert * fn_saniert *
            (energie.c_QT_saniert + energie.d_QL) - params['eta_p'] * (energie.e_QS + energie.f_QI)
        )

        energie.ga_qH = energie.g_QH / gebaeude.AN if gebaeude.AN > 0 else 0.0
        energie.ga_qH_saniert = energie.g_QH_saniert / gebaeude.AN if gebaeude.AN > 0 else 0.0
        
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
