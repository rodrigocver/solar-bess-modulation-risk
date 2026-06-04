"""Risk metrics: VaR/CVaR, delta sensitivity, and efficient-frontier utilities.

Functions
---------
compute_var_cvar(daily_pnl, confidence) -> (var, cvar)
compute_daily_delta(prices_arr, peak_hours) -> np.ndarray (365,)
compute_delta_sensitivity(daily_delta, daily_net_sem, daily_net_com, pct) -> dict
identify_sweet_spot(results) -> str | None
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from solar_bess_risk.economics import ScenarioResult
    from solar_bess_risk.config import SimulationParams
    from solar_bess_risk.data_sources import PriceProfile
    from solar_bess_risk.profile import SolarProfile
    from solar_bess_risk.simulation import ScenarioDefinition


def compute_var_cvar(
    daily_pnl: np.ndarray,
    confidence: float = 0.95,
) -> tuple[float, float]:
    """Compute VaR and CVaR at *confidence* level on a daily P&L distribution.

    Parameters
    ----------
    daily_pnl : np.ndarray
        Array of shape (N,) with daily net P&L values (BRL). Negative values
        represent losses.
    confidence : float
        Confidence level, e.g. 0.95 for 95%. The VaR is the quantile at
        level ``(1 - confidence)`` — the threshold that the worst
        ``(1 - confidence)`` fraction of days falls below.

    Returns
    -------
    var : float
        Value at Risk: the (1-confidence) quantile of the distribution.
        Typically negative (a loss figure).
    cvar : float
        Conditional Value at Risk (Expected Shortfall): mean of all observations
        at or below *var*. Always <= *var*.

    Notes
    -----
    Both metrics are expressed as daily BRL figures. Multiply by 365 for the
    annual equivalent. A less-negative CVaR is *better* (less tail risk).
    """
    sorted_pnl = np.sort(daily_pnl)
    n = len(sorted_pnl)
    cutoff = int(np.floor((1.0 - confidence) * n))
    cutoff = max(cutoff, 1)  # always include at least the worst day
    var = float(sorted_pnl[cutoff - 1])
    cvar = float(sorted_pnl[:cutoff].mean())
    return var, cvar


def compute_daily_delta(
    prices_arr: np.ndarray,
    peak_hours: frozenset[int],
) -> np.ndarray:
    """Compute daily spread (delta) = mean(PLD at peak hours) - mean(PLD at off-peak).

    Parameters
    ----------
    prices_arr : np.ndarray
        Hourly PLD array, shape (8760,).
    peak_hours : frozenset[int]
        Hour-of-day indices considered peak (0-based).

    Returns
    -------
    np.ndarray
        Shape (365,) — daily delta in BRL/MWh. Positive values indicate the
        market paid more at peak than off-peak (favourable for BESS arbitrage).
    """
    peak_mask = np.array([h in peak_hours for h in range(24)], dtype=bool)
    off_peak_mask = ~peak_mask
    prices_daily = prices_arr[:8760].reshape(365, 24)

    # Guard against empty masks (edge case in unit tests)
    if not peak_mask.any() or not off_peak_mask.any():
        return np.zeros(365, dtype=np.float64)

    peak_mean = prices_daily[:, peak_mask].mean(axis=1)
    off_peak_mean = prices_daily[:, off_peak_mask].mean(axis=1)
    return (peak_mean - off_peak_mean).astype(np.float64)


def compute_delta_sensitivity(
    daily_delta: np.ndarray,
    daily_net_sem: np.ndarray,
    daily_net_com: np.ndarray,
    pct: float = 0.05,
) -> dict:
    """Summarise portfolio performance on the best and worst delta days.

    Parameters
    ----------
    daily_delta : np.ndarray
        Daily spread values, shape (365,), from :func:`compute_daily_delta`.
    daily_net_sem : np.ndarray
        Daily net balance without BESS, shape (365,), in BRL.
    daily_net_com : np.ndarray
        Daily net balance with BESS, shape (365,), in BRL.
    pct : float
        Fraction used to define tails. Default 0.05 = top/bottom 5% (~18 days).

    Returns
    -------
    dict
        Keys: ``"worst"``, ``"best"`` — each a sub-dict with:
        - ``"n_days"`` : int
        - ``"delta_mean_brl_mwh"`` : float — mean spread in the tail
        - ``"delta_min_brl_mwh"`` / ``"delta_max_brl_mwh"`` : float
        - ``"net_sem_mean_brl"`` : float — mean daily P&L without BESS
        - ``"net_com_mean_brl"`` : float — mean daily P&L with BESS
        - ``"bess_improvement_mean_brl"`` : float — net_com - net_sem mean
        - ``"net_sem_total_brl"`` : float — sum over tail days
        - ``"net_com_total_brl"`` : float — sum over tail days
    """
    n = len(daily_delta)
    n_tail = max(1, int(np.floor(pct * n)))

    sorted_idx = np.argsort(daily_delta)
    worst_idx = sorted_idx[:n_tail]
    best_idx = sorted_idx[-n_tail:]

    def _summary(idx: np.ndarray) -> dict:
        return {
            "n_days": int(len(idx)),
            "delta_mean_brl_mwh": float(daily_delta[idx].mean()),
            "delta_min_brl_mwh": float(daily_delta[idx].min()),
            "delta_max_brl_mwh": float(daily_delta[idx].max()),
            "net_sem_mean_brl": float(daily_net_sem[idx].mean()),
            "net_com_mean_brl": float(daily_net_com[idx].mean()),
            "bess_improvement_mean_brl": float(
                (daily_net_com[idx] - daily_net_sem[idx]).mean()
            ),
            "net_sem_total_brl": float(daily_net_sem[idx].sum()),
            "net_com_total_brl": float(daily_net_com[idx].sum()),
        }

    return {
        "worst": _summary(worst_idx),  # flat-market days — BESS idle risk
        "best": _summary(best_idx),    # high-spread days — BESS arbitrage value
    }


def compute_historical_risk_metrics(
    *,
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    curtailment_series: np.ndarray | None = None,
    confidence: float = 0.95,
    max_solar_years: int | None = None,
    must_mw: float | None = None,
) -> dict:
    """Compute VaR/CVaR using every available historical solar year.

    The same PLD profile is replayed against each solar year. The sem-BESS
    balance uses ``gen_lim_mw`` and ONS curtailment; the com-BESS balance uses
    the dispatch engine's executed grid injection. This keeps clipping and ONS
    curtailment separated and prevents double-counting.

    ``max_solar_years`` is intended for smoke tests only. Production reports
    should use every available solar year.
    """
    from solar_bess_risk.simulation import simulate_scenario

    daily_sem: list[np.ndarray] = []
    daily_com: list[np.ndarray] = []
    daily_delta = compute_daily_delta(prices.prices_brl_per_mwh, scenario.peak_hours)

    n_solar_years = solar.n_years
    if max_solar_years is not None:
        n_solar_years = max(1, min(solar.n_years, max_solar_years))

    for year_idx in range(1, n_solar_years + 1):
        dispatch = simulate_scenario(
            solar,
            prices,
            scenario,
            params,
            curtailment_series=curtailment_series,
            solar_year_idx=year_idx,
            must_mw=must_mw,
        )
        gen_lim, _gen_bess = solar.get_year_arrays(year_idx)
        injection_sem = gen_lim - dispatch.ons_curtailment_mwh
        injection_com = dispatch.grid_injection_mwh
        net_sem = (injection_sem - solar.garantia_fisica_mw) * prices.prices_brl_per_mwh
        net_com = (injection_com - solar.garantia_fisica_mw) * prices.prices_brl_per_mwh
        daily_sem.append(net_sem.reshape(365, 24).sum(axis=1))
        daily_com.append(net_com.reshape(365, 24).sum(axis=1))

    daily_net_sem = np.concatenate(daily_sem)
    daily_net_com = np.concatenate(daily_com)
    daily_delta_all = np.tile(daily_delta, n_solar_years)
    var_sem, cvar_sem = compute_var_cvar(daily_net_sem, confidence=confidence)
    var_com, cvar_com = compute_var_cvar(daily_net_com, confidence=confidence)
    sensitivity = compute_delta_sensitivity(daily_delta_all, daily_net_sem, daily_net_com)

    return {
        "n_solar_years": int(n_solar_years),
        "n_days": int(len(daily_net_sem)),
        "confidence": float(confidence),
        "daily_net_sem_brl": daily_net_sem,
        "daily_net_com_brl": daily_net_com,
        "daily_delta": daily_delta_all,
        "var_95_sem_bess_brl": var_sem,
        "cvar_95_sem_bess_brl": cvar_sem,
        "var_95_com_bess_brl": var_com,
        "cvar_95_com_bess_brl": cvar_com,
        "risk_constraint_met": bool(cvar_com >= cvar_sem),
        "worst5pct_summary": sensitivity["worst"],
        "best5pct_summary": sensitivity["best"],
    }


def identify_sweet_spot(results: list[ScenarioResult]) -> str | None:
    """Return the label of the BESS scenario at the efficient-frontier sweet spot.

    The sweet spot is the scenario where the marginal improvement in CVaR (tail
    risk reduction) per BRL of additional CAPEX starts decelerating — i.e., the
    point of diminishing returns on risk-adjusted CAPEX.

    Excludes the Base (0 MW) scenario from consideration.

    Parameters
    ----------
    results : list[ScenarioResult]
        Ordered list of scenario results (typically Base, A, B ...).

    Returns
    -------
    str | None
        Label of the sweet-spot scenario, or ``None`` if only one BESS scenario
        is available or no meaningful trend can be identified.
    """
    # Filter out Base (0 MWh) and invalid scenarios
    bess_results = [
        r for r in results
        if r.bess_energy_mwh > 0 and hasattr(r, "cvar_95_com_bess_brl")
    ]
    if len(bess_results) < 2:
        return bess_results[0].scenario.label if bess_results else None

    # Sort by CAPEX ascending
    bess_results = sorted(bess_results, key=lambda r: r.capex_brl)

    # Base CVaR (no BESS) — use the first result's sem_bess metrics
    base_cvar = results[0].cvar_95_sem_bess_brl if hasattr(results[0], "cvar_95_sem_bess_brl") else None

    # Compute marginal CVaR improvement per BRL of incremental CAPEX
    efficiencies: list[tuple[float, ScenarioResult]] = []
    prev_capex = 0.0
    prev_cvar = base_cvar if base_cvar is not None else bess_results[0].cvar_95_com_bess_brl

    for r in bess_results:
        delta_capex = r.capex_brl - prev_capex
        delta_cvar = r.cvar_95_com_bess_brl - prev_cvar  # positive = improvement
        if delta_capex > 0:
            efficiency = delta_cvar / delta_capex
        else:
            efficiency = float("nan")
        efficiencies.append((efficiency, r))
        prev_capex = r.capex_brl
        prev_cvar = r.cvar_95_com_bess_brl

    # Sweet spot: the last scenario where efficiency is still positive and
    # hasn't dropped by more than 50% of the best efficiency observed
    valid = [(eff, r) for eff, r in efficiencies if not np.isnan(eff) and eff > 0]
    if not valid:
        return bess_results[-1].scenario.label

    best_eff = max(e for e, _ in valid)
    threshold = best_eff * 0.5  # diminishing returns threshold

    sweet_spot = valid[0][1]
    for eff, r in valid:
        if eff >= threshold:
            sweet_spot = r
        else:
            break

    return sweet_spot.scenario.label
