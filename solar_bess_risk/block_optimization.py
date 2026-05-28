"""Block-count optimization for BESS scenarios."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from solar_bess_risk.config import (
    BESS_BLOCK_SPECS,
    CAPEX_USD_PER_KWH,
    SCENARIO_TEMPLATES,
    SimulationParams,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.projection import project_cashflows_with_rte
from solar_bess_risk.simulation import DispatchResult, ScenarioDefinition, simulate_scenario


@dataclass(frozen=True)
class BlockOptimizationConfig:
    """Configuration for the block-count search."""

    max_blocks_multiplier: float = 2.0
    roi_tolerance_to_best: float = 0.95
    full_projection_top_n: int = 5
    capex_scenarios: tuple[tuple[str, float], ...] = (
        ("base", 1.0),
        ("capex_-10%", 0.90),
        ("capex_-25%", 0.75),
        ("capex_-50%", 0.50),
    )


def optimize_blocks_for_results(
    *,
    results_by_key: dict[str, tuple],
    solar: SolarProfile,
    params: SimulationParams,
    rte_table: dict[int, float],
    config: BlockOptimizationConfig | None = None,
    progress_cb=None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Evaluate integer block counts for every reported scenario tab.

    Returns a detailed candidate table and one recommendation row per scenario.
    """
    cfg = config or BlockOptimizationConfig()
    detail_rows: list[dict] = []

    for tab_name, data in results_by_key.items():
        base_dispatch, pld, gf, _gen, _peak_hours, duration_h, year_label, rte = data[:8]
        start_year = int(year_label) if isinstance(year_label, int) and year_label >= 2025 else (
            min(rte_table) if rte_table else 2025
        )
        detail_rows.extend(
            _optimize_single_case(
                tab_name=tab_name,
                solar=solar,
                pld=pld,
                gf=gf,
                duration_h=duration_h,
                rte=float(rte),
                start_year=start_year,
                params=params,
                curtailment_series=base_dispatch.curtailment_mwh,
                rte_table=rte_table,
                config=cfg,
                progress_cb=progress_cb,
            )
        )

    detail = pd.DataFrame(detail_rows)
    if detail.empty:
        return detail, pd.DataFrame()

    group_cols = ["cenario", "capex_scenario"]
    detail["ranking_retorno"] = (
        detail.groupby(group_cols)["roi_vida_util"]
        .rank(method="min", ascending=False)
        .astype(int)
    )
    detail["ranking_payback"] = (
        detail.assign(_payback_rank=pd.to_numeric(detail["payback_anos"], errors="coerce").fillna(float("inf")))
        .groupby(group_cols)["_payback_rank"]
        .rank(method="min", ascending=True)
        .astype(int)
    )
    detail["recomendado"] = False
    recommended_rows: list[pd.Series] = []

    for (_scenario_name, _capex_scenario), group in detail.groupby(group_cols, sort=False):
        viable = group[group["payback_anos"].notna() & (group["roi_vida_util"] > 0)].copy()
        if viable.empty:
            chosen_idx = group["lifetime_net_savings_brl"].idxmax()
        else:
            best_roi = float(viable["roi_vida_util"].max())
            near_best = viable[viable["roi_vida_util"] >= best_roi * cfg.roi_tolerance_to_best]
            chosen_idx = near_best.sort_values(
                ["payback_anos", "n_blocos"],
                ascending=[True, True],
            ).index[0]
        detail.loc[chosen_idx, "recomendado"] = True
        recommended_rows.append(detail.loc[chosen_idx])

    recommended = pd.DataFrame(recommended_rows).reset_index(drop=True)
    return detail.reset_index(drop=True), recommended


