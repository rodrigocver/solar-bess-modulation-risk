"""Year-by-year economic projection for BESS scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import numpy as np

from solar_bess_risk.config import DEFAULT_RTE_COMMISSIONING_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

MAX_CYCLE_LIFE_CALENDAR_MULTIPLIER = 4


@dataclass(frozen=True)
class CashflowProjection:
    """Undiscounted yearly cashflow projection using the RTE trajectory."""

    payback_years: float | None
    lifetime_net_savings_brl: float
    lcos_brl_per_mwh: float | None
    lifetime_discharge_mwh: float
    annual_gross_savings_brl: tuple[float, ...]
    annual_net_savings_brl: tuple[float, ...]
    annual_discharge_mwh: tuple[float, ...]
    annual_rte: tuple[float, ...]
    projected_calendar_years: float = 0.0
    target_lifetime_discharge_mwh: float = 0.0
    target_equivalent_cycles: float = 0.0
    cycle_life_reached: bool = False
    lcoe_discount_rate: float = 0.0


def rte_for_year(rte_table: dict[int, float], year: int, fallback: float) -> float:
    """Return RTE for a calendar year, clamping outside the supplier curve."""
    if not rte_table:
        return fallback
    if year in rte_table:
        return rte_table[year]
    first_year = min(rte_table)
    last_year = max(rte_table)
    if year < first_year:
        return rte_table[first_year]
    if year > last_year:
        return rte_table[last_year]
    previous_years = [candidate for candidate in rte_table if candidate <= year]
    return rte_table[max(previous_years)]


def project_cashflows_with_rte(
    *,
    solar: SolarProfile,
    pld: np.ndarray,
    price_source: str,
    bq_submarket: str,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    curtailment_series: np.ndarray | None,
    rte_table: dict[int, float],
    start_year: int,
) -> CashflowProjection:
    """Project payback and LCOS by re-simulating each future year with that year's RTE.

    The PLD/generation year is held constant for the selected scenario tab. The
    yearly RTE changes along the supplier curve, so lower future RTE reduces
    stored energy, discharge, benefit and payback naturally.
    """
    fallback_rte = scenario.rte if scenario.rte != 1.0 else params.bess_roundtrip_efficiency
    if start_year < DEFAULT_RTE_COMMISSIONING_YEAR:
        start_year = DEFAULT_RTE_COMMISSIONING_YEAR

    cumulative = 0.0
    previous = 0.0
    payback: float | None = None
    annual_gross: list[float] = []
    annual_net: list[float] = []
    annual_discharge: list[float] = []
    annual_rte: list[float] = []
    discounted_o_and_m = 0.0
    discounted_discharge = 0.0
    annual_o_and_m = scenario.capex_brl * params.bess_o_and_m_pct_capex
    target_equivalent_cycles = params.useful_life_years * 365.0
    target_lifetime_discharge = scenario.bess_energy_mwh * target_equivalent_cycles
    max_calendar_years = max(
        params.useful_life_years,
        params.useful_life_years * MAX_CYCLE_LIFE_CALENDAR_MULTIPLIER,
    )
    price_profile = PriceProfile(pld, price_source, bq_submarket, start_year)

    projected_calendar_years = 0.0
    cycle_life_reached = target_lifetime_discharge <= 1e-10

    for offset in range(max_calendar_years):
        if cycle_life_reached:
            break

        cashflow_year = start_year + offset
        rte = rte_for_year(rte_table, cashflow_year, fallback_rte)
        yearly_scenario = replace(scenario, rte=rte)
        yearly_dispatch = simulate_scenario(
            solar,
            price_profile,
            yearly_scenario,
            params,
            curtailment_series=curtailment_series,
        )

        injection_sem = solar.generation_mw - yearly_dispatch.curtailment_mwh
        injection_com = (
            solar.generation_mw
            - yearly_dispatch.charge_mwh
            - yearly_dispatch.curtailment_lost_mwh
            + yearly_dispatch.discharge_mwh
        )
        gross = float(np.sum((injection_com - injection_sem) * pld))
        discharge_mwh = float(np.sum(yearly_dispatch.discharge_mwh))
        if discharge_mwh <= 1e-10 and target_lifetime_discharge > 1e-10:
            year_fraction = 1.0
        else:
            remaining_discharge = target_lifetime_discharge - sum(annual_discharge)
            year_fraction = min(1.0, remaining_discharge / discharge_mwh) if discharge_mwh > 1e-10 else 1.0

        gross *= year_fraction
        net = gross - annual_o_and_m * year_fraction
        discharge_mwh *= year_fraction
        discount_factor = 1 / ((1 + params.lcoe_discount_rate) ** (offset + year_fraction))
        discounted_o_and_m += annual_o_and_m * year_fraction * discount_factor
        discounted_discharge += discharge_mwh * discount_factor

        annual_rte.append(rte)
        annual_gross.append(gross)
        annual_net.append(net)
        annual_discharge.append(discharge_mwh)
        projected_calendar_years += year_fraction

        cumulative += net
        if payback is None and cumulative >= scenario.capex_brl:
            if net <= 0:
                payback = offset + year_fraction
            else:
                payback = offset + year_fraction * (scenario.capex_brl - previous) / net
        previous = cumulative
        cycle_life_reached = sum(annual_discharge) + 1e-9 >= target_lifetime_discharge

    lifetime_discharge = float(sum(annual_discharge))
    total_discounted_cost = scenario.capex_brl + discounted_o_and_m
    lcos = total_discounted_cost / discounted_discharge if discounted_discharge > 1e-10 else None

    return CashflowProjection(
        payback_years=payback,
        lifetime_net_savings_brl=cumulative,
        lcos_brl_per_mwh=lcos,
        lifetime_discharge_mwh=lifetime_discharge,
        annual_gross_savings_brl=tuple(annual_gross),
        annual_net_savings_brl=tuple(annual_net),
        annual_discharge_mwh=tuple(annual_discharge),
        annual_rte=tuple(annual_rte),
        projected_calendar_years=projected_calendar_years,
        target_lifetime_discharge_mwh=target_lifetime_discharge,
        target_equivalent_cycles=target_equivalent_cycles,
        cycle_life_reached=cycle_life_reached,
        lcoe_discount_rate=params.lcoe_discount_rate,
    )
