"""Unit tests for solar_bess_risk.data_sources module.

Tests written FIRST (TDD) — must FAIL until data_sources.py is implemented.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams


def _setup_mock_bq(mock_bq_module, n_rows=HOURS_PER_YEAR, price=220.0, query_error=None, client_error=None):
    """Configure a mock google.cloud.bigquery module and return mock client."""
    if client_error:
        mock_bq_module.Client.side_effect = client_error
        return None

    mock_client = MagicMock()
    mock_bq_module.Client.return_value = mock_client

    if query_error:
        mock_client.query.side_effect = query_error
        return mock_client

    mock_result = MagicMock()
    mock_result.__iter__ = MagicMock(
        return_value=iter([{"pld_brl_per_mwh": price}] * n_rows)
    )
    mock_result.__len__ = MagicMock(return_value=n_rows)
    mock_client.query.return_value = mock_result
    # Also set up QueryJobConfig and ScalarQueryParameter
    mock_bq_module.QueryJobConfig.return_value = MagicMock()
    mock_bq_module.ScalarQueryParameter.return_value = MagicMock()
    return mock_client


class TestFetchPriceBigquery:
    """BigQuery PLD price fetcher."""

    def test_returns_price_profile(self):
        from solar_bess_risk.data_sources import PriceProfile, fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq)

        with patch.dict(sys.modules, {"google.cloud.bigquery": mock_bq, "google.cloud": MagicMock()}):
            # Need to reload to pick up the mock
            import importlib
            import solar_bess_risk.data_sources as ds
            # Patch the import inside the function
            with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
                params = SimulationParams()
                profile = fetch_price_bigquery(params)
                assert isinstance(profile, PriceProfile)

    def test_source_is_bigquery_pld(self):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq)

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams()
            profile = fetch_price_bigquery(params)
            assert profile.source == "bigquery_pld"

    def test_prices_length_8760(self):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq)

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams()
            profile = fetch_price_bigquery(params)
            assert len(profile.prices_brl_per_mwh) == HOURS_PER_YEAR

    def test_all_prices_non_negative(self):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq, price=150.0)

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams()
            profile = fetch_price_bigquery(params)
            assert np.all(profile.prices_brl_per_mwh >= 0)

    def test_submarket_and_year_populated(self):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq)

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams(bq_submarket="NE", bq_year=2024)
            profile = fetch_price_bigquery(params)
            assert profile.bq_submarket == "NE"
            assert profile.bq_year == 2024

    def test_auth_error_raises_datasource_error(self):
        from solar_bess_risk.data_sources import DataSourceError, fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq, client_error=Exception("Authentication failed"))

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams()
            with pytest.raises(DataSourceError):
                fetch_price_bigquery(params)

    def test_row_count_mismatch_raises_datasource_error(self):
        from solar_bess_risk.data_sources import DataSourceError, fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq, n_rows=100, price=220.0)

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams()
            with pytest.raises(DataSourceError, match="8.760"):
                fetch_price_bigquery(params)

    def test_network_error_raises_datasource_error(self):
        from solar_bess_risk.data_sources import DataSourceError, fetch_price_bigquery

        mock_bq = MagicMock()
        _setup_mock_bq(mock_bq, query_error=Exception("Network unreachable"))

        with patch("solar_bess_risk.data_sources._get_bigquery_module", return_value=mock_bq):
            params = SimulationParams()
            with pytest.raises(DataSourceError):
                fetch_price_bigquery(params)
