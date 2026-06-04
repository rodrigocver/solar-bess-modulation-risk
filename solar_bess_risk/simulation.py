"""Hour-by-hour BESS dispatch engine (v2 — Garantia Física model).

Functions
---------
simulate_scenario(solar, prices, scenario, params) -> DispatchResult
simulate_all_scenarios(solar, prices, scenarios, params, progress_cb) -> list

Modelo de despacho canônico
---------------------------
O modo de despacho **canônico** é o ``charge_mode == 3`` (arbitragem day-ahead,
``_simulate_price_aware_dispatch``). Os modos legados ``0-2`` são mantidos apenas
para retrocompatibilidade e testes; novos resultados de produção usam sempre o
modo 3.

Duas premissas estruturais do modo 3 ficam aqui documentadas explicitamente:

1. **Previsão perfeita de PLD (foresight)** — o planejamento de cada dia conhece
   antecipadamente a curva horária de PLD do próprio dia (``day_pld``). Trata-se
   de uma hipótese otimista de backtest: superestima o valor da arbitragem em
   relação à operação real com previsão imperfeita. Os resultados devem ser lidos
   como um *limite superior* do ganho de arbitragem.
2. **Gap operacional de 1 hora** — a BESS não pode carregar e descarregar em horas
   consecutivas; é exigida ao menos 1 hora ociosa entre uma carga e uma descarga
   (e vice-versa), em ambos os modos (legado e canônico).
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
    """One of the fixed BESS scenarios.

    Parameters
    ----------
    label : str
        Scenario label ("A", "B", etc.).
    peak_hours : frozenset[int]
        Hour-of-day indices considered peak.
    duration_h : int
        BESS storage duration in hours.
    bess_power_mw : float
        BESS discharge rated power in MW.
    bess_energy_mwh : float
        BESS energy capacity in MWh.
    capex_brl : float
        BESS CAPEX in BRL.
    charge_power_mw : float | None
        BESS charge power limit in MW. Defaults to ``bess_power_mw``.
    peak_hour_weights : dict[int, float] | None
        Fraction of each hour inside the guarantee window. Defaults to 1.0
        for every hour in ``peak_hours``.
    charge_mode : int
        0 = legacy (charge from surplus/curtailment, discharge during peak_hours).
        3 = day-ahead: for each day, pair low-opportunity-cost charge with
        higher-value future discharge; discharge above GF is allowed.
    """

    label: str
    peak_hours: frozenset[int]
    duration_h: int
    bess_power_mw: float
    bess_energy_mwh: float
    capex_brl: float
    charge_power_mw: float | None = None
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
        Total curtailable energy available at each hour, shape ``(8760,)``.
        Backward-compatible alias for ONS curtailment + clipping.
    curtailment_lost_mwh : np.ndarray
        Total curtailable energy that could not be stored, shape ``(8760,)``.
    carga_nao_realizada_diaria_mwh : np.ndarray
        Daily missed cycle: bess_energy - actual daily discharge, shape ``(365,)``.
    ons_curtailment_mwh : np.ndarray | None
        External ONS curtailment available before BESS recovery.
    clipping_available_mwh : np.ndarray | None
        Generation unlocked by BESS availability: max(gen_mw - gen_lim_mw, 0).
    curtailment_recovered_mwh : np.ndarray | None
        Total curtailable energy recovered by BESS charging.
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
    ons_curtailment_mwh: np.ndarray | None = None
    clipping_available_mwh: np.ndarray | None = None
    curtailment_total_available_mwh: np.ndarray | None = None
    curtailment_recovered_mwh: np.ndarray | None = None

    def __post_init__(self) -> None:
        """Populate split curtailment arrays for older tests/callers."""
        zeros = np.zeros_like(self.curtailment_mwh, dtype=np.float64)
        if self.ons_curtailment_mwh is None:
            self.ons_curtailment_mwh = self.curtailment_mwh
        if self.clipping_available_mwh is None:
            self.clipping_available_mwh = zeros
        if self.curtailment_total_available_mwh is None:
            self.curtailment_total_available_mwh = self.curtailment_mwh
        if self.curtailment_recovered_mwh is None:
            self.curtailment_recovered_mwh = np.maximum(
                0.0,
                self.curtailment_total_available_mwh - self.curtailment_lost_mwh,
            )


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
    deficit_mwh: np.ndarray | None = None,
) -> bool:
    """Choose drain hours by descending PLD within the current deadline window."""
    if current_soc_mwh <= 1e-10 or bess_power_mw <= 1e-10:
        return False

    deadline = _drain_deadline_exclusive(hour_index, deadline_hour)
    candidates = [
        h for h in range(hour_index, deadline)
        if curtailment_mwh[h] <= 1e-10 and h not in blocked_charge_hours
        and (deficit_mwh is None or deficit_mwh[h] > 1e-10)
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


@dataclass
class _DailyDispatchPlan:
    """Day-ahead plan separated from chronological execution."""

    charge_curt_mwh: np.ndarray
    charge_solar_mwh: np.ndarray
    discharge_mwh: np.ndarray


def _empty_daily_dispatch_plan() -> _DailyDispatchPlan:
    """Create zeroed 24-hour plan arrays for one operating day."""
    return _DailyDispatchPlan(
        charge_curt_mwh=np.zeros(24, dtype=np.float64),
        charge_solar_mwh=np.zeros(24, dtype=np.float64),
        discharge_mwh=np.zeros(24, dtype=np.float64),
    )


def _plan_carryover_drain(
    plan: _DailyDispatchPlan,
    *,
    current_soc: float,
    day_pld: np.ndarray,
    day_gen: np.ndarray,
    day_curt: np.ndarray,
    bess_power: float,
    drain_deadline_hour: int,
    must_mw: float | None = None,
) -> None:
    """Plan mandatory carryover drain before the 05:00 deadline."""
    carryover_remaining = current_soc
    dawn_candidates = [
        h for h in range(drain_deadline_hour)
        if day_curt[h] <= 1e-10
    ]
    for h_local in sorted(dawn_candidates, key=lambda h: (-float(day_pld[h]), h)):
        if carryover_remaining <= 1e-10:
            break
        limit = bess_power
        if must_mw is not None:
            limit = min(limit, max(0.0, must_mw - day_gen[h_local]))
        disch = min(limit, carryover_remaining)
        plan.discharge_mwh[h_local] = disch
        carryover_remaining -= disch


def _planned_soc_after_each_hour(
    plan: _DailyDispatchPlan,
    *,
    rte: float,
    drain_deadline_hour: int,
) -> np.ndarray:
    """Compute planned post-deadline SoC profile for capacity checks."""
    planned = np.zeros(24, dtype=np.float64)
    soc_local = 0.0
    for local_h in range(drain_deadline_hour, 24):
        soc_local += (plan.charge_curt_mwh[local_h] + plan.charge_solar_mwh[local_h]) * rte
        soc_local -= plan.discharge_mwh[local_h]
        planned[local_h] = soc_local
    return planned


def _charge_sources_for_discharge(
    plan: _DailyDispatchPlan,
    *,
    discharge_h_local: int,
    day_gen: np.ndarray,
    day_curt: np.ndarray,
    day_pld: np.ndarray,
    rte: float,
    drain_deadline_hour: int,
    discharge_hours: set[int],
    min_gap_hours: int = 1,
) -> list[tuple[float, int, str]]:
    """Build charge candidates for a discharge hour, preserving current tie-breaks.

    A mandatory ``min_gap_hours`` idle gap is enforced between any charge hour
    and any discharge hour (canonical mode-3 constraint): a charge candidate is
    rejected when it sits within ``min_gap_hours`` of the target discharge hour
    or of any already-committed discharge hour.
    """
    charge_sources: list[tuple[float, int, str]] = []
    for charge_h_local in range(drain_deadline_hour, discharge_h_local):
        if charge_h_local == discharge_h_local:
            continue
        # 1-hour (min_gap_hours) charge/discharge separation versus the target
        # discharge hour and versus every already-committed discharge hour.
        if discharge_h_local - charge_h_local <= min_gap_hours:
            continue
        if any(abs(charge_h_local - d) <= min_gap_hours for d in discharge_hours):
            continue
        if day_curt[charge_h_local] - plan.charge_curt_mwh[charge_h_local] > 1e-10:
            charge_sources.append((0.0, charge_h_local, "curtailment"))
        direct_solar_available = max(0.0, day_gen[charge_h_local] - day_curt[charge_h_local])
        if (
            direct_solar_available - plan.charge_solar_mwh[charge_h_local] > 1e-10
            and rte * float(day_pld[discharge_h_local]) > float(day_pld[charge_h_local])
        ):
            charge_sources.append((float(day_pld[charge_h_local]), charge_h_local, "solar"))
    return charge_sources


def _optimise_day_ahead_plan(
    *,
    current_soc: float,
    day_pld: np.ndarray,
    day_gen: np.ndarray,
    day_curt: np.ndarray,
    bess_power: float,
    charge_power: float,
    bess_energy: float,
    rte: float,
    drain_deadline_hour: int,
    must_mw: float | None = None,
) -> _DailyDispatchPlan:
    """Create a linear day-ahead charge/discharge plan for one day."""
    plan = _empty_daily_dispatch_plan()
    _plan_carryover_drain(
        plan,
        current_soc=current_soc,
        day_pld=day_pld,
        day_gen=day_gen,
        day_curt=day_curt,
        bess_power=bess_power,
        drain_deadline_hour=drain_deadline_hour,
        must_mw=must_mw,
    )

    # Canonical mode-3 constraint: enforce a 1-hour idle gap between any charge
    # and any discharge hour. Track committed charge/discharge hours so the
    # day-ahead plan never schedules charge and discharge in adjacent hours.
    # Carryover-drain discharge hours seed the discharge set before pairing.
    min_gap_hours = 1
    discharge_hours: set[int] = {h for h in range(24) if plan.discharge_mwh[h] > 1e-10}
    charge_hours: set[int] = set()

    discharge_candidates = [
        h for h in range(drain_deadline_hour, 24)
        if day_curt[h] <= 1e-10
    ]
    for discharge_h_local in sorted(
        discharge_candidates,
        key=lambda h: (-float(day_pld[h]), h),
    ):
        # Skip discharge hours adjacent to an already-committed charge hour.
        if any(
            abs(discharge_h_local - c) <= min_gap_hours for c in charge_hours
        ):
            continue
        limit = bess_power
        if must_mw is not None:
            limit = min(limit, max(0.0, must_mw - day_gen[discharge_h_local]))
        discharge_headroom = limit - plan.discharge_mwh[discharge_h_local]
        if discharge_headroom <= 1e-10:
            continue

        charge_sources = _charge_sources_for_discharge(
            plan,
            discharge_h_local=discharge_h_local,
            day_gen=day_gen,
            day_curt=day_curt,
            day_pld=day_pld,
            rte=rte,
            drain_deadline_hour=drain_deadline_hour,
            discharge_hours=discharge_hours,
            min_gap_hours=min_gap_hours,
        )

        for _source_cost, charge_h_local, source in sorted(charge_sources):
            if discharge_headroom <= 1e-10:
                break

            hourly_charge_headroom = (
                charge_power - plan.charge_curt_mwh[charge_h_local] - plan.charge_solar_mwh[charge_h_local]
            )
            if hourly_charge_headroom <= 1e-10:
                continue

            if source == "curtailment":
                source_avail = day_curt[charge_h_local] - plan.charge_curt_mwh[charge_h_local]
            else:
                direct_solar_available = max(
                    0.0, day_gen[charge_h_local] - day_curt[charge_h_local]
                )
                source_avail = direct_solar_available - plan.charge_solar_mwh[charge_h_local]
            if source_avail <= 1e-10:
                continue

            planned_soc = _planned_soc_after_each_hour(
                plan,
                rte=rte,
                drain_deadline_hour=drain_deadline_hour,
            )
            capacity_headroom_mwh = float(
                np.min(bess_energy - planned_soc[charge_h_local:discharge_h_local])
            )
            if capacity_headroom_mwh <= 1e-10:
                continue

            charge_delta = min(
                source_avail,
                hourly_charge_headroom,
                capacity_headroom_mwh / rte,
                discharge_headroom / rte,
            )
            if charge_delta <= 1e-10:
                continue

            discharge_delta = charge_delta * rte
            if source == "curtailment":
                plan.charge_curt_mwh[charge_h_local] += charge_delta
            else:
                plan.charge_solar_mwh[charge_h_local] += charge_delta
            plan.discharge_mwh[discharge_h_local] += discharge_delta
            discharge_headroom -= discharge_delta
            # Commit hours so the gap is honoured for the rest of the plan.
            charge_hours.add(charge_h_local)
            discharge_hours.add(discharge_h_local)

    return plan


def _execute_price_aware_day(
    *,
    day: int,
    current_soc: float,
    plan: _DailyDispatchPlan,
    day_gen: np.ndarray,
    day_curt: np.ndarray,
    gf: float,
    bess_power: float,
    bess_energy: float,
    rte: float,
    soc: np.ndarray,
    charge: np.ndarray,
    discharge: np.ndarray,
    grid_inj: np.ndarray,
    deficit: np.ndarray,
    residual: np.ndarray,
    curt_arr: np.ndarray,
    curt_lost: np.ndarray,
    must_mw: float | None = None,
) -> float:
    """Execute an already-built daily plan in chronological order."""
    start = day * 24
    for h_local in range(24):
        h_global = start + h_local
        gen_h = float(day_gen[h_local])
        curt_h = float(day_curt[h_local])

        curt_arr[h_global] = curt_h

        # Deficit uses effective injection (gen minus curtailment)
        deficit[h_global] = max(0.0, gf - max(0.0, gen_h - curt_h))

        planned_discharge = plan.discharge_mwh[h_local]
        planned_curt_charge = plan.charge_curt_mwh[h_local]
        planned_solar_charge = plan.charge_solar_mwh[h_local]

        if planned_discharge > 1e-10 and curt_h <= 1e-10:
            curt_lost[h_global] = curt_h

            limit = bess_power
            if must_mw is not None:
                limit = min(limit, max(0.0, must_mw - gen_h))
            disch = min(planned_discharge, limit, current_soc)
            current_soc -= disch
            discharge[h_global] = disch

            grid_inj[h_global] = max(0.0, gen_h - curt_h) + discharge[h_global]
            residual[h_global] = max(0.0, gf - grid_inj[h_global])

        elif planned_curt_charge + planned_solar_charge > 1e-10:
            direct_solar_available = max(0.0, gen_h - curt_h)
            remaining_cap = bess_energy - current_soc
            if remaining_cap > 1e-10:
                planned_curt_charge = min(planned_curt_charge, curt_h)
                planned_solar_charge = min(planned_solar_charge, direct_solar_available)
                planned_total_charge = planned_curt_charge + planned_solar_charge
                if planned_total_charge > 1e-10:
                    charge_scale = min(1.0, remaining_cap / (planned_total_charge * rte))
                    ch_curt = planned_curt_charge * charge_scale
                    ch_solar = planned_solar_charge * charge_scale
                    current_soc += (ch_curt + ch_solar) * rte
                else:
                    ch_curt = 0.0
                    ch_solar = 0.0
            else:
                ch_curt = 0.0
                ch_solar = 0.0

            curt_lost[h_global] = max(0.0, curt_h - ch_curt)
            charge[h_global] = ch_curt + ch_solar

            grid_inj[h_global] = max(0.0, direct_solar_available - ch_solar)
            residual[h_global] = max(0.0, gf - grid_inj[h_global])

        else:
            curt_lost[h_global] = curt_h
            grid_inj[h_global] = max(0.0, gen_h - curt_h)
            residual[h_global] = max(0.0, deficit[h_global])

        soc[h_global] = current_soc

    return current_soc


def _must_excess_curtailment(
    gen_bess: np.ndarray,
    ons_curt_arr: np.ndarray,
    clip_arr: np.ndarray,
    must_mw: float | None,
) -> np.ndarray:
    """Combine available curtailment with the MUST injection cap.

    The MUST cap and inverter clipping both measure the top of the same
    generation profile against different ceilings, so they are combined with
    ``max`` (not summed) to avoid double-counting the same energy.

    Parameters
    ----------
    gen_bess : np.ndarray
        BESS-enabled generation per hour in MW, shape ``(8760,)``.
    ons_curt_arr : np.ndarray
        External ONS curtailment available per hour in MW.
    clip_arr : np.ndarray
        Inverter clipping released by the BESS per hour in MW.
    must_mw : float | None
        MUST injection cap in MW. ``None`` disables the cap (legacy behavior).

    Returns
    -------
    np.ndarray
        Total available curtailment per hour in MW.
    """
    if must_mw is None or not np.isfinite(must_mw):
        return np.minimum(gen_bess, ons_curt_arr + clip_arr)
    must_excess = np.maximum(0.0, gen_bess - must_mw)
    return np.minimum(gen_bess, ons_curt_arr + np.maximum(clip_arr, must_excess))


def _simulate_price_aware_dispatch(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    curtailment_series: np.ndarray | None = None,
    solar_year_idx: int = 1,
    must_mw: float | None = None,
) -> DispatchResult:
    """Price-aware day-ahead dispatch (charge_mode == 3).

    For each calendar day the algorithm optimizes marginal charge/discharge
    pairs with the day-ahead PLD curve:
    1. Any carryover SoC is drained by the 05:00 operational deadline in the
       highest-PLD feasible dawn hours.
    2. Same-day discharge hours are ranked by descending PLD, regardless of
       whether there is GF deficit; discharge above GF is allowed and valued
       at PLD through the net-balance economics.
    3. For each discharge hour, prior charge hours are ranked by marginal
       opportunity cost (curtailment first at zero cost, then solar by PLD).
    4. A charge/discharge pair is accepted only when its marginal value is
       positive: ``rte × PLD_discharge > PLD_charge`` for solar charge.
    5. A mandatory 1-hour idle gap separates any charge hour from any discharge
       hour (no charge/discharge in consecutive hours). This is the canonical
       mode-3 operational constraint and mirrors the legacy gap rule.

    Premissas estruturais (ver docstring do módulo):

    - **Previsão perfeita de PLD**: o planejamento usa a curva horária real do
      dia (``day_pld``). É uma hipótese otimista de backtest — os ganhos de
      arbitragem representam um limite superior frente à operação real.
    - **Robustez do deadline de drenagem**: a drenagem de carryover é limitada
      por ``min(bess_power, must_mw − geração)``. Sob um teto de MUST muito
      agressivo combinado a geração não nula na madrugada, a janela de drenagem
      pode ser insuficiente e a verificação ``SoC(05:00) ≈ 0`` levanta
      ``SimulationConstraintError`` (falha explícita, sem mascarar o problema).
      Com o sweep padrão (≤ 40%) e geração ~0 na madrugada isso não ocorre.

    Parameters
    ----------
    solar : SolarProfile
        Solar generation profile.
    prices : PriceProfile
        Hourly PLD prices used to rank hours per day.
    scenario : ScenarioDefinition
        Scenario sizing. ``duration_h`` is only a scheduling count for how
        many discharge hours are selected per day; energy and CAPEX come from
        the scenario itself.
    params : SimulationParams
        Simulation parameters (RTE comes from here unless overridden on scenario).
    curtailment_series : np.ndarray | None
        Optional 8760-element curtailment array.
    must_mw : float | None
        MUST injection cap in MW. ``None`` disables the cap (legacy behavior).
        When set, hourly generation above ``must_mw`` is treated as available
        curtailment (combined with clipping via ``max``, not summed).

    Returns
    -------
    DispatchResult
        Hour-by-hour dispatch results.
    """
    gf = solar.garantia_fisica_mw
    bess_power = scenario.bess_power_mw
    charge_power = scenario.charge_power_mw or scenario.bess_power_mw
    bess_energy = scenario.bess_energy_mwh
    duration_h = scenario.duration_h
    rte = scenario.rte if scenario.rte != 1.0 else params.bess_roundtrip_efficiency
    # Select the correct solar year (gen_lim=sem BESS, gen_bess=com BESS)
    gen_lim, gen_bess = solar.get_year_arrays(solar_year_idx)
    gen = gen_bess  # dispatch uses BESS-enabled generation
    price_arr = prices.prices_brl_per_mwh
    has_curtailment = curtailment_series is not None
    ons_curt_arr = (
        np.maximum(0.0, curtailment_series)
        if has_curtailment
        else np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    )
    # Clipping energy = BESS releases inverters; treated as zero-cost curtailment
    clip_arr = np.maximum(0.0, gen_bess - gen_lim)
    curtailment_arr_input = _must_excess_curtailment(
        gen_bess, ons_curt_arr, clip_arr, must_mw
    )

    drain_deadline_hour = 5
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
        day_gen = gen[start : start + 24]  # gen_bess slice for dispatch
        day_curt = curtailment_arr_input[start : start + 24]  # ons + clip combined

        if day == 0:
            current_soc = 0.0

        plan = _optimise_day_ahead_plan(
            current_soc=current_soc,
            day_pld=day_pld,
            day_gen=day_gen,
            day_curt=day_curt,
            bess_power=bess_power,
            charge_power=charge_power,
            bess_energy=bess_energy,
            rte=rte,
            drain_deadline_hour=drain_deadline_hour,
            must_mw=must_mw,
        )
        current_soc = _execute_price_aware_day(
            day=day,
            current_soc=current_soc,
            plan=plan,
            day_gen=day_gen,
            day_curt=day_curt,
            gf=gf,
            bess_power=bess_power,
            bess_energy=bess_energy,
            rte=rte,
            soc=soc,
            charge=charge,
            discharge=discharge,
            grid_inj=grid_inj,
            deficit=deficit,
            residual=residual,
            curt_arr=curt_arr,
            curt_lost=curt_lost,
            must_mw=must_mw,
        )

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
    if np.any(charge > charge_power + 1e-10):
        raise SimulationConstraintError(
            f"Charge power violated for scenario {scenario.label}: "
            f"max={charge.max():.6f}, power={charge_power}"
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
        ons_curtailment_mwh=ons_curt_arr,
        clipping_available_mwh=clip_arr,
        curtailment_total_available_mwh=curtailment_arr_input,
    )


def simulate_scenario(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    curtailment_series: np.ndarray | None = None,
    solar_year_idx: int = 1,
    must_mw: float | None = None,
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
    must_mw : float | None
        MUST injection cap in MW. ``None`` disables the cap (legacy behavior).

    Returns
    -------
    DispatchResult
        Hour-by-hour dispatch results.
    """
    if scenario.charge_mode == 3:
        return _simulate_price_aware_dispatch(
            solar, prices, scenario, params, curtailment_series, solar_year_idx, must_mw
        )
    gf = solar.garantia_fisica_mw
    bess_power = scenario.bess_power_mw
    charge_power = scenario.charge_power_mw or scenario.bess_power_mw
    bess_energy = scenario.bess_energy_mwh
    rte = scenario.rte if scenario.rte != 1.0 else params.bess_roundtrip_efficiency
    # Select the correct solar year (gen_lim=sem BESS, gen_bess=com BESS)
    gen_lim, gen_bess = solar.get_year_arrays(solar_year_idx)
    gen = gen_bess
    price_arr = prices.prices_brl_per_mwh

    has_curtailment = curtailment_series is not None
    ons_curt_arr = (
        np.maximum(0.0, curtailment_series)
        if has_curtailment
        else np.zeros(HOURS_PER_YEAR, dtype=np.float64)
    )
    clip_arr = np.maximum(0.0, gen_bess - gen_lim)
    curtailment_arr_input = _must_excess_curtailment(
        gen_bess, ons_curt_arr, clip_arr, must_mw
    )

    # Pre-compute daily h-rule thresholds for excess-solar charging.
    # Excess solar is stored only when the worst-case discharge price, after
    # round-trip losses, beats the current injection price:
    #   rte × min_PLD_peak > PLD_h
    # min_PLD_peak is computed per day using the known day-ahead PLD curve.
    # Curtailment (external ONS curtailment) has zero alternative value and is
    # always stored regardless of this rule.
    daily_min_pld_peak = np.zeros(365, dtype=np.float64)
    for day in range(365):
        start = day * 24
        peak_prices = [
            float(price_arr[start + hour])
            for hour in scenario.peak_hours
            if start + hour < HOURS_PER_YEAR
        ]
        daily_min_pld_peak[day] = min(peak_prices) if peak_prices else 0.0

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

        # Curtailment available this hour (ONS + clipping) before deficit calculation.
        curtailment_h = float(curtailment_arr_input[h])
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
            limit = bess_power
            if must_mw is not None:
                limit = min(limit, max(0.0, must_mw - gen_h))
            discharge_h = min(target_h, limit, current_soc)
            current_soc -= discharge_h
            discharge[h] = discharge_h

        # --- Phase 1b: Daily drain outside charging hours ---
        # The battery MUST reach SoC = 0 before the next day's 05:00 deadline.
        # The drain window may expand before the peak window when needed, but
        # remains capped by bess_power and never operates during curtailment.
        # The master 1-hour gap rule applies to this drain too.
        if discharge_h <= 1e-10:
            deadline = _drain_deadline_exclusive(h, drain_deadline_hour)
            normal_drain_capacity = 0.0
            for future_h in range(h, deadline):
                if curtailment_arr_input[future_h] <= 1e-10:
                    limit = bess_power
                    if must_mw is not None:
                        limit = min(limit, max(0.0, must_mw - gen[future_h]))
                    normal_drain_capacity += limit
            needs_expanded_drain = current_soc > normal_drain_capacity + 1e-10

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
            limit = bess_power
            if must_mw is not None:
                limit = min(limit, max(0.0, must_mw - gen_h))
            drain_h = min(limit, current_soc)
            current_soc -= drain_h
            discharge[h] = drain_h
            discharge_h = drain_h

        residual[h] = max(0.0, deficit_h - discharge_h)

        # --- Phase 2: Charge from available sources (if allowed) ---
        charge_h = 0.0
        if can_charge and discharge_h <= 1e-10:
            direct_solar_available = max(0.0, gen_h - curtailment_h)
            excesso_solar = max(0.0, effective_gen_h - gf)
            remaining_capacity = bess_energy - current_soc
            # Charging is limited by PCS/charge_power and remaining energy capacity.
            can_charge_mw = (
                min(charge_power, remaining_capacity / rte)
                if remaining_capacity > 1e-10 else 0.0
            )

            if deficit_h > 0.0:
                # During deficit hours, only charge from curtailment (solar is below GF)
                carga_curt = min(curtailment_h, can_charge_mw)
                charge_h = carga_curt
                curt_lost[h] = max(0.0, curtailment_h - carga_curt)
            else:
                # No deficit: charge from curtailment (always free) then solar excess
                # (only when h-rule confirms storing beats selling at current price).
                carga_curt = min(curtailment_h, can_charge_mw)
                h_rule_ok = rte * daily_min_pld_peak[h // 24] > float(price_arr[h])
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
        if must_mw is not None and np.isfinite(must_mw):
            grid_inj[h] = min(grid_inj[h], must_mw)

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
    if np.any(charge > charge_power + 1e-10):
        raise SimulationConstraintError(
            f"Charge power violated for scenario {scenario.label}: "
            f"max={charge.max():.6f}, power={charge_power}"
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
        ons_curtailment_mwh=ons_curt_arr,
        clipping_available_mwh=clip_arr,
        curtailment_total_available_mwh=curtailment_arr_input,
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
        List of scenario definitions (currently A and B).
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
