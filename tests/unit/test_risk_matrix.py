"""Unit tests for solar_bess_risk.risk_matrix — PLD × curtailment grid."""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import (
    HOURS_PER_YEAR,
    RISK_MATRIX_CURTAILMENT_TARGETS_PCT,
    RISK_MATRIX_PLD_FACTORS,
    SimulationParams,
)
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.risk_matrix import (
    annual_insurance_premium_brl,
    build_risk_matrix_html,
    compute_risk_matrix,
)
from solar_bess_risk.simulation import ScenarioDefinition


@pytest.fixture
def params() -> SimulationParams:
    return SimulationParams(csv_path="/tmp/test.csv", mwac=100.0)


@pytest.fixture
def solar_profile() -> SolarProfile:
    gen = np.zeros(HOURS_PER_YEAR)
    for h in range(HOURS_PER_YEAR):
        if 6 <= (h % 24) <= 17:
            gen[h] = 80.0
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
        generation_lim_mw=gen.copy(),
        generation_bess_mw=gen.copy(),
    )


@pytest.fixture
def scenario(solar_profile) -> ScenarioDefinition:
    gf = solar_profile.garantia_fisica_mw
    return ScenarioDefinition(
        label="B",
        peak_hours=frozenset({17, 18, 19, 20}),
        duration_h=4,
        bess_power_mw=gf,
        bess_energy_mwh=gf * 4,
        capex_brl=gf * 4 * 150.0 * 1000 * 5.0,
        charge_mode=3,
    )


@pytest.fixture
def base_pld() -> np.ndarray:
    rng = np.random.default_rng(0)
    return np.abs(rng.normal(200.0, 60.0, HOURS_PER_YEAR)) + 50.0


@pytest.fixture
def base_curt() -> np.ndarray:
    # 10% curtailment fraction every daylight hour
    curt = np.zeros(HOURS_PER_YEAR)
    for h in range(HOURS_PER_YEAR):
        if 6 <= (h % 24) <= 17:
            curt[h] = 0.10
    return curt


def test_premium_positive(scenario, params):
    premium = annual_insurance_premium_brl(scenario, params)
    assert premium > 0


def test_matrix_dimensions(solar_profile, base_pld, base_curt, scenario, params):
    result = compute_risk_matrix(
        solar=solar_profile,
        base_pld=base_pld,
        base_curtailment_pct_profile=base_curt,
        scenario=scenario,
        params=params,
        bq_submarket="SE",
    )
    assert len(result.cells) == len(RISK_MATRIX_PLD_FACTORS)
    for row in result.cells:
        assert len(row) == len(RISK_MATRIX_CURTAILMENT_TARGETS_PCT)
    assert result.base_curtailment_pct > 0


def test_curtailment_factor_scales_to_targets(solar_profile, base_pld, base_curt, scenario, params):
    result = compute_risk_matrix(
        solar=solar_profile,
        base_pld=base_pld,
        base_curtailment_pct_profile=base_curt,
        scenario=scenario,
        params=params,
        bq_submarket="SE",
    )
    # The curtailment axis scales the ONS base (~base_curtailment_pct) up to each
    # nominal target: factor = target / base_ons_pct.
    base_pct = result.base_curtailment_pct
    for row in result.cells:
        for cell in row:
            expected_factor = cell.curtailment_target_pct / base_pct
            assert cell.curtailment_factor == pytest.approx(expected_factor, rel=1e-9)
            # Realized ONS curtailment % matches the nominal target.
            assert cell.realized_curtailment_pct == pytest.approx(
                cell.curtailment_target_pct, rel=1e-3
            )


def test_pld_factor_scales_modulation(solar_profile, base_pld, base_curt, scenario, params):
    """Modulation (R$/MWh) is linear in PLD: ×2 PLD ⇒ ×2 modulation for same curtailment."""
    result = compute_risk_matrix(
        solar=solar_profile,
        base_pld=base_pld,
        base_curtailment_pct_profile=base_curt,
        scenario=scenario,
        params=params,
        bq_submarket="SE",
        pld_factors=(1.0, 2.0),
        curtailment_targets_pct=(15.0,),
    )
    base_cell = result.cells[0][0]
    doubled_cell = result.cells[1][0]
    assert base_cell.mod_sem_bess is not None
    assert doubled_cell.mod_sem_bess == pytest.approx(2.0 * base_cell.mod_sem_bess, rel=1e-6)


def test_no_curtailment_profile_disables_curtailment(solar_profile, base_pld, scenario, params):
    result = compute_risk_matrix(
        solar=solar_profile,
        base_pld=base_pld,
        base_curtailment_pct_profile=None,
        scenario=scenario,
        params=params,
        bq_submarket="SE",
    )
    assert result.base_curtailment_pct == 0.0
    for row in result.cells:
        for cell in row:
            assert cell.curtailment_factor == 0.0


def test_html_renders_all_metrics(solar_profile, base_pld, base_curt, scenario, params, tmp_path):
    result = compute_risk_matrix(
        solar=solar_profile,
        base_pld=base_pld,
        base_curtailment_pct_profile=base_curt,
        scenario=scenario,
        params=params,
        bq_submarket="SE",
    )
    path = tmp_path / "matriz_risco.html"
    build_risk_matrix_html(result, str(path), project_name="TESTE")
    html = path.read_text(encoding="utf-8")
    assert "Modulação s/ BESS" in html
    assert "c/ BESS" in html
    assert "Caixa Adicionado Total" in html
    assert "TESTE" in html
    # combined modulação quadro + caixa adicionado
    assert html.count("matrix-block") >= 2
    # binary vivid colouring (no gradient), green/red premium legend
    assert "#15a34a" in html
    assert "#e11d48" in html
    assert "atinge o prêmio anual" in html
