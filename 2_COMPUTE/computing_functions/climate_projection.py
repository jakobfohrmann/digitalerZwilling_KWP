"""
Solar and climate projection utilities for Leipzig.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, Iterable, Mapping, Sequence, Tuple

import matplotlib.pyplot as plt
import pandas as pd


COEFFICIENTS = [
    ("Horizontal", 0, 0.0, 1.0, 0.0),
    ("NO", 30, -0.70, 1.10, 0.00),
    ("NO", 45, -0.63, 1.06, 0.00),
    ("NO", 60, -0.59, 1.03, 0.00),
    ("NO", 90, -0.69, 1.01, 0.00),
    ("O", 30, -0.12, 1.02, 0.00),
    ("O", 45, -0.11, 1.01, 0.00),
    ("O", 60, -0.13, 1.00, 0.00),
    ("O", 90, -0.27, 0.99, 0.00),
    ("SO", 30, 0.60, 0.90, 0.00),
    ("SO", 45, 0.82, 0.85, 0.00),
    ("SO", 60, 0.98, 0.81, 0.00),
    ("SO", 90, 0.00, 1.15, -0.63),
    ("S", 30, 0.92, 0.84, 0.00),
    ("S", 45, 0.19, 1.17, -0.61),
    ("S", 60, 0.29, 1.16, -0.66),
    ("S", 90, 0.28, 1.15, -0.75),
    ("SW", 30, 0.67, 0.88, 0.00),
    ("SW", 45, 0.92, 0.83, 0.00),
    ("SW", 60, 0.19, 1.12, -0.57),
    ("SW", 90, 0.20, 1.09, -0.63),
    ("W", 30, -0.01, 1.00, 0.00),
    ("W", 45, 0.03, 0.98, 0.00),
    ("W", 60, 0.03, 0.96, 0.00),
    ("W", 90, -0.09, 0.94, 0.00),
    ("NW", 30, -0.64, 1.08, 0.00),
    ("NW", 45, -0.55, 1.04, 0.00),
    ("NW", 60, -0.50, 1.01, 0.00),
    ("NW", 90, -0.62, 0.99, 0.00),
    ("N", 30, -0.67, 1.07, 0.00),
    ("N", 45, -0.30, 0.95, 0.00),
    ("N", 60, -0.03, 0.86, 0.00),
    ("N", 90, -0.14, 0.85, 0.00),
]

DEFAULT_SURFACES_TO_PLOT = ("Horizontal_0", "S_45", "S_90", "W_90")
DEFAULT_HDD_DELTAS_PER_YEAR = {"rcp45": -3.9, "rcp85": -7.1}
REQUIRED_IWU_KEYS = {
    "Year_Start",
    "HD",
    "HDD",
    "RHDD",
    "G_Hor",
    "G_Hor_HD",
    "G_E_HD",
    "G_S_HD",
    "G_W_HD",
    "G_N_HD",
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_IWU_PATH = PROJECT_ROOT / "2_COMPUTE" / "computing_inputs" / "params_klima_gebäudetypologie" / "IWU-gradtage.csv"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "2_COMPUTE" / "computing_inputs" / "params_klima_gebäudetypologie" / "annual_climate_solar_projections_2100.csv"


def _column_name(orientation: str, tilt_deg: int) -> str:
    return f"{orientation}_{tilt_deg}"


def _annual_f_ab(u: float) -> float:
    """
    Annual correction factor based on monthly average over m=1..12.
    """
    values = [
        1.0 + u * math.sin(((m - 0.5) / 12.0) * math.pi)
        for m in range(1, 13)
    ]
    return sum(values) / 12.0


def _coerce_float(value: str) -> float:
    return float(str(value).replace(",", "."))


def _clean_iwu_token(token: str) -> str:
    return token.strip().replace('"', "")


def _read_iwu_rows(iwu_csv_path: str | Path) -> Tuple[Sequence[str], Dict[str, Dict[str, str]]]:
    path = Path(iwu_csv_path)
    if not path.exists():
        raise FileNotFoundError(f"IWU file not found: {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError("IWU file is empty.")

    header = [_clean_iwu_token(cell) for cell in lines[0].split(",")]
    if len(header) < 3:
        raise ValueError("IWU file header has unexpected format.")

    climate_columns = [col for col in header[1:] if col]
    data: Dict[str, Dict[str, str]] = {}

    for line in lines[1:]:
        if not line.strip():
            continue
        row = [_clean_iwu_token(cell) for cell in line.split(",")]
        key = row[0] if row else ""
        if not key:
            continue
        values_by_col: Dict[str, str] = {}
        for idx, col_name in enumerate(climate_columns, start=1):
            values_by_col[col_name] = row[idx] if idx < len(row) else ""
        data[key] = values_by_col

    return climate_columns, data


def load_iwu_baseline(
    iwu_csv_path: str | Path = DEFAULT_IWU_PATH,
    climate_column: str = "Klima.2",
) -> Dict[str, float]:
    """
    Load baseline climate and solar reference values from IWU CSV.
    """
    climate_columns, data = _read_iwu_rows(iwu_csv_path)
    if not climate_columns:
        raise ValueError("No climate columns found in IWU file.")

    chosen_column = climate_column if climate_column in climate_columns else climate_columns[-1]

    missing_keys = [key for key in REQUIRED_IWU_KEYS if key not in data]
    if missing_keys:
        raise ValueError(f"IWU file misses required keys: {missing_keys}")

    baseline_year = int(_coerce_float(data["Year_Start"][chosen_column]))
    hdd0 = _coerce_float(data["HDD"][chosen_column])
    rhdd0 = _coerce_float(data["RHDD"][chosen_column])
    hd0 = _coerce_float(data["HD"][chosen_column])
    g_hor0 = _coerce_float(data["G_Hor"][chosen_column])
    g_hor_hd0 = _coerce_float(data["G_Hor_HD"][chosen_column])
    g_e_hd0 = _coerce_float(data["G_E_HD"][chosen_column])
    g_s_hd0 = _coerce_float(data["G_S_HD"][chosen_column])
    g_w_hd0 = _coerce_float(data["G_W_HD"][chosen_column])
    g_n_hd0 = _coerce_float(data["G_N_HD"][chosen_column])

    if (
        hdd0 <= 0
        or hd0 < 0
        or rhdd0 < 0
        or g_hor0 <= 0
        or g_hor_hd0 < 0
        or g_e_hd0 < 0
        or g_s_hd0 < 0
        or g_w_hd0 < 0
        or g_n_hd0 < 0
    ):
        raise ValueError("IWU baseline contains invalid negative or zero values.")

    return {
        "baseline_year": baseline_year,
        "HDD0": hdd0,
        "RHDD0": rhdd0,
        "HD0": hd0,
        "nHD0": hd0,
        "G_Hor0": g_hor0,
        "G_Hor_HD0": g_hor_hd0,
        "G_E_HD0": g_e_hd0,
        "G_S_HD0": g_s_hd0,
        "G_W_HD0": g_w_hd0,
        "G_N_HD0": g_n_hd0,
        "climate_column": chosen_column,
    }


def project_horizontal_irradiance(
    baseline_horizontal_irradiance: float,
    baseline_year: int = 2005,
    end_year: int = 2100,
    growth_rate_per_decade: float = 0.01,
) -> pd.DataFrame:
    """
    Project horizontal irradiance forward with compound growth.
    """
    if end_year < baseline_year:
        raise ValueError("end_year must be greater than or equal to baseline_year.")
    if baseline_horizontal_irradiance < 0:
        raise ValueError("baseline_horizontal_irradiance must be non-negative.")

    years = list(range(baseline_year, end_year + 1))
    annual_factor = (1.0 + growth_rate_per_decade) ** (1.0 / 10.0)

    projected = []
    for year in years:
        years_since_baseline = year - baseline_year
        i_hor = baseline_horizontal_irradiance * (annual_factor ** years_since_baseline)
        projected.append(i_hor)

    return pd.DataFrame({"year": years, "I_hor_projected": projected})


def project_hdd_absolute_delta(
    baseline_hdd: float,
    baseline_year: int,
    end_year: int,
    delta_per_year: float,
) -> pd.DataFrame:
    """
    Project HDD with constant absolute delta per year.
    """
    years = list(range(baseline_year, end_year + 1))
    values = [max(0.0, baseline_hdd + (year - baseline_year) * delta_per_year) for year in years]
    return pd.DataFrame({"year": years, "HDD": values})


def project_hd_from_hdd_ratio(hdd_series: pd.Series, baseline_hdd: float, baseline_hd: float) -> pd.Series:
    """
    Scale HD according to relative HDD change.
    """
    if baseline_hdd <= 0:
        raise ValueError("baseline_hdd must be positive.")
    return baseline_hd * (hdd_series / baseline_hdd)


def project_rhdd_from_hdd(
    hdd_series: pd.Series,
    baseline_hdd: float,
    n_hd0: float,
    delta_t_i_minus_thg: float = 5.0,
) -> pd.Series:
    """
    RHDD(t)=HDD(t)+(Ti-Thg)*nHD0*HDD(t)/HDD0
    """
    if baseline_hdd <= 0:
        raise ValueError("baseline_hdd must be positive.")
    factor = 1.0 + (delta_t_i_minus_thg * n_hd0) / baseline_hdd
    return hdd_series * factor


def convert_to_surface_irradiance(
    horizontal_projection_df: pd.DataFrame,
    coefficients: Sequence[Tuple[str, int, float, float, float]] = COEFFICIENTS,
) -> pd.DataFrame:
    """
    Convert projected horizontal irradiance to orientation/tilt irradiance.

    Formula:
    g_ab = exp(beta0) * (f_ab * g_hor) ** beta1
    """
    required_cols = {"year", "I_hor_projected"}
    if not required_cols.issubset(horizontal_projection_df.columns):
        raise ValueError("horizontal_projection_df must contain 'year' and 'I_hor_projected'.")

    df_out = pd.DataFrame(index=horizontal_projection_df["year"].astype(int))
    df_out.index.name = "year"

    g_hor_values = horizontal_projection_df["I_hor_projected"].astype(float).to_numpy()

    for orientation, tilt_deg, beta0, beta1, u in coefficients:
        f_ab_annual = _annual_f_ab(u)
        col = _column_name(orientation, tilt_deg)
        projected = math.exp(beta0) * (f_ab_annual * g_hor_values) ** beta1
        df_out[col] = pd.Series(projected, index=df_out.index)

    return df_out


def build_climate_projection_table(
    baseline: Mapping[str, float],
    end_year: int = 2100,
    growth_rate_per_decade: float = 0.01,
    hdd_deltas_per_year: Mapping[str, float] = DEFAULT_HDD_DELTAS_PER_YEAR,
    delta_t_i_minus_thg: float = 5.0,
) -> pd.DataFrame:
    """
    Build annual climate + solar table for each scenario.
    """
    baseline_year = int(baseline["baseline_year"])
    hdd0 = float(baseline["HDD0"])
    hd0 = float(baseline["HD0"])
    g_hor0 = float(baseline["G_Hor0"])
    n_hd0 = float(baseline["nHD0"])
    # Constant IWU heating-period shares relative to annual horizontal irradiance.
    g_hor_hd_ratio = float(baseline["G_Hor_HD0"]) / g_hor0
    g_e_hd_ratio = float(baseline["G_E_HD0"]) / g_hor0
    g_s_hd_ratio = float(baseline["G_S_HD0"]) / g_hor0
    g_w_hd_ratio = float(baseline["G_W_HD0"]) / g_hor0
    g_n_hd_ratio = float(baseline["G_N_HD0"]) / g_hor0

    scenario_frames = []
    for scenario, hdd_delta in hdd_deltas_per_year.items():
        hdd_df = project_hdd_absolute_delta(
            baseline_hdd=hdd0,
            baseline_year=baseline_year,
            end_year=end_year,
            delta_per_year=float(hdd_delta),
        )
        hdd_df["HD"] = project_hd_from_hdd_ratio(hdd_df["HDD"], baseline_hdd=hdd0, baseline_hd=hd0)
        hdd_df["RHDD"] = project_rhdd_from_hdd(
            hdd_df["HDD"],
            baseline_hdd=hdd0,
            n_hd0=n_hd0,
            delta_t_i_minus_thg=delta_t_i_minus_thg,
        )

        horizontal_df = project_horizontal_irradiance(
            baseline_horizontal_irradiance=g_hor0,
            baseline_year=baseline_year,
            end_year=end_year,
            growth_rate_per_decade=growth_rate_per_decade,
        )
        horizontal_df = horizontal_df.rename(columns={"I_hor_projected": "G_Hor"})

        merged = hdd_df.merge(horizontal_df, on="year", how="left")
        merged["G_Hor_HD"] = merged["G_Hor"] * g_hor_hd_ratio
        merged["G_E_HD"] = merged["G_Hor"] * g_e_hd_ratio
        merged["G_S_HD"] = merged["G_Hor"] * g_s_hd_ratio
        merged["G_W_HD"] = merged["G_Hor"] * g_w_hd_ratio
        merged["G_N_HD"] = merged["G_Hor"] * g_n_hd_ratio
        merged.insert(1, "scenario", scenario)
        scenario_frames.append(
            merged[
                [
                    "year",
                    "scenario",
                    "HDD",
                    "HD",
                    "RHDD",
                    "G_Hor",
                    "G_Hor_HD",
                    "G_E_HD",
                    "G_S_HD",
                    "G_W_HD",
                    "G_N_HD",
                ]
            ]
        )

    combined = pd.concat(scenario_frames, ignore_index=True)
    combined = combined.sort_values(["scenario", "year"], ascending=[True, True]).reset_index(drop=True)
    return combined


def validate_projection_table(
    projection_df: pd.DataFrame,
    baseline: Mapping[str, float],
    end_year: int,
    hdd_deltas_per_year: Mapping[str, float],
    delta_t_i_minus_thg: float = 5.0,
) -> None:
    """
    Validate consistency assumptions for projected climate table.
    """
    baseline_year = int(baseline["baseline_year"])
    expected_years = set(range(baseline_year, end_year + 1))

    for scenario in hdd_deltas_per_year.keys():
        subset = projection_df[projection_df["scenario"] == scenario]
        if set(subset["year"].astype(int).tolist()) != expected_years:
            raise ValueError(f"Year range mismatch in scenario {scenario}.")

    numeric_non_negative = ["HDD", "HD", "RHDD", "G_Hor"]
    for col in numeric_non_negative:
        if (projection_df[col] < 0).any():
            raise ValueError(f"Column {col} contains negative values.")

    for scenario in hdd_deltas_per_year.keys():
        baseline_row = projection_df[
            (projection_df["scenario"] == scenario) & (projection_df["year"] == baseline_year)
        ]
        if baseline_row.empty:
            raise ValueError(f"Baseline year row missing for {scenario}.")
        row = baseline_row.iloc[0]
        if not math.isclose(float(row["HDD"]), float(baseline["HDD0"]), rel_tol=0.0, abs_tol=1e-8):
            raise ValueError(f"HDD baseline mismatch for {scenario}.")
        if not math.isclose(float(row["HD"]), float(baseline["HD0"]), rel_tol=0.0, abs_tol=1e-8):
            raise ValueError(f"HD baseline mismatch for {scenario}.")

    expected_ratio = 1.0 + (delta_t_i_minus_thg * float(baseline["nHD0"])) / float(baseline["HDD0"])
    ratio = projection_df["RHDD"] / projection_df["HDD"].replace(0.0, pd.NA)
    ratio = ratio.dropna()
    if not ((ratio - expected_ratio).abs() < 1e-8).all():
        raise ValueError("RHDD/HDD ratio is not constant as expected by formula.")


def export_surface_projection_to_csv(surface_df: pd.DataFrame, output_csv_path: str | Path) -> None:
    """
    Export wide-format surface projection table to CSV.
    """
    Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
    surface_df.to_csv(output_csv_path, index=True)


def export_climate_projection_to_csv(projection_df: pd.DataFrame, output_csv_path: str | Path) -> None:
    """
    Export scenario climate + solar projection table.
    """
    Path(output_csv_path).parent.mkdir(parents=True, exist_ok=True)
    df_to_export = projection_df.copy()
    float_cols = df_to_export.select_dtypes(include=["float", "float64", "float32"]).columns
    df_to_export[float_cols] = df_to_export[float_cols].round(2)
    df_to_export.to_csv(output_csv_path, index=False, float_format="%.2f")


def plot_surface_projection(
    surface_df: pd.DataFrame,
    surfaces: Iterable[str] = DEFAULT_SURFACES_TO_PLOT,
    uncertainty_fraction: float = 0.12,
    title: str = "Projected Solar Irradiance by Surface",
) -> Tuple[plt.Figure, plt.Axes]:
    """
    Plot selected surface projections with +/- uncertainty bands.
    """
    selected = [surface for surface in surfaces if surface in surface_df.columns]
    if not selected:
        raise ValueError("None of the requested surfaces exist in surface_df.")

    fig, ax = plt.subplots(figsize=(10, 6))
    years = surface_df.index.values

    for surface in selected:
        values = surface_df[surface].astype(float)
        lower = values * (1.0 - uncertainty_fraction)
        upper = values * (1.0 + uncertainty_fraction)

        ax.plot(years, values, label=surface)
        ax.fill_between(years, lower, upper, alpha=0.2)

    ax.set_title(title)
    ax.set_xlabel("Year")
    ax.set_ylabel("Irradiance [W/m²]")
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    return fig, ax


def run_solar_projection(
    baseline_horizontal_irradiance: float,
    baseline_year: int = 2005,
    end_year: int = 2100,
    growth_rate_per_decade: float = 0.01,
    surfaces_to_plot: Iterable[str] = DEFAULT_SURFACES_TO_PLOT,
    output_csv_path: str = "solar_projection.csv",
    show_plot: bool = True,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Keep old solar-only workflow for compatibility.
    """
    horizontal_df = project_horizontal_irradiance(
        baseline_horizontal_irradiance=baseline_horizontal_irradiance,
        baseline_year=baseline_year,
        end_year=end_year,
        growth_rate_per_decade=growth_rate_per_decade,
    )
    surface_df = convert_to_surface_irradiance(horizontal_df)
    export_surface_projection_to_csv(surface_df, output_csv_path)
    plot_surface_projection(surface_df, surfaces=surfaces_to_plot, uncertainty_fraction=0.12)

    if show_plot:
        plt.show()

    return horizontal_df, surface_df


