"""Solar profile generation and CSV loading.

Functions
---------
generate_synthetic_profile(params) -> SolarProfile
load_solar_csv(path) -> SolarProfile
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd
import pvlib

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams


@dataclass(frozen=True)
class SolarProfile:
    """8,760 hourly AC generation values for a 1 MWac plant, normalised.

    Parameters
    ----------
    generation_mw : np.ndarray
        Hourly AC power in MW, shape ``(8760,)``, values ∈ [0.0, 1.0].
    source : str
        ``'synthetic'`` or ``'csv'``.
    source_path : str | None
        CSV path if source='csv'; None if synthetic.
    annual_energy_mwh : float
        ``sum(generation_mw)`` — total annual energy.
    """

    generation_mw: np.ndarray
    source: Literal["synthetic", "csv"]
    source_path: str | None
    annual_energy_mwh: float


def generate_synthetic_profile(params: SimulationParams) -> SolarProfile:
    """Generate a deterministic synthetic solar profile using pvlib Ineichen.

    Parameters
    ----------
    params : SimulationParams
        Must contain ``synthetic_profile_lat``, ``synthetic_profile_lon``,
        ``synthetic_profile_alt_m``.

    Returns
    -------
    SolarProfile
        Profile normalised to 1.0 MWac with source='synthetic'.
    """
    location = pvlib.location.Location(
        latitude=params.synthetic_profile_lat,
        longitude=params.synthetic_profile_lon,
        altitude=params.synthetic_profile_alt_m,
        tz="America/Sao_Paulo",
    )

    times = pd.date_range(
        "2025-01-01", periods=HOURS_PER_YEAR, freq="h", tz="America/Sao_Paulo"
    )
    cs = location.get_clearsky(times, model="ineichen")
    ghi = cs["ghi"].values.astype(np.float64)

    # Normalise by peak → capacity factor [0, 1]
    peak = ghi.max()
    if peak > 0:
        cf = ghi / peak
    else:
        cf = np.zeros(HOURS_PER_YEAR, dtype=np.float64)

    # Clip to [0, 1] MWac
    generation_mw = np.clip(cf, 0.0, 1.0)
    annual_energy_mwh = float(np.sum(generation_mw))

    return SolarProfile(
        generation_mw=generation_mw,
        source="synthetic",
        source_path=None,
        annual_energy_mwh=annual_energy_mwh,
    )


def load_solar_csv(path: str) -> SolarProfile:
    """Load a solar generation profile from a single-column CSV.

    Parameters
    ----------
    path : str
        Path to CSV file with 8,760 rows of non-negative numeric values in MW.

    Returns
    -------
    SolarProfile
        Loaded profile with source='csv'.

    Raises
    ------
    ValueError
        If row count ≠ 8,760, any value is non-numeric, or any value is negative.
    """
    lines = open(path, "r").read().strip().splitlines()

    values: list[float] = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        try:
            val = float(line)
        except ValueError:
            raise ValueError(
                f"ERRO: CSV '{path}': linha {i + 1}: valor inválido '{line}' "
                f"— esperado número ≥ 0."
            )
        if val < 0:
            raise ValueError(
                f"ERRO: CSV '{path}': linha {i + 1}: valor inválido '{val}' "
                f"— esperado número ≥ 0."
            )
        values.append(val)

    if len(values) != HOURS_PER_YEAR:
        raise ValueError(
            f"ERRO: CSV '{path}': {len(values)} linhas encontradas; "
            f"esperado exatamente 8.760."
        )

    generation_mw = np.array(values, dtype=np.float64)
    # Cap at 1.0 MWac
    generation_mw = np.clip(generation_mw, 0.0, 1.0)
    annual_energy_mwh = float(np.sum(generation_mw))

    return SolarProfile(
        generation_mw=generation_mw,
        source="csv",
        source_path=path,
        annual_energy_mwh=annual_energy_mwh,
    )
