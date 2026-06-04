"""US1 tests — MUST injection cap in the price-aware dispatch engine.

TDD (constitution Principle III): these tests are written before the
implementation of the ``must_mw`` cap and MUST fail until it exists.
"""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

TOL = 1e-9


def _solar_midday_peak(mwac: float = 100.0) -> SolarProfile:
    """Solar with a midday injection peak and no inverter clipping.

    gen_lim == gen_bess (clip = 0) so the MUST cap is the only top-of-profile
    constraint. Evening hours have zero generation (discharge window).
    """
    gen = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    for day in range(365):
        gen[day * 24 + 12] = 80.0  # midday peak (MW)
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
    arr[19::24] = 500.0  # high PLD in the evening discharge window
    return PriceProfile(arr, "synthetic", "SE", 2025)


def test_must_mw_none_is_backward_compatible():
    """must_mw=None must reproduce the current dispatch exactly."""
    solar, scenario, prices = _solar_midday_peak(), _scenario(), _prices()
    params = SimulationParams(csv_path="midday.csv", mwac=100.0)

    base = simulate_scenario(solar, prices, scenario, params, curtailment_series=None)
    same = simulate_scenario(
        solar, prices, scenario, params, curtailment_series=None, must_mw=None
    )
    np.testing.assert_allclose(base.grid_injection_mwh, same.grid_injection_mwh)
    np.testing.assert_allclose(base.curtailment_mwh, same.curtailment_mwh)


def test_must_cap_limits_solar_injection():
    """With a MUST cap below the peak, direct solar injection is capped.

    The discharge window has zero solar generation, so total injection equals
    the discharge there (kept <= must_mw by sizing), and elsewhere equals the
    capped solar injection. Hence grid_injection <= must_mw everywhere.
    """
    solar, scenario, prices = _solar_midday_peak(), _scenario(), _prices()
    params = SimulationParams(csv_path="midday.csv", mwac=100.0)
    must_mw = 50.0  # below the 80 MW midday peak

    capped = simulate_scenario(
        solar, prices, scenario, params, curtailment_series=None, must_mw=must_mw
    )

    assert np.all(capped.grid_injection_mwh <= must_mw + TOL)
    # Curtailment now appears at midday (excess above MUST)
    assert capped.curtailment_mwh[12] >= 80.0 - must_mw - TOL


def test_must_cap_no_double_counting_uses_max_not_sum():
    """Available curtailment = ons + max(clip, must_excess), never the sum.

    With clip == 0 and must_excess == 30 at the peak hour, the total available
    curtailment must equal 30 (= max(0, 30)), not 0 + 0 + 30 double-added.
    """
    solar, scenario, prices = _solar_midday_peak(), _scenario(), _prices()
    params = SimulationParams(csv_path="midday.csv", mwac=100.0)
    must_mw = 50.0

    capped = simulate_scenario(
        solar, prices, scenario, params, curtailment_series=None, must_mw=must_mw
    )

    gen_bess = solar.generation_bess_mw
    clip = np.maximum(0.0, gen_bess - solar.generation_lim_mw)
    must_excess = np.maximum(0.0, gen_bess - must_mw)
    expected_available = np.maximum(clip, must_excess)  # ons = 0 here
    np.testing.assert_allclose(
        capped.curtailment_total_available_mwh, expected_available
    )
    # Cannot curtail more energy than generated
    assert np.all(capped.curtailment_total_available_mwh <= gen_bess + TOL)


def test_must_cap_energy_reconciliation():
    """Generated energy reconciles with injection + lost + net storage (rte=1)."""
    solar, scenario, prices = _solar_midday_peak(), _scenario(), _prices()
    # rte=1 end-to-end: scenario.rte==1.0 falls back to params efficiency,
    # so pin the param to 1.0 for an exact energy balance.
    params = SimulationParams(
        csv_path="midday.csv", mwac=100.0, bess_roundtrip_efficiency=1.0
    )
    must_mw = 50.0

    d = simulate_scenario(
        solar, prices, scenario, params, curtailment_series=None, must_mw=must_mw
    )

    total_gen = float(solar.generation_bess_mw.sum())
    total_inj = float(d.grid_injection_mwh.sum())
    total_lost = float(d.curtailment_lost_mwh.sum())
    leftover_soc = float(d.soc_mwh[-1])
    # rte=1: gen = injection + spilled + energy still stored at year end
    assert abs(total_gen - (total_inj + total_lost + leftover_soc)) <= 1e-6 * total_gen


def test_must_cap_limits_discharge_on_top_of_generation():
    """BESS discharge must use only the remaining MUST headroom."""
    gen = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    prices_arr = np.full(HOURS_PER_YEAR, 100.0)
    for day in range(365):
        gen[day * 24 + 10] = 80.0
        gen[day * 24 + 18] = 45.0
        prices_arr[day * 24 + 10] = 10.0
        prices_arr[day * 24 + 18] = 1_000.0

    solar = SolarProfile(
        generation_mw=gen,
        annual_energy_mwh=float(gen.sum()),
        fc=float(gen.sum()) / (100.0 * HOURS_PER_YEAR),
        garantia_fisica_mw=20.0,
        csv_filename="must-headroom.csv",
        generation_lim_mw=gen,
        generation_bess_mw=gen,
        generation_years_lim_mw=gen.reshape(1, HOURS_PER_YEAR),
        generation_years_bess_mw=gen.reshape(1, HOURS_PER_YEAR),
        n_years=1,
    )
    scenario = ScenarioDefinition(
        label="H",
        peak_hours=frozenset({18}),
        duration_h=1,
        bess_power_mw=20.0,
        charge_power_mw=20.0,
        bess_energy_mwh=20.0,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )
    params = SimulationParams(
        csv_path="must-headroom.csv", mwac=100.0, bess_roundtrip_efficiency=1.0
    )

    d = simulate_scenario(
        solar,
        PriceProfile(prices_arr, "synthetic", "SE", 2025),
        scenario,
        params,
        must_mw=50.0,
    )

    assert np.all(d.grid_injection_mwh <= 50.0 + TOL)
    assert d.discharge_mwh[18] <= 5.0 + TOL
    assert d.grid_injection_mwh[18] == pytest.approx(50.0)


