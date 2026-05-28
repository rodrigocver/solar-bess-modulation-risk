"""Unit tests for solar_bess_risk.economics — exposure, savings, payback (v2)."""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams


@pytest.fixture
def params() -> SimulationParams:
    return SimulationParams(
        csv_path="/tmp/test.csv",
        mwac=100.0,
        capex_usd_per_kwh=200.0,
        usd_brl_rate=5.0,
        useful_life_years=20,
    )


@pytest.fixture
def uniform_price_profile():
    from solar_bess_risk.data_sources import PriceProfile
    return PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, 500.0),
        source="bigquery_pld_SE_2025",
        bq_submarket="SE",
        bq_year=2025,
    )


@pytest.fixture
def scenario_a_with_dispatch():
    """Scenario A with a simple dispatch result."""
    from solar_bess_risk.simulation import ScenarioDefinition, DispatchResult

    gf = 50.0  # garantia fisica
    scenario = ScenarioDefinition(
        label="A",
        peak_hours=frozenset({18, 19}),
        duration_h=2,
        bess_power_mw=gf,
        bess_energy_mwh=gf * 2,
        capex_brl=gf * 2 * 200.0 * 1000 * 5.0,  # 100,000,000 BRL
    )

    # Create dispatch: BESS covers half the deficit
    deficit = np.zeros(HOURS_PER_YEAR)
    discharge = np.zeros(HOURS_PER_YEAR)
    residual = np.zeros(HOURS_PER_YEAR)
    charge = np.zeros(HOURS_PER_YEAR)
    soc = np.zeros(HOURS_PER_YEAR)
    grid_inj = np.zeros(HOURS_PER_YEAR)

    for h in range(HOURS_PER_YEAR):
        if h % 24 in {18, 19}:
            deficit[h] = gf  # Full deficit (gen=0 during peak)
            discharge[h] = gf * 0.5  # BESS covers half
            residual[h] = gf * 0.5

    dispatch = DispatchResult(
        soc_mwh=soc,
        charge_mwh=charge,
        discharge_mwh=discharge,
        grid_injection_mwh=grid_inj,
        deficit_mwh=deficit,
        residual_deficit_mwh=residual,
        curtailment_mwh=np.zeros(HOURS_PER_YEAR),
        curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
    )
    return scenario, dispatch, gf


