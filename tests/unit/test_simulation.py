"""Unit tests for solar_bess_risk.simulation — dispatch engine (v2)."""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams


@pytest.fixture
def params() -> SimulationParams:
    return SimulationParams(csv_path="/tmp/test.csv", mwac=100.0)


@pytest.fixture
def solar_profile():
    """A profile with generation that varies: 80 MW day, 0 night."""
    from solar_bess_risk.profile import SolarProfile
    gen = np.zeros(HOURS_PER_YEAR)
    for h in range(HOURS_PER_YEAR):
        hour_of_day = h % 24
        if 6 <= hour_of_day <= 17:
            gen[h] = 80.0  # Above garantia fisica during day
        else:
            gen[h] = 0.0
    annual = float(np.sum(gen))
    mwac = 100.0
    fc = annual / (mwac * HOURS_PER_YEAR)
    gf = mwac * fc
    return SolarProfile(
        generation_mw=gen,
        annual_energy_mwh=annual,
        fc=fc,
        garantia_fisica_mw=gf,
        csv_filename="test.csv",
    )


@pytest.fixture
def price_profile():
    """Uniform price profile for testing."""
    from solar_bess_risk.data_sources import PriceProfile
    return PriceProfile(
        prices_brl_per_mwh=np.full(HOURS_PER_YEAR, 500.0),
        source="bigquery_pld_SE_2025",
        bq_submarket="SE",
        bq_year=2025,
    )


@pytest.fixture
def scenario_a(solar_profile):
    """Scenario A: peak hours {18,19}, duration 2h."""
    from solar_bess_risk.simulation import ScenarioDefinition
    gf = solar_profile.garantia_fisica_mw
    return ScenarioDefinition(
        label="A",
        peak_hours=frozenset({18, 19}),
        duration_h=2,
        bess_power_mw=gf,
        bess_energy_mwh=gf * 2,
        capex_brl=gf * 2 * 200.0 * 1000 * 5.0,
    )


@pytest.fixture
def scenario_c(solar_profile):
    """Scenario C: peak hours {17,18,19,20}, duration 4h."""
    from solar_bess_risk.simulation import ScenarioDefinition
    gf = solar_profile.garantia_fisica_mw
    return ScenarioDefinition(
        label="C",
        peak_hours=frozenset({17, 18, 19, 20}),
        duration_h=4,
        bess_power_mw=gf,
        bess_energy_mwh=gf * 4,
        capex_brl=gf * 4 * 200.0 * 1000 * 5.0,
    )


