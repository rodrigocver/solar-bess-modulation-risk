"""Tests for PLD source selection in the main run pipeline."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile


def test_fetch_pld_for_historical_year_uses_local_file(monkeypatch):
    import solar_bess_risk.__main__ as main_mod

    params = SimulationParams(csv_path="/tmp/solar.csv", mwac=100.0, bq_submarket="SE")
    local_profile = PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, 100.0),
        source="local_pld_SE_2025",
        bq_submarket="SE",
        bq_year=2025,
    )

    monkeypatch.setattr(
        main_mod,
        "load_price_local_pld",
        lambda year, submarket, path=None, source_year=2025: local_profile,
    )
    monkeypatch.setattr(
        main_mod,
        "fetch_price_bigquery",
        lambda params: (_ for _ in ()).throw(AssertionError("BigQuery should not be used")),
    )

    result, factor = main_mod._fetch_pld_for_year(2025, params)

    assert result is local_profile
    assert factor is None


def test_fetch_pld_for_2026_uses_bigquery_observed_and_local_2025_base(monkeypatch):
    import solar_bess_risk.__main__ as main_mod
    import solar_bess_risk.backtest as backtest_mod

    params = SimulationParams(csv_path="/tmp/solar.csv", mwac=100.0, bq_submarket="SE")
    base_profile = PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, 200.0),
        source="local_pld_SE_2025",
        bq_submarket="SE",
        bq_year=2025,
    )
    projected_profile = PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, 250.0),
        source="bigquery_pld_SE_2026_partial_projected_from_2025",
        bq_submarket="SE",
        bq_year=2026,
    )
    loaded_years: list[int] = []

    def fake_load_local(year: int, submarket: str, path=None, source_year=2025) -> PriceProfile:
        assert source_year == 2025
        loaded_years.append(year)
        return base_profile

    def fake_fetch_observed(year_params):
        assert year_params.bq_year == 2026
        return pd.Series(np.full(100, 250.0))

    def fake_project(observed, base_prices, *, target_year, base_year, submarket):
        assert base_prices is base_profile
        assert target_year == 2026
        assert base_year == 2025
        assert submarket == "SE"
        return SimpleNamespace(
            profile=projected_profile,
            metadata=SimpleNamespace(
                observed_hours=100,
                projected_hours=HOURS_PER_YEAR - 100,
                projection_factor=1.25,
            ),
        )

    monkeypatch.setattr(main_mod, "load_price_local_pld", fake_load_local)
    monkeypatch.setattr(
        main_mod,
        "fetch_price_bigquery",
        lambda params: (_ for _ in ()).throw(AssertionError("Full-year BigQuery should not be used")),
    )
    monkeypatch.setattr(backtest_mod, "_fetch_observed_primary_series", fake_fetch_observed)
    monkeypatch.setattr(backtest_mod, "_project_partial_year_prices", fake_project)

    result, factor = main_mod._fetch_pld_for_year(2026, params)

    assert result is projected_profile
    assert factor == 1.25
    assert loaded_years == [2025]
