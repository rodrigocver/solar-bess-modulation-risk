"""Unit tests for solar_bess_risk.data_sources — BigQuery PLD price fetcher (v2)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import DataSourceError, PriceProfile


@pytest.fixture
def params() -> SimulationParams:
    return SimulationParams(
        csv_path="/tmp/test.csv",
        mwac=100.0,
        bq_year=2025,
        bq_submarket="SE",
    )


def _mock_bq_rows(n: int = HOURS_PER_YEAR, price: float = 200.0):
    """Create mock BigQuery result rows."""
    start = datetime(2025, 1, 1)
    return [
        {"pld": price, "datetime": (start + timedelta(hours=i)).isoformat()}
        for i in range(n)
    ]


class TestFetchPriceBigquery:
    """Tests for fetch_price_bigquery."""

    def test_returns_price_profile_with_correct_source(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_rows = _mock_bq_rows(HOURS_PER_YEAR, 200.0)
        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.return_value = mock_rows

            result = fetch_price_bigquery(params)

        assert isinstance(result, PriceProfile)
        assert result.source == "bigquery_pld_SE_2025"

    def test_returns_8760_prices(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_rows = _mock_bq_rows(HOURS_PER_YEAR, 150.0)
        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.return_value = mock_rows

            result = fetch_price_bigquery(params)

        assert len(result.prices_brl_per_mwh) == HOURS_PER_YEAR

    def test_all_prices_non_negative(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_rows = _mock_bq_rows(HOURS_PER_YEAR, 100.0)
        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.return_value = mock_rows

            result = fetch_price_bigquery(params)

        assert np.all(result.prices_brl_per_mwh >= 0)

    def test_auth_failure_raises_datasource_error(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_bq.return_value.Client.side_effect = Exception("Auth failed")

            with pytest.raises(DataSourceError):
                fetch_price_bigquery(params)

    def test_network_error_raises_datasource_error(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.side_effect = Exception("Network error")

            with pytest.raises(DataSourceError):
                fetch_price_bigquery(params)

    def test_wrong_row_count_raises_datasource_error(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_rows = _mock_bq_rows(100, 200.0)  # Only 100 rows
        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.return_value = mock_rows

            with pytest.raises(DataSourceError, match="8760|8.760"):
                fetch_price_bigquery(params)

    def test_deterministic_price_arrays(self, params):
        from solar_bess_risk.data_sources import fetch_price_bigquery

        mock_rows = _mock_bq_rows(HOURS_PER_YEAR, 250.0)
        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.return_value = mock_rows

            r1 = fetch_price_bigquery(params)
            r2 = fetch_price_bigquery(params)

        np.testing.assert_array_equal(r1.prices_brl_per_mwh, r2.prices_brl_per_mwh)


def test_envision_rte_file_locks_block_and_pcs_metadata():
    from solar_bess_risk.rte import get_rte_metadata

    metadata = get_rte_metadata("dados/11 - Envision.xlsx")
    assert metadata == {
        "rte_source_file": "11 - Envision.xlsx",
        "typical_block_mwh": 10.1,
        "pcs_mva": 2.52,
    }
