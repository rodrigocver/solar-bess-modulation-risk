"""BigQuery PLD price data fetcher.

Primary source
--------------
``modelagem-de-precos.pld_horario.pld_horario_pivot`` is the requested project
table. It stores one row per hour with ``datetime`` plus one PLD column per
submarket.

Fallback source
---------------
``benchmarkingmercado.ccee_infomercado`` exposes a monthly 31x24 grid. Short
months contain padding rows and may also carry null values. The fallback parser
therefore reconstructs timestamps from ``date + (hora - 1)`` and keeps only
hours that still belong to that calendar month; padding is ignored explicitly.

Leap years have 8,784 calendar hours. This model uses a fixed 8,760-hour solar
profile, so 29/Feb is removed from PLD data before validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams


class DataSourceError(Exception):
    """Raised when a price data source is unavailable or returns invalid data."""


@dataclass(frozen=True)
class PriceProfile:
    """8,760 hourly energy prices.

    Parameters
    ----------
    prices_brl_per_mwh : np.ndarray
        Hourly PLD prices in BRL/MWh, shape ``(8760,)``.
    source : str
        ``"bigquery_pld_{submarket}_{year}"``.
    bq_submarket : str
        CCEE submarket (e.g. ``"SE"``).
    bq_year : int
        Year fetched from CCEE PLD table.
    """

    prices_brl_per_mwh: np.ndarray
    source: str
    bq_submarket: str
    bq_year: int


BQ_BILLING_PROJECT = "cver-solar"
BQ_PRIMARY_TABLE = "modelagem-de-precos.pld_horario.pld_horario_pivot"
BQ_LEGACY_TABLE = (
    "benchmarkingmercado.ccee_infomercado"
    ".preco_da_liquidacao_das_diferencas_pld_por_submercado_hora"
)

# Mapeamento: código curto → nome completo usado na tabela
_SUBMARKET_MAP: dict[str, str] = {
    "SE": "SUDESTE",
    "S":  "SUL",
    "NE": "NORDESTE",
    "N":  "NORTE",
}

_PIVOT_COLUMN_BY_SUBMARKET: dict[str, str] = {
    "SE": "SUDESTE",
    "S": "SUL",
    "NE": "NORDESTE",
    "N": "NORTE",
}

LEGACY_BQ_QUERY = f"""\
SELECT date, hora, value
FROM `{BQ_LEGACY_TABLE}`
WHERE ano = @ano_date
  AND submercado = @submarket
ORDER BY date, hora
"""


def _get_bigquery_module():
    from google.cloud import bigquery
    return bigquery


def _is_leap_year(year: int) -> bool:
    return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)


def _result_to_dataframe(result) -> pd.DataFrame:
    """Convert a BigQuery result or test double to a DataFrame."""
    if hasattr(result, "to_dataframe"):
        return result.to_dataframe()
    return pd.DataFrame(list(result))


def _expected_index(year: int) -> pd.DatetimeIndex:
    """Return the model's expected 8,760-hour index for ``year``."""
    idx = pd.date_range(
        f"{year}-01-01 00:00:00",
        f"{year}-12-31 23:00:00",
        freq="h",
    )
    if _is_leap_year(year):
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
    return idx


def _normalise_hourly_prices(
    df: pd.DataFrame,
    *,
    year: int,
    source_label: str,
    datetime_col: str = "datetime",
    price_col: str = "pld",
) -> np.ndarray:
    """Validate, de-duplicate, and align hourly PLD prices to 8,760 hours."""
    required = {datetime_col, price_col}
    missing_cols = required.difference(df.columns)
    if missing_cols:
        raise DataSourceError(
            f"BigQuery retornou colunas incompletas para {source_label}: "
            f"faltando {sorted(missing_cols)}."
        )

    work = df[[datetime_col, price_col]].copy()
    work["datetime"] = pd.to_datetime(work[datetime_col], errors="coerce")
    if work["datetime"].isna().any():
        bad = int(work["datetime"].isna().sum())
        raise DataSourceError(f"{source_label}: {bad} timestamps inválidos.")
    if getattr(work["datetime"].dt, "tz", None) is not None:
        work["datetime"] = work["datetime"].dt.tz_convert(None)

    work["pld"] = pd.to_numeric(work[price_col], errors="coerce")
    work = work[work["datetime"].dt.year == year].copy()
    if _is_leap_year(year):
        feb29 = (work["datetime"].dt.month == 2) & (work["datetime"].dt.day == 29)
        work = work[~feb29].copy()

    # Duplicate timestamps should not change the hourly series; average preserves
    # deterministic behaviour and exposes true missing hours below.
    series = work.groupby("datetime", sort=True)["pld"].mean()
    expected = _expected_index(year)
    aligned = series.reindex(expected)

    missing = aligned[aligned.isna()]
    if not missing.empty:
        sample = ", ".join(ts.strftime("%Y-%m-%d %H:%M") for ts in missing.index[:10])
        raise DataSourceError(
            f"{source_label}: {len(missing)} horas válidas sem PLD após normalização; "
            f"primeiras lacunas: {sample}. Esperado {HOURS_PER_YEAR} horas completas."
        )

    if len(aligned) != HOURS_PER_YEAR:
        raise DataSourceError(
            f"{source_label}: {len(aligned)} horas após normalização; "
            f"esperado {HOURS_PER_YEAR}."
        )

    prices = aligned.to_numpy(dtype=np.float64)
    if np.any(prices < 0):
        raise DataSourceError(f"{source_label}: BigQuery retornou preços negativos.")
    return prices


