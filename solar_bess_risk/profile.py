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
    """Hourly AC generation values loaded from CSV.

    Parameters
    ----------
    generation_mw : np.ndarray
        Year-1 hourly AC power **without BESS**, shape ``(8760,)``. Backward compat.
    annual_energy_mwh : float
        Mean annual energy across all years (sem BESS baseline), MWh.
    fc : float
        Capacity factor: ``annual_energy_mwh / (mwac * 8760)``.
    garantia_fisica_mw : float
        Physical guarantee: ``mwac * fc`` (average across years).
    csv_filename : str
        Basename of the source CSV file.
    generation_lim_mw : np.ndarray | None
        Year-1 hourly generation **without BESS**, shape ``(8760,)``.
    generation_bess_mw : np.ndarray | None
        Year-1 hourly generation **with BESS**, shape ``(8760,)``.
    generation_years_lim_mw : np.ndarray | None
        All years sem-BESS, shape ``(n_years, 8760)``.
    generation_years_bess_mw : np.ndarray | None
        All years com-BESS, shape ``(n_years, 8760)``.
    n_years : int
        Number of solar years available (rows in the 2-D arrays).
    """

    generation_mw: np.ndarray
    annual_energy_mwh: float
    fc: float
    garantia_fisica_mw: float
    csv_filename: str
    generation_lim_mw: np.ndarray | None = None
    generation_bess_mw: np.ndarray | None = None
    generation_years_lim_mw: np.ndarray | None = None
    generation_years_bess_mw: np.ndarray | None = None
    n_years: int = 1

    def get_year_arrays(self, year_idx: int) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(gen_lim_1d, gen_bess_1d)`` for a 1-based solar year index.

        Clamps ``year_idx`` to ``[1, n_years]`` so callers beyond the available
        range silently re-use the last year rather than raising.
        """
        idx = max(0, min(year_idx - 1, self.n_years - 1))
        if self.generation_years_lim_mw is not None:
            gen_lim = self.generation_years_lim_mw[idx]
            gen_bess = (
                self.generation_years_bess_mw[idx]
                if self.generation_years_bess_mw is not None
                else gen_lim
            )
        else:
            gen_lim = self.generation_lim_mw if self.generation_lim_mw is not None else self.generation_mw
            gen_bess = self.generation_bess_mw if self.generation_bess_mw is not None else self.generation_mw
        return gen_lim, gen_bess


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
        gen_lim_2d, gen_bess_2d = _read_generation_series_dual(path, sep)
    except Exception as exc:
        if isinstance(exc, ValueError):
            raise
        raise ValueError(
            f"ERRO: Falha ao ler CSV '{path}': {exc}"
        ) from exc

    if gen_lim_2d.shape[1] != HOURS_PER_YEAR:
        raise ValueError(
            f"ERRO: CSV '{path}' coluna gen_lim_mw: {gen_lim_2d.shape[1]} horas por ano, "
            f"esperado exatamente {HOURS_PER_YEAR}."
        )

    n_years = gen_lim_2d.shape[0]

    # Per-year annual energy; mean for scalar backward-compat fields
    annual_energy_by_year = gen_lim_2d.sum(axis=1)  # shape (n_years,)
    annual_energy_mwh = float(annual_energy_by_year.mean())

    if annual_energy_mwh <= 0:
        raise StructuredError(
            "CSV solar com energia anual zero; não é possível derivar a garantia física."
        )

    fc = annual_energy_mwh / (mwac * HOURS_PER_YEAR)
    garantia_fisica_mw = mwac * fc

    # Year-1 slices for backward-compat 1-D fields
    gen_lim_arr = gen_lim_2d[0]
    gen_bess_arr = gen_bess_2d[0]

    print(f"  CSV carregado: {os.path.basename(path)}")
    if n_years > 1:
        print(f"  Modo multi-ano: {n_years} anos de dados ({n_years * HOURS_PER_YEAR:,} horas total).")
    has_dual = not np.array_equal(gen_lim_2d, gen_bess_2d)
    if has_dual:
        clip_total = float(np.maximum(0, gen_bess_2d - gen_lim_2d).sum() / n_years)
        print(f"  Modo dual-coluna: gen_lim (sem BESS) + gen_mw (com BESS).")
        print(f"  Energia de clipping média disponível para BESS: {clip_total:.1f} MWh/ano")
    print(
        f"  Geração (sem BESS) — min: {gen_lim_2d.min():.2f} MW, "
        f"max: {gen_lim_2d.max():.2f} MW, "
        f"média: {gen_lim_2d.mean():.2f} MW"
    )
    print(f"  fc = {fc:.4f} | garantia_fisica = {garantia_fisica_mw:.2f} MW")

    return SolarProfile(
        generation_mw=gen_lim_arr,
        annual_energy_mwh=annual_energy_mwh,
        fc=fc,
        garantia_fisica_mw=garantia_fisica_mw,
        csv_filename=os.path.basename(path),
        generation_lim_mw=gen_lim_arr,
        generation_bess_mw=gen_bess_arr,
        generation_years_lim_mw=gen_lim_2d,
        generation_years_bess_mw=gen_bess_2d,
        n_years=n_years,
    )


def _detect_separator(path: str) -> str:
    """Detect comma vs semicolon separator from the first line."""
    with open(path, "r", encoding="utf-8-sig") as handle:
        first_line = handle.readline()
    return ";" if ";" in first_line else ","


def _coerce_column(series: pd.Series, label: str, silent: bool = False) -> np.ndarray:
    """Convert a pandas Series to a clamped float64 ndarray (negatives → 0)."""
    numeric = pd.to_numeric(series, errors="coerce")
    invalid_mask = numeric.isna()
    if invalid_mask.any():
        first_bad = int(np.flatnonzero(invalid_mask.to_numpy())[0])
        raise ValueError(
            f"Coluna '{label}': valor não numérico na posição {first_bad} "
            f"(valor={series.iloc[first_bad]!r})."
        )
    neg_count = int((numeric < 0).sum())
    if neg_count and not silent:
        print(f"  Aviso ({label}): {neg_count} valores negativos → zero.")
    return numeric.clip(lower=0).to_numpy(dtype=np.float64)


def _read_generation_series_dual(path: str, sep: str) -> tuple[np.ndarray, np.ndarray]:
    """Read generation columns from CSV.

    Returns ``(gen_lim_2d, gen_bess_2d)`` as float64 arrays of shape
    ``(n_years, 8760)``. For single-year CSVs ``n_years == 1``.
    Negative values are clamped to 0.
    """
    df = pd.read_csv(path, sep=sep)
    df.columns = [str(c).strip() for c in df.columns]

    if "gen_mw" in df.columns and "gen_lim_mw" in df.columns:
        n_rows = len(df)
        if n_rows > HOURS_PER_YEAR:
            if "year_idx" not in df.columns:
                raise ValueError(
                    f"ERRO: CSV tem {n_rows} linhas mas não possui coluna 'year_idx'; "
                    f"esperado {HOURS_PER_YEAR} linhas ou coluna year_idx para multi-ano."
                )
            years = sorted(df["year_idx"].unique())
            lim_blocks, bess_blocks = [], []
            total_neg_lim, total_neg_bess = 0, 0
            for y in years:
                block = df[df["year_idx"] == y].reset_index(drop=True)
                if len(block) != HOURS_PER_YEAR:
                    raise ValueError(
                        f"ERRO: year_idx={y} tem {len(block)} linhas, "
                        f"esperado {HOURS_PER_YEAR}."
                    )
                total_neg_lim += int((pd.to_numeric(block["gen_lim_mw"], errors="coerce") < 0).sum())
                total_neg_bess += int((pd.to_numeric(block["gen_mw"], errors="coerce") < 0).sum())
                lim_blocks.append(_coerce_column(block["gen_lim_mw"], f"gen_lim_mw[ano={y}]", silent=True))
                bess_blocks.append(_coerce_column(block["gen_mw"], f"gen_mw[ano={y}]", silent=True))
            if total_neg_lim:
                print(f"  Aviso (gen_lim_mw): {total_neg_lim} valores negativos → zero ({len(years)} anos).")
            if total_neg_bess:
                print(f"  Aviso (gen_mw): {total_neg_bess} valores negativos → zero ({len(years)} anos).")
            return np.stack(lim_blocks, axis=0), np.stack(bess_blocks, axis=0)
        else:
            lim = _coerce_column(df["gen_lim_mw"], "gen_lim_mw")
            bess = _coerce_column(df["gen_mw"], "gen_mw")
            return lim[np.newaxis, :], bess[np.newaxis, :]

    # Legacy / single-column fallback
    legacy = _read_generation_series_legacy(path, sep, df)
    arr = _coerce_column(legacy, "geracao")
    return arr[np.newaxis, :], arr[np.newaxis, :]


def _read_generation_series_legacy(path: str, sep: str, df: pd.DataFrame) -> pd.Series:
    """Read the intended generation column from a legacy single-column CSV."""
    if "avg_generation" in df.columns:
        return df["avg_generation"]

    if len(df.columns) == 1:
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
