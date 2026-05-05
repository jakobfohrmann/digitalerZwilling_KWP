"""Berechnet Energie-Referenzwerte aus Gebäudetypologie-Daten."""

import math
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from energy.models import DEFAULT_ENERGY_PARAMETERS, Energie
from energy.renovation_cycles import (
    baujahr_from_baualtersklasse,
    load_sanierungszyklen_u_values,
    get_sanierungsjahr,
    select_u_values_for_year,
)
from iwu_gradtage_loader import load_iwu_gradtage, Klima
from typology.models import Gebaeude
from typology.loader import load_gebaeudetypologie


def _compute_heating_reduction_factors(
    gebaeude: Gebaeude,
    params: Dict[str, float],
    h: float,
) -> Tuple[float, float, float]:
    """Berechnet fze, fre, fn für einen spezifischen Wärmeverlustkoeffizienten h."""
    fze = params['fze_basis'] + params['fze_zusatz'] / (1 + h) if h > 0 else params['fze_basis']

    ref_flaeche = (params['nre_ref_flaeche_efh_rh']
                   if gebaeude.typ in ('EFH', 'RH')
                   else params['nre_ref_flaeche_sonstige'])

    fre = (1 / (params['fre_h_faktor'] * math.sqrt(h) *
                (params['nre_basis'] + params['nre_faktor_atan'] *
                 math.atan((gebaeude.AN - ref_flaeche) / params['nre_divisor_flaeche'])) ** 2 + 1)
           if h > 0 else 1.0)

    fn = params['fn_basis'] + params['fn_zaehler'] / (1 + params['fn_h_faktor'] * h) if h > 0 else params['fn_basis']
    return fze, fre, fn


def create_energie_instanzen_for_gebaeude(
    gebaeude_liste: List[Gebaeude],
    klima_csv_path: Optional[str] = None,
    energy_params: Optional[Dict[str, float]] = None,
    climate_hdd_rhdd: Optional[Tuple[float, float]] = None,
    climate_overrides: Optional[Dict[str, float]] = None,
) -> List[Energie]:
    """Erstellt Energie-Instanzen für eine Liste von Gebaeude-Objekten."""
    params = {**DEFAULT_ENERGY_PARAMETERS, **(energy_params or {})}

    klima: Klima = load_iwu_gradtage(klima_csv_path)
    if climate_hdd_rhdd is not None:
        klima.HDD, klima.RHDD = float(climate_hdd_rhdd[0]), float(climate_hdd_rhdd[1])
    if climate_overrides:
        for key, val in climate_overrides.items():
            if hasattr(klima, key):
                setattr(klima, key, float(val))

    cycle_u_values = load_sanierungszyklen_u_values()
    betrachtungsjahr = datetime.now().year
    result = []

    for g in gebaeude_liste:
        e = Energie(a_Referenz=g.reference, b_Baualtersklasse=g.bal)

        e.c_QT = (g.f_dach * g.U_dach * g.A_dach + g.f_ogd * g.U_ogd * g.A_ogd +
                  g.f_aw * g.U_aw * g.A_aw + g.f_kd * g.U_kd * g.A_kd +
                  g.f_fen * g.U_fen * g.A_fen + g.f_tuer * g.U_tuer * g.A_tuer +
                  g.U_wb * g.A_summe)

        san_jahr = get_sanierungsjahr(baujahr_from_baualtersklasse(g.bal), betrachtungsjahr)
        san_u = select_u_values_for_year(cycle_u_values, san_jahr)
        e.c_QT_saniert = (
            g.f_dach * san_u.get('dach', g.U_dach) * g.A_dach +
            g.f_ogd * g.U_ogd * g.A_ogd +
            g.f_aw * san_u.get('wand', g.U_aw) * g.A_aw +
            g.f_kd * g.U_kd * g.A_kd +
            g.f_fen * san_u.get('fenster', g.U_fen) * g.A_fen +
            g.f_tuer * san_u.get('tuer', g.U_tuer) * g.A_tuer +
            g.U_wb * g.A_summe
        )

        luftfaktor = params['f_gebaeude_efh_rh'] if g.typ in ('EFH', 'RH') else params['f_gebaeude_sonstige']
        e.d_QL = params['cp_rho_3600'] * luftfaktor * g.V * (g.n_f + g.n_x)

        e.e_QS = (params['f_s_verschattung'] * params['f_w_strahlung'] * g.g_F *
                  (params['f_hor'] * g.A_hor * klima.G_Hor_HD +
                   params['f_orientierung'] * g.A_ost * klima.G_E_HD +
                   params['f_orientierung'] * g.A_sued * klima.G_S_HD +
                   params['f_orientierung'] * g.A_west * klima.G_W_HD +
                   params['f_orientierung'] * g.A_nord * klima.G_N_HD))

        e.f_QI = (params['qi_flaechenfaktor_ve'] * params['qi_umrechnung_watt_zu_kwh_tag'] *
                  klima.HD * g.V * params['phi_wm2'])

        h_u = (e.c_QT + e.d_QL) / g.AN if g.AN > 0 else 0.0
        h_s = (e.c_QT_saniert + e.d_QL) / g.AN if g.AN > 0 else 0.0
        fze_u, fre_u, fn_u = _compute_heating_reduction_factors(g, params, h_u)
        fze_s, fre_s, fn_s = _compute_heating_reduction_factors(g, params, h_s)

        e.g_QH = (params['qh_umrechnung_watt_zu_kwh_tag'] * klima.RHDD * fze_u * fre_u * fn_u *
                  (e.c_QT + e.d_QL) - params['eta_p'] * (e.e_QS + e.f_QI))
        e.g_QH_saniert = (params['qh_umrechnung_watt_zu_kwh_tag'] * klima.RHDD * fze_s * fre_s * fn_s *
                          (e.c_QT_saniert + e.d_QL) - params['eta_p'] * (e.e_QS + e.f_QI))

        e.ga_qH = e.g_QH / g.AN if g.AN > 0 else 0.0
        e.ga_qH_saniert = e.g_QH_saniert / g.AN if g.AN > 0 else 0.0
        result.append(e)

    return result


def create_energie_instanzen(
    csv_path: Optional[str] = None,
    klima_csv_path: Optional[str] = None,
    energy_params: Optional[Dict[str, float]] = None,
    climate_hdd_rhdd: Optional[Tuple[float, float]] = None,
    climate_overrides: Optional[Dict[str, float]] = None,
) -> List[Energie]:
    """Erstellt Energie-Instanzen aus der Gebäudetypologie-CSV."""
    return create_energie_instanzen_for_gebaeude(
        load_gebaeudetypologie(csv_path),
        klima_csv_path=klima_csv_path,
        energy_params=energy_params,
        climate_hdd_rhdd=climate_hdd_rhdd,
        climate_overrides=climate_overrides,
    )


def get_default_energy_parameters() -> Dict[str, float]:
    return DEFAULT_ENERGY_PARAMETERS.copy()
