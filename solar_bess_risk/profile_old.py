"""Solar profile CSV loading and garantia física computation.

Functions
---------
load_solar_csv(path, mwac) -> SolarProfile
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np

from solar_bess_risk.config import HOURS_PER_YEAR


class StructuredError(Exception):
    """Raised for structured validation errors with context."""


@dataclass(frozen=True)
class SolarProfile:
    """8,760 hourly AC generation values loaded from CSV.

    Parameters
    ----------
    generation_mw : np.ndarray
        Hourly AC power in MW, shape ``(8760,)``, all values >= 0.
    annual_energy_mwh : float
        ``sum(generation_mw)`` — total annual energy.
    fc : float
        Capacity factor: ``annual_energy_mwh / (mwac * 8760)``.
    garantia_fisica_mw : float
        Physical guarantee: ``mwac * fc``.
    csv_filename : str
        Basename of the source CSV file.
    """

    generation_mw: np.ndarray
    annual_energy_mwh: float
    fc: float
    garantia_fisica_mw: float
    csv_filename: str


def load_solar_csv(path: str, mwac: float) -> SolarProfile:
    """Load a solar generation profile from a CSV file.

    Parameters
    ----------
    path : str
        Path to the CSV file (8,760 rows of non-negative MW values).
    mwac : float
        Plant AC capacity in MW. Must be > 0.

    Returns
    -------
    SolarProfile
        Loaded profile with garantia física computed.

    Raises
    ------
    ValueError
        If row count != 8,760, any value is non-numeric, or any value is negative.
    StructuredError
        If the profile has zero annual energy.
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
                f"— esperado número >= 0."
            )
        if val < 0:
            raise ValueError(
                f"ERRO: CSV '{path}': linha {i + 1}: valor negativo {val} "
                f"— esperado número >= 0."
            )
        values.append(val)

    if len(values) != HOURS_PER_YEAR:
        raise ValueError(
            f"ERRO: CSV '{path}': {len(values)} linhas encontradas; "
            f"esperado exatamente 8760."
        )

    generation_mw = np.array(values, dtype=np.float64)
    annual_energy_mwh = float(np.sum(generation_mw))

    if annual_energy_mwh <= 0:
        raise StructuredError(
            "Solar CSV has zero annual energy; cannot derive garantia física"
        )

    fc = annual_energy_mwh / (mwac * HOURS_PER_YEAR)
    garantia_fisica_mw = mwac * fc

    print(f"  CSV carregado: {os.path.basename(path)}")
    print(f"  Geração — min: {generation_mw.min():.2f} MW, max: {generation_mw.max():.2f} MW, "
          f"média: {generation_mw.mean():.2f} MW")
    print(f"  fc = {fc:.4f} | garantia_fisica = {garantia_fisica_mw:.2f} MW")

    return SolarProfile(
        generation_mw=generation_mw,
        annual_energy_mwh=annual_energy_mwh,
        fc=fc,
        garantia_fisica_mw=garantia_fisica_mw,
        csv_filename=os.path.basename(path),
    )