def _fetch_primary_prices(client, bigquery, params: SimulationParams, submarket: str) -> np.ndarray:
    """Fetch hourly PLD from the reference table with native timestamps."""
    pivot_column = _PIVOT_COLUMN_BY_SUBMARKET.get(params.bq_submarket.upper())
    if pivot_column is None:
        raise DataSourceError(f"Submercado inválido para tabela pivot: {params.bq_submarket}")
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
    result = client.query(query, job_config=job_config)
    df = _result_to_dataframe(result)
    print(f"  Fonte horária primária: {len(df)} linhas brutas.")
    return _normalise_hourly_prices(
        df,
        year=params.bq_year,
        source_label=BQ_PRIMARY_TABLE,
        datetime_col="datetime",
        price_col="pld",
    )


def _fetch_legacy_monthly_grid(client, bigquery, params: SimulationParams, submarket: str) -> np.ndarray:
    """Fetch and normalise the legacy 31x24 monthly-grid PLD table."""
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("ano_date", "DATE", f"{params.bq_year}-01-01"),
            bigquery.ScalarQueryParameter("submarket", "STRING", submarket),
        ]
    )
    result = client.query(LEGACY_BQ_QUERY, job_config=job_config)
    df = _result_to_dataframe(result)
    if df.empty:
        raise DataSourceError(
            f"{BQ_LEGACY_TABLE}: 0 linhas para submercado={submarket}, ano={params.bq_year}."
        )

    print(f"  Fonte mensal 31x24 fallback: {len(df)} linhas brutas.")
    required = {"date", "hora", "value"}
    missing_cols = required.difference(df.columns)
    if missing_cols:
        raise DataSourceError(
            f"{BQ_LEGACY_TABLE}: colunas incompletas; faltando {sorted(missing_cols)}."
        )

    work = df.copy()
    work["month_start"] = pd.to_datetime(work["date"], errors="coerce")
    work["hora"] = pd.to_numeric(work["hora"], errors="coerce")
    if work["month_start"].isna().any() or work["hora"].isna().any():
        raise DataSourceError(f"{BQ_LEGACY_TABLE}: campos date/hora inválidos.")

    work["datetime"] = work["month_start"] + pd.to_timedelta(work["hora"] - 1, unit="h")
    valid_calendar_hour = (
        (work["datetime"].dt.year == params.bq_year)
        & (work["datetime"].dt.month == work["month_start"].dt.month)
    )
    padding_rows = int((~valid_calendar_hour).sum())
    work = work[valid_calendar_hour].copy()
    print(f"  Padding mensal ignorado: {padding_rows} linhas.")

    work = work.rename(columns={"value": "pld"})
    return _normalise_hourly_prices(
        work,
        year=params.bq_year,
        source_label=BQ_LEGACY_TABLE,
        datetime_col="datetime",
        price_col="pld",
    )


def fetch_price_bigquery(params: SimulationParams) -> PriceProfile:
    """Busca preços PLD horários no BigQuery (CCEE).

    Parameters
    ----------
    params : SimulationParams
        Deve conter ``bq_submarket``, ``bq_year`` e opcionalmente
        ``bq_service_account_path``.

    Returns
    -------
    PriceProfile
        Perfil validado de 8.760 horas.

    Raises
    ------
    DataSourceError
        Em falha de auth, rede, resultado vazio ou contagem != 8760.
    """
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
            client = bigquery.Client(
                project=BQ_BILLING_PROJECT,
                credentials=credentials,
            )
        else:
            client = bigquery.Client(project=BQ_BILLING_PROJECT)
    except Exception as exc:
        raise DataSourceError(f"Erro de autenticação BigQuery: {exc}") from exc

    bq_submarket_label = _SUBMARKET_MAP.get(params.bq_submarket.upper(), params.bq_submarket)

    print(
        f"  Buscando PLD no BigQuery — "
        f"submercado={bq_submarket_label}, ano={params.bq_year}..."
    )

    errors: list[str] = []
    try:
        prices = _fetch_primary_prices(client, bigquery, params, bq_submarket_label)
    except Exception as exc:
        errors.append(f"fonte primária: {exc}")
        try:
            prices = _fetch_legacy_monthly_grid(client, bigquery, params, bq_submarket_label)
        except Exception as fallback_exc:
            errors.append(f"fallback 31x24: {fallback_exc}")
            raise DataSourceError("Erro na consulta/normalização BigQuery. " + " | ".join(errors)) from fallback_exc

    print(
        f"  PLD — min: R${prices.min():.2f}, "
        f"max: R${prices.max():.2f}, "
        f"média: R${prices.mean():.2f}/MWh"
    )

    return PriceProfile(
        prices_brl_per_mwh=prices,
        source=f"bigquery_pld_{params.bq_submarket}_{params.bq_year}",
        bq_submarket=params.bq_submarket,
        bq_year=params.bq_year,
    )
