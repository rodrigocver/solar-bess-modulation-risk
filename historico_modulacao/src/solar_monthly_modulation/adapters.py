"""Adapters around existing Solar+BESS data loaders."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from solar_bess_risk.data_sources import (
    BQ_PRIMARY_TABLE,
    PriceProfile,
    _PIVOT_COLUMN_BY_SUBMARKET,
    _expected_index,
    _get_bigquery_module,
    _is_leap_year,
    _result_to_dataframe,
    load_price_local_pld,
)
from solar_bess_risk.profile import SolarProfile, load_solar_csv

from solar_monthly_modulation.constants import HOURS_PER_YEAR
from solar_monthly_modulation.errors import ModulationValidationError
from solar_monthly_modulation.models import HourlyPriceSeries


def load_solar_without_bess(csv_path: str, mwac: float) -> SolarProfile:
    """Load a validated solar generation profile without BESS.

    Parameters
    ----------
    csv_path : str
        Source CSV path for the solar generation curve.
    mwac : float
        Plant AC capacity in MWac.

    Returns
    -------
    solar_bess_risk.profile.SolarProfile
        Validated solar profile from the existing project loader.
    """

    try:
        return load_solar_csv(csv_path, mwac)
    except FileNotFoundError as exc:
        raise ModulationValidationError(str(exc)) from exc
    except ValueError as exc:
        fallback = _load_legacy_multi_year_avg_generation(csv_path, mwac)
        if fallback is not None:
            return fallback
        raise ModulationValidationError(str(exc)) from exc


def load_local_pld_year(
    year: int,
    submarket: str,
    pld_base_dir: str | Path,
) -> PriceProfile:
    """Load a validated local PLD series for one year.

    Parameters
    ----------
    year : int
        PLD calendar year.
    submarket : str
        CCEE submarket code.
    pld_base_dir : str or pathlib.Path
        Directory containing local PLD files.

    Returns
    -------
    solar_bess_risk.data_sources.PriceProfile
        Validated hourly PLD profile with 8,760 BRL/MWh values.
    """

    try:
        return load_price_local_pld(year, submarket, base_dir=pld_base_dir)
    except Exception as exc:
        raise ModulationValidationError(str(exc)) from exc


def load_price_series_for_year(
    year: int,
    submarket: str,
    pld_base_dir: str | Path,
    bq_service_account_path: str | None = None,
) -> HourlyPriceSeries:
    """Load local historical PLD or observed BigQuery PLD for one year.

    Parameters
    ----------
    year : int
        PLD calendar year.
    submarket : str
        CCEE submarket code.
    pld_base_dir : str or pathlib.Path
        Local PLD directory for years available as CSV.
    bq_service_account_path : str or None
        Optional service account JSON path for BigQuery authentication.

    Returns
    -------
    HourlyPriceSeries
        Timestamped hourly PLD values in BRL/MWh.
    """

    if year <= 2025:
        profile = load_local_pld_year(year, submarket, pld_base_dir)
        return HourlyPriceSeries(
            year=year,
            submarket=submarket,
            timestamps=_expected_index(year),
            prices_brl_per_mwh=pd.Series(profile.prices_brl_per_mwh, index=_expected_index(year)),
            source=profile.source,
        )
    return load_observed_bigquery_pld(year, submarket, bq_service_account_path)


def load_observed_bigquery_pld(
    year: int,
    submarket: str,
    bq_service_account_path: str | None = None,
) -> HourlyPriceSeries:
    """Load currently available hourly PLD from the BigQuery primary table.

    Parameters
    ----------
    year : int
        PLD calendar year, including partial current years such as 2026.
    submarket : str
        CCEE submarket code.
    bq_service_account_path : str or None
        Optional service account JSON path for BigQuery authentication.

    Returns
    -------
    HourlyPriceSeries
        Observed hourly PLD values only; no projection or interpolation is applied.

    Raises
    ------
    ModulationValidationError
        If BigQuery is unavailable or returns no valid observed prices.
    """

    pivot_column = _PIVOT_COLUMN_BY_SUBMARKET.get(submarket.upper())
    if pivot_column is None:
        raise ModulationValidationError(f"Submercado inválido para BigQuery: {submarket}.")

    try:
        bigquery = _get_bigquery_module()
        if bq_service_account_path:
            from google.oauth2 import service_account as sa

            credentials = sa.Credentials.from_service_account_file(
                bq_service_account_path,
                scopes=["https://www.googleapis.com/auth/bigquery"],
            )
            client = bigquery.Client(project="cver-solar", credentials=credentials)
        else:
            client = bigquery.Client(project="cver-solar")
    except Exception as exc:
        raise ModulationValidationError(f"Erro de autenticação BigQuery: {exc}") from exc

    query = f"""\
