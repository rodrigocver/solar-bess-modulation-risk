"""Solar profile CSV loading and garantia física computation.

Functions
---------
load_solar_csv(path, mwac) -> SolarProfile
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import numpy as np
import pandas as pd

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

    Preferred project format is a semicolon-separated CSV with an
    ``avg_generation`` column (index, month, day, hour, minute,
    avg_generation, ano_1). A headerless one-column CSV is also accepted for
    tests and simple inputs. Negative values are clamped to zero because the
    Baguaçu file contains small negative night-time sensor/model noise.

    Parameters
    ----------
    path : str
        Path to the CSV file.
    mwac : float
        Plant AC capacity in MW. Must be > 0.

    Returns
    -------
    SolarProfile
        Loaded profile with garantia física computed.

    Raises
    ------
    FileNotFoundError
        If the CSV file does not exist.
    ValueError
        If ``avg_generation`` column is missing or row count != 8,760.
    StructuredError
        If the profile has zero annual energy.
    """
    if mwac <= 0:
        raise ValueError(f"ERRO: MWac deve ser > 0; recebido {mwac}.")

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"ERRO: CSV não encontrado: '{path}'. "
            "Coloque o arquivo na raiz do projeto."
        )

    sep = _detect_separator(path)
    try:
        raw_generation = _read_generation_series(path, sep)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(
            f"ERRO: Falha ao ler CSV '{path}': {exc}"
        ) from exc

    if len(raw_generation) != HOURS_PER_YEAR:
        raise ValueError(
            f"ERRO: CSV '{path}': {len(raw_generation)} linhas de dados encontradas; "
            f"esperado exatamente {HOURS_PER_YEAR}."
        )

    numeric_generation = pd.to_numeric(raw_generation, errors="coerce")
    invalid_mask = numeric_generation.isna()
    if invalid_mask.any():
        first_bad_idx = int(np.flatnonzero(invalid_mask.to_numpy())[0])
        bad_value = raw_generation.iloc[first_bad_idx]
        raise ValueError(
            f"ERRO: CSV '{path}': valor não numérico na linha {first_bad_idx} "
            f"(valor={bad_value!r})."
        )

    negative_count = int((numeric_generation < 0).sum())
    if negative_count:
        print(f"  Aviso: {negative_count} valores negativos no CSV foram considerados zero.")

    generation_mw = numeric_generation.clip(lower=0).to_numpy(dtype=np.float64)
    annual_energy_mwh = float(np.sum(generation_mw))

    if annual_energy_mwh <= 0:
        raise StructuredError(
            "CSV solar com energia anual zero; não é possível derivar a garantia física."
        )

    fc = annual_energy_mwh / (mwac * HOURS_PER_YEAR)
    garantia_fisica_mw = mwac * fc

    print(f"  CSV carregado: {os.path.basename(path)}")
    print(
        f"  Geração — min: {generation_mw.min():.2f} MW, "
        f"max: {generation_mw.max():.2f} MW, "
        f"média: {generation_mw.mean():.2f} MW"
    )
    print(f"  fc = {fc:.4f} | garantia_fisica = {garantia_fisica_mw:.2f} MW")

    return SolarProfile(
        generation_mw=generation_mw,
        annual_energy_mwh=annual_energy_mwh,
        fc=fc,
        garantia_fisica_mw=garantia_fisica_mw,
        csv_filename=os.path.basename(path),
    )


def _detect_separator(path: str) -> str:
    """Detect comma vs semicolon separator from the first line."""
    with open(path, "r", encoding="utf-8-sig") as handle:
        first_line = handle.readline()
    return ";" if ";" in first_line else ","


def _read_generation_series(path: str, sep: str) -> pd.Series:
    """Read the intended generation column from a supported CSV layout."""
    df = pd.read_csv(path, sep=sep)
    df.columns = [str(c).strip() for c in df.columns]

    if "avg_generation" in df.columns:
        return df["avg_generation"]

    if len(df.columns) == 1:
        # Headerless one-column files are parsed by pandas with the first data
        # row as the column name unless we explicitly re-read with header=None.
        return pd.read_csv(path, sep=sep, header=None).iloc[:, 0]

    preferred_names = ("generation_mw", "generation", "geracao", "ano_1")
    for name in preferred_names:
        if name in df.columns:
            return df[name]

    numeric_columns = []
    for column in df.columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.notna().sum() == len(df):
            numeric_columns.append(column)

    if len(numeric_columns) == 1:
        return df[numeric_columns[0]]

    available = ", ".join(df.columns.tolist())
    raise ValueError(
        f"ERRO: CSV '{path}' não possui coluna 'avg_generation' nem uma única "
        f"coluna numérica inequívoca. Colunas encontradas: {available}"
    )
