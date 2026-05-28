"""Year-by-year economic projection for BESS scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import numpy as np

from solar_bess_risk.config import DEFAULT_RTE_COMMISSIONING_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario


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
    annual_o_and_m = scenario.capex_brl * params.bess_o_and_m_pct_capex
    price_profile = PriceProfile(pld, price_source, bq_submarket, start_year)

    for offset in range(params.useful_life_years):
        cashflow_year = start_year + offset
        rte = rte_for_year(rte_table, cashflow_year, fallback_rte)
        annual_rte.append(rte)
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
        net = gross - annual_o_and_m
        discharge_mwh = float(np.sum(yearly_dispatch.discharge_mwh))

        annual_gross.append(gross)
        annual_net.append(net)
        annual_discharge.append(discharge_mwh)

        cumulative += net
        if payback is None and cumulative >= scenario.capex_brl:
            if net <= 0:
                payback = float(offset + 1)
            else:
                payback = offset + (scenario.capex_brl - previous) / net
        previous = cumulative

    lifetime_discharge = float(sum(annual_discharge))
    total_cost = scenario.capex_brl + annual_o_and_m * params.useful_life_years
    lcos = total_cost / lifetime_discharge if lifetime_discharge > 1e-10 else None

    return CashflowProjection(
        payback_years=payback,
        lifetime_net_savings_brl=cumulative,
        lcos_brl_per_mwh=lcos,
        lifetime_discharge_mwh=lifetime_discharge,
        annual_gross_savings_brl=tuple(annual_gross),
        annual_net_savings_brl=tuple(annual_net),
        annual_discharge_mwh=tuple(annual_discharge),
        annual_rte=tuple(annual_rte),
    )
