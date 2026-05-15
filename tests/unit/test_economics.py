"""Unit tests for solar_bess_risk.economics module.

Tests written FIRST (TDD) — must FAIL until economics.py is implemented.
"""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.simulation import BESSConfig, DispatchResult


def _make_dispatch(
    charge_curtail: float = 0.1,
    charge_grid: float = 0.0,
    discharge_val: float = 0.1,
    top_up: list[int] | None = None,
) -> DispatchResult:
    """Create a simple DispatchResult for testing."""
    cc = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    cg = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    dis = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    soc = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    cw = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    cwo = np.zeros(HOURS_PER_YEAR, dtype=np.float64)

    # Set charge during daylight hours (6-18 each day)
    for d in range(365):
        for h in range(6, 12):
            idx = d * 24 + h
            cc[idx] = charge_curtail
            cwo[idx] = charge_curtail + 0.05  # some remained as curtailment
            cw[idx] = 0.05
        for h in range(12, 18):
            idx = d * 24 + h
            dis[idx] = discharge_val
        if charge_grid > 0:
            idx = d * 24 + 2  # 2 AM grid charge
            cg[idx] = charge_grid

    return DispatchResult(
        soc_mwh=soc,
        charge_curtail_mwh=cc,
        charge_grid_mwh=cg,
        discharge_mwh=dis,
        curtailment_with_bess_mwh=cw,
        curtailment_without_bess_mwh=cwo,
        top_up_hours=top_up or [],
    )


def _make_bess_cfg(energy_cap: float = 10.0) -> BESSConfig:
    return BESSConfig(
        energy_capacity_mwh=energy_cap,
        rated_power_mw=energy_cap / 2.0,
        capex_brl=energy_cap * 1000 * 250 * 5,  # 250 USD/kWh, rate 5
        duration_h=2.0,
        ilr=1.3,
        bess_size_ratio_pct=25.0,
    )


def _make_prices(price: float = 220.0) -> PriceProfile:
    return PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, price, dtype=np.float64),
        source="bigquery_pld",
        bq_submarket="SE",
        bq_year=2025,
    )


class TestIncrementalRevenue:
    """Revenue formula tests."""

    def test_uniform_price_revenue(self):
        from solar_bess_risk.economics import compute_incremental_revenue

        price = 220.0
        rte = 85.0
        dispatch = _make_dispatch(charge_curtail=0.1)
        prices = _make_prices(price)

        revenue = compute_incremental_revenue(dispatch, prices, rte)
        # Revenue = sum(charge_curtail * price * rte/100)
        expected = float(np.sum(dispatch.charge_curtail_mwh)) * price * (rte / 100.0)
        assert abs(revenue - expected) < 1e-6

    def test_hourly_price_revenue(self):
        from solar_bess_risk.economics import compute_incremental_revenue

        rte = 85.0
        # Create varying prices
        prices_arr = np.random.default_rng(42).uniform(100, 300, HOURS_PER_YEAR)
        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr,
            source="bigquery_pld",
            bq_submarket="SE",
            bq_year=2025,
        )
        dispatch = _make_dispatch(charge_curtail=0.1)
        revenue = compute_incremental_revenue(dispatch, prices, rte)
        expected = float(np.sum(dispatch.charge_curtail_mwh * prices_arr * (rte / 100.0)))
        assert abs(revenue - expected) < 1e-4


class TestLCOS:
    """LCOS formula tests."""

    def test_lcos_reference_case(self):
        from solar_bess_risk.economics import compute_lcos

        cfg = _make_bess_cfg(10.0)
        params = SimulationParams(
            degradation_pct_yr=2.0,
            discount_rate_pct=10.0,
            useful_life_yr=15,
        )
        dispatch = _make_dispatch(discharge_val=0.1)
        lcos = compute_lcos(cfg, dispatch, params)
        assert lcos is not None
        assert lcos > 0

        # Manual computation
        e_y1 = float(np.sum(dispatch.discharge_mwh))
        d = 0.02
        r = 0.10
        denom = sum(e_y1 * (1 - d) ** (y - 1) / (1 + r) ** y for y in range(1, 16))
        expected = cfg.capex_brl / denom
        assert abs(lcos - expected) < 1e-2

    def test_lcos_none_when_zero_discharge(self):
        from solar_bess_risk.economics import compute_lcos

        cfg = _make_bess_cfg(10.0)
        params = SimulationParams()
        dispatch = _make_dispatch(charge_curtail=0.0, discharge_val=0.0)
        lcos = compute_lcos(cfg, dispatch, params)
        assert lcos is None

    def test_lcos_no_degradation(self):
        from solar_bess_risk.economics import compute_lcos

        cfg = _make_bess_cfg(10.0)
        params = SimulationParams(degradation_pct_yr=0.0)
        dispatch = _make_dispatch(discharge_val=0.1)
        lcos = compute_lcos(cfg, dispatch, params)
        assert lcos is not None
        assert lcos > 0


