"""Hour-by-hour BESS dispatch engine.

Functions
---------
compute_annual_solar_energy_no_bess(profile, ilr) -> float
simulate_scenario(bess_cfg, solar, prices, params) -> DispatchResult
simulate_all_scenarios(params, solar, prices, progress_cb) -> list[DispatchResult]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile


class SimulationConstraintError(Exception):
    """Raised when a post-simulation SoC bound assertion fails."""


@dataclass
class BESSConfig:
    """Computed sizing for a single (ILR, BESS size ratio, duration) scenario.

    Parameters
    ----------
    energy_capacity_mwh : float
        BESS energy capacity in MWh.
    rated_power_mw : float
        BESS rated power in MW.
    capex_brl : float
        BESS CAPEX in BRL.
    duration_h : float
        Storage duration in hours.
    ilr : float
        Inverter loading ratio.
    bess_size_ratio_pct : float
        BESS size as % of annual solar energy without BESS.
    """

    energy_capacity_mwh: float
    rated_power_mw: float
    capex_brl: float
    duration_h: float
    ilr: float
    bess_size_ratio_pct: float


@dataclass
class DispatchResult:
    """Hour-by-hour simulation output for one scenario.

    Parameters
    ----------
    soc_mwh : np.ndarray
        State of charge at end of each hour, shape ``(8760,)``.
    charge_curtail_mwh : np.ndarray
        Energy charged from curtailment per hour.
    charge_grid_mwh : np.ndarray
        Energy charged from grid generation (top-up) per hour.
    discharge_mwh : np.ndarray
        Energy discharged per hour.
    curtailment_with_bess_mwh : np.ndarray
        Residual curtailment per hour after BESS.
    curtailment_without_bess_mwh : np.ndarray
        Curtailment per hour without BESS.
    top_up_hours : list[int]
        Hour indices selected for grid top-up charging.
    """

    soc_mwh: np.ndarray
    charge_curtail_mwh: np.ndarray
    charge_grid_mwh: np.ndarray
    discharge_mwh: np.ndarray
    curtailment_with_bess_mwh: np.ndarray
    curtailment_without_bess_mwh: np.ndarray
    top_up_hours: list[int]


def compute_annual_solar_energy_no_bess(
    profile: SolarProfile, ilr: float
) -> float:
    """Compute annual solar energy without BESS for a given ILR.

    Parameters
    ----------
    profile : SolarProfile
        Solar generation profile.
    ilr : float
        Inverter loading ratio.

    Returns
    -------
    float
        Annual energy in MWh clipped at 1.0 MWac.
    """
    return float(np.sum(np.minimum(profile.generation_mw * ilr, 1.0)))


def simulate_scenario(
    bess_cfg: BESSConfig,
    solar: SolarProfile,
    prices: PriceProfile,
    params: SimulationParams,
) -> DispatchResult:
    """Simulate one BESS scenario hour-by-hour for 8,760 hours.

    Parameters
    ----------
    bess_cfg : BESSConfig
        BESS sizing for this scenario.
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly price profile.
    params : SimulationParams
        Simulation parameters.

    Returns
    -------
    DispatchResult
        Hour-by-hour results.

    Raises
    ------
    SimulationConstraintError
        If post-simulation SoC bounds are violated.
    """
    energy_cap = bess_cfg.energy_capacity_mwh
    rated_power = bess_cfg.rated_power_mw
    rte = params.rte_pct / 100.0
    min_soc_threshold = (params.min_soc_threshold_pct / 100.0) * energy_cap
    injection_floor = params.min_injection_floor_mw
    ilr = bess_cfg.ilr

    # Pre-compute DC generation and curtailment arrays
    solar_dc_mw = solar.generation_mw * ilr
    ac_mw = np.minimum(solar_dc_mw, 1.0)
    curtailment_without_bess = np.maximum(solar_dc_mw - 1.0, 0.0)

    # Output arrays
    soc = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    charge_curtail = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    charge_grid = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    discharge = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    curtailment_with_bess = np.copy(curtailment_without_bess)

    top_up_hours: list[int] = []
    # Track which hours are marked for top-up in advance
    top_up_scheduled: set[int] = set()

    if energy_cap <= 0 or rated_power <= 0:
        # BESS=0% — no dispatch
        return DispatchResult(
            soc_mwh=soc,
            charge_curtail_mwh=charge_curtail,
            charge_grid_mwh=charge_grid,
            discharge_mwh=discharge,
            curtailment_with_bess_mwh=curtailment_with_bess,
            curtailment_without_bess_mwh=curtailment_without_bess,
            top_up_hours=[],
        )

    current_soc = 0.0
    price_arr = prices.prices_brl_per_mwh

    for h in range(HOURS_PER_YEAR):
        curtail_h = curtailment_without_bess[h]

        if curtail_h > 0:
            # Curtailment charging (primary)
            delta_charge = min(curtail_h, rated_power, energy_cap - current_soc)
            current_soc += delta_charge
            charge_curtail[h] = delta_charge
            curtailment_with_bess[h] = curtail_h - delta_charge

            # If this hour is also scheduled for top-up AND there's still room
            if h in top_up_scheduled and current_soc < energy_cap:
                # Additional grid top-up (curtailment hour = Priority 1,
                # injection floor is not binding since solar > 1 MWac)
                grid_charge = min(rated_power - delta_charge, energy_cap - current_soc)
                if grid_charge > 0:
                    current_soc += grid_charge
                    charge_grid[h] = grid_charge
                    top_up_hours.append(h)

        elif h in top_up_scheduled:
            # Grid top-up charging (scheduled, no curtailment this hour)
            # Enforce injection floor: net injection = ac_mw[h] - grid_charge >= floor
            max_from_floor = max(0.0, ac_mw[h] - injection_floor)
            grid_charge = min(rated_power, energy_cap - current_soc, max_from_floor)
            if grid_charge > 0:
                current_soc += grid_charge
                charge_grid[h] = grid_charge
                top_up_hours.append(h)

        elif current_soc > 0:
            # Discharge
            delta_discharge = min(rated_power, current_soc)
            current_soc -= delta_discharge
            discharge[h] = delta_discharge

        soc[h] = current_soc

        # End-of-day top-up scheduling (at hour 23 of each day)
        if h % 24 == 23 and current_soc < min_soc_threshold:
            # Schedule top-up for next day
            next_day_start = h + 1
            next_day_end = min(h + 25, HOURS_PER_YEAR)
            if next_day_start >= HOURS_PER_YEAR:
                continue

            # Two-priority window selection
            # Priority 1: next-day hours with curtailment
            priority1 = []
            priority2_candidates = []
            for nh in range(next_day_start, next_day_end):
                if curtailment_without_bess[nh] > 0:
                    priority1.append(nh)
                else:
                    priority2_candidates.append(nh)

            # Priority 2: remaining hours ranked by PLD price ascending
            priority2 = sorted(priority2_candidates, key=lambda idx: price_arr[idx])

            candidates = priority1 + priority2

            # Select hours until target SoC is reachable
            needed = min_soc_threshold - current_soc
            for ch in candidates:
                if needed <= 0:
                    break
                top_up_scheduled.add(ch)
                # Estimate charge per hour
                est_charge = min(rated_power, energy_cap - current_soc)
                needed -= est_charge

    # Post-simulation SoC bound assertion
    if np.any(soc < -1e-10) or np.any(soc > energy_cap + 1e-10):
        raise SimulationConstraintError(
            f"SoC constraint violated: min={soc.min():.6f}, max={soc.max():.6f}, "
            f"capacity={energy_cap:.6f}"
        )

    return DispatchResult(
        soc_mwh=soc,
        charge_curtail_mwh=charge_curtail,
        charge_grid_mwh=charge_grid,
        discharge_mwh=discharge,
        curtailment_with_bess_mwh=curtailment_with_bess,
        curtailment_without_bess_mwh=curtailment_without_bess,
        top_up_hours=top_up_hours,
    )


def simulate_all_scenarios(
    params: SimulationParams,
    solar: SolarProfile,
    prices: PriceProfile,
    progress_cb: Callable[[int, int, str], None] | None = None,
) -> list[tuple[BESSConfig, DispatchResult]]:
    """Simulate all scenarios defined by params.

    Parameters
    ----------
    params : SimulationParams
        Simulation parameters.
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Price profile.
    progress_cb : callable, optional
        Callback ``(current, total, label)`` for progress reporting.

    Returns
    -------
    list[tuple[BESSConfig, DispatchResult]]
        List of (config, result) tuples for all scenarios.
    """
    results: list[tuple[BESSConfig, DispatchResult]] = []
    total = params.total_scenarios
    idx = 0

    for ilr in params.ilr_values:
        annual_no_bess = compute_annual_solar_energy_no_bess(solar, ilr)

        for bess_pct in params.bess_size_ratios_pct:
            for dur_h in params.storage_durations_h:
                idx += 1
                energy_cap = (bess_pct / 100.0) * annual_no_bess
                rated_power = energy_cap / dur_h if dur_h > 0 and energy_cap > 0 else 0.0
                capex_brl = energy_cap * 1000 * params.capex_usd_per_kwh * params.usd_brl_rate

                cfg = BESSConfig(
                    energy_capacity_mwh=energy_cap,
                    rated_power_mw=rated_power,
                    capex_brl=capex_brl,
                    duration_h=dur_h,
                    ilr=ilr,
                    bess_size_ratio_pct=bess_pct,
                )

                label = f"ILR={ilr}, BESS={bess_pct}%, dur={dur_h}h"
                if progress_cb:
                    progress_cb(idx, total, label)

                result = simulate_scenario(cfg, solar, prices, params)
                results.append((cfg, result))

    return results
