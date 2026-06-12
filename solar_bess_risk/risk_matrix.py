"""Risk matrix: PLD × curtailment sensitivity grid (additive feature).

This module expands the 2025 *base* scenario (no MUST reduction) across a grid
of PLD multipliers and curtailment targets, producing a standalone HTML report
(``matriz_risco.html``). It does **not** touch the existing 2025/2026 pipeline.

Per cell it reports four metrics, consistent with the executive pitch table:

- Modulação s/ BESS (R$/MWh)
- Modulação c/ BESS (R$/MWh)
- Modulação de Equilíbrio s/ BESS (R$/MWh)
- Caixa Adicionado Total (R$ MM/ano)

The PLD axis scales the 2025 base PLD profile by a multiplier; the curtailment
axis scales the 2025 base curtailment fraction profile so each column reaches a
target annual curtailment/generation percentage.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from solar_bess_risk.config import (
    DEFAULT_MODULATION_MODE,
    RISK_MATRIX_CURTAILMENT_TARGETS_PCT,
    RISK_MATRIX_PLD_FACTORS,
    SimulationParams,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.modulation import modulation_value_brl_per_mwh
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario


# ---------------------------------------------------------------------------
# Self-contained modulation / premium math (mirrors bess_pitch_agent.py)
# ---------------------------------------------------------------------------


def _modulation_value_brl_per_mwh(
    injection_mwh: np.ndarray,
    pld_brl_per_mwh: np.ndarray,
    gf_energy_mwh: float,
    mode: str = DEFAULT_MODULATION_MODE,
) -> float | None:
    """Modulation metric (R$/MWh) — delegates to the centralized implementation."""
    return modulation_value_brl_per_mwh(
        injection_mwh, pld_brl_per_mwh, gf_energy_mwh, mode
    )


def _daily_price_scale_mask(discharge_mwh: np.ndarray, hours_per_day: int = 24) -> np.ndarray:
    """Mark every hour of each day in which the BESS discharged."""
    discharge = np.asarray(discharge_mwh, dtype=np.float64) > 1e-10
    mask = np.zeros_like(discharge, dtype=bool)
    for start in range(0, len(discharge), hours_per_day):
        end = min(start + hours_per_day, len(discharge))
        if np.any(discharge[start:end]):
            mask[start:end] = True
    return mask


def annual_insurance_premium_brl(scenario: ScenarioDefinition, params: SimulationParams) -> float:
    """Annual insurance premium = CAPEX annuity + annual O&M (BRL).

    Mirrors ``bess_pitch_agent.calcular_premio_seguro`` but is computed directly
    from the scenario/params instead of parsing HTML. Uses ``lcoe_discount_rate``
    as the WACC and ``useful_life_years`` as the annuity horizon.
    """
    capex_total = float(scenario.capex_brl)
    opex_anual = capex_total * params.bess_o_and_m_pct_capex
    wacc = params.lcoe_discount_rate
    nper = max(1, int(params.useful_life_years))
    if wacc > 0:
        annuity = capex_total * wacc / (1.0 - (1.0 + wacc) ** (-nper))
    else:
        annuity = capex_total / nper
    return annuity + opex_anual


def _equilibrium_modulation_brl_per_mwh(
    *,
    injection_sem: np.ndarray,
    injection_com: np.ndarray,
    pld: np.ndarray,
    discharge_mwh: np.ndarray,
    gf_energy_mwh: float,
    premium_brl: float,
    mode: str = DEFAULT_MODULATION_MODE,
) -> float | None:
    """Modulação de equilíbrio s/ BESS.

    Scales the PLD of every hour of discharge days by a linear factor solved so
    that the BESS cash added equals the annual premium, then recomputes the
    modulation without BESS under that re-priced PLD.
    """
    pld_arr = np.asarray(pld, dtype=np.float64)
    mask = _daily_price_scale_mask(discharge_mwh)
    delta = np.asarray(injection_com, dtype=np.float64) - np.asarray(injection_sem, dtype=np.float64)

    cash_without_scaled = float(np.sum(delta[~mask] * pld_arr[~mask]))
    cash_scaled_at_1 = float(np.sum(delta[mask] * pld_arr[mask]))
    if abs(cash_scaled_at_1) <= 1e-10:
        return None

    factor = (premium_brl - cash_without_scaled) / cash_scaled_at_1
    if factor < 0 or not np.isfinite(factor):
        return None

    pld_eq = pld_arr.copy()
    pld_eq[mask] *= factor
    value = _modulation_value_brl_per_mwh(injection_sem, pld_eq, gf_energy_mwh, mode)
    if value is None or not np.isfinite(value):
        return None
    return float(value)


# ---------------------------------------------------------------------------
# Matrix data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskMatrixCell:
    """One (PLD factor × curtailment target) cell of the risk matrix."""

    pld_factor: float
    curtailment_target_pct: float
    curtailment_factor: float
    realized_curtailment_pct: float
    mod_sem_bess: float | None
    mod_com_bess: float | None
    mod_equilibrio: float | None
    caixa_adicionado_mm: float


@dataclass(frozen=True)
class RiskMatrixResult:
    """Full PLD × curtailment matrix plus axis metadata."""

    pld_factors: tuple[float, ...]
    curtailment_targets_pct: tuple[float, ...]
    base_curtailment_pct: float
    premium_brl: float
    cells: tuple[tuple[RiskMatrixCell, ...], ...]  # indexed [pld_idx][curt_idx]


def _ons_curt_pct(ons_mw: np.ndarray, sum_gen_lim: float) -> float:
    """ONS curtailment as a % of generation (external grid curtailment only).

    This is the *ONS-only* metric (~11.1% for the base 2025 profile), excluding
    the inverter-clipping component (``gen_bess - gen_lim``) that the BESS
    recovers. The risk matrix anchors its curtailment axis on this ONS figure
    and scales it up to the 15/20/25/30 % stress scenarios.
    """
    if sum_gen_lim <= 0:
        return 0.0
    return 100.0 * float(np.sum(ons_mw)) / sum_gen_lim


def compute_risk_matrix(
    *,
    solar: SolarProfile,
    base_pld: np.ndarray,
    base_curtailment_pct_profile: np.ndarray | None,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    bq_submarket: str,
    base_year: int = 2025,
    pld_factors: tuple[float, ...] = RISK_MATRIX_PLD_FACTORS,
    curtailment_targets_pct: tuple[float, ...] = RISK_MATRIX_CURTAILMENT_TARGETS_PCT,
) -> RiskMatrixResult:
    """Build the PLD × curtailment risk matrix for the base (no-MUST) scenario.

    Parameters
    ----------
    solar : SolarProfile
        Loaded solar profile (year 1 arrays are used).
    base_pld : np.ndarray
        2025 base hourly PLD (R$/MWh), shape (8760,).
    base_curtailment_pct_profile : np.ndarray | None
        2025 base hourly curtailment fraction (0–1), shape (8760,). ``None``
        disables curtailment for every cell (all factors collapse to no curt).
    scenario : ScenarioDefinition
        4h BESS scenario definition (no MUST).
    params : SimulationParams
        Simulation parameters.
    bq_submarket : str
        Submarket label for the synthetic ``PriceProfile``.
    base_year : int
        Calendar year used for the synthetic ``PriceProfile`` (default 2025).
    pld_factors, curtailment_targets_pct : tuple[float, ...]
        Grid axes.

    Returns
    -------
    RiskMatrixResult
        Computed grid plus axis metadata.
    """
    gen_lim, gen_bess = solar.get_year_arrays(1)
    gen_lim = np.asarray(gen_lim, dtype=np.float64)
    gen_bess = np.asarray(gen_bess, dtype=np.float64)
    gf = float(solar.garantia_fisica_mw)
    gf_energy = gf * len(base_pld)
    premium_brl = annual_insurance_premium_brl(scenario, params)
    modulation_mode = getattr(params, "modulation_mode", DEFAULT_MODULATION_MODE)

    sum_gen_lim = float(np.sum(gen_lim))

    if base_curtailment_pct_profile is not None and sum_gen_lim > 0:
        ons_base_mw = np.asarray(base_curtailment_pct_profile, dtype=np.float64) * gen_lim
        # Base curtailment % = ONS-only figure (~11.1%), excluding inverter
        # clipping. The axis scenarios (15/20/25/30 %) scale this ONS curtailment.
        base_curt_pct = _ons_curt_pct(ons_base_mw, sum_gen_lim)
    else:
        ons_base_mw = None
        base_curt_pct = 0.0

    # Scale the ONS curtailment from its base (~11.1%) up to each target column.
    curt_factors: list[float] = []
    for target_pct in curtailment_targets_pct:
        if ons_base_mw is None or base_curt_pct <= 1e-9:
            curt_factors.append(0.0)
        else:
            curt_factors.append(float(target_pct) / base_curt_pct)

    rows: list[tuple[RiskMatrixCell, ...]] = []
    for pld_factor in pld_factors:
        pld = np.asarray(base_pld, dtype=np.float64) * float(pld_factor)
        price_profile = PriceProfile(
            pld,
            f"risk_matrix_pld_{base_year}_x{pld_factor:.2f}",
            bq_submarket,
            base_year,
        )
        row_cells: list[RiskMatrixCell] = []
        for target_pct, curt_factor in zip(curtailment_targets_pct, curt_factors):
            if ons_base_mw is None or base_curt_pct <= 1e-9:
                curt_series = None
            else:
                # Scaled ONS curtailment (MW); the dispatch still adds the fixed
                # inverter clipping internally via min(gen_bess, ons + clip).
                curt_series = curt_factor * ons_base_mw

            dispatch = simulate_scenario(
                solar,
                price_profile,
                scenario,
                params,
                curtailment_series=curt_series,
            )

            injection_sem = gen_lim - np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64)
            injection_com = np.asarray(dispatch.grid_injection_mwh, dtype=np.float64)

            mod_sem = _modulation_value_brl_per_mwh(injection_sem, pld, gf_energy, modulation_mode)
            mod_com = _modulation_value_brl_per_mwh(injection_com, pld, gf_energy, modulation_mode)
            net_sem = float(np.sum((injection_sem - gf) * pld))
            net_com = float(np.sum((injection_com - gf) * pld))
            caixa_mm = (net_com - net_sem) / 1e6
            mod_eq = _equilibrium_modulation_brl_per_mwh(
                injection_sem=injection_sem,
                injection_com=injection_com,
                pld=pld,
                discharge_mwh=dispatch.discharge_mwh,
                gf_energy_mwh=gf_energy,
                premium_brl=premium_brl,
                mode=modulation_mode,
            )

            # Realized ONS curtailment % (scaled base, excludes inverter clipping).
            if ons_base_mw is None:
                realized_pct = 0.0
            else:
                realized_pct = _ons_curt_pct(
                    np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64), sum_gen_lim
                )

            row_cells.append(
                RiskMatrixCell(
                    pld_factor=float(pld_factor),
                    curtailment_target_pct=float(target_pct),
                    curtailment_factor=curt_factor,
                    realized_curtailment_pct=realized_pct,
                    mod_sem_bess=mod_sem,
                    mod_com_bess=mod_com,
                    mod_equilibrio=mod_eq,
                    caixa_adicionado_mm=caixa_mm,
                )
            )
        rows.append(tuple(row_cells))

    return RiskMatrixResult(
        pld_factors=tuple(float(f) for f in pld_factors),
        curtailment_targets_pct=tuple(float(t) for t in curtailment_targets_pct),
        base_curtailment_pct=base_curt_pct,
        premium_brl=premium_brl,
        cells=tuple(rows),
    )


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------


def _fmt_mod(value: float | None) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"R$ {value:.0f}/MWh"


def _fmt_caixa(value: float) -> str:
    return f"+ R$ {value:.0f} MM"


def _vivid_style(is_good: bool) -> str:
    """Binary vivid colour (no gradient).

    Green when the BESS reaches the annual premium for that scenario, red when it
    does not. White text for contrast on the saturated background.
    """
    if is_good:
        return "background-color:#15a34a; color:#fff;"
    return "background-color:#e11d48; color:#fff;"


def _cell_reaches_premium(cell: "RiskMatrixCell", premio_mm: float) -> bool:
    """The BESS is 'good' (green) when the cash it adds covers the annual premium."""
    caixa = cell.caixa_adicionado_mm
    if caixa is None or not np.isfinite(caixa):
        return False
    return caixa >= premio_mm


def _modulation_table(result: RiskMatrixResult, premio_mm: float) -> str:
    """Combined quadro: modulação s/ BESS and c/ BESS in the same cell.

    Coloured with the binary green/red premium criterion.
    """
    col_headers = "".join(
        f"<th>{t:.0f}% curtailment</th>" for t in result.curtailment_targets_pct
    )
    body_rows = []
    for pld_factor, row in zip(result.pld_factors, result.cells):
        cells_html = []
        for cell in row:
            style = _vivid_style(_cell_reaches_premium(cell, premio_mm))
            sem = _fmt_mod(cell.mod_sem_bess)
            com = _fmt_mod(cell.mod_com_bess)
            cells_html.append(
                f'<td style="{style}"><div class="mod-pair">'
                f'<span class="mod-row"><b>s/ BESS</b> {sem}</span>'
                f'<span class="mod-row"><b>c/ BESS</b> {com}</span>'
                f"</div></td>"
            )
        label = f"PLD ×{pld_factor:.2f}"
        if abs(pld_factor - 1.0) < 1e-9:
            label += " (2025)"
        body_rows.append(
            f'<tr><th class="row-head">{label}</th>{"".join(cells_html)}</tr>'
        )
    return f"""
    <div class="matrix-block">
        <h2>Modulação s/ BESS &amp; c/ BESS (R$/MWh)</h2>
        <table>
            <thead><tr><th class="corner">PLD \\ Curtailment</th>{col_headers}</tr></thead>
            <tbody>{"".join(body_rows)}</tbody>
        </table>
    </div>"""


def _metric_table(
    result: RiskMatrixResult,
    premio_mm: float,
    *,
    title: str,
    extractor,
    formatter,
) -> str:
    """Render one metric as a PLD (rows) × curtailment (cols) table.

    Cells use the binary green/red premium criterion (no colour gradient).
    """
    col_headers = "".join(
        f"<th>{t:.0f}% curtailment</th>" for t in result.curtailment_targets_pct
    )
    body_rows = []
    for pld_factor, row in zip(result.pld_factors, result.cells):
        cells_html = []
        for cell in row:
            raw = extractor(cell)
            style = _vivid_style(_cell_reaches_premium(cell, premio_mm))
            if raw is None or not np.isfinite(raw):
                cells_html.append(f'<td style="{style}">n/a</td>')
            else:
                cells_html.append(f'<td style="{style}">{formatter(raw)}</td>')
        label = f"PLD ×{pld_factor:.2f}"
        if abs(pld_factor - 1.0) < 1e-9:
            label += " (2025)"
        body_rows.append(
            f'<tr><th class="row-head">{label}</th>{"".join(cells_html)}</tr>'
        )

    return f"""
    <div class="matrix-block">
        <h2>{title}</h2>
        <table>
            <thead><tr><th class="corner">PLD \\ Curtailment</th>{col_headers}</tr></thead>
            <tbody>{"".join(body_rows)}</tbody>
        </table>
    </div>"""


def build_risk_matrix_html(
    result: RiskMatrixResult,
    output_path: str,
    *,
    project_name: str = "Projeto Solar",
) -> str:
    """Render the risk matrix to a standalone HTML file. Returns the path."""
    premio_mm = result.premium_brl / 1e6

    tables = "".join(
        [
            _modulation_table(result, premio_mm),
            _metric_table(
                result,
                premio_mm,
                title="Caixa Adicionado Total (R$ MM/ano)",
                extractor=lambda c: c.caixa_adicionado_mm,
                formatter=lambda v: _fmt_caixa(v),
            ),
        ]
    )

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Matriz de Risco — BESS {project_name}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
:root {{ --navy:#0f172a; --blue:#1d4ed8; --green:#059669; --bg:#f8fafc; --border:#e2e8f0; --muted:#64748b; }}
* {{ margin:0; padding:0; box-sizing:border-box; font-family:'Inter',sans-serif; }}
body {{ background:#e2e8f0; color:#1e293b; padding:2rem; }}
.container {{ max-width:1500px; margin:0 auto; background:#fff; border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,.05); padding:2rem; }}
.header h1 {{ font-size:1.7rem; font-weight:800; color:var(--navy); text-transform:uppercase; letter-spacing:.5px; }}
.header h1 span {{ color:var(--blue); }}
.header p {{ color:var(--muted); font-weight:600; margin-top:.25rem; }}
.summary {{ display:flex; gap:2rem; background:var(--navy); color:#fff; padding:1rem 2rem; border-radius:8px; margin:1.5rem 0 2rem; flex-wrap:wrap; }}
.summary .item .lbl {{ font-size:.72rem; color:#94a3b8; font-weight:700; text-transform:uppercase; }}
.summary .item .val {{ font-size:1.15rem; font-weight:700; }}
.matrix-block {{ margin-bottom:2.5rem; }}
.matrix-block h2 {{ font-size:1.15rem; font-weight:700; color:var(--navy); margin-bottom:.75rem; padding-left:.6rem; border-left:4px solid var(--blue); }}
table {{ width:100%; border-collapse:collapse; text-align:center; }}
th {{ background:#1e293b; color:#fff; padding:.8rem; font-size:.8rem; text-transform:uppercase; letter-spacing:.4px; border:1px solid #1e293b; }}
th.corner {{ background:#0f172a; }}
td, th.row-head {{ padding:.9rem .6rem; border:1px solid var(--border); font-size:1rem; font-weight:700; }}
th.row-head {{ background:var(--bg); color:var(--navy); text-align:left; white-space:nowrap; }}
.mod-pair {{ display:flex; flex-direction:column; gap:.2rem; line-height:1.25; }}
.mod-pair .mod-row {{ font-size:.95rem; white-space:nowrap; }}
.mod-pair .mod-row b {{ font-weight:800; opacity:.85; font-size:.66rem; text-transform:uppercase; letter-spacing:.3px; margin-right:.35rem; }}
.legend {{ display:flex; gap:1.5rem; align-items:center; margin:0 0 1.5rem; font-weight:700; font-size:.85rem; color:var(--navy); flex-wrap:wrap; }}
.legend .swatch {{ display:inline-block; width:1rem; height:1rem; border-radius:3px; vertical-align:middle; margin-right:.45rem; }}
.note {{ font-size:.85rem; color:var(--muted); font-weight:600; margin-top:1rem; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>Matriz de Risco — BESS <span>{project_name}</span></h1>
    <p>Sensibilidade PLD × Curtailment (cenário base, sem redução de MUST)</p>
  </div>
  <div class="summary">
    <div class="item"><div class="lbl">Prêmio Anual</div><div class="val">R$ {premio_mm:.0f} MM / ano</div></div>
    <div class="item"><div class="lbl">Curtailment ONS base 2025</div><div class="val">{result.base_curtailment_pct:.1f}%</div></div>
    <div class="item"><div class="lbl">Fatores PLD</div><div class="val">{", ".join(f"{f:.2f}" for f in result.pld_factors)}</div></div>
    <div class="item"><div class="lbl">Alvos Curtailment</div><div class="val">{", ".join(f"{t:.0f}%" for t in result.curtailment_targets_pct)}</div></div>
  </div>
  <div class="legend">
    <span><span class="swatch" style="background:#15a34a"></span>BESS atinge o prêmio anual (Caixa Adicionado ≥ Prêmio)</span>
    <span><span class="swatch" style="background:#e11d48"></span>BESS não atinge o prêmio anual</span>
  </div>
  {tables}
  <p class="note">
    Eixo PLD: multiplicador aplicado ao PLD base de 2025. Eixo Curtailment:
    curtailment ONS de 2025 (base {result.base_curtailment_pct:.1f}%) escalado para atingir o
    percentual-alvo de curtailment ONS/geração. O clipping de inversor recuperado
    pelo BESS não é escalado (entra fixo no despacho).
  </p>
</div>
</body>
</html>"""

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return output_path
