from pathlib import Path
import sys

import numpy as np
import pytest

from solar_bess_risk.simulation import DispatchResult


AGENTS_DIR = Path(__file__).resolve().parents[2] / ".agents"
sys.path.append(str(AGENTS_DIR))

import bess_pitch_agent  # noqa: E402


def _dispatch(*, injection_com, discharge, curtailment=None, curtailment_lost=None):
    arr = np.asarray(injection_com, dtype=np.float64)
    zeros = np.zeros_like(arr)
    curt = zeros.copy() if curtailment is None else np.asarray(curtailment, dtype=np.float64)
    lost = (
        zeros.copy()
        if curtailment_lost is None
        else np.asarray(curtailment_lost, dtype=np.float64)
    )
    return DispatchResult(
        soc_mwh=zeros.copy(),
        charge_mwh=zeros.copy(),
        discharge_mwh=np.asarray(discharge, dtype=np.float64),
        grid_injection_mwh=arr,
        deficit_mwh=zeros.copy(),
        residual_deficit_mwh=zeros.copy(),
        curtailment_mwh=curt,
        curtailment_lost_mwh=lost,
        carga_nao_realizada_diaria_mwh=np.zeros(1),
        ons_curtailment_mwh=zeros.copy(),
        clipping_available_mwh=zeros.copy(),
    )


def test_equilibrium_modulation_displays_without_bess_value_for_base_scenario():
    pld = np.full(24, 100.0)
    injection_sem = np.zeros(24)
    injection_com = np.zeros(24)
    discharge = np.zeros(24)

    injection_sem[0] = 10.0
    injection_com[0] = 5.0
    injection_com[1] = 10.0
    discharge[1] = 10.0

    data = (
        _dispatch(injection_com=injection_com, discharge=discharge),
        pld,
        10.0,
        injection_sem,
        frozenset({1}),
        4,
        2025,
    )
    dados = {
        "premio_anual_seguro_mm": 0.001,
        "2025_base": {"nome": "2025-4h"},
    }

    bess_pitch_agent.adicionar_modulacao_equilibrio(
        dados,
        {"2025-4h": data},
    )

    scenario = dados["2025_base"]
    assert scenario["fator_pld_descarga_equilibrio"] == pytest.approx(2.0)
    assert scenario["caixa_equilibrio_mm"] == pytest.approx(0.001)
    assert scenario["mod_equilibrio_brl_mwh"] == pytest.approx(191.6666667)
    assert scenario["mod_equilibrio_com_bess_brl_mwh"] == pytest.approx(187.5)
    assert scenario["delta_mod_equilibrio_brl_mwh"] == pytest.approx(4.1666667)
    assert scenario["mod_equilibrio_inteira"] == 192


def test_equilibrium_modulation_accounts_for_must_savings():
    data = (
        _dispatch(injection_com=[0.0, 10.0], discharge=[0.0, 10.0]),
        np.array([100.0, 100.0]),
        10.0,
        np.array([0.0, 0.0]),
        frozenset({1}),
        4,
        2025,
        1.0,
        None,
        None,
        None,
        1000.0,
    )
    dados = {
        "premio_anual_seguro_mm": 0.003,
        "2025_must": {"nome": "2025 - 4h redução de MUST (10%)"},
    }

    bess_pitch_agent.adicionar_modulacao_equilibrio(
        dados,
        {},
        {"2025 - 4h redução de MUST (10%)": data},
    )

    scenario = dados["2025_must"]
    assert scenario["fator_pld_descarga_equilibrio"] == pytest.approx(2.0)
    assert scenario["caixa_equilibrio_mm"] == pytest.approx(0.003)
    assert scenario["mod_equilibrio_brl_mwh"] == pytest.approx(200.0)
    assert scenario["mod_equilibrio_com_bess_brl_mwh"] == pytest.approx(100.0)


def test_pitch_html_renders_equilibrium_modulation_column(tmp_path):
    dados = {
        "nome_projeto": "PROJETO TESTE",
        "potencia_ac_mw": 100.0,
        "garantia_fisica_mw": 10.0,
        "energia_bess_mwh": 20.0,
        "representatividades_gf_pct": 8.0,
        "capex_total_mm": 10.0,
        "parcela_capex_mm": 1.0,
        "opex_anual_mm": 0.2,
        "premio_anual_seguro_mm": 1.2,
        "vida_util_anos": 20,
        "wacc_utilizado_pct": 10.0,
        "2025_base": {
            "mod_original_inteira": 50,
            "mod_com_bess_inteira": 20,
            "mod_equilibrio_brl_mwh": 35.4,
            "fator_pld_descarga_equilibrio": 1.75,
            "caixa_adicionado_mm": 1.0,
            "curtailment_geracao": "10%",
            "curtailment_recuperado": "60%",
            "delta_cvar_dia_mil": 100.0,
        },
    }
    path = tmp_path / "pitch.html"

    bess_pitch_agent.gerar_html_apresentacao(dados, path)

    html = path.read_text(encoding="utf-8")
    assert "Modulação de Equilíbrio s/ BESS" in html
    assert "R$ 35/MWh" in html
    assert "PLD dias c/ descarga × 1.75" in html


def test_cross_curtailment_scenarios_render_in_section_four(tmp_path):
    pld = np.full(24, 100.0)
    injection_sem = np.zeros(24)
    injection_com = np.zeros(24)
    discharge = np.zeros(24)
    curtailment = np.zeros(24)
    curtailment_lost = np.zeros(24)

    injection_com[1] = 10.0
    discharge[1] = 10.0
    curtailment[10] = 5.0
    curtailment_lost[10] = 2.0
    data = (
        _dispatch(
            injection_com=injection_com,
            discharge=discharge,
            curtailment=curtailment,
            curtailment_lost=curtailment_lost,
        ),
        pld,
        10.0,
        injection_sem,
        frozenset({1}),
        4,
        2025,
        1.0,
        None,
        None,
        {
            "cvar_95_sem_bess_brl": -5000.0,
            "cvar_95_com_bess_brl": -3500.0,
        },
    )
    dados = {
        "nome_projeto": "PROJETO TESTE",
        "potencia_ac_mw": 100.0,
        "garantia_fisica_mw": 10.0,
        "energia_bess_mwh": 20.0,
        "representatividades_gf_pct": 8.0,
        "capex_total_mm": 10.0,
        "parcela_capex_mm": 1.0,
        "opex_anual_mm": 0.2,
        "premio_anual_seguro_mm": 1.2,
        "vida_util_anos": 20,
        "wacc_utilizado_pct": 10.0,
    }

    bess_pitch_agent.adicionar_cenarios_curtailment_cruzado(
        dados,
        {"2025 com curtailment de 2026": data},
    )
    cenario = dados["curtailment_cruzado"][0]
    assert cenario["mod_original_inteira"] == 100
    assert cenario["mod_com_bess_inteira"] == 96
    assert cenario["caixa_adicionado_mm"] == pytest.approx(0.001)
    assert cenario["curtailment_recuperado"] == "60%"
    assert cenario["delta_cvar_dia_mil"] == pytest.approx(1.5)

    path = tmp_path / "pitch.html"
    bess_pitch_agent.gerar_html_apresentacao(dados, path)

    html = path.read_text(encoding="utf-8")
    assert "Sensibilidade Cruzada de Curtailment" in html
    assert "2025 com curtailment de 2026" in html
    assert "Sem redução de MUST" in html
