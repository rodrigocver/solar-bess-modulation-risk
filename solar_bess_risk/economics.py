"""Economic metrics: exposure, savings, payback, coverage (v2).

Functions
---------
compute_scenario_economics(solar, prices, scenario, dispatch, params) -> ScenarioResult
compute_all_scenarios(solar, prices, dispatch_pairs, params) -> list[ScenarioResult]
build_top10_peak_hours(results, prices) -> pd.DataFrame
payback_display(result) -> str
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR, PAYBACK_NOT_ACHIEVABLE, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.risk_metrics import (
    compute_daily_delta,
    compute_delta_sensitivity,
    compute_var_cvar,
)
from solar_bess_risk.simulation import DispatchResult, ScenarioDefinition


@dataclass
class ScenarioResult:
    """Scalar annual metrics for one scenario (A, B, or C).

    Parameters
    ----------
    scenario : ScenarioDefinition
        The source scenario definition.
    dispatch : DispatchResult
        Full hourly dispatch time-series.
    fc : float
        Capacity factor.
    garantia_fisica_mw : float
        Physical guarantee in MW.
    bess_energy_mwh : float
        BESS energy capacity in MWh.
    bess_power_mw : float
        BESS rated power in MW.
    capex_brl : float
        BESS CAPEX in BRL.
    annual_exposure_without_bess_brl : float
        Annual financial exposure without BESS in BRL/yr.
    annual_exposure_with_bess_brl : float
        Annual financial exposure with BESS in BRL/yr.
    annual_savings_brl : float
        First-year net benefit from BESS in BRL/yr after fixed O&M.
    annual_gross_savings_brl : float
        First-year gross benefit before fixed O&M, measured as the signed
        net-balance improvement with BESS versus without BESS.
    annual_o_and_m_brl : float
        Fixed annual O&M cost in BRL/yr.
    lifetime_net_savings_brl : float
        Sum of net savings over useful life with degradation.
    payback_years : float | None
        Simple payback in years; None if savings <= 0.
    coverage_pct : float
        Energy coverage percentage (0-100): how much deficit MWh the BESS eliminates.
    reducao_exposicao_pct : float
        Financial exposure reduction percentage (0-100).
    deficit_mwh_sem_bess : float
        Total annual deficit MWh without BESS (all hours).
    deficit_mwh_com_bess : float
        Total annual deficit MWh with BESS (all hours).
    daily_net_sem_brl : np.ndarray
        Daily net balance without BESS, shape (365,), in BRL.
    daily_net_com_brl : np.ndarray
        Daily net balance with BESS, shape (365,), in BRL.
    var_95_sem_bess_brl : float
        VaR 95% of the daily net balance distribution without BESS (BRL/day).
        Represents the worst-day loss threshold at 5th percentile.
    cvar_95_sem_bess_brl : float
        CVaR 95% without BESS: mean daily loss of the worst 5% of days (BRL/day).
    var_95_com_bess_brl : float
        VaR 95% of the daily net balance distribution with BESS (BRL/day).
    cvar_95_com_bess_brl : float
        CVaR 95% with BESS: mean daily loss of the worst 5% of days (BRL/day).
    risk_constraint_met : bool
        True when CVaR with BESS >= CVaR without BESS — i.e., adding the BESS
        does not worsen the tail risk relative to the purely solar portfolio.
    daily_delta : np.ndarray
        Daily spread (BRL/MWh): mean(PLD at peak hours) - mean(PLD at off-peak).
        Shape (365,). Positive = market paid premium at peak hours.
    worst5pct_summary : dict
        Portfolio performance summary on the 5% worst delta (flat-market) days.
    best5pct_summary : dict
        Portfolio performance summary on the 5% best delta (high-spread) days.
    """

    scenario: ScenarioDefinition
    dispatch: DispatchResult
    fc: float
    garantia_fisica_mw: float
    bess_energy_mwh: float
    bess_power_mw: float
    capex_brl: float
    annual_exposure_without_bess_brl: float
    annual_exposure_with_bess_brl: float
    annual_savings_brl: float
    annual_gross_savings_brl: float
    annual_o_and_m_brl: float
    lifetime_net_savings_brl: float
    payback_years: float | None
    coverage_pct: float
    reducao_exposicao_pct: float
    deficit_mwh_sem_bess: float
    deficit_mwh_com_bess: float
    net_balance_sem_bess_brl: float
    """Annual signed net balance without BESS: sum((gen - gf) × PLD).

    Positive = annual solar surplus revenue; negative = net annual exposure.
    Captures the fact that daytime surplus partially offsets nighttime deficit.
    """
    net_balance_com_bess_brl: float
    """Annual signed net balance with BESS: sum((grid_injection - gf) × PLD).

    Reflects the BESS impact on the net position (discharge adds to injection
    in expensive hours; useful-solar charging reduces injection in cheap hours).
    """
    net_balance_daily_sem_bess_brl: float
    """Mean daily signed net balance without BESS (net_balance_sem / 365)."""
    net_balance_daily_com_bess_brl: float
    """Mean daily signed net balance with BESS (net_balance_com / 365)."""
    net_balance_delta_brl: float
    """Annual signed net-balance improvement from BESS: with BESS minus without BESS."""
    # --- Tail-risk metrics (VaR/CVaR at 95%) ---
    daily_net_sem_brl: np.ndarray = None  # type: ignore[assignment]
    daily_net_com_brl: np.ndarray = None  # type: ignore[assignment]
    var_95_sem_bess_brl: float = 0.0
    cvar_95_sem_bess_brl: float = 0.0
    var_95_com_bess_brl: float = 0.0
    cvar_95_com_bess_brl: float = 0.0
    risk_constraint_met: bool = False
    daily_delta: np.ndarray = None  # type: ignore[assignment]
    worst5pct_summary: dict = None  # type: ignore[assignment]
    best5pct_summary: dict = None  # type: ignore[assignment]


def payback_display(result: ScenarioResult) -> str:
    """Return display string for payback years.

    Parameters
    ----------
    result : ScenarioResult
        Scenario result.

    Returns
    -------
    str
        Formatted payback or "não atingível".
    """
    if result.payback_years is None:
        return PAYBACK_NOT_ACHIEVABLE
    return f"{result.payback_years:.1f}"


def compute_scenario_economics(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    dispatch: DispatchResult,
    params: SimulationParams,
) -> ScenarioResult:
    """Compute all economic metrics for one scenario.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly price profile.
    scenario : ScenarioDefinition
        Scenario sizing and peak hours.
    dispatch : DispatchResult
        Hour-by-hour dispatch results.
    params : SimulationParams
        Simulation parameters.

    Returns
    -------
    ScenarioResult
        Complete scenario metrics.
    """
    gf = solar.garantia_fisica_mw
    price_arr = prices.prices_brl_per_mwh

    # Exposure without BESS: deficit (all hours) × PLD
    exposure_without = float(np.sum(dispatch.deficit_mwh * price_arr))
    # Exposure with BESS: residual deficit (all hours) × PLD
    exposure_with = float(np.sum(dispatch.residual_deficit_mwh * price_arr))

    # Coverage metrics (spec §6) — over all 8760 hours
    deficit_mwh_sem_bess = float(np.sum(dispatch.deficit_mwh))
    deficit_mwh_com_bess = float(np.sum(dispatch.residual_deficit_mwh))

    if deficit_mwh_sem_bess > 0:
        coverage = (1 - deficit_mwh_com_bess / deficit_mwh_sem_bess) * 100
    else:
        coverage = 0.0

    if exposure_without > 0:
        reducao_exposicao = (1 - exposure_with / exposure_without) * 100
    else:
        reducao_exposicao = 0.0

    # --- Net balance (signed position) ---
    # Sem BESS uses the inverter-limited series and only external ONS curtailment.
    # Com BESS uses the executed simulation grid injection, avoiding double
    # counting curtailment charge versus direct solar charge.
    gen_lim = solar.generation_lim_mw if solar.generation_lim_mw is not None else solar.generation_mw
    ons_curt = dispatch.ons_curtailment_mwh

    injection_sem = gen_lim - ons_curt
    injection_com = dispatch.grid_injection_mwh

    net_hourly_sem = (injection_sem - gf) * price_arr
    net_hourly_com = (injection_com - gf) * price_arr

    net_balance_sem = float(np.sum(net_hourly_sem))
    net_balance_com = float(np.sum(net_hourly_com))
    net_balance_delta = net_balance_com - net_balance_sem

    gross_savings = net_balance_delta
    annual_o_and_m = scenario.capex_brl * params.bess_o_and_m_pct_capex
    first_year_net_savings = gross_savings - annual_o_and_m
    lifetime_net_savings, payback = _discounted_cashflow_payback(
        capex_brl=scenario.capex_brl,
        gross_savings_brl=gross_savings,
        annual_o_and_m_brl=annual_o_and_m,
        discount_rate=params.lcoe_discount_rate,
        useful_life_years=params.useful_life_years,
    )

    # Full 365-day daily distributions (used for VaR/CVaR and sensitivity)
    daily_net_sem_arr = net_hourly_sem.reshape(365, 24).sum(axis=1)
    daily_net_com_arr = net_hourly_com.reshape(365, 24).sum(axis=1)

    # Mean over 365 daily sums (same total, expressed as daily average)
    net_daily_sem = float(daily_net_sem_arr.mean())
    net_daily_com = float(daily_net_com_arr.mean())

    # --- Tail-risk metrics (VaR / CVaR at 95%) ---
    var_sem, cvar_sem = compute_var_cvar(daily_net_sem_arr)
    var_com, cvar_com = compute_var_cvar(daily_net_com_arr)
    # Risk constraint: CVaR with BESS must be >= CVaR without BESS
    # (less-negative = less tail risk; BESS should not amplify tail losses via idle CAPEX debt)
    risk_constraint_met = cvar_com >= cvar_sem

    # --- Delta sensitivity analysis ---
    daily_delta_arr = compute_daily_delta(price_arr, scenario.peak_hours)
    sensitivity = compute_delta_sensitivity(
        daily_delta_arr, daily_net_sem_arr, daily_net_com_arr
    )

    return ScenarioResult(
        scenario=scenario,
        dispatch=dispatch,
        fc=solar.fc,
        garantia_fisica_mw=gf,
        bess_energy_mwh=scenario.bess_energy_mwh,
        bess_power_mw=scenario.bess_power_mw,
        capex_brl=scenario.capex_brl,
        annual_exposure_without_bess_brl=exposure_without,
        annual_exposure_with_bess_brl=exposure_with,
        annual_savings_brl=first_year_net_savings,
        annual_gross_savings_brl=gross_savings,
        annual_o_and_m_brl=annual_o_and_m,
        lifetime_net_savings_brl=lifetime_net_savings,
        payback_years=payback,
        coverage_pct=coverage,
        reducao_exposicao_pct=reducao_exposicao,
        deficit_mwh_sem_bess=deficit_mwh_sem_bess,
        deficit_mwh_com_bess=deficit_mwh_com_bess,
        net_balance_sem_bess_brl=net_balance_sem,
        net_balance_com_bess_brl=net_balance_com,
        net_balance_daily_sem_bess_brl=net_daily_sem,
        net_balance_daily_com_bess_brl=net_daily_com,
        net_balance_delta_brl=net_balance_delta,
        # Tail-risk fields
        daily_net_sem_brl=daily_net_sem_arr,
        daily_net_com_brl=daily_net_com_arr,
        var_95_sem_bess_brl=var_sem,
        cvar_95_sem_bess_brl=cvar_sem,
        var_95_com_bess_brl=var_com,
        cvar_95_com_bess_brl=cvar_com,
        risk_constraint_met=risk_constraint_met,
        daily_delta=daily_delta_arr,
        worst5pct_summary=sensitivity["worst"],
        best5pct_summary=sensitivity["best"],
    )


def _discounted_cashflow_payback(
    *,
    capex_brl: float,
    gross_savings_brl: float,
    annual_o_and_m_brl: float,
    discount_rate: float,
    useful_life_years: int,
) -> tuple[float, float | None]:
    """Return lifetime net savings and simple/nominal payback.

    Battery capacity fade is intentionally NOT modelled here with a fixed annual
    factor. Degradation is governed exclusively by the manufacturer SOH curve in
    ``projection.project_cashflows_with_rte`` (the canonical cashflow). This
    single-year helper therefore keeps gross savings flat. Payback is reported
    on a simple/nominal basis; discounting is reserved for LCOS.
    """
    cumulative = 0.0
    previous = 0.0
    for year in range(1, useful_life_years + 1):
        net = gross_savings_brl - annual_o_and_m_brl
        cumulative += net
        if cumulative >= capex_brl:
            if net <= 0:
                return cumulative, float(year)
            fraction = (capex_brl - previous) / net
            return cumulative, (year - 1) + fraction
        previous = cumulative
    return cumulative, None


def compute_all_scenarios(
    solar: SolarProfile,
    prices: PriceProfile,
    dispatch_pairs: list[tuple[ScenarioDefinition, DispatchResult]],
    params: SimulationParams,
) -> list[ScenarioResult]:
    """Compute economics for all scenarios.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly price profile.
    dispatch_pairs : list[tuple[ScenarioDefinition, DispatchResult]]
        Paired scenario definitions and dispatch results.
    params : SimulationParams
        Simulation parameters.

    Returns
    -------
    list[ScenarioResult]
        Economic results for each scenario.
    """
    return [
        compute_scenario_economics(solar, prices, scenario, dispatch, params)
        for scenario, dispatch in dispatch_pairs
    ]


def build_top10_peak_hours(
    results: list[ScenarioResult],
    prices: PriceProfile,
) -> pd.DataFrame:
    """Build top-10 peak hours table by highest PLD.

    Parameters
    ----------
    results : list[ScenarioResult]
        Scenario results (must be 3).
    prices : PriceProfile
        Hourly price profile.

    Returns
    -------
    pd.DataFrame
        10 rows with columns: hour_index, date, hour_of_day, pld_brl_per_mwh,
        plus per-scenario dispatch_mwh and residual_deficit_mwh.
    """
    # Union of all peak hours across scenarios
    all_peak_hours: set[int] = set()
    for r in results:
        all_peak_hours.update(r.scenario.peak_hours)

    # Find peak hour indices (hours where hour_of_day is in the union)
    peak_indices = [h for h in range(HOURS_PER_YEAR) if h % 24 in all_peak_hours]

    # Sort by PLD descending, take top 10
    peak_prices = prices.prices_brl_per_mwh[peak_indices]
    top10_positions = np.argsort(peak_prices)[::-1][:10]
    top10_hours = [peak_indices[p] for p in top10_positions]

    rows = []
    for h in top10_hours:
        day = h // 24 + 1
        hour_of_day = h % 24
        row = {
            "hour_index": h,
            "date": f"Dia {day}",
            "hour_of_day": hour_of_day,
            "pld_brl_per_mwh": prices.prices_brl_per_mwh[h],
        }
        for r in results:
            label = r.scenario.label
            row[f"dispatch_mwh_{label}"] = r.dispatch.discharge_mwh[h]
            row[f"residual_deficit_mwh_{label}"] = r.dispatch.residual_deficit_mwh[h]
        rows.append(row)

    return pd.DataFrame(rows)
