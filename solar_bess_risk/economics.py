"""Economic metrics: LCOS, revenue, payback, scenario results.

Functions
---------
compute_incremental_revenue(dispatch, prices, rte_pct) -> float
compute_lcos(bess_cfg, dispatch, params) -> float | None
compute_payback(capex_brl, revenue_brl_yr) -> float | None
compute_scenario_result(bess_cfg, dispatch, prices, params) -> ScenarioResult
compute_payback_sensitivity(base_result, prices, params) -> np.ndarray
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from solar_bess_risk.config import (
    HOURS_PER_YEAR,
    LCOS_NOT_COMPUTABLE,
    PAYBACK_NOT_ACHIEVABLE,
    SimulationParams,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.simulation import BESSConfig, DispatchResult


@dataclass
class ScenarioResult:
    """Scalar annual metrics for one (ILR, BESS %, duration) scenario.

    Parameters
    ----------
    scenario_id : tuple[float, float, float]
        ``(ilr, bess_size_ratio_pct, duration_h)``.
    curtailment_without_bess_mwh_yr : float
        Total curtailment without BESS in MWh/yr.
    curtailment_with_bess_mwh_yr : float
        Total curtailment with BESS in MWh/yr.
    curtailment_avoided_pct : float
        Percentage of curtailment avoided.
    effective_cf_pct : float
        Effective capacity factor in %.
    equivalent_cycles_yr : float
        Equivalent BESS cycles per year.
    incremental_revenue_brl_yr : float
        Incremental annual revenue in BRL/yr.
    energy_from_curtail_mwh_yr : float
        Annual energy absorbed from curtailment in MWh/yr.
    energy_from_grid_mwh_yr : float
        Annual energy charged from grid top-up in MWh/yr.
    lcos_brl_per_mwh : float | None
        LCOS in BRL/MWh; None if not computable.
    payback_yr : float | None
        Simple payback in years; None if not achievable.
    top_up_hour_slots : list[str]
        Grid top-up hour slots as HH:00 strings.
    """

    scenario_id: tuple[float, float, float]
    curtailment_without_bess_mwh_yr: float
    curtailment_with_bess_mwh_yr: float
    curtailment_avoided_pct: float
    effective_cf_pct: float
    equivalent_cycles_yr: float
    incremental_revenue_brl_yr: float
    energy_from_curtail_mwh_yr: float
    energy_from_grid_mwh_yr: float
    lcos_brl_per_mwh: float | None
    payback_yr: float | None
    top_up_hour_slots: list[str]

    @property
    def lcos_display(self) -> str:
        """Display string for LCOS."""
        if self.lcos_brl_per_mwh is None:
            return LCOS_NOT_COMPUTABLE
        return f"{self.lcos_brl_per_mwh:,.2f}"

    @property
    def payback_display(self) -> str:
        """Display string for payback."""
        if self.payback_yr is None:
            return PAYBACK_NOT_ACHIEVABLE
        return f"{self.payback_yr:,.1f}"


def compute_incremental_revenue(
    dispatch: DispatchResult,
    prices: PriceProfile,
    rte_pct: float,
) -> float:
    """Compute incremental annual revenue from curtailment charging.

    Parameters
    ----------
    dispatch : DispatchResult
        Hour-by-hour dispatch results.
    prices : PriceProfile
        Hourly price profile.
    rte_pct : float
        Round-trip efficiency in %.

    Returns
    -------
    float
        Annual revenue in BRL/yr.
    """
    rte = rte_pct / 100.0
    return float(
        np.sum(dispatch.charge_curtail_mwh * prices.prices_brl_per_mwh * rte)
    )


def compute_lcos(
    bess_cfg: BESSConfig,
    dispatch: DispatchResult,
    params: SimulationParams,
) -> float | None:
    """Compute Levelized Cost of Storage (LCOS).

    Parameters
    ----------
    bess_cfg : BESSConfig
        BESS configuration.
    dispatch : DispatchResult
        Hour-by-hour dispatch results.
    params : SimulationParams
        Simulation parameters.

    Returns
    -------
    float | None
        LCOS in BRL/MWh, or None if denominator is zero.
    """
    e_y1 = float(np.sum(dispatch.discharge_mwh))
    if e_y1 <= 0:
        return None

    d = params.degradation_pct_yr / 100.0
    r = params.discount_rate_pct / 100.0
    n = params.useful_life_yr

    denominator = sum(
        e_y1 * (1 - d) ** (y - 1) / (1 + r) ** y for y in range(1, n + 1)
    )

    if denominator <= 0:
        return None

    return bess_cfg.capex_brl / denominator


def compute_payback(capex_brl: float, revenue_brl_yr: float) -> float | None:
    """Compute simple payback period.

    Parameters
    ----------
    capex_brl : float
        BESS CAPEX in BRL.
    revenue_brl_yr : float
        Annual incremental revenue in BRL/yr.

    Returns
    -------
    float | None
        Payback in years, or None if revenue ≤ 0.
    """
    if revenue_brl_yr <= 0:
        return None
    return capex_brl / revenue_brl_yr


def compute_scenario_result(
    bess_cfg: BESSConfig,
    dispatch: DispatchResult,
    prices: PriceProfile,
    params: SimulationParams,
) -> ScenarioResult:
    """Compute all scalar metrics for one scenario.

    Parameters
    ----------
    bess_cfg : BESSConfig
        BESS configuration.
    dispatch : DispatchResult
        Hour-by-hour dispatch results.
    prices : PriceProfile
        Hourly price profile.
    params : SimulationParams
        Simulation parameters.

    Returns
    -------
    ScenarioResult
        Complete scenario metrics.
    """
    rte = params.rte_pct / 100.0

    curtail_without = float(np.sum(dispatch.curtailment_without_bess_mwh))
    curtail_with = float(np.sum(dispatch.curtailment_with_bess_mwh))

    if curtail_without > 0:
        avoided_pct = (1.0 - curtail_with / curtail_without) * 100.0
    else:
        avoided_pct = 0.0

    total_discharge_to_grid = float(np.sum(dispatch.discharge_mwh)) * rte
    total_curtail_charged = float(np.sum(dispatch.charge_curtail_mwh))
    total_grid_charged = float(np.sum(dispatch.charge_grid_mwh))

    # Effective CF: BESS net contribution = discharge*rte - charge_grid
    # Full plant CF (including solar base) is computed when the profile is available
    # in the end-to-end wiring. Here we track the BESS delta.
    grid_injection_mwh = max(total_discharge_to_grid - total_grid_charged, 0.0)
    effective_cf = grid_injection_mwh / HOURS_PER_YEAR * 100.0

    # Equivalent cycles
    if bess_cfg.energy_capacity_mwh > 0:
        equiv_cycles = float(np.sum(dispatch.discharge_mwh)) / bess_cfg.energy_capacity_mwh
    else:
        equiv_cycles = 0.0

    revenue = compute_incremental_revenue(dispatch, prices, params.rte_pct)
    lcos = compute_lcos(bess_cfg, dispatch, params)
    payback = compute_payback(bess_cfg.capex_brl, revenue)

    # Top-up hour slots: convert hour indices to HH:00 strings
    hour_of_day_set = sorted(set(h % 24 for h in dispatch.top_up_hours))
    top_up_slots = [f"{hod:02d}:00" for hod in hour_of_day_set]

    return ScenarioResult(
        scenario_id=(bess_cfg.ilr, bess_cfg.bess_size_ratio_pct, bess_cfg.duration_h),
        curtailment_without_bess_mwh_yr=curtail_without,
        curtailment_with_bess_mwh_yr=curtail_with,
        curtailment_avoided_pct=avoided_pct,
        effective_cf_pct=effective_cf,
        equivalent_cycles_yr=equiv_cycles,
        incremental_revenue_brl_yr=revenue,
        energy_from_curtail_mwh_yr=total_curtail_charged,
        energy_from_grid_mwh_yr=total_grid_charged,
        lcos_brl_per_mwh=lcos,
        payback_yr=payback,
        top_up_hour_slots=top_up_slots,
    )


def compute_payback_sensitivity(
    base_result: ScenarioResult,
    prices: PriceProfile,
    params: SimulationParams,
) -> np.ndarray:
    """Compute payback sensitivity over 10×10 grid of price × CAPEX.

    Parameters
    ----------
    base_result : ScenarioResult
        Base scenario result.
    prices : PriceProfile
        Price profile (base price = mean of PLD array).
    params : SimulationParams
        Simulation parameters.

    Returns
    -------
    np.ndarray
        10×10 array of payback values (np.inf where not achievable).
    """
    base_price = float(np.mean(prices.prices_brl_per_mwh))
    base_capex = params.capex_usd_per_kwh

    price_factors = np.linspace(0.5, 1.5, 10)
    capex_factors = np.linspace(0.5, 1.5, 10)

    grid = np.full((10, 10), np.inf, dtype=np.float64)

    # Base energy from curtailment (MWh) — used for revenue scaling
    base_energy = base_result.energy_from_curtail_mwh_yr
    rte = params.rte_pct / 100.0

    for i, pf in enumerate(price_factors):
        for j, cf in enumerate(capex_factors):
            adjusted_price = base_price * pf
            adjusted_capex = base_capex * cf
            revenue = base_energy * adjusted_price * rte
            capex_brl = (
                adjusted_capex
                * params.usd_brl_rate
                * base_result.scenario_id[1]  # bess_pct
                / 100.0
                * base_energy  # approximate sizing
                * 1000  # MWh -> kWh
            )
            if revenue > 0 and capex_brl > 0:
                grid[i, j] = capex_brl / revenue
            else:
                grid[i, j] = np.inf

    return grid