def test_price_aware_does_not_double_count_curtailment_and_direct_solar():
    """Charging from curtailment plus solar cannot exceed physical generation."""
    gen = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    prices_arr = np.full(HOURS_PER_YEAR, 100.0)
    for day in range(365):
        gen[day * 24 + 10] = 100.0
        prices_arr[day * 24 + 10] = 10.0
        prices_arr[day * 24 + 18] = 1_000.0

    solar = SolarProfile(
        generation_mw=gen,
        annual_energy_mwh=float(gen.sum()),
        fc=float(gen.sum()) / (100.0 * HOURS_PER_YEAR),
        garantia_fisica_mw=5.0,
        csv_filename="no-creation.csv",
        generation_lim_mw=gen,
        generation_bess_mw=gen,
        generation_years_lim_mw=gen.reshape(1, HOURS_PER_YEAR),
        generation_years_bess_mw=gen.reshape(1, HOURS_PER_YEAR),
        n_years=1,
    )
    scenario = ScenarioDefinition(
        label="N",
        peak_hours=frozenset({18}),
        duration_h=1,
        bess_power_mw=180.0,
        charge_power_mw=180.0,
        bess_energy_mwh=180.0,
        capex_brl=1.0,
        rte=1.0,
        charge_mode=3,
    )
    params = SimulationParams(
        csv_path="no-creation.csv", mwac=100.0, bess_roundtrip_efficiency=1.0
    )

    d = simulate_scenario(
        solar,
        PriceProfile(prices_arr, "synthetic", "SE", 2025),
        scenario,
        params,
        must_mw=20.0,
    )

    assert d.charge_mwh[10] <= gen[10] + TOL
    assert d.grid_injection_mwh.sum() + d.curtailment_lost_mwh.sum() + d.soc_mwh[-1] == pytest.approx(
        gen.sum()
    )


def test_must_cap_holds_across_full_synthetic_year_with_sweep_like_caps():
    """A MUST sweep must never produce hourly injection above the tested cap."""
    solar, scenario, prices = _solar_midday_peak(), _scenario(), _prices()
    params = SimulationParams(
        csv_path="midday.csv", mwac=100.0, bess_roundtrip_efficiency=1.0
    )

    for must_mw in (80.0, 60.0, 50.0, 30.0, 20.0):
        result = simulate_scenario(
            solar,
            prices,
            scenario,
            params,
            curtailment_series=None,
            must_mw=must_mw,
        )

        assert np.max(result.grid_injection_mwh) <= must_mw + TOL


def test_price_aware_energy_reconciliation_includes_rte_losses():
    """With RTE < 1, generated energy reconciles after explicit charge losses."""
    gen = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    prices_arr = np.full(HOURS_PER_YEAR, 100.0)
    for day in range(365):
        gen[day * 24 + 10] = 100.0
        prices_arr[day * 24 + 10] = 10.0
        prices_arr[day * 24 + 18] = 1_000.0

    solar = SolarProfile(
        generation_mw=gen,
        annual_energy_mwh=float(gen.sum()),
        fc=float(gen.sum()) / (100.0 * HOURS_PER_YEAR),
        garantia_fisica_mw=5.0,
        csv_filename="rte-losses.csv",
        generation_lim_mw=gen,
        generation_bess_mw=gen,
        generation_years_lim_mw=gen.reshape(1, HOURS_PER_YEAR),
        generation_years_bess_mw=gen.reshape(1, HOURS_PER_YEAR),
        n_years=1,
    )
    scenario = ScenarioDefinition(
        label="LOSS",
        peak_hours=frozenset({18}),
        duration_h=1,
        bess_power_mw=50.0,
        charge_power_mw=50.0,
        bess_energy_mwh=50.0,
        capex_brl=1.0,
        rte=0.8,
        charge_mode=3,
    )
    params = SimulationParams(
        csv_path="rte-losses.csv", mwac=100.0, bess_roundtrip_efficiency=0.8
    )

    result = simulate_scenario(
        solar,
        PriceProfile(prices_arr, "synthetic", "SE", 2025),
        scenario,
        params,
        must_mw=100.0,
    )

    total_gen = float(gen.sum())
    total_injection = float(result.grid_injection_mwh.sum())
    total_spilled = float(result.curtailment_lost_mwh.sum())
    stored_at_end = float(result.soc_mwh[-1])
    charge_losses = float(result.charge_mwh.sum() * (1.0 - scenario.rte))

    assert total_gen == pytest.approx(
        total_injection + total_spilled + stored_at_end + charge_losses
    )
