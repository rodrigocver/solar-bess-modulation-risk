"""Unit tests for BESS block-count optimization."""

from __future__ import annotations

import numpy as np

from solar_bess_risk.block_optimization import BlockOptimizationConfig, optimize_blocks_for_results
from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import DispatchResult, ScenarioDefinition


def test_optimize_blocks_marks_one_recommendation_per_scenario():
    generation = np.zeros(HOURS_PER_YEAR)
    prices = np.full(HOURS_PER_YEAR, 50.0)
    for day in range(365):
        start = day * 24
        generation[start + 10:start + 12] = 20.0
        prices[start + 20:start + 22] = 500.0

    solar = SolarProfile(
        generation_mw=generation,
        annual_energy_mwh=float(generation.sum()),
        fc=0.1,
        garantia_fisica_mw=4.0,
        csv_filename="synthetic.csv",
    )
    dispatch = DispatchResult(
        soc_mwh=np.zeros(HOURS_PER_YEAR),
        charge_mwh=np.zeros(HOURS_PER_YEAR),
        discharge_mwh=np.zeros(HOURS_PER_YEAR),
        grid_injection_mwh=generation.copy(),
        deficit_mwh=np.maximum(0.0, solar.garantia_fisica_mw - generation),
        residual_deficit_mwh=np.maximum(0.0, solar.garantia_fisica_mw - generation),
        curtailment_mwh=np.zeros(HOURS_PER_YEAR),
        curtailment_lost_mwh=np.zeros(HOURS_PER_YEAR),
        carga_nao_realizada_diaria_mwh=np.zeros(365),
    )
    scenario = ScenarioDefinition(
        label="A",
        peak_hours=frozenset({20, 21}),
        duration_h=2,
        bess_power_mw=4.54,
        charge_power_mw=4.54,
        bess_energy_mwh=10.1,
        capex_brl=100_000.0,
        rte=1.0,
        charge_mode=3,
    )
    results_by_key = {
        "2025-2h": (
            dispatch,
            prices,
            solar.garantia_fisica_mw,
            generation,
            scenario.peak_hours,
            scenario.duration_h,
            2025,
            1.0,
            scenario,
        )
    }
    params = SimulationParams(
        csv_path="synthetic.csv",
        mwac=40.0,
        usd_brl_rate=5.0,
        useful_life_years=2,
        bess_o_and_m_pct_capex=0.0,
    )

    detail, recommended = optimize_blocks_for_results(
        results_by_key=results_by_key,
        solar=solar,
        params=params,
        rte_table={2025: 1.0, 2026: 1.0},
        config=BlockOptimizationConfig(max_blocks_multiplier=1.0, full_projection_top_n=1),
    )

    assert not detail.empty
    assert len(recommended) == 4
    assert int(detail["recomendado"].sum()) == 4
    assert {"ranking_retorno", "ranking_payback", "roi_vida_util", "capex_scenario"} <= set(detail.columns)
    assert int(detail["projecao_rte_completa"].sum()) == 4
    assert set(recommended["capex_scenario"]) == {"base", "capex_-10%", "capex_-25%", "capex_-50%"}