class TestPayback:
    """Payback formula tests."""

    def test_payback_none_when_zero_revenue(self):
        from solar_bess_risk.economics import compute_payback

        result = compute_payback(1_000_000.0, 0.0)
        assert result is None

    def test_payback_none_when_negative_revenue(self):
        from solar_bess_risk.economics import compute_payback

        result = compute_payback(1_000_000.0, -100.0)
        assert result is None

    def test_payback_basic(self):
        from solar_bess_risk.economics import compute_payback

        result = compute_payback(1_000_000.0, 100_000.0)
        assert result is not None
        assert abs(result - 10.0) < 1e-10


class TestEffectiveCF:
    """Effective capacity factor formula."""

    def test_effective_cf(self):
        from solar_bess_risk.economics import compute_scenario_result

        dispatch = _make_dispatch(charge_curtail=0.1, discharge_val=0.08)
        cfg = _make_bess_cfg(10.0)
        prices = _make_prices(220.0)
        params = SimulationParams()

        result = compute_scenario_result(cfg, dispatch, prices, params)
        # CF = sum(grid_injection) / (1.0 * 8760) * 100
        # grid_injection = dispatch * rte ... but we verify it's a percentage
        assert 0 <= result.effective_cf_pct <= 100


class TestEquivalentCycles:
    """Equivalent cycles formula."""

    def test_equivalent_cycles(self):
        from solar_bess_risk.economics import compute_scenario_result

        dispatch = _make_dispatch(charge_curtail=0.1, discharge_val=0.08)
        cfg = _make_bess_cfg(10.0)
        prices = _make_prices(220.0)
        params = SimulationParams()

        result = compute_scenario_result(cfg, dispatch, prices, params)
        expected = float(np.sum(dispatch.discharge_mwh)) / cfg.energy_capacity_mwh
        assert abs(result.equivalent_cycles_yr - expected) < 1e-6


class TestEnergyTracking:
    """energy_from_curtail_mwh_yr and energy_from_grid_mwh_yr."""

    def test_energy_tracking(self):
        from solar_bess_risk.economics import compute_scenario_result

        dispatch = _make_dispatch(charge_curtail=0.1, charge_grid=0.05, discharge_val=0.08)
        cfg = _make_bess_cfg(10.0)
        prices = _make_prices(220.0)
        params = SimulationParams()

        result = compute_scenario_result(cfg, dispatch, prices, params)
        assert abs(result.energy_from_curtail_mwh_yr - float(np.sum(dispatch.charge_curtail_mwh))) < 1e-6
        assert abs(result.energy_from_grid_mwh_yr - float(np.sum(dispatch.charge_grid_mwh))) < 1e-6


class TestTopUpHourSlots:
    """top_up_hour_slots contains correct HH:00 strings."""

    def test_top_up_hour_slots(self):
        from solar_bess_risk.economics import compute_scenario_result

        dispatch = _make_dispatch(charge_curtail=0.1)
        dispatch = DispatchResult(
            soc_mwh=dispatch.soc_mwh,
            charge_curtail_mwh=dispatch.charge_curtail_mwh,
            charge_grid_mwh=dispatch.charge_grid_mwh,
            discharge_mwh=dispatch.discharge_mwh,
            curtailment_with_bess_mwh=dispatch.curtailment_with_bess_mwh,
            curtailment_without_bess_mwh=dispatch.curtailment_without_bess_mwh,
            top_up_hours=[2, 3, 26, 27],  # hours 2,3 (day0) and 2,3 (day1)
        )
        cfg = _make_bess_cfg(10.0)
        prices = _make_prices(220.0)
        params = SimulationParams()

        result = compute_scenario_result(cfg, dispatch, prices, params)
        assert isinstance(result.top_up_hour_slots, list)
        for s in result.top_up_hour_slots:
            assert s.endswith(":00")


class TestPaybackSensitivity:
    """Payback sensitivity sweep returns 10×10 grid."""

    def test_sensitivity_grid_shape(self):
        from solar_bess_risk.economics import compute_payback_sensitivity, compute_scenario_result

        dispatch = _make_dispatch(charge_curtail=0.1, discharge_val=0.08)
        cfg = _make_bess_cfg(10.0)
        prices = _make_prices(220.0)
        params = SimulationParams()

        result = compute_scenario_result(cfg, dispatch, prices, params)
        grid = compute_payback_sensitivity(result, prices, params)
        assert grid.shape == (10, 10)