SELECT datetime, `{pivot_column}` AS pld
FROM `{BQ_PRIMARY_TABLE}`
WHERE DATE(datetime) BETWEEN @start_date AND @end_date
ORDER BY datetime
"""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", f"{year}-01-01"),
            bigquery.ScalarQueryParameter("end_date", "DATE", f"{year}-12-31"),
        ]
    )
    try:
        df = _result_to_dataframe(client.query(query, job_config=job_config))
    except Exception as exc:
        raise ModulationValidationError(f"Erro ao consultar PLD {year} no BigQuery: {exc}") from exc
    return _observed_dataframe_to_price_series(df, year, submarket)


def _load_legacy_multi_year_avg_generation(
    csv_path: str,
    mwac: float,
) -> SolarProfile | None:
    """Load legacy stacked ``avg_generation`` files without ``year_idx``.

    Parameters
    ----------
    csv_path : str
        Source CSV path.
    mwac : float
        Plant AC capacity in MWac.

    Returns
    -------
    SolarProfile or None
        Solar profile when the file matches the legacy stacked format; otherwise None.
    """

    path = Path(csv_path)
    if not path.exists() or mwac <= 0:
        return None
    sep = _detect_separator(path)
    df = pd.read_csv(path, sep=sep)
    df.columns = [str(column).strip() for column in df.columns]
    if "avg_generation" not in df.columns:
        return None
    if len(df) <= HOURS_PER_YEAR or len(df) % HOURS_PER_YEAR != 0:
        return None

    numeric = pd.to_numeric(df["avg_generation"], errors="coerce")
    if numeric.isna().any():
        first_bad = int(np.flatnonzero(numeric.isna().to_numpy())[0])
        raise ModulationValidationError(
            f"Coluna 'avg_generation': valor não numérico na posição {first_bad}."
        )

    clipped = numeric.clip(lower=0).to_numpy(dtype=np.float64)
    n_years = len(clipped) // HOURS_PER_YEAR
    yearly = clipped.reshape(n_years, HOURS_PER_YEAR)
    annual_energy_mwh = float(yearly.sum(axis=1).mean())
    if annual_energy_mwh <= 0:
        raise ModulationValidationError(
            "CSV solar com energia anual zero; não é possível calcular modulação."
        )
    fc = annual_energy_mwh / (mwac * HOURS_PER_YEAR)
    garantia_fisica_mw = mwac * fc

    print(
        f"  CSV legado multi-ano carregado: {path.name} "
        f"({n_years} anos x {HOURS_PER_YEAR} horas)."
    )
    return SolarProfile(
        generation_mw=yearly[0],
        annual_energy_mwh=annual_energy_mwh,
        fc=fc,
        garantia_fisica_mw=garantia_fisica_mw,
        csv_filename=path.name,
        generation_lim_mw=yearly[0],
        generation_bess_mw=yearly[0],
        generation_years_lim_mw=yearly,
        generation_years_bess_mw=yearly,
        n_years=n_years,
    )


def _detect_separator(path: Path) -> str:
    with path.open("r", encoding="utf-8-sig") as handle:
        first_line = handle.readline()
    return ";" if ";" in first_line else ","


def _observed_dataframe_to_price_series(
    df: pd.DataFrame,
    year: int,
    submarket: str,
) -> HourlyPriceSeries:
    required = {"datetime", "pld"}
    missing = required.difference(df.columns)
    if missing:
        raise ModulationValidationError(
            f"BigQuery PLD {year}: colunas ausentes {sorted(missing)}."
        )

    work = df[["datetime", "pld"]].copy()
    work["datetime"] = pd.to_datetime(work["datetime"], errors="coerce")
    work["pld"] = pd.to_numeric(work["pld"], errors="coerce")
    work = work.dropna(subset=["datetime", "pld"])
    work = work[work["datetime"].dt.year == year].copy()
    if _is_leap_year(year):
        feb29 = (work["datetime"].dt.month == 2) & (work["datetime"].dt.day == 29)
        work = work[~feb29].copy()
    if work.empty:
        raise ModulationValidationError(f"BigQuery PLD {year}: nenhum dado observado.")
    if (work["pld"] < 0).any():
        raise ModulationValidationError(f"BigQuery PLD {year}: preços negativos encontrados.")

    series = work.groupby("datetime", sort=True)["pld"].mean()
    expected = _expected_index(year)
    observed = series.reindex(expected).dropna()
    if observed.empty:
        raise ModulationValidationError(f"BigQuery PLD {year}: série observada vazia.")

    print(
        f"  PLD BigQuery observado {year} — horas={len(observed)}, "
        f"submercado={submarket.upper()}, min=R${observed.min():.2f}, "
        f"max=R${observed.max():.2f}, média=R${observed.mean():.2f}/MWh"
    )
    return HourlyPriceSeries(
        year=year,
        submarket=submarket.upper(),
        timestamps=pd.DatetimeIndex(observed.index),
        prices_brl_per_mwh=observed.astype(float),
        source=f"bigquery_observed_pld_{submarket.upper()}_{year}",
    )
