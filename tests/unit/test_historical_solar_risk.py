"""Tests for dual solar series and historical risk metrics."""

from __future__ import annotations

import numpy as np

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.risk_metrics import compute_historical_risk_metrics
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario


def _dual_solar(n_years: int = 2) -> SolarProfile:
    gen_lim = np.zeros((n_years, HOURS_PER_YEAR))
    gen_bess = np.zeros((n_years, HOURS_PER_YEAR))
    for year in range(n_years):
        for day in range(365):
            gen_lim[year, day * 24 + 10] = 10.0 + year
            gen_bess[year, day * 24 + 10] = 20.0 + year
            gen_lim[year, day * 24 + 20] = 0.0
            gen_bess[year, day * 24 + 20] = 0.0
    annual = float(gen_lim.sum(axis=1).mean())
    return SolarProfile(
        generation_mw=gen_lim[0],
        annual_energy_mwh=annual,
        fc=annual / (100.0 * HOURS_PER_YEAR),
        garantia_fisica_mw=5.0,
        csv_filename="dual.csv",
        generation_lim_mw=gen_lim[0],
        generation_bess_mw=gen_bess[0],
        generation_years_lim_mw=gen_lim,
        generation_years_bess_mw=gen_bess,
        n_years=n_years,
    )


def test_clipping_is_available_curtailment_without_ons_curtailment():
    solar = _dual_solar()
    prices = np.full(HOURS_PER_YEAR, 10.0)
    prices[20::24] = 1_000.0
    scenario = ScenarioDefinition(
        label="A",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=5.0,
        charge_power_mw=5.0,
        bess_energy_mwh=5.0,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )
    dispatch = simulate_scenario(
        solar,
        PriceProfile(prices, "synthetic", "SE", 2025),
        scenario,
        SimulationParams(csv_path="dual.csv", mwac=100.0),
        curtailment_series=None,
    )

    assert dispatch.clipping_available_mwh[10] == 10.0
    assert dispatch.ons_curtailment_mwh[10] == 0.0
    assert dispatch.curtailment_mwh[10] == 10.0
    assert dispatch.charge_mwh[10] > 0.0


def test_historical_risk_uses_all_solar_years():
    solar = _dual_solar(n_years=3)
    prices = np.full(HOURS_PER_YEAR, 10.0)
    prices[20::24] = 1_000.0
    scenario = ScenarioDefinition(
        label="A",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=5.0,
        charge_power_mw=5.0,
        bess_energy_mwh=5.0,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )

    risk = compute_historical_risk_metrics(
        solar=solar,
        prices=PriceProfile(prices, "synthetic", "SE", 2025),
        scenario=scenario,
        params=SimulationParams(csv_path="dual.csv", mwac=100.0),
        curtailment_series=None,
    )

    assert risk["n_solar_years"] == 3
    assert risk["n_days"] == 3 * 365
    assert len(risk["daily_net_sem_brl"]) == 3 * 365
    assert risk["cvar_95_com_bess_brl"] >= risk["cvar_95_sem_bess_brl"]


def test_historical_risk_can_limit_solar_years_for_smoke_tests():
    solar = _dual_solar(n_years=3)
    prices = np.full(HOURS_PER_YEAR, 10.0)
    scenario = ScenarioDefinition(
        label="A",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=5.0,
        charge_power_mw=5.0,
        bess_energy_mwh=5.0,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )

    risk = compute_historical_risk_metrics(
        solar=solar,
        prices=PriceProfile(prices, "synthetic", "SE", 2025),
        scenario=scenario,
        params=SimulationParams(csv_path="dual.csv", mwac=100.0),
        curtailment_series=None,
        max_solar_years=2,
    )

    assert risk["n_solar_years"] == 2
    assert risk["n_days"] == 2 * 365
