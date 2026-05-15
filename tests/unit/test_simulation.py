"""Unit tests for solar_bess_risk.simulation module.

Tests written FIRST (TDD) — must FAIL until simulation.py is implemented.
"""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.profile import SolarProfile


def _make_solar_profile(cf: float = 0.3) -> SolarProfile:
    """Create a simple synthetic-like solar profile for testing."""
    gen = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    # Simulate daylight hours (6–18) with capacity factor `cf`
    for d in range(365):
        for h in range(6, 18):
            gen[d * 24 + h] = cf
    return SolarProfile(
        generation_mw=gen,
        source="synthetic",
        source_path=None,
        annual_energy_mwh=float(np.sum(gen)),
    )


def _make_price_profile(price: float = 220.0):
    """Create a uniform price profile for testing."""
    from solar_bess_risk.data_sources import PriceProfile

    return PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, price, dtype=np.float64),
        source="bigquery_pld",
        bq_submarket="SE",
        bq_year=2025,
    )


class TestSoCBounds:
    """SoC never < 0 or > energy_cap_mwh across 8760 hours."""

    def test_soc_within_bounds(self):
        from solar_bess_risk.simulation import BESSConfig, simulate_scenario

        params = SimulationParams(ilr_values=[1.3])
        solar = _make_solar_profile(0.9)  # high CF → curtailment at ILR 1.3
        prices = _make_price_profile()

        # Compute annual energy without BESS for ILR 1.3
        annual_no_bess = float(np.sum(np.minimum(solar.generation_mw * 1.3, 1.0)))
        energy_cap = 0.25 * annual_no_bess  # 25% BESS
        rated_power = energy_cap / 2.0

        cfg = BESSConfig(
            energy_capacity_mwh=energy_cap,
            rated_power_mw=rated_power,
            capex_brl=energy_cap * 1000 * 250 * 5,
            duration_h=2.0,
            ilr=1.3,
            bess_size_ratio_pct=25.0,
        )
        result = simulate_scenario(cfg, solar, prices, params)
        assert np.all(result.soc_mwh >= -1e-10)
        assert np.all(result.soc_mwh <= energy_cap + 1e-10)


class TestPowerLimits:
    """Power flow per hour ≤ rated_power_mw."""

    def test_charge_within_rated_power(self):
        from solar_bess_risk.simulation import BESSConfig, simulate_scenario

        params = SimulationParams(ilr_values=[1.3])
        solar = _make_solar_profile(0.9)
        prices = _make_price_profile()

        annual_no_bess = float(np.sum(np.minimum(solar.generation_mw * 1.3, 1.0)))
        energy_cap = 0.25 * annual_no_bess
        rated_power = energy_cap / 2.0

        cfg = BESSConfig(
            energy_capacity_mwh=energy_cap,
            rated_power_mw=rated_power,
            capex_brl=energy_cap * 1000 * 250 * 5,
            duration_h=2.0,
            ilr=1.3,
            bess_size_ratio_pct=25.0,
        )
        result = simulate_scenario(cfg, solar, prices, params)
        total_charge = result.charge_curtail_mwh + result.charge_grid_mwh
        assert np.all(total_charge <= rated_power + 1e-10)
        assert np.all(result.discharge_mwh <= rated_power + 1e-10)


class TestNoSimultaneousChargeDischarge:
    """Charge and discharge never non-zero in the same hour."""

    def test_no_simultaneous(self):
        from solar_bess_risk.simulation import BESSConfig, simulate_scenario

        params = SimulationParams(ilr_values=[1.3])
        solar = _make_solar_profile(0.9)
        prices = _make_price_profile()

        annual_no_bess = float(np.sum(np.minimum(solar.generation_mw * 1.3, 1.0)))
        energy_cap = 0.25 * annual_no_bess
        rated_power = energy_cap / 2.0

        cfg = BESSConfig(
            energy_capacity_mwh=energy_cap,
            rated_power_mw=rated_power,
            capex_brl=energy_cap * 1000 * 250 * 5,
            duration_h=2.0,
            ilr=1.3,
            bess_size_ratio_pct=25.0,
        )
        result = simulate_scenario(cfg, solar, prices, params)
        total_charge = result.charge_curtail_mwh + result.charge_grid_mwh
        simultaneous = (total_charge > 1e-10) & (result.discharge_mwh > 1e-10)
        assert not np.any(simultaneous)


