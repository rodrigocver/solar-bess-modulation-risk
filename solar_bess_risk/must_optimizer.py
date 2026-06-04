"""MUST (Montante de Uso do Sistema de Transmissão) reduction optimizer.

For a fixed BESS duration scenario, sweeps candidate MUST reduction fractions
and selects the one maximizing the net annual benefit:

    net_benefit = tust_savings + (net_balance_com(must) − net_balance_com(0%))

The initial MUST always equals the project AC power (``mwac``), so a reduction
of ``pct`` yields ``must_mw = mwac × (1 − pct)`` and abdicates
``delta_must_mw = mwac × pct`` of contracted transmission capacity.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from solar_bess_risk.config import (
    DEFAULT_TUST_BRL_PER_KW_MONTH,
    KW_PER_MW,
    MONTHS_PER_YEAR,
    SimulationParams,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.economics import compute_scenario_economics
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario


@dataclass(frozen=True)
class MustEvaluationPoint:
    """One point of the MUST reduction sweep for a scenario.

    Parameters
    ----------
    reduction_pct : float
        MUST reduction fraction evaluated (0-1).
    must_mw : float
        Resulting MUST in MW = ``mwac × (1 − reduction_pct)``.
    delta_must_mw : float
        Abdicated capacity in MW = ``mwac × reduction_pct``.
    tust_savings_brl_per_yr : float
        Annual TUST savings in BRL = ``tust × 12 × delta_must_mw × 1000``.
    net_balance_com_brl : float
        Net balance with BESS under this MUST in BRL/yr.
    net_balance_delta_vs_baseline_brl : float
        ``net_balance_com − net_balance_com(reduction 0%)`` in BRL/yr.
    net_benefit_brl_per_yr : float
        ``tust_savings + net_balance_delta_vs_baseline`` in BRL/yr.
    curtailment_lost_mwh : float
        Energy spilled under this MUST in MWh/yr (SC-005 audit).
    """

    reduction_pct: float
    must_mw: float
    delta_must_mw: float
    tust_savings_brl_per_yr: float
    net_balance_com_brl: float
    net_balance_delta_vs_baseline_brl: float
    net_benefit_brl_per_yr: float
    curtailment_lost_mwh: float


@dataclass(frozen=True)
class MustOptimizationResult:
    """Optimization result for one BESS duration scenario.

    Parameters
    ----------
    scenario_label : str
        Scenario label ("A", "B", ...).
    duration_h : int
        BESS duration in hours.
    mwac : float
        Project AC power in MW = initial MUST.
    tust_brl_per_kw_month : float
        TUST used in R$/kW.month.
    tust_is_default : bool
        True when the documented default (7.23) was applied (SC-006).
    optimal_reduction_pct : float
        Optimal MUST reduction fraction (0-1).
    optimal_must_mw : float
        MUST at the optimum in MW.
    optimal_net_benefit_brl_per_yr : float
        Net benefit at the optimum in BRL/yr.
    sweep : list[MustEvaluationPoint]
        Full sensitivity curve.
    """

    scenario_label: str
    duration_h: int
    mwac: float
    tust_brl_per_kw_month: float
    tust_is_default: bool
    optimal_reduction_pct: float
    optimal_must_mw: float
    optimal_net_benefit_brl_per_yr: float
    sweep: list[MustEvaluationPoint]


def tust_annual_savings_brl(
    *, tust_brl_per_kw_month: float, delta_must_mw: float
) -> float:
    """Annual TUST savings from abdicating ``delta_must_mw`` of MUST.

    Parameters
    ----------
    tust_brl_per_kw_month : float
        Transmission usage tariff in R$/kW.month.
    delta_must_mw : float
        Abdicated MUST capacity in MW.

    Returns
    -------
    float
        Annual savings in BRL = ``tust × 12 × delta_must_mw × 1000``.
    """
    return tust_brl_per_kw_month * MONTHS_PER_YEAR * delta_must_mw * KW_PER_MW


def _sweep_fractions(max_pct: float, step_pct: float) -> list[float]:
    """Build the reduction sweep grid ``[0, step, 2·step, ..., max]``.

    Parameters
    ----------
    max_pct : float
        Maximum reduction fraction (inclusive endpoint, 0-1).
    step_pct : float
        Step of the grid as a fraction (> 0).

    Returns
    -------
    list[float]
        Ordered reduction fractions starting at 0.0.
    """
    if step_pct <= 0.0:
        raise ValueError(f"ERRO: must_sweep_step_pct={step_pct} deve ser > 0.")
    n_steps = int(math.floor(max_pct / step_pct + 1e-9))
    fractions = [round(i * step_pct, 10) for i in range(n_steps + 1)]
    if fractions[-1] < max_pct - 1e-9:
        fractions.append(round(max_pct, 10))
    return fractions


def optimize_must_reduction(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    *,
    curtailment_series: np.ndarray | None = None,
    solar_year_idx: int = 1,
) -> MustOptimizationResult:
    """Find the MUST reduction maximizing net annual benefit for one scenario.

    The sweep always includes ``reduction_pct == 0`` as the baseline (no
    reduction, ``must_mw == mwac``), against which every other point's net
    balance delta is measured.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly PLD prices.
    scenario : ScenarioDefinition
        BESS duration scenario sizing.
    params : SimulationParams
        Simulation parameters; supplies ``mwac``, ``tust_brl_per_kw_month``,
        ``must_sweep_max_pct`` and ``must_sweep_step_pct``.
    curtailment_series : np.ndarray | None, keyword-only
        Optional 8760-element ONS curtailment array.
    solar_year_idx : int, keyword-only
        Solar year index passed to the dispatch engine.

    Returns
    -------
    MustOptimizationResult
        Optimal reduction plus the full sensitivity sweep.

    Raises
    ------
    ValueError
        If ``mwac`` is not strictly positive.
    """
    mwac = params.mwac
    if not (mwac > 0.0):
        raise ValueError(f"ERRO: mwac={mwac} deve ser > 0 para otimizar MUST.")

    tust = params.tust_brl_per_kw_month
    fractions = _sweep_fractions(params.must_sweep_max_pct, params.must_sweep_step_pct)

    sweep: list[MustEvaluationPoint] = []
    baseline_net_balance: float | None = None
    for pct in fractions:
        must_mw = mwac * (1.0 - pct)
        dispatch = simulate_scenario(
            solar,
            prices,
            scenario,
            params,
            curtailment_series=curtailment_series,
            solar_year_idx=solar_year_idx,
            must_mw=must_mw,
        )
        econ = compute_scenario_economics(solar, prices, scenario, dispatch, params)
        net_balance_com = econ.net_balance_com_bess_brl
        if pct == 0.0:
            baseline_net_balance = net_balance_com
        # Baseline is always the first (pct == 0.0) grid point.
        assert baseline_net_balance is not None, "sweep must start at pct=0.0"

        delta_must_mw = mwac * pct
        tust_savings = tust_annual_savings_brl(
            tust_brl_per_kw_month=tust, delta_must_mw=delta_must_mw
        )
        net_balance_delta = net_balance_com - baseline_net_balance
        sweep.append(
            MustEvaluationPoint(
                reduction_pct=pct,
                must_mw=must_mw,
                delta_must_mw=delta_must_mw,
                tust_savings_brl_per_yr=tust_savings,
                net_balance_com_brl=net_balance_com,
                net_balance_delta_vs_baseline_brl=net_balance_delta,
                net_benefit_brl_per_yr=tust_savings + net_balance_delta,
                curtailment_lost_mwh=float(np.sum(dispatch.curtailment_lost_mwh)),
            )
        )

    best = max(sweep, key=lambda p: p.net_benefit_brl_per_yr)
    tust_is_default = tust == DEFAULT_TUST_BRL_PER_KW_MONTH
    return MustOptimizationResult(
        scenario_label=scenario.label,
        duration_h=scenario.duration_h,
        mwac=mwac,
        tust_brl_per_kw_month=tust,
        tust_is_default=tust_is_default,
        optimal_reduction_pct=best.reduction_pct,
        optimal_must_mw=best.must_mw,
        optimal_net_benefit_brl_per_yr=best.net_benefit_brl_per_yr,
        sweep=sweep,
    )


def write_must_reduction_dispatch_csv(
    *,
    year: int,
    duration_h: int,
    optimal_reduction_pct: float,
    must_mw: float,
    mwac: float,
    dispatch,
    pld: np.ndarray,
    output_dir: str | Path,
) -> Path:
    """Write the hourly (8760h) dispatch under the optimal MUST cap to CSV.

    Parameters
    ----------
    year : int
        Backtest year of the scenario.
    duration_h : int
        BESS duration in hours.
    optimal_reduction_pct : float
        Optimal MUST reduction fraction (0-1).
    must_mw : float
        MUST injection cap in MW under the optimum.
    mwac : float
        Project AC power in MW (initial MUST).
    dispatch : DispatchResult
        Dispatch result simulated under ``must_mw``.
    pld : np.ndarray
        Hourly PLD in R$/MWh, shape ``(8760,)``.
    output_dir : str | Path
        Directory where the CSV is written.

    Returns
    -------
    Path
        Path to the written CSV file.
    """
    import pandas as pd

    n = len(dispatch.grid_injection_mwh)
    available = (
        dispatch.curtailment_total_available_mwh
        if dispatch.curtailment_total_available_mwh is not None
        else dispatch.curtailment_mwh
    )
    recovered = (
        dispatch.curtailment_recovered_mwh
        if dispatch.curtailment_recovered_mwh is not None
        else np.maximum(0.0, available - dispatch.curtailment_lost_mwh)
    )
    df = pd.DataFrame(
        {
            "hora": np.arange(n, dtype=int),
            "pld_brl_per_mwh": pld[:n],
            "must_mw": np.full(n, must_mw),
            "injecao_rede_mwh": dispatch.grid_injection_mwh,
            "carga_bess_mwh": dispatch.charge_mwh,
            "descarga_bess_mwh": dispatch.discharge_mwh,
            "soc_mwh": dispatch.soc_mwh,
            "curtailment_disponivel_mwh": available,
            "curtailment_absorvido_bess_mwh": recovered,
            "curtailment_perdido_mwh": dispatch.curtailment_lost_mwh,
            "deficit_mwh": dispatch.deficit_mwh,
            "deficit_residual_mwh": dispatch.residual_deficit_mwh,
        }
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    pct_slug = f"{optimal_reduction_pct * 100:.0f}pct"
    csv_path = output_path / f"must_reduction_{year}_{duration_h}h_{pct_slug}.csv"
    df.to_csv(csv_path, index=False)
    return csv_path
