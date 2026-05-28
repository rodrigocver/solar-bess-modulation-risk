"""Unit tests for year-by-year RTE cashflow projection."""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.projection import project_cashflows_with_rte, rte_for_year
from solar_bess_risk.simulation import ScenarioDefinition


def test_rte_for_year_clamps_to_supplier_curve_edges():
    table = {2025: 0.90, 2026: 0.85}

    assert rte_for_year(table, 2024, 0.80) == 0.90
    assert rte_for_year(table, 2025, 0.80) == 0.90
    assert rte_for_year(table, 2027, 0.80) == 0.85


def test_projection_uses_lower_future_rte_for_payback_and_lcos():
    generation = np.zeros(HOURS_PER_YEAR)
    prices = np.full(HOURS_PER_YEAR, 10.0)
    for day in range(365):
        generation[day * 24 + 10] = 100.0
        prices[day * 24 + 20] = 1_000.0

    solar = SolarProfile(
        generation_mw=generation,
        annual_energy_mwh=float(generation.sum()),
        fc=0.1,
        garantia_fisica_mw=50.0,
        csv_filename="synthetic.csv",
    )
    scenario = ScenarioDefinition(
        label="B",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=50.0,
        charge_power_mw=50.0,
        bess_energy_mwh=50.0,
        capex_brl=1_000_000.0,
        rte=1.0,
        charge_mode=3,
    )
    params = SimulationParams(
        csv_path="synthetic.csv",
        mwac=100.0,
        useful_life_years=2,
        bess_o_and_m_pct_capex=0.0,
    )

    projection = project_cashflows_with_rte(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=params,
        curtailment_series=None,
        rte_table={2025: 1.0, 2026: 0.50},
        start_year=2025,
    )

    assert projection.annual_rte[:2] == (1.0, 0.50)
    assert projection.annual_discharge_mwh[1] < projection.annual_discharge_mwh[0]
    assert projection.annual_net_savings_brl[1] < projection.annual_net_savings_brl[0]
    assert projection.projected_calendar_years > params.useful_life_years
    assert projection.lcos_brl_per_mwh is not None


def test_projection_extends_calendar_years_until_cycle_life_is_reached():
    generation = np.zeros(HOURS_PER_YEAR)
    prices = np.full(HOURS_PER_YEAR, 10.0)
    for day in range(365):
        generation[day * 24 + 10] = 100.0
        prices[day * 24 + 20] = 1_000.0

    solar = SolarProfile(
        generation_mw=generation,
        annual_energy_mwh=float(generation.sum()),
        fc=0.1,
        garantia_fisica_mw=50.0,
        csv_filename="synthetic.csv",
    )
    scenario = ScenarioDefinition(
        label="B",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=25.0,
        charge_power_mw=25.0,
        bess_energy_mwh=50.0,
        capex_brl=1_000_000.0,
        rte=1.0,
        charge_mode=3,
    )
    params = SimulationParams(
        csv_path="synthetic.csv",
        mwac=100.0,
        useful_life_years=2,
        bess_o_and_m_pct_capex=0.0,
    )

    projection = project_cashflows_with_rte(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=params,
        curtailment_series=None,
        rte_table={2025: 1.0},
        start_year=2025,
    )

    assert projection.cycle_life_reached is True
    assert projection.projected_calendar_years > params.useful_life_years
    assert projection.target_equivalent_cycles == 730.0
    assert projection.lifetime_discharge_mwh == pytest.approx(scenario.bess_energy_mwh * 730.0)
    assert projection.annual_discharge_mwh[-1] < projection.annual_discharge_mwh[0]


def test_projection_stops_at_calendar_safety_limit_when_cycle_life_is_not_reached():
    generation = np.zeros(HOURS_PER_YEAR)
    prices = np.full(HOURS_PER_YEAR, 100.0)
    solar = SolarProfile(
        generation_mw=generation,
        annual_energy_mwh=1.0,
        fc=0.1,
        garantia_fisica_mw=50.0,
        csv_filename="synthetic.csv",
    )
    scenario = ScenarioDefinition(
        label="B",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=50.0,
        charge_power_mw=50.0,
        bess_energy_mwh=50.0,
        capex_brl=1_000_000.0,
        rte=1.0,
        charge_mode=3,
    )
    params = SimulationParams(
        csv_path="synthetic.csv",
        mwac=100.0,
        useful_life_years=2,
        bess_o_and_m_pct_capex=0.0,
    )

    projection = project_cashflows_with_rte(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=params,
        curtailment_series=None,
        rte_table={2025: 1.0},
        start_year=2025,
    )

    assert projection.cycle_life_reached is False
    assert projection.projected_calendar_years == 8.0
    assert projection.lifetime_discharge_mwh == 0.0
    assert projection.lcos_brl_per_mwh is None


def test_lcos_uses_configured_discount_rate():
    generation = np.zeros(HOURS_PER_YEAR)
    prices = np.full(HOURS_PER_YEAR, 10.0)
    for day in range(365):
        generation[day * 24 + 10] = 100.0
        prices[day * 24 + 20] = 1_000.0

    solar = SolarProfile(
        generation_mw=generation,
        annual_energy_mwh=float(generation.sum()),
        fc=0.1,
        garantia_fisica_mw=50.0,
        csv_filename="synthetic.csv",
    )
    scenario = ScenarioDefinition(
        label="B",
        peak_hours=frozenset({20}),
        duration_h=1,
        bess_power_mw=50.0,
        charge_power_mw=50.0,
        bess_energy_mwh=50.0,
        capex_brl=1_000_000.0,
        rte=1.0,
        charge_mode=3,
    )
    base_params = SimulationParams(
        csv_path="synthetic.csv",
        mwac=100.0,
        useful_life_years=2,
        bess_o_and_m_pct_capex=0.0,
        lcoe_discount_rate=0.0,
    )
    discounted_params = SimulationParams(
        csv_path="synthetic.csv",
        mwac=100.0,
        useful_life_years=2,
        bess_o_and_m_pct_capex=0.0,
        lcoe_discount_rate=0.05,
    )

    projection_zero = project_cashflows_with_rte(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=base_params,
        curtailment_series=None,
        rte_table={2025: 1.0},
        start_year=2025,
    )
    projection_discounted = project_cashflows_with_rte(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=discounted_params,
        curtailment_series=None,
        rte_table={2025: 1.0},
        start_year=2025,
    )

    assert projection_zero.lcos_brl_per_mwh is not None
    assert projection_discounted.lcos_brl_per_mwh is not None
    assert projection_discounted.lcoe_discount_rate == 0.05
    assert projection_discounted.lcos_brl_per_mwh > projection_zero.lcos_brl_per_mwh