class TestExposureFormulas:
    """Test exposure_without, exposure_with, savings formulas."""

    def test_exposure_without_uniform_price(self, uniform_price_profile, params):
        """exposure_without = garantia_fisica × count_peak_hours × P."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.simulation import ScenarioDefinition, DispatchResult
        from solar_bess_risk.profile import SolarProfile

        gf = 50.0
        mwac = 100.0
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        # Full deficit everywhere (gen=0)
        deficit = np.zeros(HOURS_PER_YEAR)
        discharge = np.zeros(HOURS_PER_YEAR)
        residual = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                deficit[h] = gf
                residual[h] = gf  # No BESS coverage
        dispatch = DispatchResult(
            soc_mwh=np.zeros(HOURS_PER_YEAR),
            charge_mwh=np.zeros(HOURS_PER_YEAR),
            discharge_mwh=discharge,
            grid_injection_mwh=np.zeros(HOURS_PER_YEAR),
            deficit_mwh=deficit,
            residual_deficit_mwh=residual,
            curtailment_mwh=np.zeros(HOURS_PER_YEAR),
            curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
        )
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(mwac*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )

        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)

        # 2 peak hours/day * 365 days = 730 peak hours
        peak_hour_count = 2 * 365
        expected_without = gf * peak_hour_count * 500.0
        assert abs(result.annual_exposure_without_bess_brl - expected_without) < 1.0

    def test_exposure_without_uses_deficit_not_gross_gf(self, uniform_price_profile, params):
        """Existing solar generation during peak hours reduces exposure without BESS."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import DispatchResult, ScenarioDefinition

        gf = 50.0
        generation = np.zeros(HOURS_PER_YEAR)
        deficit = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                generation[h] = 20.0
                deficit[h] = gf - generation[h]

        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        dispatch = DispatchResult(
            soc_mwh=np.zeros(HOURS_PER_YEAR),
            charge_mwh=np.zeros(HOURS_PER_YEAR),
            discharge_mwh=np.zeros(HOURS_PER_YEAR),
            grid_injection_mwh=generation.copy(),
            deficit_mwh=deficit,
            residual_deficit_mwh=deficit.copy(),
            curtailment_mwh=np.zeros(HOURS_PER_YEAR),
            curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
        )
        solar = SolarProfile(
            generation_mw=generation,
            annual_energy_mwh=float(generation.sum()),
            fc=0.1,
            garantia_fisica_mw=gf,
            csv_filename="t.csv",
        )

        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        expected_without = (gf - 20.0) * 2 * 365 * 500.0
        assert abs(result.annual_exposure_without_bess_brl - expected_without) < 1.0

    def test_exposure_uses_24h_deficit_by_model_decision(self, uniform_price_profile, params):
        """Exposure is intentionally computed on the 24h annual deficit, not only peak hours."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        gf = 50.0
        generation = np.full(HOURS_PER_YEAR, gf - 10.0)
        solar = SolarProfile(
            generation_mw=generation,
            annual_energy_mwh=float(generation.sum()),
            fc=0.4,
            garantia_fisica_mw=gf,
            csv_filename="t.csv",
        )
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        dispatch = simulate_scenario(solar, uniform_price_profile, scenario, params)
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)

        expected_24h = 10.0 * HOURS_PER_YEAR * 500.0
        expected_peak_only = 10.0 * 2 * 365 * 500.0
        assert abs(result.annual_exposure_without_bess_brl - expected_24h) < 1.0
        assert result.annual_exposure_without_bess_brl > expected_peak_only

    def test_exposure_with_uses_residual(self, scenario_a_with_dispatch, uniform_price_profile, params):
        """exposure_with = sum(residual_deficit * PLD) for peak hours."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile

        scenario, dispatch, gf = scenario_a_with_dispatch
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)

        # residual = gf * 0.5 for each peak hour, price = 500
        peak_hours_count = 2 * 365
        expected_with = gf * 0.5 * peak_hours_count * 500.0
        assert abs(result.annual_exposure_with_bess_brl - expected_with) < 1.0

    def test_savings_equals_diff_less_o_and_m(self, scenario_a_with_dispatch, uniform_price_profile, params):
        """net savings = exposure reduction - annual O&M."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile

        scenario, dispatch, gf = scenario_a_with_dispatch
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        expected = (
            result.net_balance_delta_brl
            - result.annual_o_and_m_brl
        )
        assert abs(result.annual_savings_brl - expected) < 1e-6


class TestPayback:
    """Payback formula tests."""

    def test_payback_formula(self, scenario_a_with_dispatch, uniform_price_profile, params):
        """payback follows degraded net annual cash flows."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile

        scenario, dispatch, gf = scenario_a_with_dispatch
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        if result.annual_savings_brl > 0:
            cumulative = 0.0
            previous = 0.0
            expected_payback = None
            for year in range(1, params.useful_life_years + 1):
                net = (
                    result.annual_gross_savings_brl
                    * ((1 - params.bess_degradation_pct_yr) ** (year - 1))
                    - result.annual_o_and_m_brl
                )
                cumulative += net
                if cumulative >= scenario.capex_brl:
                    expected_payback = (year - 1) + (scenario.capex_brl - previous) / net
                    break
                previous = cumulative
            assert expected_payback is not None
            assert abs(result.payback_years - expected_payback) < 1e-6

    def test_payback_none_when_savings_zero(self, uniform_price_profile, params):
        """payback_years is None when annual_savings <= 0."""
        from solar_bess_risk.economics import compute_scenario_economics, ScenarioResult
        from solar_bess_risk.simulation import ScenarioDefinition, DispatchResult
        from solar_bess_risk.profile import SolarProfile

        gf = 50.0
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        # Full deficit, BESS covers nothing → residual == deficit → savings = 0
        deficit = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                deficit[h] = gf
        dispatch = DispatchResult(
            soc_mwh=np.zeros(HOURS_PER_YEAR),
            charge_mwh=np.zeros(HOURS_PER_YEAR),
            discharge_mwh=np.zeros(HOURS_PER_YEAR),
            grid_injection_mwh=np.zeros(HOURS_PER_YEAR),
            deficit_mwh=deficit,
            residual_deficit_mwh=deficit.copy(),  # No BESS coverage
            curtailment_mwh=np.zeros(HOURS_PER_YEAR),
            curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
        )
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        assert result.payback_years is None

    def test_payback_display_nao_atingivel(self, uniform_price_profile, params):
        """payback_display returns 'não atingível' when None."""
        from solar_bess_risk.economics import compute_scenario_economics, payback_display
        from solar_bess_risk.simulation import ScenarioDefinition, DispatchResult
        from solar_bess_risk.profile import SolarProfile

        gf = 50.0
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        # Full deficit, no BESS coverage → savings = 0 → payback = None
        deficit = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                deficit[h] = gf
        dispatch = DispatchResult(
            soc_mwh=np.zeros(HOURS_PER_YEAR),
            charge_mwh=np.zeros(HOURS_PER_YEAR),
            discharge_mwh=np.zeros(HOURS_PER_YEAR),
            grid_injection_mwh=np.zeros(HOURS_PER_YEAR),
            deficit_mwh=deficit,
            residual_deficit_mwh=deficit.copy(),
            curtailment_mwh=np.zeros(HOURS_PER_YEAR),
            curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
        )
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        assert payback_display(result) == "não atingível"