class TestSimulateScenario:
    """Core dispatch invariants."""

    def test_soc_never_below_zero(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        assert np.all(result.soc_mwh >= -1e-10)

    def test_soc_never_above_capacity(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        assert np.all(result.soc_mwh <= scenario_a.bess_energy_mwh + 1e-10)

    def test_no_simultaneous_charge_discharge(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        # charge and discharge never both > 0 in same hour
        simultaneous = (result.charge_mwh > 1e-10) & (result.discharge_mwh > 1e-10)
        assert not np.any(simultaneous)

    def test_one_hour_gap_between_charge_and_discharge(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)

        charged = result.charge_mwh > 1e-10
        discharged = result.discharge_mwh > 1e-10
        assert not np.any(charged[:-1] & discharged[1:])
        assert not np.any(discharged[:-1] & charged[1:])

    def test_charge_only_when_excess_and_not_peak(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        gf = solar_profile.garantia_fisica_mw
        for h in range(HOURS_PER_YEAR):
            if result.charge_mwh[h] > 1e-10:
                assert solar_profile.generation_mw[h] > gf - 1e-10
                assert h % 24 not in scenario_a.peak_hours

    def test_discharge_only_when_no_curtailment(self, solar_profile, price_profile, scenario_a, params):
        """Discharge can use an expanded drain window, but never during curtailment."""
        from solar_bess_risk.simulation import simulate_scenario
        curtailment = np.zeros(HOURS_PER_YEAR)
        curtailment[13:18] = scenario_a.bess_power_mw
        result = simulate_scenario(
            solar_profile, price_profile, scenario_a, params, curtailment_series=curtailment
        )
        for h in range(HOURS_PER_YEAR):
            if result.discharge_mwh[h] > 1e-10:
                assert curtailment[h] <= 1e-10
                assert result.discharge_mwh[h] <= scenario_a.bess_power_mw + 1e-10

    def test_deficit_formula(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        gf = solar_profile.garantia_fisica_mw
        for h in range(HOURS_PER_YEAR):
            # Deficit = max(0, GF - (gen - curtailment)); no curtailment in this profile
            expected_deficit = max(0.0, gf - solar_profile.generation_mw[h])
            assert abs(result.deficit_mwh[h] - expected_deficit) < 1e-10

    def test_residual_deficit_formula(self, solar_profile, price_profile, scenario_a, params):
        """residual = max(0, deficit - discharge) — drain at hour 23 may exceed deficit."""
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        residual = np.maximum(0.0, result.deficit_mwh - result.discharge_mwh)
        np.testing.assert_allclose(result.residual_deficit_mwh, residual, atol=1e-10)

    def test_residual_deficit_non_negative(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        assert np.all(result.residual_deficit_mwh >= -1e-10)

    def test_grid_injection_formula(self, solar_profile, price_profile, scenario_a, params):
        from solar_bess_risk.simulation import simulate_scenario
        result = simulate_scenario(solar_profile, price_profile, scenario_a, params)
        expected = solar_profile.generation_mw - result.charge_mwh + result.discharge_mwh
        np.testing.assert_allclose(result.grid_injection_mwh, expected, atol=1e-10)

    def test_a2_edge_case_excess_during_peak(self, price_profile, params):
        """Excess during peak hour → no charge, deficit = 0, BESS idle."""
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        # All hours generate at 100 MW, mwac=100, so gf ~= 100
        gen = np.full(HOURS_PER_YEAR, 100.0)
        mwac = 100.0
        annual = float(np.sum(gen))
        fc = annual / (mwac * HOURS_PER_YEAR)
        gf = mwac * fc  # = 100.0

        solar = SolarProfile(
            generation_mw=gen, annual_energy_mwh=annual,
            fc=fc, garantia_fisica_mw=gf, csv_filename="test.csv"
        )
        scenario = ScenarioDefinition(
            label="A", peak_hours=frozenset({18, 19}), duration_h=2,
            bess_power_mw=gf, bess_energy_mwh=gf * 2,
            capex_brl=gf * 2 * 200 * 1000 * 5.0,
        )
        result = simulate_scenario(solar, price_profile, scenario, params)
        # During peak hours, generation == gf, so deficit = 0, no discharge
        for h in range(HOURS_PER_YEAR):
            if h % 24 in scenario.peak_hours:
                assert result.charge_mwh[h] < 1e-10
                assert abs(result.deficit_mwh[h]) < 1e-10


class TestDeadlineDrain:
    """Battery must be empty by the following 05:00 deadline."""

    def _prices_trigger_charging(self) -> "np.ndarray":
        """Off-peak 100 BRL/MWh, peak {18,19} 1000 BRL/MWh → h-rule passes (0.85×1000=850>100)."""
        from solar_bess_risk.data_sources import PriceProfile
        arr = np.full(HOURS_PER_YEAR, 100.0)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                arr[h] = 1000.0
        return arr

    def _scenario_with_charging(self, solar_profile, duration_h: int, peak_hours: frozenset):
        from solar_bess_risk.simulation import ScenarioDefinition
        gf = solar_profile.garantia_fisica_mw
        return ScenarioDefinition(
            label="X",
            peak_hours=peak_hours,
            duration_h=duration_h,
            bess_power_mw=gf,
            bess_energy_mwh=gf * duration_h,
            capex_brl=0.0,
            rte=0.85,
        )

    def test_soc_zero_by_5am_deadline(self, solar_profile, params):
        """With h-rule active and solar charging, SoC must be 0 by 05:00."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import simulate_scenario

        prices = PriceProfile(
            prices_brl_per_mwh=self._prices_trigger_charging(),
            source="test", bq_submarket="SE", bq_year=2025,
        )
        scenario = self._scenario_with_charging(solar_profile, 2, frozenset({18, 19}))
        result = simulate_scenario(solar_profile, prices, scenario, params)

        soc_at_deadline = result.soc_mwh[28::24]
        assert np.all(soc_at_deadline < 1e-9), (
            f"SoC not zero by 05:00 — max residual: {soc_at_deadline.max():.6f} MWh"
        )

    def test_no_discharge_outside_peak_or_drain_window(self, solar_profile, params):
        """Expanded daily drain may discharge in dawn hours, but never above PCS."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import simulate_scenario

        prices = PriceProfile(
            prices_brl_per_mwh=self._prices_trigger_charging(),
            source="test", bq_submarket="SE", bq_year=2025,
        )
        peak_hours = frozenset({18, 19})
        scenario = self._scenario_with_charging(solar_profile, 2, peak_hours)
        result = simulate_scenario(solar_profile, prices, scenario, params)

        for h in range(HOURS_PER_YEAR):
            if result.discharge_mwh[h] > 1e-10:
                assert result.discharge_mwh[h] <= scenario.bess_power_mw + 1e-10

    def test_4h_scenario_drains_to_zero_with_limited_post_peak_hours(self, solar_profile, params):
        """4h scenario drains to zero without exceeding the PCS power limit."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import simulate_scenario

        # Use prices that trigger charging: off-peak 50, peak {17-20} = 2000
        arr = np.full(HOURS_PER_YEAR, 50.0)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {17, 18, 19, 20}:
                arr[h] = 2000.0
        prices = PriceProfile(
            prices_brl_per_mwh=arr, source="test", bq_submarket="SE", bq_year=2025
        )
        scenario = self._scenario_with_charging(solar_profile, 4, frozenset({17, 18, 19, 20}))
        result = simulate_scenario(solar_profile, prices, scenario, params)

        soc_at_deadline = result.soc_mwh[28::24]
        assert np.all(soc_at_deadline < 1e-9), (
            f"4h scenario: SoC not zero by 05:00 — max: {soc_at_deadline.max():.6f} MWh"
        )
        assert np.all(result.discharge_mwh <= scenario.bess_power_mw + 1e-10)

    def test_soc_may_cross_midnight_but_zero_by_deadline(self, solar_profile, params):
        """SoC may cross midnight, but not the next 05:00 deadline."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import simulate_scenario

        prices = PriceProfile(
            prices_brl_per_mwh=self._prices_trigger_charging(),
            source="test", bq_submarket="SE", bq_year=2025,
        )
        scenario = self._scenario_with_charging(solar_profile, 2, frozenset({18, 19}))
        result = simulate_scenario(solar_profile, prices, scenario, params)

        assert np.all(result.soc_mwh[28::24] < 1e-9)

    def test_price_aware_mode_may_discharge_midnight_but_respects_deadline(self, solar_profile, params):
        """Mode 3 may use dawn drain, but respects 05:00 deadline and gap."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        prices_arr = np.full(HOURS_PER_YEAR, 100.0)
        for day in range(365):
            start = day * 24
            prices_arr[start + 0] = 2000.0
            prices_arr[start + 18] = 1000.0

        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr, source="test", bq_submarket="SE", bq_year=2025
        )
        gf = solar_profile.garantia_fisica_mw
        scenario = ScenarioDefinition(
            label="P3",
            peak_hours=frozenset(),
            duration_h=2,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 2,
            capex_brl=0.0,
            rte=0.85,
            charge_mode=3,
        )
        result = simulate_scenario(solar_profile, prices, scenario, params)

        assert np.all(result.soc_mwh[28::24] < 1e-9)
        assert np.all(result.discharge_mwh <= scenario.bess_power_mw + 1e-10)

        charged = result.charge_mwh > 1e-10
        discharged = result.discharge_mwh > 1e-10
        assert not np.any(charged[:-1] & discharged[1:])
        assert not np.any(discharged[:-1] & charged[1:])

    def test_curtailment_charge_is_limited_by_pcs_and_energy_capacity(self, solar_profile, price_profile, params):
        """Curtailment charging is limited by PCS and remaining MWh capacity."""
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        gf = solar_profile.garantia_fisica_mw
        scenario = ScenarioDefinition(
            label="CURT",
            peak_hours=frozenset({18, 19}),
            duration_h=10,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 10,
            capex_brl=0.0,
            rte=0.85,
        )
        curtailment = np.zeros(HOURS_PER_YEAR)
        curtailment[11] = gf * 7

        result = simulate_scenario(
            solar_profile, price_profile, scenario, params, curtailment_series=curtailment
        )

        assert abs(result.charge_mwh[11] - scenario.bess_power_mw) < 1e-9
        assert result.curtailment_lost_mwh[11] >= curtailment[11] - scenario.bess_power_mw - 1e-9
        assert np.all(result.soc_mwh[28::24] < 1e-9)
        assert np.all(result.discharge_mwh <= scenario.bess_power_mw + 1e-10)

    def test_no_discharge_during_curtailment_even_for_peak_and_drain(self, solar_profile, params):
        """Curtailment hours are globally blocked for discharge."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import simulate_scenario

        prices = PriceProfile(
            prices_brl_per_mwh=self._prices_trigger_charging(),
            source="test", bq_submarket="SE", bq_year=2025,
        )
        scenario = self._scenario_with_charging(solar_profile, 4, frozenset({13, 14, 17, 18}))
        curtailment = np.zeros(HOURS_PER_YEAR)
        curtailment[13] = scenario.bess_power_mw
        curtailment[14] = scenario.bess_power_mw
        curtailment[17] = scenario.bess_power_mw

        result = simulate_scenario(
            solar_profile, prices, scenario, params, curtailment_series=curtailment
        )

        assert np.all(result.discharge_mwh[curtailment > 1e-10] < 1e-9)

    def test_expanded_drain_prioritizes_highest_pld_hours(self, solar_profile, params):
        """Expanded drain must wait for higher PLD hours when deadline capacity allows it."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        prices_arr = np.full(HOURS_PER_YEAR, 100.0)
        for hour in (18, 19, 22, 23):
            prices_arr[hour] = 1000.0 + hour
        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr, source="test", bq_submarket="SE", bq_year=2025
        )
        gf = solar_profile.garantia_fisica_mw
        rte = 0.85
        scenario = ScenarioDefinition(
            label="PLD",
            peak_hours=frozenset({18, 19}),
            duration_h=4,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 4,
            capex_brl=0.0,
            rte=rte,
        )
        curtailment = np.zeros(HOURS_PER_YEAR)
        curtailment[11] = scenario.bess_power_mw / rte

        result = simulate_scenario(
            solar_profile, prices, scenario, params, curtailment_series=curtailment
        )

        assert np.all(result.discharge_mwh[12:18] < 1e-9)
        assert np.all(result.discharge_mwh[[18, 19, 22, 23]] > 1e-9)

    def test_price_aware_no_discharge_during_curtailment(self, solar_profile, params):
        """Mode 3 also blocks discharge in curtailment hours."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        prices_arr = np.full(HOURS_PER_YEAR, 100.0)
        prices_arr[13] = 2000.0
        prices_arr[14] = 1900.0
        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr, source="test", bq_submarket="SE", bq_year=2025
        )
        gf = solar_profile.garantia_fisica_mw
        scenario = ScenarioDefinition(
            label="P3",
            peak_hours=frozenset(),
            duration_h=2,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 2,
            capex_brl=0.0,
            rte=0.85,
            charge_mode=3,
        )
        curtailment = np.zeros(HOURS_PER_YEAR)
        curtailment[13] = gf
        curtailment[14] = gf

        result = simulate_scenario(
            solar_profile, prices, scenario, params, curtailment_series=curtailment
        )

        assert np.all(result.discharge_mwh[curtailment > 1e-10] < 1e-9)

    def test_price_aware_ignores_high_pld_hour_before_feasible_charge(self, params):
        """Day-ahead mode must not schedule an impossible pre-charge discharge."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        gf = 50.0
        gen = np.full(HOURS_PER_YEAR, gf)
        prices_arr = np.full(HOURS_PER_YEAR, 100.0)
        for day in range(365):
            start = day * 24
            gen[start + 1] = 0.0      # expensive deficit before any charge
            prices_arr[start + 1] = 2000.0
            gen[start + 10] = 150.0   # feasible charge source
            prices_arr[start + 10] = 10.0
            gen[start + 20] = 0.0     # later deficit can be covered
            prices_arr[start + 20] = 1000.0

        solar = SolarProfile(
            generation_mw=gen,
            annual_energy_mwh=float(gen.sum()),
            fc=0.5,
            garantia_fisica_mw=gf,
            csv_filename="test.csv",
        )
        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr, source="test", bq_submarket="SE", bq_year=2025
        )
        scenario = ScenarioDefinition(
            label="P3",
            peak_hours=frozenset(),
            duration_h=2,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 2,
            capex_brl=0.0,
            rte=1.0,
            charge_mode=3,
        )

        result = simulate_scenario(
            solar,
            prices,
            scenario,
            SimulationParams(csv_path=params.csv_path, mwac=params.mwac, bess_roundtrip_efficiency=1.0),
        )

        assert np.all(result.discharge_mwh[1::24] < 1e-9)
        assert np.all(result.discharge_mwh[20::24] > 1e-9)

    def test_price_aware_reserves_scarce_energy_for_highest_future_pld(self, params):
        """Mode 3 must not drain chronologically when later PLD is higher."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        generation = np.zeros(HOURS_PER_YEAR)
        prices_arr = np.full(HOURS_PER_YEAR, 10.0)
        generation[10:12] = 100.0
        prices_arr[18] = 300.0
        prices_arr[19] = 500.0
        prices_arr[20] = 450.0

        solar = SolarProfile(
            generation_mw=generation,
            annual_energy_mwh=float(generation.sum()),
            fc=0.1,
            garantia_fisica_mw=50.0,
            csv_filename="test.csv",
        )
        scenario = ScenarioDefinition(
            label="P3",
            peak_hours=frozenset({18, 19, 20}),
            duration_h=2,
            bess_power_mw=50.0,
            charge_power_mw=50.0,
            bess_energy_mwh=100.0,
            capex_brl=0.0,
            rte=1.0,
            charge_mode=3,
        )

        result = simulate_scenario(
            solar,
            PriceProfile(prices_arr, "test", "SE", 2025),
            scenario,
            SimulationParams(csv_path=params.csv_path, mwac=params.mwac, bess_roundtrip_efficiency=1.0),
        )

        assert result.discharge_mwh[18] == 0.0
        assert result.discharge_mwh[19] == 50.0
        assert result.discharge_mwh[20] == 50.0

    def test_price_aware_uses_marginal_pairing_instead_of_min_discharge_pld(self, params):
        """A charge hour may be valid for 19h/20h even if it is not valid for 18h."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.profile import SolarProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        generation = np.zeros(HOURS_PER_YEAR)
        prices_arr = np.full(HOURS_PER_YEAR, 10.0)
        generation[12:15] = 100.0
        prices_arr[12] = 296.0
        prices_arr[13] = 300.0
        prices_arr[14] = 305.0
        prices_arr[18] = 344.0
        prices_arr[19] = 400.0
        prices_arr[20] = 397.0

        solar = SolarProfile(
            generation_mw=generation,
            annual_energy_mwh=float(generation.sum()),
            fc=0.1,
            garantia_fisica_mw=50.0,
            csv_filename="test.csv",
        )
        scenario = ScenarioDefinition(
            label="P3",
            peak_hours=frozenset({18, 19, 20}),
            duration_h=3,
            bess_power_mw=50.0,
            charge_power_mw=50.0,
            bess_energy_mwh=150.0,
            capex_brl=0.0,
            rte=0.86,
            charge_mode=3,
        )

        result = simulate_scenario(
            solar,
            PriceProfile(prices_arr, "test", "SE", 2025),
            scenario,
            SimulationParams(csv_path=params.csv_path, mwac=params.mwac, bess_roundtrip_efficiency=0.86),
        )

        assert result.charge_mwh[13] > 0.0
        assert result.charge_mwh[14] > 0.0
        assert result.discharge_mwh[19] > 0.0
        assert result.discharge_mwh[20] > 0.0


class TestHRule:
    """h-rule: excess solar stored only when rte × min_PLD_peak > PLD_h."""

    def _make_profile(self, gen_array: "np.ndarray", mwac: float = 100.0):
        from solar_bess_risk.profile import SolarProfile
        annual = float(np.sum(gen_array))
        fc = annual / (mwac * HOURS_PER_YEAR)
        gf = mwac * fc
        return SolarProfile(
            generation_mw=gen_array,
            annual_energy_mwh=annual,
            fc=fc,
            garantia_fisica_mw=gf,
            csv_filename="test.csv",
        )

    def test_no_charge_when_hrule_fails_uniform_price(self, params):
        """With uniform PLD=500 and rte=0.85: rte×500=425 < 500 → h-rule always fails.
        Battery must never charge from solar excess.
        """
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        # Flat generation at 150 MW (above any reasonable GF)
        gen = np.full(HOURS_PER_YEAR, 150.0)
        solar = self._make_profile(gen)
        gf = solar.garantia_fisica_mw

        prices = PriceProfile(
            prices_brl_per_mwh=np.full(HOURS_PER_YEAR, 500.0),
            source="test",
            bq_submarket="SE",
            bq_year=2025,
        )
        scenario = ScenarioDefinition(
            label="A",
            peak_hours=frozenset({18, 19}),
            duration_h=2,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 2,
            capex_brl=0.0,
            rte=0.85,
        )
        result = simulate_scenario(solar, prices, scenario, params)
        # h-rule: 0.85 × 500 = 425 < 500 → no solar charging ever
        assert np.all(result.charge_mwh < 1e-10), (
            "Battery should not charge when rte × min_PLD_peak < PLD_h (sell is better)"
        )

    def test_charges_when_hrule_passes_higher_peak_pld(self, params):
        """With low off-peak PLD and high peak PLD: rte × PLD_peak > PLD_off-peak → charges."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        # Build prices: off-peak daytime gets 200 BRL/MWh, peak hours {18,19} get 1000 BRL/MWh
        prices_arr = np.full(HOURS_PER_YEAR, 200.0)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                prices_arr[h] = 1000.0

        # Generation: 150 MW during daytime (6-17), 0 at night including peak hours.
        # This creates large excess (gen >> gf) during daytime and deficit at peak.
        gen = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if 6 <= h % 24 <= 17:
                gen[h] = 150.0
        solar = self._make_profile(gen)
        gf = solar.garantia_fisica_mw  # ≈ 150 × 12/24 / (100/100) ≈ 75 MW

        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr,
            source="test",
            bq_submarket="SE",
            bq_year=2025,
        )
        scenario = ScenarioDefinition(
            label="A",
            peak_hours=frozenset({18, 19}),
            duration_h=2,
            bess_power_mw=gf,
            bess_energy_mwh=gf * 2,
            capex_brl=0.0,
            rte=0.85,
        )
        result = simulate_scenario(solar, prices, scenario, params)
        # h-rule: 0.85 × 1000 = 850 > 200 → charging must happen in daytime off-peak hours
        assert np.any(result.charge_mwh > 1e-10), (
            "Battery should charge when rte × min_PLD_peak > PLD_h"
        )

    def test_charge_capped_by_bess_power_but_can_fill_over_multiple_hours(self, params):
        """PCS caps each charge hour; repeated eligible hours can still fill the battery."""
        from solar_bess_risk.data_sources import PriceProfile
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

        # Prices: off-peak very low (100), peak very high (800) → h-rule passes
        prices_arr = np.full(HOURS_PER_YEAR, 100.0)
        for h in range(HOURS_PER_YEAR):
            if h % 24 in {18, 19}:
                prices_arr[h] = 800.0

        # Small GF (mwac=10) but large daytime excess (generation=200 MW on a 10 MW plant)
        gen = np.zeros(HOURS_PER_YEAR)
        for h in range(HOURS_PER_YEAR):
            if 6 <= h % 24 <= 17:
                gen[h] = 200.0
        solar = self._make_profile(gen, mwac=10.0)
        gf = solar.garantia_fisica_mw  # ≈ 1.8 MW (small)

        prices = PriceProfile(
            prices_brl_per_mwh=prices_arr,
            source="test",
            bq_submarket="SE",
            bq_year=2025,
        )
        rte = 0.85
        scenario = ScenarioDefinition(
            label="A",
            peak_hours=frozenset({18, 19}),
            duration_h=2,
            bess_power_mw=gf,       # bess_power ≈ 1.8 MW
            bess_energy_mwh=gf * 2,  # capacity ≈ 3.6 MWh
            capex_brl=0.0,
            rte=rte,
        )
        result = simulate_scenario(solar, prices, scenario, params)

        # If bess_power cap were still applied: max charge per hour ≈ 1.8 MW.
        # Without the cap: battery should fill to capacity (≈ gf*2 MWh) quickly.
        # In first eligible hour (h=6, excess ≈ 200 - gf >> gf), SoC should
        # jump well above gf (the old per-hour limit).
        max_soc = result.soc_mwh.max()
        # Battery capacity = gf*2, so max achievable SoC = gf*2 * rte ≈ 3.1 MWh.
        # With power cap it would only reach gf * rte ≈ 1.5 MWh in first hour.
        assert max_soc > gf * rte + 1e-3, (
            f"SoC {max_soc:.4f} should exceed old bess_power-cap limit "
            f"{gf * rte:.4f} when charging is uncapped"
        )


class TestSimulateAllScenarios:
    """Test simulate_all_scenarios returns correct structure."""

    def test_returns_list_of_3_tuples(self, solar_profile, price_profile, params):
        from solar_bess_risk.simulation import ScenarioDefinition, simulate_all_scenarios
        gf = solar_profile.garantia_fisica_mw
        scenarios = [
            ScenarioDefinition("A", frozenset({18, 19}), 2, gf, gf * 2, gf * 2 * 1_000_000),
            ScenarioDefinition("B", frozenset({17, 18, 19}), 3, gf, gf * 3, gf * 3 * 1_000_000),
            ScenarioDefinition("C", frozenset({17, 18, 19, 20}), 4, gf, gf * 4, gf * 4 * 1_000_000),
        ]
        results = simulate_all_scenarios(solar_profile, price_profile, scenarios, params)
        assert len(results) == 3
        for scenario_def, dispatch in results:
            assert hasattr(dispatch, "soc_mwh")
            assert hasattr(scenario_def, "label")
