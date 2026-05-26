"""Hour-by-hour BESS dispatch engine (v2 — Garantia Física model).

Functions
---------
simulate_scenario(solar, prices, scenario, params) -> DispatchResult
simulate_all_scenarios(solar, prices, scenarios, params, progress_cb) -> list
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


@dataclass(frozen=True)
class ScenarioDefinition:
    """One of three fixed scenarios (A/B/C).

    Parameters
    ----------
    label : str
        Scenario label ("A", "B", or "C").
    peak_hours : frozenset[int]
        Hour-of-day indices considered peak.  When ``charge_mode == 3`` this
        field is ignored — discharge hours are derived from daily PLD ranking.
    duration_h : int
        BESS storage duration in hours.
    bess_power_mw : float
        BESS rated power in MW (= garantia_fisica_mw).
    bess_energy_mwh : float
        BESS energy capacity in MWh (= garantia_fisica_mw * duration_h).
    capex_brl : float
        BESS CAPEX in BRL.
    peak_hour_weights : dict[int, float] | None
        Fraction of each hour inside the guarantee window. Defaults to 1.0
        for every hour in ``peak_hours``.
    charge_mode : int
        0 = legacy (charge from surplus/curtailment, discharge during peak_hours).
        3 = price-aware: for each day, discharge in the ``duration_h`` hours
        with highest PLD; charge from free sources (curtailment + clipping) in
        all other hours, then fill remaining capacity with useful solar in the
        cheapest hours first.
    """

    label: str
    peak_hours: frozenset[int]
    duration_h: int
    bess_power_mw: float
    bess_energy_mwh: float
    capex_brl: float
    peak_hour_weights: dict[int, float] | None = None
    rte: float = 1.0
    charge_mode: int = 0


@dataclass
class DispatchResult:
    """Hour-by-hour simulation output for one scenario.

    Parameters
    ----------
    soc_mwh : np.ndarray
        State of charge at end of each hour, shape ``(8760,)``.
    charge_mwh : np.ndarray
        Energy charged per hour (solar excess + curtailment), shape ``(8760,)``.
    discharge_mwh : np.ndarray
        Energy discharged per hour, shape ``(8760,)``.
    grid_injection_mwh : np.ndarray
        Net power delivered to grid each hour, shape ``(8760,)``.
    deficit_mwh : np.ndarray
        max(0, garantia_fisica - generation) for ALL hours.
    residual_deficit_mwh : np.ndarray
        max(0, garantia_fisica - generation - discharge) for ALL hours.
    curtailment_mwh : np.ndarray
        Curtailment MW available at each hour, shape ``(8760,)``.
    curtailment_lost_mwh : np.ndarray
        Curtailment that could not be stored, shape ``(8760,)``.
    carga_nao_realizada_diaria_mwh : np.ndarray
        Daily missed cycle: bess_energy - actual daily discharge, shape ``(365,)``.
    """

    soc_mwh: np.ndarray
    charge_mwh: np.ndarray
    discharge_mwh: np.ndarray
    grid_injection_mwh: np.ndarray
    deficit_mwh: np.ndarray
    residual_deficit_mwh: np.ndarray
    curtailment_mwh: np.ndarray
    curtailment_lost_mwh: np.ndarray
    carga_nao_realizada_diaria_mwh: np.ndarray


def _drain_deadline_exclusive(hour_index: int, deadline_hour: int) -> int:
    """Return the first hour outside the current drain deadline window."""
    day_start = (hour_index // 24) * 24
    if hour_index % 24 < deadline_hour:
        return min(day_start + deadline_hour, HOURS_PER_YEAR)
    return min(day_start + 24 + deadline_hour, HOURS_PER_YEAR)


def _is_pld_ranked_discharge_hour(
    *,
    hour_index: int,
    current_soc_mwh: float,
    bess_power_mw: float,
    prices_brl_per_mwh: np.ndarray,
    curtailment_mwh: np.ndarray,
    blocked_charge_hours: set[int],
    deadline_hour: int,
) -> bool:
    """Choose drain hours by descending PLD within the current deadline window."""
    if current_soc_mwh <= 1e-10 or bess_power_mw <= 1e-10:
        return False

    deadline = _drain_deadline_exclusive(hour_index, deadline_hour)
    candidates = [
        h for h in range(hour_index, deadline)
        if curtailment_mwh[h] <= 1e-10 and h not in blocked_charge_hours
    ]
    if hour_index not in candidates:
        return False

    slots_needed = int(np.ceil((current_soc_mwh - 1e-10) / bess_power_mw))
    if slots_needed >= len(candidates):
        return True

    selected = sorted(
        candidates,
        key=lambda h: (-float(prices_brl_per_mwh[h]), h),
    )[:slots_needed]
    return hour_index in set(selected)


def _simulate_price_aware_dispatch(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    curtailment_series: np.ndarray | None = None,
) -> DispatchResult:
    """Price-aware day-ahead dispatch (charge_mode == 3).

    For each calendar day the algorithm:
    1. Identifies the ``duration_h`` hours with highest PLD as discharge hours.
    2. In all other hours, absorbs curtailment + solar surplus (clipping) at
       zero opportunity cost.
    3. Fills the remaining BESS capacity with useful solar (gen below GF) in
       cheapest-first order until the battery is full.
    4. Discharges in the expensive hours to cover the deficit there.

    A mandatory 1-hour gap is enforced between charge and discharge actions,
    including daily drain actions.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly PLD prices used to rank hours per day.
    scenario : ScenarioDefinition
        Scenario sizing; ``duration_h`` drives how many hours are selected
        as discharge hours per day.
    params : SimulationParams
        Simulation parameters (RTE comes from here unless overridden on scenario).
    curtailment_series : np.ndarray | None
        Optional 8760-element curtailment array.

    Returns
    -------
    DispatchResult
        Hour-by-hour dispatch results.
    """
    gf = solar.garantia_fisica_mw
    bess_power = scenario.bess_power_mw
    bess_energy = scenario.bess_energy_mwh
    duration_h = scenario.duration_h
    rte = scenario.rte if scenario.rte != 1.0 else params.bess_roundtrip_efficiency
    gen = solar.generation_mw
    price_arr = prices.prices_brl_per_mwh
    has_curtailment = curtailment_series is not None
    curtailment_arr_input = (
        np.maximum(0.0, curtailment_series)
        if has_curtailment
        else np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    )

    drain_deadline_hour = 5
    curtailment_arr_input = (
        np.maximum(0.0, curtailment_series)
        if has_curtailment
        else np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    )
    soc = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    charge = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    discharge = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    grid_inj = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    deficit = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    residual = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    curt_arr = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    curt_lost = np.zeros(HOURS_PER_YEAR, dtype=np.float64)

    current_soc = 0.0

    for day in range(365):
        start = day * 24
        day_pld = price_arr[start : start + 24]
        day_gen = gen[start : start + 24]
        day_curt = (
            np.maximum(0.0, curtailment_series[start : start + 24])
            if has_curtailment
            else np.zeros(24, dtype=np.float64)
        )

        if day == 0:
            current_soc = 0.0
            last_action: str = "idle"

        # ── Step 1: discharge hours = top-N by PLD ──────────────────────────
        discharge_locals: set[int] = set(
            int(h) for h in np.argsort(day_pld)[::-1][:duration_h]
        )
        all_charge_locals: list[int] = sorted(set(range(24)) - discharge_locals)

        # ── Step 1b: economic filter ──────────────────────────────────────────
        # Both surplus solar (gen > GF) and useful-solar fill (gen < GF) carry an
        # opportunity cost equal to their current-hour PLD. Store only when
        # rte × min_discharge_pld > PLD_h (h-rule).
        # Curtailment (ONS-mandated) has zero alternative value → always absorbed.
        min_discharge_pld = (
            min(float(day_pld[h]) for h in discharge_locals) if discharge_locals else 0.0
        )
        economic_fill_locals: set[int] = {
            h for h in all_charge_locals
            if rte * min_discharge_pld > float(day_pld[h])
        }

        # ── Step 2: pre-plan free charging (curtailment + surplus if h-rule passes) ─
        # Iterate in time order so we can track the simulated SoC evolution.
        # Charge rate is NOT capped by bess_power_mw; duration defines energy
        # capacity only. Each hour absorbs up to remaining SoC.
        temp_soc = current_soc
        free_plan: dict[int, float] = {}  # h_local → power [MW]

        for h_local in all_charge_locals:
            curt_h = float(day_curt[h_local])
            gen_h = float(day_gen[h_local])
            surplus_h = max(0.0, gen_h - gf)

            # Surplus solar passes through h-rule; curtailment is always free
            h_rule_ok_surplus = rte * min_discharge_pld > float(day_pld[h_local])
            effective_surplus = surplus_h if h_rule_ok_surplus else 0.0
            free_avail = curt_h + effective_surplus

            if free_avail < 1e-10:
                free_plan[h_local] = 0.0
                continue

            remaining_cap = bess_energy - temp_soc
            if remaining_cap < 1e-10:
                free_plan[h_local] = 0.0
                continue

            # No bess_power cap on charging — absorb all available up to remaining capacity
            ch_energy = min(free_avail * rte, remaining_cap)
            ch_power = ch_energy / rte

            free_plan[h_local] = ch_power
            temp_soc += ch_energy

        # ── Step 3: fill remaining capacity with useful solar (cheapest first) ─
        # Only hours that pass the h-rule (rte × min_pld_desc > pld_charge).
        solar_fill_plan: dict[int, float] = {h: 0.0 for h in all_charge_locals}
        needed = bess_energy - temp_soc

        if needed > 1e-10:
            sorted_cheap = sorted(economic_fill_locals, key=lambda h: day_pld[h])
            temp_soc_fill = temp_soc

            for h_local in sorted_cheap:
                if needed < 1e-10:
                    break

                gen_h = float(day_gen[h_local])
                useful_gen = min(gen_h, gf)  # solar available below GF
                if useful_gen < 1e-10:
                    continue

                remaining_cap = max(0.0, bess_energy - temp_soc_fill)

                # No bess_power cap — charging limited only by available gen and capacity
                ch_energy = min(useful_gen * rte, remaining_cap, needed)
                ch_power = ch_energy / rte

                if ch_power > 1e-10:
                    solar_fill_plan[h_local] = ch_power
                    temp_soc_fill += ch_energy
                    needed -= ch_energy

        # ── Step 4: forward pass — execute plan in time order ───────────────
        blocked_charge_hours = {
            start + h for h in all_charge_locals
            if free_plan.get(h, 0.0) > 1e-10 or solar_fill_plan.get(h, 0.0) > 1e-10
        }
        for h_local in range(24):
            h_global = start + h_local
            gen_h = float(day_gen[h_local])
            curt_h = float(day_curt[h_local])

            if has_curtailment:
                curt_arr[h_global] = curt_h

            # Deficit uses effective injection (gen minus curtailment)
            deficit[h_global] = max(0.0, gf - max(0.0, gen_h - curt_h))
            can_discharge = last_action != "charged"
            can_charge = last_action != "discharged"
            charge_h = 0.0
            discharge_h = 0.0

            if h_local in discharge_locals and curt_h <= 1e-10:
                # ─── Discharge hour ──────────────────────────────────────────
                # No charging during discharge hours: absorbing curtailment here
                # would inflate SoC beyond N×P, preventing full drain within the
                # N scheduled hours and causing carryover to the next day.
                curt_lost[h_global] = curt_h

                if current_soc > 1e-10 and can_discharge:
                    disch = min(bess_power, current_soc)
                    current_soc -= disch
                    discharge[h_global] = disch
                    discharge_h = disch

                grid_inj[h_global] = gen_h - curt_h + discharge[h_global]
                residual[h_global] = max(0.0, gf - grid_inj[h_global])

            elif (
                current_soc > 1e-10
                and can_discharge
                and curt_h <= 1e-10
                and free_plan.get(h_local, 0.0) <= 1e-10
                and solar_fill_plan.get(h_local, 0.0) <= 1e-10
                and _is_pld_ranked_discharge_hour(
                    hour_index=h_global,
                    current_soc_mwh=current_soc,
                    bess_power_mw=bess_power,
                    prices_brl_per_mwh=price_arr,
                    curtailment_mwh=curtailment_arr_input,
                    blocked_charge_hours=blocked_charge_hours,
                    deadline_hour=drain_deadline_hour,
                )
            ):
                # Daily drain: choose non-charge hours by descending PLD within
                # the deadline window, always capped by PCS.
                disch = min(bess_power, current_soc)
                current_soc -= disch
                discharge[h_global] = disch
                discharge_h = disch
                grid_inj[h_global] = gen_h - curt_h + disch
                residual[h_global] = max(0.0, deficit[h_global] - disch)

            elif can_charge:
                # ─── Charge hour ─────────────────────────────────────────────
                planned_free = free_plan.get(h_local, 0.0)
                planned_fill = solar_fill_plan.get(h_local, 0.0)

                # Execute free charge (curtailment + surplus if h-rule passed in plan)
                # No bess_power cap — absorb up to remaining capacity
                ch_free = 0.0
                if planned_free > 1e-10:
                    remaining_cap = bess_energy - current_soc
                    if remaining_cap > 1e-10:
                        actual_energy = min(planned_free * rte, remaining_cap)
                        ch_free = actual_energy / rte
                        current_soc += actual_energy

                # Track curtailment loss: curt absorbed up to ch_free capacity
                ch_curt_absorbed = min(curt_h, ch_free)
                curt_lost[h_global] = max(0.0, curt_h - ch_curt_absorbed)

                # Execute solar fill (only in economic_fill_locals hours)
                # No bess_power cap — charging limited only by plan and remaining capacity
                ch_fill = 0.0
                if planned_fill > 1e-10:
                    remaining_cap = bess_energy - current_soc
                    if remaining_cap > 1e-10:
                        actual_energy = min(planned_fill * rte, remaining_cap)
                        ch_fill = actual_energy / rte
                        current_soc += actual_energy

                charge[h_global] = ch_free + ch_fill
                charge_h = charge[h_global]

                # Grid injection: curtailment and solar-fill reduce injection;
                # free charge from surplus doesn't (already above GF).
                grid_inj[h_global] = max(0.0, gen_h - curt_h - ch_fill)
                residual[h_global] = max(0.0, gf - grid_inj[h_global])

            else:
                curt_lost[h_global] = curt_h
                grid_inj[h_global] = max(0.0, gen_h - curt_h)
                residual[h_global] = max(0.0, deficit[h_global])

            if discharge_h > 0.0:
                last_action = "discharged"
            elif charge_h > 0.0:
                last_action = "charged"
            else:
                last_action = "idle"

            soc[h_global] = current_soc

    soc_deadline = soc[24 + drain_deadline_hour - 1 :: 24]
    if np.any(soc_deadline > 1e-9):
        raise SimulationConstraintError(
            f"SoC deadline violated for scenario {scenario.label}: "
            f"max SoC at {drain_deadline_hour:02d}:00 deadline={soc_deadline.max():.6f}"
        )

    # Compute daily "carga não realizada"
    daily_discharge = discharge.reshape(365, 24).sum(axis=1)
    carga_nao_realizada_diaria = np.maximum(0.0, bess_energy - daily_discharge)

    if np.any(discharge > bess_power + 1e-10):
        raise SimulationConstraintError(
            f"Discharge power violated for scenario {scenario.label}: "
            f"max={discharge.max():.6f}, power={bess_power}"
        )

    return DispatchResult(
        soc_mwh=soc,
        charge_mwh=charge,
        discharge_mwh=discharge,
        grid_injection_mwh=grid_inj,
        deficit_mwh=deficit,
        residual_deficit_mwh=residual,
        curtailment_mwh=curt_arr,
        curtailment_lost_mwh=curt_lost,
        carga_nao_realizada_diaria_mwh=carga_nao_realizada_diaria,
    )


def simulate_scenario(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    curtailment_series: np.ndarray | None = None,
) -> DispatchResult:
    """Simulate one BESS scenario hour-by-hour for 8,760 hours.

    When ``scenario.charge_mode == 3``, delegates to the price-aware
    day-ahead dispatch (see ``_simulate_price_aware_dispatch``).

    Otherwise (modes 0-2), the BESS discharges in ANY hour where
    generation < garantia_fisica and it has stored energy.  Charging
    occurs from solar excess + curtailment whenever generation >=
    garantia_fisica.  A mandatory 1-hour gap is enforced between charge
    and discharge events.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly price profile. Used by charge_mode == 3; ignored otherwise.
    scenario : ScenarioDefinition
        Scenario sizing and peak hours.
    params : SimulationParams
        Simulation parameters.
    curtailment_series : np.ndarray | None
        Optional 8760-element array of curtailment MW per hour.

    Returns
    -------
    DispatchResult
        Hour-by-hour dispatch results.
    """
    if scenario.charge_mode == 3:
        return _simulate_price_aware_dispatch(solar, prices, scenario, params, curtailment_series)
    gf = solar.garantia_fisica_mw
    bess_power = scenario.bess_power_mw
    bess_energy = scenario.bess_energy_mwh
    rte = scenario.rte if scenario.rte != 1.0 else params.bess_roundtrip_efficiency
    gen = solar.generation_mw
    price_arr = prices.prices_brl_per_mwh

    has_curtailment = curtailment_series is not None
    curtailment_arr_input = (
        np.maximum(0.0, curtailment_series)
        if has_curtailment
        else np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    )

    # Pre-compute h-rule threshold for excess-solar charging.
    # Excess solar is stored only when the worst-case discharge price, after
    # round-trip losses, beats the current injection price:
    #   rte × min_PLD_peak > PLD_h
    # min_PLD_peak = minimum hourly PLD across ALL peak hours in the year.
    # Curtailment (external ONS curtailment) has zero alternative value and is
    # always stored regardless of this rule.
    peak_mask = np.array(
        [h % 24 in scenario.peak_hours for h in range(HOURS_PER_YEAR)], dtype=bool
    )
    min_pld_peak = float(np.min(price_arr[peak_mask])) if peak_mask.any() else 0.0

    # Last peak hour-of-day (e.g. 20 for {17,18,19,20}, 19 for {18,19}).
    # Drain may continue through the following dawn and must respect bess_power_mw.
    last_peak_hour: int = max(scenario.peak_hours) if scenario.peak_hours else 23
    drain_deadline_hour = 5

    # Output arrays
    soc = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    charge = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    discharge = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    grid_inj = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    deficit = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    residual = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    curt_arr = np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    curt_lost = np.zeros(HOURS_PER_YEAR, dtype=np.float64)

    current_soc = 0.0

    # State for 1-hour gap rule:
    # 'idle' = can do anything; 'charged' = last action was charge (must idle 1h before discharge)
    # 'discharged' = last action was discharge (must idle 1h before charge)
    last_action: str = "idle"  # "idle", "charged", "discharged"

    for h in range(HOURS_PER_YEAR):
        hour_of_day = h % 24
        gen_h = gen[h]

        # Curtailment available this hour (must be read before deficit calculation)
        curtailment_h = 0.0
        if has_curtailment:
            curtailment_h = max(0.0, curtailment_series[h])
            curt_arr[h] = curtailment_h

        # Deficit for ALL hours — effective injection sem BESS = gen minus curtailment
        effective_gen_h = max(0.0, gen_h - curtailment_h)
        deficit_h = max(0.0, gf - effective_gen_h)
        deficit[h] = deficit_h

        # Determine allowed actions based on 1-hour gap rule
        can_discharge = last_action != "charged"
        can_charge = last_action != "discharged"

        # --- Phase 1: Discharge ONLY during peak hours (garantia física dispatch) ---
        # Peak discharge covers the garantia física deficit first. Outside the
        # peak window, discharge is only daily drain to make room for stored energy.
        discharge_h = 0.0
        needs_expanded_drain = False
        if (
            hour_of_day in scenario.peak_hours
            and current_soc > 1e-10
            and can_discharge
            and curtailment_h <= 1e-10
        ):
            # In peak hours, use the BESS to cover deficit when present; if no
            # deficit exists, keep draining at PCS limit so the day can end with
            # SoC = 0 without a forced over-power discharge at 23:00.
            target_h = deficit_h if deficit_h > 0.0 else bess_power
            discharge_h = min(target_h, bess_power, current_soc)
            current_soc -= discharge_h
            discharge[h] = discharge_h

        # --- Phase 1b: Daily drain outside charging hours ---
        # The battery MUST reach SoC = 0 before the next day's 05:00 deadline.
        # The drain window may expand before the peak window when needed, but
        # remains capped by bess_power and never operates during curtailment.
        # The master 1-hour gap rule applies to this drain too.
        if discharge_h <= 1e-10:
            deadline = _drain_deadline_exclusive(h, drain_deadline_hour)
            normal_drain_hours = sum(
                1 for future_h in range(h, deadline)
                if curtailment_arr_input[future_h] <= 1e-10
            )
            needs_expanded_drain = current_soc > normal_drain_hours * bess_power + 1e-10

        if (
            discharge_h <= 1e-10
            and current_soc > 1e-10
            and can_discharge
            and curtailment_h <= 1e-10
            and (
                hour_of_day > last_peak_hour
                or hour_of_day < drain_deadline_hour
                or needs_expanded_drain
            )
            and _is_pld_ranked_discharge_hour(
                hour_index=h,
                current_soc_mwh=current_soc,
                bess_power_mw=bess_power,
                prices_brl_per_mwh=price_arr,
                curtailment_mwh=curtailment_arr_input,
                blocked_charge_hours=set(),
                deadline_hour=drain_deadline_hour,
            )
        ):
            drain_h = min(bess_power, current_soc)
            current_soc -= drain_h
            discharge[h] = drain_h
            discharge_h = drain_h

        residual[h] = max(0.0, deficit_h - discharge_h)

        # --- Phase 2: Charge from available sources (if allowed) ---
        charge_h = 0.0
        if can_charge and discharge_h <= 1e-10:
            excesso_solar = max(0.0, effective_gen_h - gf)
            remaining_capacity = bess_energy - current_soc
            # Charge rate is NOT capped by bess_power_mw: the duration (2h/4h) defines
            # energy capacity only. Charging absorbs all available energy up to SoC limit.
            can_charge_mw = remaining_capacity / rte if remaining_capacity > 1e-10 else 0.0

            if deficit_h > 0.0:
                # During deficit hours, only charge from curtailment (solar is below GF)
                carga_curt = min(curtailment_h, can_charge_mw)
                charge_h = carga_curt
                curt_lost[h] = max(0.0, curtailment_h - carga_curt)
            else:
                # No deficit: charge from curtailment (always free) then solar excess
                # (only when h-rule confirms storing beats selling at current price).
                carga_curt = min(curtailment_h, can_charge_mw)
                h_rule_ok = rte * min_pld_peak > float(price_arr[h])
                carga_solar = (
                    min(excesso_solar, can_charge_mw - carga_curt) if h_rule_ok else 0.0
                )
                charge_h = carga_curt + carga_solar
                curt_lost[h] = max(0.0, curtailment_h - carga_curt)
        else:
            # Can't charge this hour (gap rule), curtailment is lost
            curt_lost[h] = curtailment_h

        # Store energy (applying RTE)
        if charge_h > 0.0:
            current_soc += charge_h * rte
            charge[h] = charge_h

        # Grid injection: effective generation + discharge (peak or drain) - solar charged
        carga_solar_grid = charge_h - min(curtailment_h, charge_h) if can_charge else 0.0
        grid_inj[h] = effective_gen_h + discharge_h - carga_solar_grid

        # Update 1-hour gap state
        if discharge_h > 0.0:
            last_action = "discharged"
        elif charge_h > 0.0:
            last_action = "charged"
        else:
            # Idle hour resets the gap — next hour can do anything
            last_action = "idle"

        soc[h] = current_soc

    # Post-simulation validation
    if np.any(soc < -1e-10) or np.any(soc > bess_energy + 1e-10):
        raise SimulationConstraintError(
            f"SoC bounds violated for scenario {scenario.label}: "
            f"min={soc.min():.6f}, max={soc.max():.6f}, capacity={bess_energy}"
        )
    if np.any(discharge > bess_power + 1e-10):
        raise SimulationConstraintError(
            f"Discharge power violated for scenario {scenario.label}: "
            f"max={discharge.max():.6f}, power={bess_power}"
        )
    soc_deadline = soc[24 + drain_deadline_hour - 1 :: 24]
    if np.any(soc_deadline > 1e-9):
        raise SimulationConstraintError(
            f"SoC deadline violated for scenario {scenario.label}: "
            f"max SoC at {drain_deadline_hour:02d}:00 deadline={soc_deadline.max():.6f}"
        )

    # Compute daily "carga não realizada":
    # Expected 1 full cycle/day. Missed = bess_energy - actual daily discharge.
    daily_discharge = discharge.reshape(365, 24).sum(axis=1)
    carga_nao_realizada_diaria = np.maximum(0.0, bess_energy - daily_discharge)

    return DispatchResult(
        soc_mwh=soc,
        charge_mwh=charge,
        discharge_mwh=discharge,
        grid_injection_mwh=grid_inj,
        deficit_mwh=deficit,
        residual_deficit_mwh=residual,
        curtailment_mwh=curt_arr,
        curtailment_lost_mwh=curt_lost,
        carga_nao_realizada_diaria_mwh=carga_nao_realizada_diaria,
    )


def _peak_weights(scenario: ScenarioDefinition) -> dict[int, float]:
    """Return peak-hour weights for the scenario."""
    if scenario.peak_hour_weights is not None:
        return dict(scenario.peak_hour_weights)
    return {hour: 1.0 for hour in scenario.peak_hours}


def simulate_all_scenarios(
    solar: SolarProfile,
    prices: PriceProfile,
    scenarios: list[ScenarioDefinition],
    params: SimulationParams,
    progress_cb: Callable[[str], None] | None = None,
) -> list[tuple[ScenarioDefinition, DispatchResult]]:
    """Simulate all scenarios and return paired results.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly price profile.
    scenarios : list[ScenarioDefinition]
        List of scenario definitions (typically 3: A, B, C).
    params : SimulationParams
        Simulation parameters.
    progress_cb : Callable[[str], None] | None
        Optional progress callback.

    Returns
    -------
    list[tuple[ScenarioDefinition, DispatchResult]]
        Paired (scenario, dispatch) tuples.
    """
    results: list[tuple[ScenarioDefinition, DispatchResult]] = []
    for i, scenario in enumerate(scenarios):
        if progress_cb:
            progress_cb(f"[{i+1}/{len(scenarios)}] Cenário {scenario.label}...")
        dispatch = simulate_scenario(solar, prices, scenario, params)
        results.append((scenario, dispatch))
    return results