class TestCoverage:
    """Coverage percentage tests."""

    def test_coverage_formula(self, scenario_a_with_dispatch, uniform_price_profile, params):
        """coverage = (1 - exposure_with/exposure_without) * 100."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile

        scenario, dispatch, gf = scenario_a_with_dispatch
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        expected = (1 - result.annual_exposure_with_bess_brl / result.annual_exposure_without_bess_brl) * 100
        assert abs(result.coverage_pct - expected) < 1e-6

    def test_full_coverage_100_pct(self, uniform_price_profile, params):
        """If BESS covers all deficit: coverage = 100%."""
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.simulation import ScenarioDefinition, DispatchResult
        from solar_bess_risk.profile import SolarProfile

        gf = 50.0
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        # Full deficit, fully covered by BESS
        deficit = np.zeros(HOURS_PER_YEAR)
        discharge = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                deficit[h] = gf
                discharge[h] = gf  # Full coverage
        dispatch = DispatchResult(
            soc_mwh=np.zeros(HOURS_PER_YEAR),
            charge_mwh=np.zeros(HOURS_PER_YEAR),
            discharge_mwh=discharge,
            grid_injection_mwh=np.zeros(HOURS_PER_YEAR),
            deficit_mwh=deficit,
            residual_deficit_mwh=np.zeros(HOURS_PER_YEAR),  # All covered
            curtailment_mwh=np.zeros(HOURS_PER_YEAR),
            curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
        )
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        result = compute_scenario_economics(solar, uniform_price_profile, scenario, dispatch, params)
        assert abs(result.coverage_pct - 100.0) < 1e-6


class TestNetBalance:
    """Signed net-balance metric complements contractual exposure reduction."""

    def test_net_balance_delta_captures_discharge_above_gf_value(self, params):
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.economics import compute_scenario_economics
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        gf = 50.0
        generation = np.full(HOURS_PER_YEAR, gf)
        prices_arr = np.full(HOURS_PER_YEAR, 100.0)
        for day in range(365):
            start = day * 24
            generation[start + 10] = 150.0
            prices_arr[start + 10] = 10.0
            generation[start + 20] = 0.0
            prices_arr[start + 20] = 1000.0

        solar = SolarProfile(
            generation_mw=generation,
            annual_energy_mwh=float(generation.sum()),
            fc=0.5,
            garantia_fisica_mw=gf,
            csv_filename="t.csv",
        )
        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr,
            source="test",
            bq_submarket="SE",
            bq_year=2025,
        )
        scenario = ScenarioDefinition(
            label="P3",
            peak_hours=frozenset(),
            duration_h=2,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 2,
            capex_brl=1.0,
            charge_power_mw=gf,
            rte=1.0,
            charge_mode=3,
        )

        dispatch = simulate_scenario(solar, prices, scenario, params)
        result = compute_scenario_economics(solar, prices, scenario, dispatch, params)

        assert result.annual_gross_savings_brl > 0
        assert result.net_balance_delta_brl > 0
        assert abs(result.annual_gross_savings_brl - result.net_balance_delta_brl) < 1e-6
        assert abs(result.net_balance_delta_brl - (
            result.net_balance_com_bess_brl - result.net_balance_sem_bess_brl
        )) < 1e-6
        assert result.payback_years is not None


class TestCapexFormula:
    """CAPEX BRL formula tests."""

    def test_capex_formula(self):
        """capex_brl = bess_energy_mwh * capex_usd_per_kwh * 1000 * usd_brl_rate."""
        from solar_bess_risk.simulation import ScenarioDefinition

        gf = 50.0
        duration = 2
        capex_usd = 200.0
        rate = 5.0
        expected = gf * duration * capex_usd * 1000 * rate
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=duration,
            bess_power_mw=gf, bess_energy_mwh=gf * duration,
            capex_brl=expected,
        )
        assert abs(scenario.capex_brl - expected) < 1e-6


class TestComputeAllScenarios:
    """Test compute_all_scenarios function."""

    def test_returns_list_of_scenario_results(self, uniform_price_profile, params):
        from solar_bess_risk.economics import compute_all_scenarios
        from solar_bess_risk.simulation import ScenarioDefinition, DispatchResult
        from solar_bess_risk.profile import SolarProfile

        gf = 50.0
        solar = SolarProfile(
            generation_mw=np.zeros(HOURS_PER_YEAR),
            annual_energy_mwh=0.1, fc=0.1/(100*HOURS_PER_YEAR),
            garantia_fisica_mw=gf, csv_filename="t.csv",
        )
        scenarios_dispatches = []
        for label, ph, dur in [("A", {18,19}, 2), ("B", {17,18,19}, 3), ("C", {17,18,19,20}, 4)]:
            s = ScenarioDefinition(label, frozenset(ph), dur, gf, gf*dur, gf*dur*1_000_000)
            deficit = np.zeros(HOURS_PER_YEAR)
            for h in range(HOURS_PER_YEAR):
                if h % 24 in ph:
                    deficit[h] = gf
            d = DispatchResult(
                soc_mwh=np.zeros(HOURS_PER_YEAR),
                charge_mwh=np.zeros(HOURS_PER_YEAR),
                discharge_mwh=np.zeros(HOURS_PER_YEAR),
                grid_injection_mwh=np.zeros(HOURS_PER_YEAR),
                deficit_mwh=deficit,
                residual_deficit_mwh=deficit.copy(),
            curtailment_mwh=np.zeros(HOURS_PER_YEAR),
            curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
            )
            scenarios_dispatches.append((s, d))

        results = compute_all_scenarios(solar, uniform_price_profile, scenarios_dispatches, params)
        assert len(results) == 3