def _optimize_single_case(
    *,
    tab_name: str,
    solar: SolarProfile,
    pld: np.ndarray,
    gf: float,
    duration_h: int,
    rte: float,
    start_year: int,
    params: SimulationParams,
    curtailment_series: np.ndarray,
    rte_table: dict[int, float],
    config: BlockOptimizationConfig,
    progress_cb=None,
) -> list[dict]:
    """Evaluate all block counts for one scenario tab."""
    block = BESS_BLOCK_SPECS[duration_h]
    template = next(t for t in SCENARIO_TEMPLATES if t.duration_h == duration_h)
    gf_blocks = math.ceil(gf / block.block_power_mw)
    max_blocks = max(gf_blocks + 1, math.ceil(gf_blocks * config.max_blocks_multiplier))
    price_profile = PriceProfile(
        prices_brl_per_mwh=pld,
        source=f"block_optimization_{tab_name}",
        bq_submarket=params.bq_submarket,
        bq_year=start_year,
    )

    rows: list[dict] = []
    fast_rows: list[tuple[dict, ScenarioDefinition, DispatchResult]] = []
    for n_blocks in range(1, max_blocks + 1):
        if progress_cb is not None and (n_blocks == 1 or n_blocks == max_blocks or n_blocks % 10 == 0):
            progress_cb(tab_name, n_blocks, max_blocks, "ranking")

        bess_power = n_blocks * block.block_power_mw
        bess_energy = n_blocks * block.block_energy_mwh
        base_capex_brl = (
            bess_energy
            * 1000.0
            * CAPEX_USD_PER_KWH[duration_h]
            * params.usd_brl_rate
        )
        scenario = ScenarioDefinition(
            label=template.label,
            peak_hours=template.peak_hours,
            duration_h=duration_h,
            bess_power_mw=bess_power,
            charge_power_mw=bess_power,
            bess_energy_mwh=bess_energy,
            capex_brl=base_capex_brl,
            peak_hour_weights=template.peak_hour_weights,
            rte=rte,
            charge_mode=3,
        )
        dispatch = simulate_scenario(
            solar,
            price_profile,
            scenario,
            params,
            curtailment_series=curtailment_series,
        )
        gross_savings = _net_balance_delta_brl(solar, dispatch, pld)
        annual_discharge = float(np.sum(dispatch.discharge_mwh))
        total_curtailment = float(np.sum(dispatch.curtailment_mwh))
        recovered_curtailment = float(np.sum(dispatch.curtailment_mwh - dispatch.curtailment_lost_mwh))
        for capex_label, capex_multiplier in config.capex_scenarios:
            capex_brl = base_capex_brl * capex_multiplier
            annual_o_and_m = capex_brl * params.bess_o_and_m_pct_capex
            annual_net = gross_savings - annual_o_and_m
            approximate_lifetime_net = _approximate_lifetime_net_savings(
                gross_savings_brl=gross_savings,
                annual_o_and_m_brl=annual_o_and_m,
                degradation_pct_yr=params.bess_degradation_pct_yr,
                useful_life_years=params.useful_life_years,
            )
            approximate_payback = _approximate_payback(
                capex_brl=capex_brl,
                gross_savings_brl=gross_savings,
                annual_o_and_m_brl=annual_o_and_m,
                degradation_pct_yr=params.bess_degradation_pct_yr,
                useful_life_years=params.useful_life_years,
            )
            approximate_lifetime_discharge = annual_discharge * params.useful_life_years
            approximate_lcos = (
                (capex_brl + annual_o_and_m * params.useful_life_years) / approximate_lifetime_discharge
                if approximate_lifetime_discharge > 1e-9 else None
            )
            row = {
                "cenario": tab_name,
                "capex_scenario": capex_label,
                "capex_multiplier": capex_multiplier,
                "capex_reduction_pct": (1.0 - capex_multiplier) * 100.0,
                "duration_h": duration_h,
                "n_blocos": n_blocks,
                "blocos_gf_atual": gf_blocks,
                "multiplo_blocos_gf": n_blocks / gf_blocks if gf_blocks else 0.0,
                "bess_power_mw": bess_power,
                "bess_energy_mwh": bess_energy,
                "charge_power_mw": bess_power,
                "capex_base_brl": base_capex_brl,
                "capex_brl": capex_brl,
                "economia_bruta_anual_brl": gross_savings,
                "o_and_m_anual_brl": annual_o_and_m,
                "economia_liquida_anual_brl": annual_net,
                "payback_anos": approximate_payback,
                "lcos_brl_mwh": approximate_lcos,
                "lifetime_net_savings_brl": approximate_lifetime_net,
                "roi_vida_util": approximate_lifetime_net / capex_brl if capex_brl else 0.0,
                "descarga_mwh_ano": annual_discharge,
                "carga_mwh_ano": float(np.sum(dispatch.charge_mwh)),
                "carga_nao_realizada_mwh_ano": float(np.sum(dispatch.carga_nao_realizada_diaria_mwh)),
                "curtailment_recuperado_pct": (
                    np.clip(recovered_curtailment / total_curtailment, 0.0, 1.0)
                    if total_curtailment > 1e-9 else 0.0
                ),
                "projecao_rte_completa": False,
            }
            scenario_with_capex = replace(scenario, capex_brl=capex_brl)
            rows.append(row)
            fast_rows.append((row, scenario_with_capex, dispatch))

    for capex_label, group in _group_fast_rows_by_capex(fast_rows).items():
        top_candidates = sorted(
            group,
            key=lambda item: (
                -float(item[0]["roi_vida_util"]),
                float(item[0]["payback_anos"]) if item[0]["payback_anos"] is not None else float("inf"),
                int(item[0]["n_blocos"]),
            ),
        )[: config.full_projection_top_n]
        progress_name = f"{tab_name}/{capex_label}"
        for index, (row, scenario, _dispatch) in enumerate(top_candidates, start=1):
            if progress_cb is not None:
                progress_cb(progress_name, index, len(top_candidates), "rte_top")
            projection = project_cashflows_with_rte(
                solar=solar,
                pld=pld,
                price_source=price_profile.source,
                bq_submarket=params.bq_submarket,
                scenario=scenario,
                params=params,
                curtailment_series=curtailment_series,
                rte_table=rte_table,
                start_year=start_year,
            )
            row["payback_anos"] = projection.payback_years
            row["lcos_brl_mwh"] = projection.lcos_brl_per_mwh
            row["lifetime_net_savings_brl"] = projection.lifetime_net_savings_brl
            row["roi_vida_util"] = (
                projection.lifetime_net_savings_brl / row["capex_brl"]
                if row["capex_brl"] else 0.0
            )
            row["projecao_rte_completa"] = True
    return rows


