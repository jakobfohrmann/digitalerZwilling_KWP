"""Wendet Sanierungsannahmen auf Gebäudedaten an."""

from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import numpy as np
import pandas as pd

from energy.calculator import create_energie_instanzen, create_energie_instanzen_for_gebaeude
from shared.helpers import ENERGIE_SPALTEN, baujahr_to_baualtersklasse, get_gebaeudetyp_fallback_chain, scale_energie_values
from shared.paths import PARAMS_KLIMA_GEB
from sanierung.assumptions import parse_sanierungszyklus_start
from sanierung.constants import SANIERUNG_DEPTHS
from sanierung.u_values import apply_u_values_to_gebaeude, get_sanierung_parts, get_sanierungs_u_values, load_sanierungs_typologie
from typology.loader import load_gebaeudetypologie


def apply_sanierung_simulation(
    gdf: gpd.GeoDataFrame,
    assumption: Dict,
    energy_params: Optional[Dict[str, float]] = None,
) -> Tuple[gpd.GeoDataFrame, Dict]:
    """Wendet Sanierungsannahmen auf Gebäude an und berechnet Energiewerte neu."""
    density = assumption['density'] / 100.0
    cycle = assumption['cycle']
    depth = assumption['depth']
    building_types = {str(t).strip().upper() for t in (assumption.get('building_types') or []) if t}
    baujahr_from = assumption.get('baujahr_from')
    baujahr_to = assumption.get('baujahr_to')
    custom_parts = assumption.get('custom_parts') or []

    cycle_start = parse_sanierungszyklus_start(cycle)
    if cycle_start is None:
        raise ValueError('Sanierungszyklus ist ungültig')

    parts = get_sanierung_parts(depth, custom_parts)
    if not parts:
        raise ValueError('Sanierungstiefe enthält keine Gebäudeteile')

    default_gebaeude = load_gebaeudetypologie()
    default_energie = create_energie_instanzen(energy_params=energy_params)

    default_e_map = {(g.typ.strip().upper(), g.bal): e for g, e in zip(default_gebaeude, default_energie)}
    default_g_map = {(g.typ.strip().upper(), g.bal): g for g in default_gebaeude}

    csv_path = str(PARAMS_KLIMA_GEB / "gebaeudetypologie.csv")
    df_typ = load_sanierungs_typologie(csv_path=csv_path)

    u_by_type = {
        g.typ.strip().upper(): get_sanierungs_u_values(df_typ, g.typ, cycle_start)
        for g in default_gebaeude
        if not building_types or g.typ.strip().upper() in building_types
    }

    renovated_gebaeude = [
        apply_u_values_to_gebaeude(g, u_by_type.get(g.typ.strip().upper()), parts)
        if not building_types or g.typ.strip().upper() in building_types
        else g
        for g in default_gebaeude
    ]
    renovated_energie = create_energie_instanzen_for_gebaeude(renovated_gebaeude, energy_params=energy_params)
    renovated_e_map = {(g.typ.strip().upper(), g.bal): e for g, e in zip(renovated_gebaeude, renovated_energie)}

    for col in ENERGIE_SPALTEN:
        if f"{col}_sim_saniert" not in gdf.columns:
            gdf[f"{col}_sim_saniert"] = np.nan
    for flag in ('sanierung_kandidat', 'sanierung_angewandt'):
        if flag not in gdf.columns:
            gdf[flag] = False

    def resolve_typ(typ, bal):
        if typ is None or bal is None:
            return None
        for candidate in get_gebaeudetyp_fallback_chain(typ):
            if (candidate, bal) in default_g_map:
                return candidate
        return None

    def heat_demand_score(row):
        ga = row.get('ga_qH')
        if pd.notna(ga):
            try:
                return float(ga)
            except (ValueError, TypeError):
                pass
        g_qh, bf = row.get('g_QH'), row.get('bezugsflaeche')
        if pd.notna(g_qh) and pd.notna(bf):
            try:
                return float(g_qh) / float(bf) if float(bf) > 0 else float('-inf')
            except (ValueError, TypeError, ZeroDivisionError):
                pass
        return float('-inf')

    matched, applied, unmatched = 0, 0, 0
    row_ctx: List[Dict] = []
    rankings: List[Tuple] = []

    for i, (idx, row) in enumerate(gdf.iterrows()):
        gebaeudetyp = str(row.get('gebaeudetyp', '') or '').strip().upper() or None
        baujahr = row.get('baujahr')
        bezugsflaeche = row.get('bezugsflaeche')

        matches_type = not building_types or gebaeudetyp in building_types
        matches_baujahr = (
            (baujahr_from is None or (pd.notna(baujahr) and float(baujahr) >= baujahr_from)) and
            (baujahr_to is None or (pd.notna(baujahr) and float(baujahr) <= baujahr_to))
        )
        is_candidate = matches_type and matches_baujahr
        gdf.loc[idx, 'sanierung_kandidat'] = bool(is_candidate)

        bal = baujahr_to_baualtersklasse(baujahr)
        resolved = resolve_typ(gebaeudetyp, bal)
        e_def = default_e_map.get((resolved, bal)) if resolved else None
        e_ren = renovated_e_map.get((resolved, bal)) if resolved else None
        ref_g = default_g_map.get((resolved, bal)) if resolved else None

        if e_def is None or ref_g is None:
            unmatched += 1
            row_ctx.append({'idx': idx, 'bezugsflaeche': bezugsflaeche, 'is_candidate': is_candidate,
                            'eligible': False, 'e_def': None, 'e_ren': None, 'ref_g': None})
            continue

        if is_candidate:
            matched += 1
        eligible = bool(is_candidate and e_ren is not None)
        if eligible:
            rankings.append((idx, heat_demand_score(row), i))

        row_ctx.append({'idx': idx, 'bezugsflaeche': bezugsflaeche, 'is_candidate': is_candidate,
                        'eligible': eligible, 'e_def': e_def, 'e_ren': e_ren, 'ref_g': ref_g})

    target = max(0, min(int(round(len(rankings) * density)), len(rankings)))
    rankings.sort(key=lambda x: (-x[1], x[2]))
    selected = {idx for idx, _, _ in rankings[:target]}

    for ctx in row_ctx:
        idx = ctx['idx']
        if ctx['e_def'] is None or ctx['ref_g'] is None:
            gdf.loc[idx, 'sanierung_angewandt'] = False
            continue
        use_ren = bool(ctx['eligible'] and idx in selected)
        e_ref = ctx['e_ren'] if use_ren else ctx['e_def']
        for col, wert in scale_energie_values(e_ref, ctx['bezugsflaeche'], ctx['ref_g'].AN).items():
            gdf.loc[idx, f"{col}_sim_saniert"] = wert
        if use_ren:
            applied += 1
        gdf.loc[idx, 'sanierung_angewandt'] = bool(use_ren)

    return gdf, {'total_buildings': len(gdf), 'candidates': matched, 'applied': applied, 'unmatched': unmatched}
