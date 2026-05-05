"""Gebaeude-Datenstruktur aus der Gebäudetypologie."""

from dataclasses import dataclass


@dataclass
class Gebaeude:
    reference: str = ""
    typ: str = ""
    bal: str = ""
    NGF: float = 0.0
    WFL: float = 0.0
    AN: float = 0.0
    V: float = 0.0
    A_dach: float = 0.0
    A_ogd: float = 0.0
    A_aw: float = 0.0
    A_kd: float = 0.0
    A_fen: float = 0.0
    A_tuer: float = 0.0
    A_summe: float = 0.0
    U_dach: float = 0.0
    U_ogd: float = 0.0
    U_aw: float = 0.0
    U_kd: float = 0.0
    U_fen: float = 0.0
    U_tuer: float = 0.0
    U_wb: float = 0.0
    U_summe: float = 0.0
    f_dach: float = 0.0
    f_ogd: float = 0.0
    f_aw: float = 0.0
    f_kd: float = 0.0
    f_fen: float = 0.0
    f_tuer: float = 0.0
    n_f: float = 0.0
    n_x: float = 0.0
    A_hor: float = 0.0
    A_ost: float = 0.0
    A_sued: float = 0.0
    A_west: float = 0.0
    A_nord: float = 0.0
    g_F: float = 0.0
    f_NA: float = 0.0
