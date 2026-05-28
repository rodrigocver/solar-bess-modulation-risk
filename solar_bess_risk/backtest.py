"""Historical PLD backtest utilities for fixed BESS guarantee scenarios."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR
from solar_bess_risk.config import BESS_BLOCK_SPECS, CAPEX_USD_PER_KWH, SCENARIO_TEMPLATES, SimulationParams
from solar_bess_risk.data_sources import (
    BQ_PRIMARY_TABLE,
    DataSourceError,
    PriceProfile,
    _PIVOT_COLUMN_BY_SUBMARKET,
    _expected_index,
    _get_bigquery_module,
    _is_leap_year,
    _result_to_dataframe,
    fetch_price_bigquery,
)
from solar_bess_risk.economics import compute_all_scenarios
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.simulation import ScenarioDefinition, simulate_all_scenarios


WINDOW_BY_LABEL = {
    "A": "18:00-20:00",
    "B": "17:00-20:00",
    "C": "17:00-21:00",
}


@dataclass(frozen=True)
class PriceFetchMetadata:
    """Describe whether a backtest price year is observed or projected."""

    source: str
    observed_hours: int
    projected_hours: int
    projection_factor: float | None = None
    projection_base_year: int | None = None


@dataclass(frozen=True)
class PriceFetchResult:
    """Price profile plus metadata used by the backtest output table."""

    profile: PriceProfile
    metadata: PriceFetchMetadata


def build_scenarios(garantia_fisica_mw: float, params: SimulationParams) -> list[ScenarioDefinition]:
    """Build BESS scenarios using block-based sizing from the solar-derived guarantee."""
    import math

    scenarios = []
    for template in SCENARIO_TEMPLATES:
        block = BESS_BLOCK_SPECS[template.duration_h]
        n_blocks = math.ceil(garantia_fisica_mw / block.block_power_mw)
        bess_power = n_blocks * block.block_power_mw
        bess_energy = n_blocks * block.block_energy_mwh
        capex_brl = bess_energy * 1000 * CAPEX_USD_PER_KWH[template.duration_h] * params.usd_brl_rate

        scenarios.append(ScenarioDefinition(
            label=template.label,
            peak_hours=template.peak_hours,
            duration_h=template.duration_h,
            bess_power_mw=bess_power,
            bess_energy_mwh=bess_energy,
            capex_brl=capex_brl,
            charge_power_mw=bess_power,
            peak_hour_weights=template.peak_hour_weights,
        ))
    return scenarios


def _client_from_params(params: SimulationParams):
    """Create a BigQuery client using the same authentication path as production fetches."""
    try:
        bigquery = _get_bigquery_module()
    except ImportError as exc:
        raise DataSourceError(
            "google-cloud-bigquery não instalado. "
            "Instale com: uv add google-cloud-bigquery"
        ) from exc

    try:
        if params.bq_service_account_path:
            from google.oauth2 import service_account as sa

            credentials = sa.Credentials.from_service_account_file(
                params.bq_service_account_path,
                scopes=["https://www.googleapis.com/auth/bigquery"],
            )
            client = bigquery.Client(project="cver-solar", credentials=credentials)
        else:
            client = bigquery.Client(project="cver-solar")
    except Exception as exc:
        raise DataSourceError(f"Erro de autenticação BigQuery: {exc}") from exc

    return client, bigquery


def _fetch_observed_primary_series(params: SimulationParams) -> pd.Series:
    """Fetch available hourly PLD from the pivot table without requiring a full year."""
    pivot_column = _PIVOT_COLUMN_BY_SUBMARKET.get(params.bq_submarket.upper())
    if pivot_column is None:
        raise DataSourceError(f"Submercado inválido para tabela pivot: {params.bq_submarket}")

    client, bigquery = _client_from_params(params)
    query = f"""\