def run_climate_and_solar_projection(
    iwu_csv_path: str | Path = DEFAULT_IWU_PATH,
    climate_column: str = "Klima.2",
    end_year: int = 2100,
    growth_rate_per_decade: float = 0.01,
    hdd_deltas_per_year: Mapping[str, float] = DEFAULT_HDD_DELTAS_PER_YEAR,
    delta_t_i_minus_thg: float = 5.0,
    output_csv_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> pd.DataFrame:
    """
    End-to-end workflow for annual climate + solar projections by scenario.
    """
    baseline = load_iwu_baseline(iwu_csv_path=iwu_csv_path, climate_column=climate_column)
    projection_df = build_climate_projection_table(
        baseline=baseline,
        end_year=end_year,
        growth_rate_per_decade=growth_rate_per_decade,
        hdd_deltas_per_year=hdd_deltas_per_year,
        delta_t_i_minus_thg=delta_t_i_minus_thg,
    )
    validate_projection_table(
        projection_df=projection_df,
        baseline=baseline,
        end_year=end_year,
        hdd_deltas_per_year=hdd_deltas_per_year,
        delta_t_i_minus_thg=delta_t_i_minus_thg,
    )
    export_climate_projection_to_csv(projection_df, output_csv_path=output_csv_path)
    return projection_df


if __name__ == "__main__":
    df = run_climate_and_solar_projection()
    print(f"Saved {len(df)} rows to: {DEFAULT_OUTPUT_PATH}")
