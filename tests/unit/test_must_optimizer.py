"""US1 tests — MUST reduction optimizer.

TDD (constitution Principle III): written before ``must_optimizer`` exists
and before the ``must_mw`` cap wiring; they MUST fail until implemented.
"""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import (
    HOURS_PER_YEAR,
    KW_PER_MW,
    MONTHS_PER_YEAR,
    SimulationParams,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition


def _solar_midday_peak(mwac: float = 100.0) -> SolarProfile:
    gen = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    for day in range(365):
        gen[day * 24 + 12] = 80.0
    annual = float(gen.sum())
    return SolarProfile(
        generation_mw=gen,
        annual_energy_mwh=annual,
        fc=annual / (mwac * HOURS_PER_YEAR),
        garantia_fisica_mw=5.0,
        csv_filename="midday.csv",
        generation_lim_mw=gen,
        generation_bess_mw=gen,
        generation_years_lim_mw=gen.reshape(1, HOURS_PER_YEAR),
        generation_years_bess_mw=gen.reshape(1, HOURS_PER_YEAR),
        n_years=1,
    )


def _scenario() -> ScenarioDefinition:
    return ScenarioDefinition(
        label="A",
        peak_hours=frozenset({19}),
        duration_h=4,
        bess_power_mw=20.0,
        charge_power_mw=20.0,
        bess_energy_mwh=40.0,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )


def _prices() -> PriceProfile:
    arr = np.full(HOURS_PER_YEAR, 10.0)
    arr[19::24] = 500.0
    return PriceProfile(arr, "synthetic", "SE", 2025)


# --- T004: parameter validation -------------------------------------------


def test_params_reject_out_of_bounds_tust():
    with pytest.raises(ValueError):
        SimulationParams(csv_path="x.csv", mwac=100.0, tust_brl_per_kw_month=-1.0)


def test_params_apply_documented_defaults():
    p = SimulationParams(csv_path="x.csv", mwac=100.0)
    assert p.tust_brl_per_kw_month == pytest.approx(7.23)
    assert 0.0 < p.must_sweep_step_pct <= p.must_sweep_max_pct <= 1.0


# --- T007: TUST savings formula -------------------------------------------


def test_tust_annual_savings_reference_case():
    from solar_bess_risk.must_optimizer import tust_annual_savings_brl

    result = tust_annual_savings_brl(tust_brl_per_kw_month=7.23, delta_must_mw=60.0)
    expected = 7.23 * MONTHS_PER_YEAR * 60.0 * KW_PER_MW
    assert result == pytest.approx(expected)


def test_tust_annual_savings_zero_when_no_reduction():
    from solar_bess_risk.must_optimizer import tust_annual_savings_brl

    assert tust_annual_savings_brl(tust_brl_per_kw_month=7.23, delta_must_mw=0.0) == 0.0


# --- T008: optimal selection ----------------------------------------------


def test_optimize_returns_single_optimum_matching_argmax():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    params = SimulationParams(csv_path="midday.csv", mwac=100.0)
    res = optimize_must_reduction(
        _solar_midday_peak(), _prices(), _scenario(), params
    )

    # Baseline point (no reduction) exists with zero net-balance delta
    base = next(p for p in res.sweep if p.reduction_pct == 0.0)
    assert base.delta_must_mw == 0.0
    assert base.net_balance_delta_vs_baseline_brl == pytest.approx(0.0)

    best = max(res.sweep, key=lambda p: p.net_benefit_brl_per_yr)
    assert res.optimal_net_benefit_brl_per_yr == pytest.approx(
        best.net_benefit_brl_per_yr
    )
    assert res.optimal_reduction_pct == pytest.approx(best.reduction_pct)
    assert res.optimal_must_mw == pytest.approx(100.0 * (1.0 - best.reduction_pct))


def test_optimize_high_tust_drives_reduction_up():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    params = SimulationParams(
        csv_path="midday.csv", mwac=100.0, tust_brl_per_kw_month=900.0
    )
    res = optimize_must_reduction(
        _solar_midday_peak(), _prices(), _scenario(), params
    )
    assert res.optimal_reduction_pct > 0.0


# --- T009: low-TUST edge --------------------------------------------------


def test_optimize_zero_tust_keeps_full_must():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    params = SimulationParams(
        csv_path="midday.csv", mwac=100.0, tust_brl_per_kw_month=0.0
    )
    res = optimize_must_reduction(
        _solar_midday_peak(), _prices(), _scenario(), params
    )
    # With no TUST benefit, any reduction can only lose net-balance value
    assert res.optimal_reduction_pct == pytest.approx(0.0)
    assert res.optimal_net_benefit_brl_per_yr == pytest.approx(0.0)


# --- T015: sensitivity sweep ----------------------------------------------


def _scenario_sized(label: str, power_mw: float, energy_mwh: float) -> ScenarioDefinition:
    return ScenarioDefinition(
        label=label,
        peak_hours=frozenset({19}),
        duration_h=int(energy_mwh / power_mw),
        bess_power_mw=power_mw,
        charge_power_mw=power_mw,
        bess_energy_mwh=energy_mwh,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )


def test_sweep_covers_grid_with_correct_step():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    params = SimulationParams(
        csv_path="midday.csv",
        mwac=100.0,
        must_sweep_max_pct=0.20,
        must_sweep_step_pct=0.05,
    )
    res = optimize_must_reduction(
        _solar_midday_peak(), _prices(), _scenario(), params
    )

    fractions = [p.reduction_pct for p in res.sweep]
    assert fractions == pytest.approx([0.0, 0.05, 0.10, 0.15, 0.20])
    # Steps are uniform at must_sweep_step_pct
    steps = np.diff(fractions)
    np.testing.assert_allclose(steps, 0.05)
    # Reported optimum coincides with the sweep maximum
    best = max(res.sweep, key=lambda p: p.net_benefit_brl_per_yr)
    assert res.optimal_reduction_pct == pytest.approx(best.reduction_pct)
    assert res.optimal_net_benefit_brl_per_yr == pytest.approx(
        best.net_benefit_brl_per_yr
    )


# --- T016: synergy monotonicity -------------------------------------------


def test_larger_bess_allows_equal_or_greater_reduction():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    solar, prices = _solar_midday_peak(), _prices()
    # Moderate TUST so the optimum is interior and sensitive to BESS sizing.
    params = SimulationParams(
        csv_path="midday.csv", mwac=100.0, tust_brl_per_kw_month=50.0
    )

    small = optimize_must_reduction(
        solar, prices, _scenario_sized("S", 10.0, 20.0), params
    )
    large = optimize_must_reduction(
        solar, prices, _scenario_sized("L", 40.0, 160.0), params
    )

    assert large.optimal_reduction_pct >= small.optimal_reduction_pct


# --- T018: TUST default flag ----------------------------------------------


def test_tust_default_flag_set_when_default_applied():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    params = SimulationParams(csv_path="midday.csv", mwac=100.0)
    res = optimize_must_reduction(
        _solar_midday_peak(), _prices(), _scenario(), params
    )
    assert res.tust_is_default is True
    assert res.tust_brl_per_kw_month == pytest.approx(7.23)


def test_tust_default_flag_cleared_when_value_provided():
    from solar_bess_risk.must_optimizer import optimize_must_reduction

    params = SimulationParams(
        csv_path="midday.csv", mwac=100.0, tust_brl_per_kw_month=12.5
    )
    res = optimize_must_reduction(
        _solar_midday_peak(), _prices(), _scenario(), params
    )
    assert res.tust_is_default is False
    assert res.tust_brl_per_kw_month == pytest.approx(12.5)
    # The provided TUST propagates into the savings of every swept point
    nonzero = next(p for p in res.sweep if p.reduction_pct > 0.0)
    expected = 12.5 * MONTHS_PER_YEAR * nonzero.delta_must_mw * KW_PER_MW
    assert nonzero.tust_savings_brl_per_yr == pytest.approx(expected)


