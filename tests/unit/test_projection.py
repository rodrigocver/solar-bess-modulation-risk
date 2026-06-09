"""Unit tests for year-by-year RTE cashflow projection."""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.projection import project_cashflows_with_rte, rte_for_year, soh_for_year
from solar_bess_risk.rte import load_rte_table, load_soh_table
from solar_bess_risk.simulation import ScenarioDefinition


def test_rte_for_year_clamps_to_supplier_curve_edges():
    table = {2025: 0.90, 2026: 0.85}

    assert rte_for_year(table, 2024, 0.80) == 0.90
    assert rte_for_year(table, 2025, 0.80) == 0.90
    assert rte_for_year(table, 2027, 0.80) == 0.85


def test_soh_for_year_clamps_to_supplier_curve_edges():
    table = {2025: 1.0, 2026: 0.95}

    assert soh_for_year(table, 2024) == 1.0
    assert soh_for_year(table, 2025) == 1.0
    assert soh_for_year(table, 2027) == 0.95


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
        rte_table={2026: 1.0, 2027: 0.50},
        soh_table={2025: 1.0, 2026: 1.0},
        start_year=2025,
    )

    assert projection.annual_rte[:2] == (1.0, 0.50)
    assert projection.annual_discharge_mwh[1] < projection.annual_discharge_mwh[0]
    assert projection.annual_net_savings_brl[1] < projection.annual_net_savings_brl[0]
    assert projection.projected_calendar_years == 30.0
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
        soh_table={2026: 1.0, 2027: 0.5},
        start_year=2025,
    )

    assert projection.projected_calendar_years == 30.0
    assert projection.target_equivalent_cycles == 30 * 365.0
    assert projection.annual_soh[:2] == pytest.approx((1.0, 0.5))
    assert projection.annual_bess_energy_mwh[:2] == pytest.approx((50.0, 25.0))


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
    assert projection.projected_calendar_years == 30.0
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
        soh_table={2025: 1.0},
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
        soh_table={2025: 1.0},
        start_year=2025,
    )

    assert projection_zero.lcos_brl_per_mwh is not None
    assert projection_discounted.lcos_brl_per_mwh is not None
    assert projection_discounted.lcoe_discount_rate == 0.05
    assert projection_discounted.lcos_brl_per_mwh > projection_zero.lcos_brl_per_mwh


def test_projection_adds_tust_savings_to_must_reduction_cashflow():
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
        soh_table={2025: 1.0},
        start_year=2025,
        tust_savings_brl_per_yr=123_456.0,
    )

    assert projection.annual_gross_savings_brl[0] == pytest.approx(123_456.0)
    assert projection.annual_net_savings_brl[0] == pytest.approx(123_456.0)


def test_tust_savings_changes_must_reduction_payback_and_lifetime_value():
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
        label="MUST",
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
        bess_o_and_m_pct_capex=0.0,
    )
    common_kwargs = dict(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=params,
        curtailment_series=None,
        rte_table={2025: 1.0},
        soh_table={2025: 1.0},
        start_year=2025,
        must_mw=50.0,
    )

    without_tust = project_cashflows_with_rte(**common_kwargs)
    with_tust = project_cashflows_with_rte(
        **common_kwargs,
        tust_savings_brl_per_yr=250_000.0,
    )

    assert without_tust.payback_years is None
    assert with_tust.payback_years == pytest.approx(4.0)
    assert with_tust.lifetime_net_savings_brl - without_tust.lifetime_net_savings_brl == pytest.approx(
        30 * 250_000.0
    )


def test_projection_uses_full_envision_soh_and_rte_curves_for_30_calendar_years():
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
        label="ENV",
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
        bess_o_and_m_pct_capex=0.0,
    )
    rte_table = load_rte_table("dados/11 - Envision.xlsx")
    soh_table = load_soh_table("dados/11 - Envision.xlsx")

    projection = project_cashflows_with_rte(
        solar=solar,
        pld=prices,
        price_source="synthetic",
        bq_submarket="SE",
        scenario=scenario,
        params=params,
        curtailment_series=None,
        rte_table=rte_table,
        soh_table=soh_table,
        start_year=2025,
    )

    expected_years = tuple(range(2026, 2056))

    assert projection.projected_calendar_years == 30.0
    assert len(projection.annual_soh) == 30
    assert projection.annual_rte == pytest.approx(tuple(rte_for_year(rte_table, y, 1.0) for y in expected_years))
    assert projection.annual_soh == pytest.approx(tuple(soh_for_year(soh_table, y) for y in expected_years))
    assert all(
        later <= earlier + 1e-12
        for earlier, later in zip(projection.annual_soh, projection.annual_soh[1:])
    )
    assert projection.annual_bess_energy_mwh == pytest.approx(
        tuple(scenario.bess_energy_mwh * soh_for_year(soh_table, y) for y in expected_years)
    )
