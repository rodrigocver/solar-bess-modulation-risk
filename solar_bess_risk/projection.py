"""Year-by-year economic projection for BESS scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import numpy as np

from solar_bess_risk.config import DEFAULT_RTE_COMMISSIONING_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

MAX_BESS_CALENDAR_YEARS = 30


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
    annual_soh: tuple[float, ...] = ()
    annual_bess_energy_mwh: tuple[float, ...] = ()
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


def soh_for_year(soh_table: dict[int, float] | None, year: int, fallback: float = 1.0) -> float:
    """Return SOH for a calendar year, clamping outside the supplier curve."""
    if not soh_table:
        return fallback
    if year in soh_table:
        return soh_table[year]
    first_year = min(soh_table)
    last_year = max(soh_table)
    if year < first_year:
        return soh_table[first_year]
    if year > last_year:
        return soh_table[last_year]
    previous_years = [candidate for candidate in soh_table if candidate <= year]
    return soh_table[max(previous_years)]


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
    must_mw: float | None = None,
    soh_table: dict[int, float] | None = None,
    tust_savings_brl_per_yr: float = 0.0,
) -> CashflowProjection:
    """Project payback and LCOS by re-simulating each future year with that year's RTE.

    The PLD/generation year is held constant for the selected scenario tab. The
    yearly RTE and SOH change along the supplier curve. SOH reduces installed
    energy capacity dynamically; calendar end of life is capped at 30 years.
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
    annual_soh: list[float] = []
    annual_bess_energy: list[float] = []
    discounted_o_and_m = 0.0
    discounted_discharge = 0.0
    annual_o_and_m = scenario.capex_brl * params.bess_o_and_m_pct_capex
    target_equivalent_cycles = MAX_BESS_CALENDAR_YEARS * 365.0
    target_lifetime_discharge = scenario.bess_energy_mwh * target_equivalent_cycles
    max_calendar_years = MAX_BESS_CALENDAR_YEARS
    price_profile = PriceProfile(pld, price_source, bq_submarket, start_year)

    projected_calendar_years = 0.0
    cycle_life_reached = target_lifetime_discharge <= 1e-10

    for offset in range(max_calendar_years):
        # Ano 0 is the commissioning/pre-operation year and is not counted.
        # Operational Year 1 corresponds to Ano 1 from the supplier curve.
        cashflow_year = start_year + offset + 1
        rte = rte_for_year(rte_table, cashflow_year, fallback_rte)
        soh = soh_for_year(soh_table, cashflow_year, 1.0)
        yearly_energy_mwh = scenario.bess_energy_mwh * soh
        yearly_scenario = replace(scenario, rte=rte, bess_energy_mwh=yearly_energy_mwh)
        # Use the solar year corresponding to the battery cycle year
        solar_year_idx = min(offset + 1, solar.n_years)
        yearly_dispatch = simulate_scenario(
            solar,
            price_profile,
            yearly_scenario,
            params,
            curtailment_series=curtailment_series,
            solar_year_idx=solar_year_idx,
            must_mw=must_mw,
        )

        # Year-specific net-balance calculation:
        # sem BESS = inverter-limited generation minus ONS curtailment;
        # com BESS = executed grid injection from the dispatch engine.
        _gen_lim, _gen_bess = solar.get_year_arrays(solar_year_idx)
        injection_sem = _gen_lim - yearly_dispatch.ons_curtailment_mwh
        injection_com = yearly_dispatch.grid_injection_mwh
        gross = float(np.sum((injection_com - injection_sem) * pld)) + tust_savings_brl_per_yr
        discharge_mwh = float(np.sum(yearly_dispatch.discharge_mwh))
        year_fraction = 1.0

        gross *= year_fraction
        net = gross - annual_o_and_m * year_fraction
        discharge_mwh *= year_fraction
        discount_factor = 1 / ((1 + params.lcoe_discount_rate) ** (offset + year_fraction))
        discounted_o_and_m += annual_o_and_m * year_fraction * discount_factor
        discounted_discharge += discharge_mwh * discount_factor

        annual_rte.append(rte)
        annual_soh.append(soh)
        annual_bess_energy.append(yearly_energy_mwh)
        annual_gross.append(gross)
        annual_net.append(net)
        annual_discharge.append(discharge_mwh)
        projected_calendar_years += year_fraction

        cumulative += net
        # Payback is reported as simple/nominal payback. LCOS remains discounted.
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
        annual_soh=tuple(annual_soh),
        annual_bess_energy_mwh=tuple(annual_bess_energy),
        projected_calendar_years=projected_calendar_years,
        target_lifetime_discharge_mwh=target_lifetime_discharge,
        target_equivalent_cycles=target_equivalent_cycles,
        cycle_life_reached=cycle_life_reached,
        lcoe_discount_rate=params.lcoe_discount_rate,
    )