def _group_fast_rows_by_capex(
    fast_rows: list[tuple[dict, ScenarioDefinition, DispatchResult]],
) -> dict[str, list[tuple[dict, ScenarioDefinition, DispatchResult]]]:
    """Group optimization candidates by CAPEX sensitivity label."""
    grouped: dict[str, list[tuple[dict, ScenarioDefinition, DispatchResult]]] = {}
    for item in fast_rows:
        grouped.setdefault(str(item[0]["capex_scenario"]), []).append(item)
    return grouped


def _net_balance_delta_brl(
    solar: SolarProfile,
    dispatch: DispatchResult,
    pld: np.ndarray,
) -> float:
    """Return annual net-balance improvement with BESS versus without BESS."""
    injection_sem = solar.generation_mw - dispatch.curtailment_mwh
    injection_com = (
        solar.generation_mw
        - dispatch.charge_mwh
        - dispatch.curtailment_lost_mwh
        + dispatch.discharge_mwh
    )
    return float(np.sum((injection_com - injection_sem) * pld))


def _approximate_lifetime_net_savings(
    *,
    gross_savings_brl: float,
    annual_o_and_m_brl: float,
    degradation_pct_yr: float,
    useful_life_years: int,
) -> float:
    """Approximate lifetime savings without re-simulating each RTE year."""
    return sum(
        gross_savings_brl * ((1 - degradation_pct_yr) ** (year - 1)) - annual_o_and_m_brl
        for year in range(1, useful_life_years + 1)
    )


def _approximate_payback(
    *,
    capex_brl: float,
    gross_savings_brl: float,
    annual_o_and_m_brl: float,
    degradation_pct_yr: float,
    useful_life_years: int,
) -> float | None:
    """Approximate payback without re-simulating each RTE year."""
    cumulative = 0.0
    previous = 0.0
    for year in range(1, useful_life_years + 1):
        net = gross_savings_brl * ((1 - degradation_pct_yr) ** (year - 1)) - annual_o_and_m_brl
        cumulative += net
        if cumulative >= capex_brl:
            if net <= 0:
                return float(year)
            return (year - 1) + (capex_brl - previous) / net
        previous = cumulative
    return None
