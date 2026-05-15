"""BigQuery PLD price data fetcher.

Functions
---------
fetch_price_bigquery(params) -> PriceProfile

Exceptions
----------
DataSourceError
    Raised on any BigQuery failure (auth, network, row count mismatch).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

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
        Always ``'bigquery_pld'``.
    bq_submarket : str
        CCEE submarket (e.g. ``"SE"``).
    bq_year : int
        Year fetched from CCEE PLD table.
    """

    prices_brl_per_mwh: np.ndarray
    source: str
    bq_submarket: str
    bq_year: int


# BigQuery table
BQ_TABLE = (
    "benchmarkingmercado.ccee_infomercado"
    ".preco_da_liquidacao_das_diferencas_pld_por_submercado_hora"
)

BQ_QUERY = f"""\
SELECT date, hora, value AS pld_brl_per_mwh
FROM `{BQ_TABLE}`
WHERE EXTRACT(YEAR FROM date) = @year
  AND submercado = @submarket
  AND value IS NOT NULL
ORDER BY date, hora
"""


def _get_bigquery_module():
    """Lazy import of google.cloud.bigquery for testability."""
    from google.cloud import bigquery
    return bigquery


def fetch_price_bigquery(params: SimulationParams) -> PriceProfile:
    """Fetch hourly PLD prices from BigQuery.

    Parameters
    ----------
    params : SimulationParams
        Must contain ``bq_billing_project``, ``bq_submarket``, ``bq_year``,
        ``bq_auth_method``, and optionally ``bq_service_account_path``.

    Returns
    -------
    PriceProfile
        Validated 8,760-row price profile.

    Raises
    ------
    DataSourceError
        On auth failure, network error, or row count mismatch.
    """
    try:
        bigquery = _get_bigquery_module()
    except ImportError as exc:
        raise DataSourceError(
            "google-cloud-bigquery não instalado. Instale com: "
            "pip install google-cloud-bigquery"
        ) from exc

    try:
        if params.bq_auth_method == "service_account" and params.bq_service_account_path:
            from google.oauth2 import service_account as sa

            credentials = sa.Credentials.from_service_account_file(
                params.bq_service_account_path,
                scopes=["https://www.googleapis.com/auth/bigquery"],
            )
            client = bigquery.Client(
                project=params.bq_billing_project, credentials=credentials
            )
        else:
            client = bigquery.Client(project=params.bq_billing_project)
    except Exception as exc:
        raise DataSourceError(
            f"Erro de autenticação BigQuery: {exc}"
        ) from exc

    try:
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("year", "INT64", params.bq_year),
                bigquery.ScalarQueryParameter("submarket", "STRING", params.bq_submarket),
            ]
        )
        result = client.query(BQ_QUERY, job_config=job_config)
        rows = list(result)
    except Exception as exc:
        raise DataSourceError(
            f"Erro na consulta BigQuery: {exc}"
        ) from exc

    n_rows = len(rows)
    if n_rows != HOURS_PER_YEAR:
        raise DataSourceError(
            f"BigQuery retornou {n_rows} linhas; esperado exatamente 8.760 "
            f"para submercado={params.bq_submarket}, ano={params.bq_year}."
        )

    prices = np.array(
        [float(row["pld_brl_per_mwh"]) for row in rows], dtype=np.float64
    )

    if np.any(prices < 0):
        raise DataSourceError(
            "BigQuery retornou preços negativos — dados inválidos."
        )

    return PriceProfile(
        prices_brl_per_mwh=prices,
        source="bigquery_pld",
        bq_submarket=params.bq_submarket,
        bq_year=params.bq_year,
    )