class TestBESSZeroPercent:
    """BESS=0% produces sum(charge_curtail_mwh) == 0."""

    def test_zero_bess(self):
        from solar_bess_risk.simulation import BESSConfig, simulate_scenario

        params = SimulationParams()
        solar = _make_solar_profile(0.9)
        prices = _make_price_profile()

        cfg = BESSConfig(
            energy_capacity_mwh=0.0,
            rated_power_mw=0.0,
            capex_brl=0.0,
            duration_h=2.0,
            ilr=1.3,
            bess_size_ratio_pct=0.0,
        )
        result = simulate_scenario(cfg, solar, prices, params)
        assert np.sum(result.charge_curtail_mwh) == 0.0


class TestMonotonicity:
    """Avoided curtailment monotonically non-decreasing across BESS sizes for fixed ILR."""

    def test_monotonic_avoided_curtailment(self):
        from solar_bess_risk.simulation import BESSConfig, simulate_scenario

        params = SimulationParams()
        solar = _make_solar_profile(0.9)
        prices = _make_price_profile()
        ilr = 1.3
        annual_no_bess = float(np.sum(np.minimum(solar.generation_mw * ilr, 1.0)))

        avoided_values = []
        for pct in [0, 10, 25, 50, 100]:
            energy_cap = (pct / 100.0) * annual_no_bess
            rated_power = energy_cap / 2.0 if energy_cap > 0 else 0.0
            cfg = BESSConfig(
                energy_capacity_mwh=energy_cap,
                rated_power_mw=rated_power,
                capex_brl=energy_cap * 1000 * 250 * 5,
                duration_h=2.0,
                ilr=ilr,
                bess_size_ratio_pct=float(pct),
            )
            result = simulate_scenario(cfg, solar, prices, params)
            curtail_without = float(np.sum(result.curtailment_without_bess_mwh))
            curtail_with = float(np.sum(result.curtailment_with_bess_mwh))
            avoided = curtail_without - curtail_with
            avoided_values.append(avoided)

        for i in range(1, len(avoided_values)):
            assert avoided_values[i] >= avoided_values[i - 1] - 1e-10


class TestAnnualSolarEnergyNoBess:
    """annual_solar_energy_no_bess_mwh computed correctly from clipped profile."""

    def test_compute_annual_solar_energy_no_bess(self):
        from solar_bess_risk.simulation import compute_annual_solar_energy_no_bess

        solar = _make_solar_profile(0.9)
        # ILR 1.3: clip at 1.0 MWac
        expected = float(np.sum(np.minimum(solar.generation_mw * 1.3, 1.0)))
        result = compute_annual_solar_energy_no_bess(solar, 1.3)
        assert abs(result - expected) < 1e-10


class TestTopUpHours:
    """top_up_hours is a list of int hour-indices when grid top-up occurred."""

    def test_top_up_hours_type(self):
        from solar_bess_risk.simulation import BESSConfig, simulate_scenario

        params = SimulationParams(ilr_values=[1.3], min_soc_threshold_pct=80.0)
        solar = _make_solar_profile(0.9)
        prices = _make_price_profile()

        annual_no_bess = float(np.sum(np.minimum(solar.generation_mw * 1.3, 1.0)))
        energy_cap = 0.25 * annual_no_bess
        rated_power = energy_cap / 2.0

        cfg = BESSConfig(
            energy_capacity_mwh=energy_cap,
            rated_power_mw=rated_power,
            capex_brl=energy_cap * 1000 * 250 * 5,
            duration_h=2.0,
            ilr=1.3,
            bess_size_ratio_pct=25.0,
        )
        result = simulate_scenario(cfg, solar, prices, params)
        assert isinstance(result.top_up_hours, list)
        for h in result.top_up_hours:
            assert isinstance(h, int)
            assert 0 <= h < HOURS_PER_YEAR