SELECT datetime, `{pivot_column}` AS pld
FROM `{BQ_PRIMARY_TABLE}`
WHERE DATE(datetime) BETWEEN @start_date AND @end_date
ORDER BY datetime
"""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("start_date", "DATE", f"{params.bq_year}-01-01"),
            bigquery.ScalarQueryParameter("end_date", "DATE", f"{params.bq_year}-12-31"),
        ]
    )
    df = _result_to_dataframe(client.query(query, job_config=job_config))
    if df.empty:
        raise DataSourceError(f"{BQ_PRIMARY_TABLE}: 0 linhas para ano {params.bq_year}.")
    required = {"datetime", "pld"}
    missing_cols = required.difference(df.columns)
    if missing_cols:
        raise DataSourceError(
            f"{BQ_PRIMARY_TABLE}: colunas incompletas; faltando {sorted(missing_cols)}."
        )

    work = df[["datetime", "pld"]].copy()
    work["datetime"] = pd.to_datetime(work["datetime"], errors="coerce")
    work["pld"] = pd.to_numeric(work["pld"], errors="coerce")
    work = work.dropna(subset=["datetime", "pld"])
    work = work[work["datetime"].dt.year == params.bq_year].copy()
    if _is_leap_year(params.bq_year):
        feb29 = (work["datetime"].dt.month == 2) & (work["datetime"].dt.day == 29)
        work = work[~feb29].copy()
    if (work["pld"] < 0).any():
        raise DataSourceError(f"{BQ_PRIMARY_TABLE}: BigQuery retornou preços negativos.")

    return work.groupby("datetime", sort=True)["pld"].mean()


def _month_hour_key(index: pd.DatetimeIndex) -> pd.MultiIndex:
    """Build a month/day/hour key used to map target year hours to base-year hours."""
    return pd.MultiIndex.from_arrays(
        [index.month, index.day, index.hour],
        names=["month", "day", "hour"],
    )


def _project_partial_year_prices(
    observed: pd.Series,
    base_prices: PriceProfile,
    *,
    target_year: int,
    base_year: int,
    submarket: str,
) -> PriceFetchResult:
    """Complete a partial target year using a monthly observed/base proportional factor."""
    expected_target = _expected_index(target_year)
    observed_aligned = observed.reindex(expected_target)
    valid_observed = observed_aligned.dropna()
    if valid_observed.empty:
        raise DataSourceError(f"Não há PLD real disponível para projetar {target_year}.")

    expected_base = _expected_index(base_year)
    base_series = pd.Series(base_prices.prices_brl_per_mwh, index=expected_base)
    base_by_key = pd.Series(base_series.to_numpy(), index=_month_hour_key(expected_base))

    comparison_base = pd.Series(
        base_by_key.reindex(_month_hour_key(valid_observed.index)).to_numpy(),
        index=valid_observed.index,
    )
    comparable = pd.DataFrame({"observed": valid_observed, "base": comparison_base}).dropna()
    comparable = comparable[comparable["base"] > 0]
    if comparable.empty:
        raise DataSourceError(
            f"Não foi possível comparar {target_year} com {base_year}: "
            "sem horas-base positivas nos meses disponíveis."
        )

    monthly_ratios = comparable.groupby(comparable.index.month).apply(
        lambda month_df: month_df["observed"].mean() / month_df["base"].mean()
    )
    projection_factor = float(monthly_ratios.mean())
    if not np.isfinite(projection_factor) or projection_factor <= 0:
        raise DataSourceError(
            f"Fator de projeção inválido para {target_year}: {projection_factor}."
        )

    projected_base = pd.Series(
        base_by_key.reindex(_month_hour_key(expected_target)).to_numpy(),
        index=expected_target,
    )
    completed = observed_aligned.copy()
    missing_mask = completed.isna()
    completed.loc[missing_mask] = projected_base.loc[missing_mask] * projection_factor
    if completed.isna().any() or len(completed) != HOURS_PER_YEAR:
        raise DataSourceError(
            f"Projeção {target_year}: série final incompleta após aplicação do fator."
        )

    prices = completed.to_numpy(dtype=np.float64)
    metadata = PriceFetchMetadata(
        source=f"bigquery_pld_{submarket}_{target_year}_partial_projected_from_{base_year}",
        observed_hours=int((~missing_mask).sum()),
        projected_hours=int(missing_mask.sum()),
        projection_factor=projection_factor,
        projection_base_year=base_year,
    )
    profile = PriceProfile(
        prices_brl_per_mwh=prices,
        source=metadata.source,
        bq_submarket=submarket,
        bq_year=target_year,
    )
    return PriceFetchResult(profile=profile, metadata=metadata)


def fetch_backtest_prices(
    params: SimulationParams,
    *,
    projection_year: int | None = None,
    projection_base_year: int = 2025,
    progress_cb: Callable[[str], None] | None = None,
) -> PriceFetchResult:
    """Fetch full-year prices or complete a partial year from a base-year projection."""
    if projection_year is None or params.bq_year != projection_year:
        profile = fetch_price_bigquery(params)
        return PriceFetchResult(
            profile=profile,
            metadata=PriceFetchMetadata(
                source=profile.source,
                observed_hours=HOURS_PER_YEAR,
                projected_hours=0,
            ),
        )

    if progress_cb:
        progress_cb(
            f"Projetando PLD {projection_year} com base em {projection_base_year}..."
        )
    base_profile = fetch_price_bigquery(replace(params, bq_year=projection_base_year))
    observed = _fetch_observed_primary_series(params)
    return _project_partial_year_prices(
        observed,
        base_profile,
        target_year=projection_year,
        base_year=projection_base_year,
        submarket=params.bq_submarket,
    )


def run_historical_backtest(
    params: SimulationParams,
    years: Iterable[int],
    progress_cb: Callable[[str], None] | None = None,
    *,
    projection_year: int | None = None,
    projection_base_year: int = 2025,
) -> pd.DataFrame:
    """Run the same solar+BESS sizing against historical PLD years."""
    solar = load_solar_csv(params.csv_path, params.mwac)
    scenarios = build_scenarios(solar.garantia_fisica_mw, params)
    rows: list[dict] = []

    for year in years:
        year_params = replace(params, bq_year=int(year))
        if progress_cb:
            progress_cb(f"Backtest PLD {year}...")
        price_result = fetch_backtest_prices(
            year_params,
            projection_year=projection_year,
            projection_base_year=projection_base_year,
            progress_cb=progress_cb,
        )
        prices = price_result.profile
        price_meta = price_result.metadata
        dispatch_pairs = simulate_all_scenarios(solar, prices, scenarios, year_params)
        results = compute_all_scenarios(solar, prices, dispatch_pairs, year_params)

        for result in results:
            rows.append(
                {
                    "year": year,
                    "scenario": result.scenario.label,
                    "window": WINDOW_BY_LABEL.get(result.scenario.label, result.scenario.label),
                    "duration_h": result.scenario.duration_h,
                    "fc": result.fc,
                    "garantia_fisica_mw": result.garantia_fisica_mw,
                    "bess_power_mw": result.bess_power_mw,
                    "bess_energy_mwh": result.bess_energy_mwh,
                    "capex_brl": result.capex_brl,
                    "pld_mean_brl_per_mwh": float(prices.prices_brl_per_mwh.mean()),
                    "pld_min_brl_per_mwh": float(prices.prices_brl_per_mwh.min()),
                    "pld_max_brl_per_mwh": float(prices.prices_brl_per_mwh.max()),
                    "exposure_without_bess_brl": result.annual_exposure_without_bess_brl,
                    "exposure_with_bess_brl": result.annual_exposure_with_bess_brl,
                    "annual_gross_savings_brl": result.annual_gross_savings_brl,
                    "annual_o_and_m_brl": result.annual_o_and_m_brl,
                    "annual_net_savings_brl": result.annual_savings_brl,
                    "lifetime_net_savings_brl": result.lifetime_net_savings_brl,
                    "coverage_pct": result.coverage_pct,
                    "payback_years": result.payback_years,
                    "price_source": prices.source,
                    "pld_observed_hours": price_meta.observed_hours,
                    "pld_projected_hours": price_meta.projected_hours,
                    "pld_projection_factor": price_meta.projection_factor,
                    "pld_projection_base_year": price_meta.projection_base_year,
                }
            )

    return pd.DataFrame(rows)


def write_backtest_csv(df: pd.DataFrame, output_dir: str | Path) -> Path:
    """Write backtest results to ``output_dir/backtest_<min>_<max>.csv``."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    first_year = int(df["year"].min())
    last_year = int(df["year"].max())
    path = output_path / f"backtest_{first_year}_{last_year}.csv"
    df.to_csv(path, index=False)
    return path
