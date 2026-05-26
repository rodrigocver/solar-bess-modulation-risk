"""Unit tests for historical backtest helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd

from solar_bess_risk.config import CAPEX_USD_PER_KWH, HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.backtest import _project_partial_year_prices, build_scenarios


def test_project_partial_year_uses_observed_hours_and_scaled_base_for_missing():
    """Observed target-year prices are preserved; missing hours use base-year shape."""
    base_index = pd.date_range("2025-01-01 00:00:00", "2025-12-31 23:00:00", freq="h")
    base_values = np.arange(HOURS_PER_YEAR, dtype=float) + 100.0
    base = PriceProfile(
        prices_brl_per_mwh=base_values,
        source="bigquery_pld_SE_2025",
        bq_submarket="SE",
        bq_year=2025,
    )

    observed_index = pd.date_range("2026-01-01 00:00:00", periods=48, freq="h")
    observed_values = pd.Series(
        base_values[:48] * 1.25,
        index=observed_index,
    )

    result = _project_partial_year_prices(
        observed_values,
        base,
        target_year=2026,
        base_year=2025,
        submarket="SE",
    )

    assert result.metadata.observed_hours == 48
    assert result.metadata.projected_hours == HOURS_PER_YEAR - 48
    assert abs(result.metadata.projection_factor - 1.25) < 1e-12
    np.testing.assert_allclose(result.profile.prices_brl_per_mwh[:48], observed_values.to_numpy())
    expected_projected = base_values[base_index.get_loc("2025-01-03 00:00:00")] * 1.25
    np.testing.assert_allclose(result.profile.prices_brl_per_mwh[48], expected_projected)


def test_capex_varies_by_duration_with_current_vendor_curve():
    """Scenario CAPEX uses 164.57/151.79 USD/kWh for 2h/4h, sized by blocks."""
    params = SimulationParams(csv_path="/tmp/solar.csv", mwac=100.0, usd_brl_rate=5.0)
    gf = 50.0
    scenarios = build_scenarios(gf, params)

    assert CAPEX_USD_PER_KWH == {2: 164.57, 4: 151.79}
    for scenario in scenarios:
        # CAPEX is based on block-sized bess_energy_mwh, not gf * duration_h
        expected = scenario.bess_energy_mwh * 1000 * CAPEX_USD_PER_KWH[scenario.duration_h] * 5.0
        assert abs(scenario.capex_brl - expected) < 1e-6
