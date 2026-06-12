"""Consultancy-style HTML report for board presentation.

Generates a professional report with averaged hourly charts showing:
- Solar generation profile
- BESS charge/discharge patterns
- Curtailment total vs recovered
- Deficit reduction with BESS
- Financial exposure reduction

All charts use mean hourly profiles (24h) for clarity.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from solar_bess_risk.config import (
    CAPEX_USD_PER_KWH,
    DEFAULT_MODULATION_MODE,
    HOURS_PER_YEAR,
)
from solar_bess_risk.modulation import modulation_value_brl_per_mwh
from solar_bess_risk.simulation import DispatchResult


def _split_curtailment(dispatch: DispatchResult) -> tuple[np.ndarray, np.ndarray]:
    """Split available curtailment into technical and MUST-policy components.

    The dispatch lumps three sources into a single ``curtailment_mwh`` array:
    external ONS curtailment, inverter clipping released by the BESS (both
    *technical*), and the energy above the MUST injection cap. When the MUST is
    deliberately reduced to capture TUST savings, the latter portion is a
    *policy* cut, not a technical loss, so consultancy KPIs must report it
    separately to avoid overstating technical curtailment.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        ``(technical_mwh, must_policy_mwh)`` per hour. They sum to the total
        available curtailment (``dispatch.curtailment_mwh``).
    """
    total = dispatch.curtailment_mwh
    ons = dispatch.ons_curtailment_mwh
    clip = dispatch.clipping_available_mwh
    if ons is None:
        ons = total
    if clip is None:
        clip = np.zeros_like(total)
    technical = np.minimum(total, ons + clip)
    must_policy = np.maximum(0.0, total - technical)
    return technical, must_policy


def _scenario_from_data(data: tuple):
    """Return the ScenarioDefinition appended by the main pipeline, when present."""
    if len(data) > 8 and hasattr(data[8], "bess_energy_mwh"):
        return data[8]
    return None


def _projection_from_data(data: tuple):
    """Return the CashflowProjection appended by the main pipeline, when present."""
    if len(data) > 9 and hasattr(data[9], "lcos_brl_per_mwh"):
        return data[9]
    return None


def _risk_from_data(data: tuple):
    """Return historical risk metrics appended by the main pipeline, when present."""
    if len(data) > 10 and isinstance(data[10], dict):
        return data[10]
    return None


def _hourly_mean_profile(arr: np.ndarray) -> np.ndarray:
    """Compute mean value per hour-of-day from an 8760 array."""
    reshaped = arr[:8760].reshape(365, 24)
    return reshaped.mean(axis=0)


def _modulation_value_brl_per_mwh(
    injection_mwh: np.ndarray,
    pld_brl_per_mwh: np.ndarray,
    gf_energy_mwh: float,
    mode: str = DEFAULT_MODULATION_MODE,
) -> float | None:
    """Thin wrapper around :func:`modulation_value_brl_per_mwh`.

    Kept for backward compatibility within this module; delegates to the
    centralized modulation implementation so the formula lives in one place.
    """
    return modulation_value_brl_per_mwh(
        injection_mwh, pld_brl_per_mwh, gf_energy_mwh, mode
    )


def _format_optional_brl_mwh(value: float | None) -> str:
    """Format an optional BRL/MWh value for report tables."""
    if value is None or not np.isfinite(value):
        return "n/a"
    return f"{value:,.2f}"


def _capex_brl_million_per_mwh(capex_brl: float, bess_energy_mwh: float) -> float | None:
    """Return BESS CAPEX in BRL million per installed MWh of energy capacity."""
    if bess_energy_mwh <= 1e-10:
        return None
    return float(capex_brl / 1e6 / bess_energy_mwh)


def _build_simulation_params_table(
    *,
    params,
    charge_mode: int,
    bq_submarket: str,
    mwac: float,
    garantia_fisica_mw: float,
    fc: float,
    effective_pld_factor_2026: float | None = None,
) -> str:
    """Build the simulation parameter table shown in the executive report."""
    if charge_mode == 3:
        charge_mode_label = "Modo 3 - Arbitragem day-ahead"
    else:
        charge_mode_label = "Modo 0 - Cobertura de deficit"

    rows = [
        ("Curva solar", getattr(params, "csv_path", "n/a")),
        ("Capacidade AC", f"{mwac:,.1f} MW"),
        ("Garantia fisica", f"{garantia_fisica_mw:,.1f} MW"),
        ("Fator de capacidade", f"{fc * 100:,.2f}%"),
        ("Submercado PLD", bq_submarket),
        ("USD/BRL", f"{getattr(params, 'usd_brl_rate', 0.0):,.2f}"),
        ("Modo de operacao", charge_mode_label),
        ("Vida util economica", f"{getattr(params, 'useful_life_years', 'n/a')} anos"),
        ("O&M anual BESS", f"{getattr(params, 'bess_o_and_m_pct_capex', 0.0) * 100:,.2f}% do CAPEX"),
        ("Payback", "simples (fluxo nominal, sem desconto)"),
        ("LCOS", f"descontado a {getattr(params, 'lcoe_discount_rate', 0.0) * 100:,.2f}% a.a."),
        ("RTE fallback", f"{getattr(params, 'bess_roundtrip_efficiency', 0.0) * 100:,.2f}%"),
    ]
    pld_factor = getattr(params, "pld_factor_2026", None)
    displayed_pld_factor = pld_factor if pld_factor is not None else effective_pld_factor_2026
    rows.append(
        ("Fator PLD 2026", f"{displayed_pld_factor:.4f}" if displayed_pld_factor is not None else "auto (BigQuery)")
    )
    rows.append(
        (
            "Premissa curtailment 2026",
            f"{getattr(params, 'curtailment_factor_2026', 1.0):.2f}\u00d7 Realizado 2025 "
            f"(alvo {getattr(params, 'curtailment_target_pct_2026', 20.0):.0f}% da gera\u00e7\u00e3o)",
        )
    )
    modulation_mode = getattr(params, "modulation_mode", DEFAULT_MODULATION_MODE)
    rows.append(
        (
            "C\u00e1lculo da modula\u00e7\u00e3o",
            "Energia (pr\u00eamio de captura, R$/MWh injetado)"
            if modulation_mode == DEFAULT_MODULATION_MODE
            else "Garantia f\u00edsica (custo, R$/MWh GF)",
        )
    )
    rows_html = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )
    return f"""<table class="params-table">
    <tbody>{rows_html}</tbody>
    </table>"""


def _build_generation_chart(
    generation_mw: np.ndarray,
    garantia_fisica_mw: float,
    mwac: float,
) -> str:
    """Chart: Average hourly solar generation vs garantia física."""
    hours = list(range(24))
    gen_profile = _hourly_mean_profile(generation_mw)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=gen_profile,
        mode='lines+markers',
        name='Geração Solar Média',
        line=dict(color='#f5a623', width=3),
        fill='tozeroy',
        fillcolor='rgba(245, 166, 35, 0.2)',
    ))
    fig.add_hline(
        y=garantia_fisica_mw,
        line_dash="dash", line_color="red", line_width=2,
        annotation_text=f"Garantia Física = {garantia_fisica_mw:.1f} MW",
        annotation_position="top right",
    )
    fig.add_hline(
        y=mwac,
        line_dash="dot", line_color="gray", line_width=1,
        annotation_text=f"Capacidade AC = {mwac:.0f} MW",
        annotation_position="bottom right",
    )
    fig.update_layout(
        title="Perfil Médio de Geração Solar (24h)",
        xaxis_title="Hora do Dia",
        yaxis_title="MW",
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=40, t=60, b=50),
    )
    fig.update_xaxes(dtick=1)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _find_typical_day(dispatch: DispatchResult) -> int:
    """Find a typical day: day with discharge closest to the daily median."""
    daily_discharge = dispatch.discharge_mwh.reshape(365, 24).sum(axis=1)
    # Pick a day that actually has both charge and discharge
    active_days = np.where(daily_discharge > 1e-10)[0]
    if len(active_days) == 0:
        return 0
    median_val = np.median(daily_discharge[active_days])
    idx = active_days[np.argmin(np.abs(daily_discharge[active_days] - median_val))]
    return int(idx)


def _build_charge_discharge_chart(
    dispatch: DispatchResult,
    peak_hours: frozenset[int],
    label: str,
) -> str:
    """Chart: Typical day charge and discharge profile (avoids averaging artifacts)."""
    hours = list(range(24))
    day_idx = _find_typical_day(dispatch)
    start = day_idx * 24

    charge_day = dispatch.charge_mwh[start:start + 24]
    discharge_day = dispatch.discharge_mwh[start:start + 24]
    soc_day = dispatch.soc_mwh[start:start + 24]

    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(go.Bar(
        x=hours, y=charge_day,
        name='Carga BESS',
        marker_color='#2196F3',
        opacity=0.7,
    ), secondary_y=False)

    fig.add_trace(go.Bar(
        x=hours, y=-discharge_day,
        name='Descarga BESS',
        marker_color='#E91E63',
        opacity=0.7,
    ), secondary_y=False)

    fig.add_trace(go.Scatter(
        x=hours, y=soc_day,
        mode='lines+markers',
        name='SoC',
        line=dict(color='#4CAF50', width=2, dash='dot'),
    ), secondary_y=True)

    # Highlight peak hours
    for h in sorted(peak_hours):
        fig.add_vrect(
            x0=h - 0.5, x1=h + 0.5,
            fillcolor="rgba(255, 152, 0, 0.1)",
            layer="below", line_width=0,
        )

    fig.update_layout(
        title=f"Dia Típico de Carga/Descarga — Cenário {label} (Dia {day_idx + 1})",
        xaxis_title="Hora do Dia",
        barmode='relative',
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=60, t=60, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_yaxes(title_text="MW (Carga +/ Descarga -)", secondary_y=False)
    fig.update_yaxes(title_text="SoC (MWh)", secondary_y=True)
    fig.update_xaxes(dtick=1)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_curtailment_chart(
    dispatch: DispatchResult,
) -> str:
    """Chart: Curtailment total vs recovered vs lost."""
    hours = list(range(24))
    curt_total = _hourly_mean_profile(dispatch.curtailment_mwh)
    curt_lost = _hourly_mean_profile(dispatch.curtailment_lost_mwh)
    curt_recovered = np.maximum(0.0, curt_total - curt_lost)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=hours, y=curt_recovered,
        name='Curtailment Recuperado (BESS)',
        marker_color='#4CAF50',
    ))
    fig.add_trace(go.Bar(
        x=hours, y=curt_lost,
        name='Curtailment Perdido',
        marker_color='#F44336',
        opacity=0.6,
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=curt_total,
        mode='lines+markers',
        name='Curtailment Total',
        line=dict(color='#FF9800', width=2, dash='dash'),
    ))
    fig.update_layout(
        title="Curtailment Médio Horário: Recuperado vs Perdido",
        xaxis_title="Hora do Dia",
        yaxis_title="MW",
        barmode='stack',
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=40, t=60, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(dtick=1)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_deficit_chart(
    dispatch: DispatchResult,
    garantia_fisica_mw: float,
) -> str:
    """Chart: Deficit without vs with BESS (mean hourly)."""
    hours = list(range(24))
    deficit_sem = _hourly_mean_profile(dispatch.deficit_mwh)
    deficit_com = _hourly_mean_profile(dispatch.residual_deficit_mwh)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=hours, y=deficit_sem,
        mode='lines',
        name='Déficit sem BESS',
        line=dict(color='#F44336', width=3),
        fill='tozeroy',
        fillcolor='rgba(244, 67, 54, 0.15)',
    ))
    fig.add_trace(go.Scatter(
        x=hours, y=deficit_com,
        mode='lines',
        name='Déficit com BESS',
        line=dict(color='#4CAF50', width=3),
        fill='tozeroy',
        fillcolor='rgba(76, 175, 80, 0.15)',
    ))
    fig.update_layout(
        title="Déficit Médio Horário: Impacto do BESS na Garantia Física",
        xaxis_title="Hora do Dia",
        yaxis_title="Déficit (MW)",
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=40, t=60, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(dtick=1)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_modulation_comparison_chart(
    results_by_key: dict[str, tuple],
    modulation_mode: str = DEFAULT_MODULATION_MODE,
) -> str:
    """Chart: modulation cost comparison across all scenarios."""
    labels = []
    mod_sem = []
    mod_com = []

    for tab_name, data in results_by_key.items():
        dispatch, pld, gf, gen = data[0], data[1], data[2], data[3]
        gf_energy = gf * HOURS_PER_YEAR
        injection_sem = gen - dispatch.ons_curtailment_mwh
        injection_com = dispatch.grid_injection_mwh
        labels.append(tab_name)
        mod_sem.append(_modulation_value_brl_per_mwh(injection_sem, pld, gf_energy, modulation_mode) or 0.0)
        mod_com.append(_modulation_value_brl_per_mwh(injection_com, pld, gf_energy, modulation_mode) or 0.0)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name='Modulação original',
        x=labels, y=mod_sem,
        marker_color='#F44336',
    ))
    fig.add_trace(go.Bar(
        name='Modulação com BESS',
        x=labels, y=mod_com,
        marker_color='#4CAF50',
    ))
    if modulation_mode == DEFAULT_MODULATION_MODE:
        chart_title = "Prêmio de Captura (Modulação por Energia) por Cenário"
        yaxis_title = "Modulação (R$/MWh injetado)"
    else:
        chart_title = "Redução do Custo de Modulação por Cenário"
        yaxis_title = "Modulação (R$/MWh GF)"
    fig.update_layout(
        title=chart_title,
        yaxis_title=yaxis_title,
        barmode='group',
        template="plotly_white",
        height=450,
        margin=dict(l=80, r=40, t=60, b=80),
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
    )
    fig.update_xaxes(tickangle=-45)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _build_coverage_chart(results_by_key: dict[str, tuple]) -> str:
    """Chart: Coverage percentage (reduction in deficit energy) per scenario."""
    labels = []
    coverages = []

    for tab_name, data in results_by_key.items():
        dispatch = data[0]
        deficit_sem = dispatch.deficit_mwh.sum()
        deficit_com = dispatch.residual_deficit_mwh.sum()
        cov = (1 - deficit_com / deficit_sem) * 100 if deficit_sem > 0 else 0
        labels.append(tab_name)
        coverages.append(cov)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=coverages,
        marker_color=['#2196F3' if c < 50 else '#4CAF50' if c < 80 else '#1B5E20' for c in coverages],
        text=[f"{c:.1f}%" for c in coverages],
        textposition='outside',
    ))
    fig.update_layout(
        title="Cobertura Energética: Redução do Déficit de Garantia Física",
        yaxis_title="Cobertura (%)",
        template="plotly_white",
        height=400,
        margin=dict(l=60, r=40, t=60, b=80),
        yaxis_range=[0, 105],
    )
    fig.update_xaxes(tickangle=-45)
    return fig.to_html(full_html=False, include_plotlyjs=False)


_CASE_LABELS: dict[int, str] = {2025: "Caso Geral", 2026: "Caso Estressado"}


def _build_comparative_summary(
    results_by_key: dict[str, tuple],
    must_reduction_by_key: dict[str, tuple] | None,
    mwac: float,
    usd_brl_rate: float,
    garantia_fisica_mw: float,
    fc: float,
    modulation_mode: str = DEFAULT_MODULATION_MODE,
) -> str:
    """Build the comparative summary grouped by backtest year.

    Each year renders its own KPI table (regular scenarios + the optional
    MUST-reduction scenario for that year). 2025 is labelled "Caso Geral" and
    2026 "Caso Estressado".

    Parameters
    ----------
    results_by_key : dict
        Regular per-scenario results. The year is ``data[6]``.
    must_reduction_by_key : dict | None
        Optional MUST-reduction scenarios (year in ``data[6]``), appended to
        the matching year's table.
    mwac, usd_brl_rate, garantia_fisica_mw, fc : float
        Forwarded to ``_build_kpi_table``.

    Returns
    -------
    str
        HTML fragment with one sub-section (h3 + table) per year.
    """
    reduction = must_reduction_by_key or {}

    # Preserve first-seen order of years across both dicts.
    years: list[int] = []
    for data in list(results_by_key.values()) + list(reduction.values()):
        year = data[6]
        if year not in years:
            years.append(year)

    sections: list[str] = []
    for year in years:
        grouped: dict[str, tuple] = {
            k: v for k, v in results_by_key.items() if v[6] == year
        }
        grouped.update({k: v for k, v in reduction.items() if v[6] == year})
        if not grouped:
            continue
        case_label = _CASE_LABELS.get(year, "Cenário")
        table = _build_kpi_table(grouped, mwac, usd_brl_rate, garantia_fisica_mw, fc, modulation_mode)
        sections.append(
            f'<h3 class="case-heading">{escape(case_label)} ({year})</h3>\n{table}'
        )

    return "\n".join(sections)


def _build_kpi_table(
    results_by_key: dict[str, tuple],
    mwac: float,
    usd_brl_rate: float,
    garantia_fisica_mw: float,
    fc: float,
    modulation_mode: str = DEFAULT_MODULATION_MODE,
) -> str:
    """Build a summary KPI table for the board."""
    rows_html = ""
    for tab_name, data in results_by_key.items():
        dispatch, pld, gf, gen, peak_hours, duration_h = data[0], data[1], data[2], data[3], data[4], data[5]
        rte = data[7] if len(data) > 7 else 1.0
        projection = _projection_from_data(data)
        risk_metrics = _risk_from_data(data)

        scenario = _scenario_from_data(data)
        if scenario is not None:
            bess_power = scenario.bess_power_mw
            bess_energy = scenario.bess_energy_mwh
            capex_brl = scenario.capex_brl
            n_blocks = round(bess_energy / 10.1)
        else:
            from solar_bess_risk.config import BESS_BLOCK_SPECS
            import math
            block = BESS_BLOCK_SPECS[duration_h]
            n_blocks = math.ceil(gf / block.block_power_mw)
            bess_power = n_blocks * block.block_power_mw
            bess_energy = n_blocks * block.block_energy_mwh
            capex_brl = bess_energy * 1000 * CAPEX_USD_PER_KWH[duration_h] * usd_brl_rate

        # Net balance (signed: positive = surplus, negative = exposure)
        # Sem BESS: inverter-limited generation minus external ONS curtailment.
        # Com BESS: executed grid injection from the dispatch engine.
        injection_sem = gen - dispatch.ons_curtailment_mwh
        injection_com = dispatch.grid_injection_mwh

        # Modulação referenciada à garantia física (obrigação de entrega).
        # custo = GF × PLD_médio − Σ(injeção × PLD), normalizado pela energia de GF.
        # A energia injetada abate o custo; a referência é sempre a GF, não a injeção.
        # Sem BESS: injection_sem; Com BESS: injection_com (despacho desloca entrega ao pico).
        gf_energy = gf * HOURS_PER_YEAR
        modulation_original = _modulation_value_brl_per_mwh(injection_sem, pld, gf_energy, modulation_mode)
        modulation_com_bess = _modulation_value_brl_per_mwh(injection_com, pld, gf_energy, modulation_mode)
        modulation_delta = (
            modulation_com_bess - modulation_original
            if modulation_original is not None and modulation_com_bess is not None
            else None
        )
        net_sem = float(((injection_sem - gf) * pld).sum())
        net_com = float(((injection_com - gf) * pld).sum())
        exp_sem = float((dispatch.deficit_mwh * pld).sum())
        exp_com = float((dispatch.residual_deficit_mwh * pld).sum())
        delta_exp = exp_sem - exp_com
        delta_exp_pct = delta_exp / exp_sem * 100.0 if abs(exp_sem) > 1e-10 else 0.0
        # Trade-off de redução de MUST (item 4.1), exibido propositadamente em
        # duas colunas separadas:
        #   - "economia" = Δ saldo de energia (net_com − net_sem), SEM TUST.
        #     Para as linhas de redução de MUST esta parcela tende a ser menor
        #     (ou negativa), pois cortar o topo do perfil reduz a receita de
        #     energia injetada.
        #   - "tust_savings" (coluna à parte) = economia recorrente de TUST.
        # A separação deixa claro que a redução de MUST "atrapalha" a economia de
        # energia, mas é compensada pela economia de TUST. O payback simples
        # (projeção nominal) soma ambas as parcelas; ver projection.project_cashflows_with_rte.
        economia = net_com - net_sem
        delta_saldo_pct = economia / abs(net_sem) * 100.0 if abs(net_sem) > 1e-10 else 0.0
        payback = (
            projection.payback_years
            if projection is not None and projection.payback_years is not None
            else capex_brl / economia if economia > 0 else float('inf')
        )
        lcos = projection.lcos_brl_per_mwh if projection is not None else None

        deficit_sem = dispatch.deficit_mwh.sum()
        deficit_com = dispatch.residual_deficit_mwh.sum()
        coverage = (1 - deficit_com / deficit_sem) * 100 if deficit_sem > 0 else 0

        curt_technical, curt_must_policy = _split_curtailment(dispatch)
        curt_total = float(np.sum(curt_technical))
        must_cut_total = float(np.sum(curt_must_policy))
        total_available = curt_total + must_cut_total
        gen_total = float(np.sum(gen))
        curt_recovered = total_available - float(dispatch.curtailment_lost_mwh.sum())
        curtailment_pct = (curt_total / gen_total * 100) if gen_total > 0 else 0
        must_cut_pct = (must_cut_total / gen_total * 100) if gen_total > 0 else 0
        curt_recovered_pct = (curt_recovered / total_available * 100) if total_available > 0 else 0
        # Split the technical curtailment into its external-grid (ONS) and
        # inverter-clipping (recovered by the BESS) components for the board.
        ons_total = float(np.sum(np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64)))
        # Clipping físico do inversor = max(0, gen_bess − gen_lim). É uma grandeza
        # independente do curtailment ONS (não um resíduo), medida diretamente do
        # despacho e normalizada pela geração limitada sem BESS (gen_lim).
        clip_total = float(np.sum(np.asarray(dispatch.clipping_available_mwh, dtype=np.float64)))
        curtailment_ons_pct = (ons_total / gen_total * 100) if gen_total > 0 else 0
        clipping_pct = (clip_total / gen_total * 100) if gen_total > 0 else 0

        missed_charge = float(dispatch.carga_nao_realizada_diaria_mwh.sum())

        payback_str = f"{payback:.1f}" if payback < 100 else "n/a"
        lcos_str = f"{lcos:,.0f}" if lcos is not None else "n/a"
        cvar_sem = risk_metrics["cvar_95_sem_bess_brl"] if risk_metrics else None
        cvar_com = risk_metrics["cvar_95_com_bess_brl"] if risk_metrics else None
        cvar_delta = (cvar_com - cvar_sem) if cvar_sem is not None and cvar_com is not None else None
        cvar_delta_str = f"{cvar_delta / 1e3:,.1f}" if cvar_delta is not None else "n/a"

        # TUST savings from MUST reduction (index 11, only present for MUST-reduction rows)
        tust_savings_brl = data[11] if len(data) > 11 and data[11] is not None else None
        tust_savings_str = f"{tust_savings_brl / 1e6:,.2f}" if tust_savings_brl is not None else "—"

        rows_html += f"""<tr>
            <td>{escape(tab_name)}</td>
            <td>{bess_power:.2f} ({n_blocks} blocos)</td>
            <td>{bess_energy:.1f}</td>
            <td>{_format_optional_brl_mwh(_capex_brl_million_per_mwh(capex_brl, bess_energy))}</td>
            <td>{_format_optional_brl_mwh(modulation_original)}</td>
            <td>{_format_optional_brl_mwh(modulation_com_bess)}</td>
            <td>{_format_optional_brl_mwh(modulation_delta)}</td>
            <td>{delta_exp / 1e6:,.2f}</td>
            <td>{delta_exp_pct:,.1f}%</td>
            <td>{economia / 1e6:,.2f}</td>
            <td>{tust_savings_str}</td>
            <td>{delta_saldo_pct:,.1f}%</td>
            <td>{coverage:.1f}%</td>
            <td>{curtailment_ons_pct:.1f}%</td>
            <td>{clipping_pct:.1f}%</td>
            <td>{must_cut_pct:.1f}%</td>
            <td>{curt_recovered_pct:.1f}%</td>
            <td>{cvar_delta_str}</td>
            <td>{missed_charge:,.0f}</td>
            <td>{payback_str}</td>
            <td>{lcos_str}</td>
        </tr>"""

    return f"""<table class="kpi-table">
    <thead><tr>
        <th>Cenário</th>
        <th>Potência BESS (MW)</th>
        <th>Energia BESS (MWh)</th>
        <th title="CAPEX do BESS em milhões de reais dividido pela capacidade energética instalada.">CAPEX (R$ MM/MWh)</th>
        <th title="Custo de modulação referenciado à garantia física, sem BESS: PLD médio − Σ(injeção sem BESS × PLD) / energia de GF.">Modulação Original (R$/MWh)</th>
        <th title="Custo de modulação referenciado à garantia física, com BESS: PLD médio − Σ(injeção com BESS × PLD) / energia de GF.">Modulação c/ BESS (R$/MWh)</th>
        <th title="Modulação c/ BESS menos modulação original. Negativo = BESS reduz o custo de modulação.">Δ Modulação (R$/MWh)</th>
        <th title="Exposição sem BESS menos exposição com BESS. Positivo = redução de exposição.">Δ Exposição (R$ MM/ano)</th>
        <th title="Δ Exposição dividido pela exposição sem BESS.">Δ Exposição (%)</th>
        <th title="Saldo líquido com BESS menos saldo líquido sem BESS. Positivo = ganho financeiro líquido do BESS.">Δ Saldo Líquido (R$ MM/ano)</th>
        <th title="Economia anual de TUST pela redução de MUST contratada. Presente apenas no cenário de otimização de MUST.">Economia MUST Anual (R$ MM/ano)</th>
        <th title="Δ Saldo Líquido dividido pelo módulo do saldo líquido sem BESS.">Δ Saldo Líquido (%)</th>
        <th>Cobertura GF</th>
        <th title="Curtailment externo do ONS (corte de rede) sobre a geração. Não inclui o clipping de inversor nem o corte por redução de MUST.">Curtailment ONS / Geração</th>
        <th title="Clipping físico de inversor = max(0, geração com BESS − geração limitada sem BESS), sobre a geração limitada sem BESS. Grandeza independente do corte do ONS.">Clipping / Geração</th>
        <th title="Energia cortada para respeitar o MUST contratado (reduzido). É uma decisão de política comercial para capturar economia de TUST, não uma perda técnica.">Corte MUST / Geração</th>
        <th>Curtailment Recuperado</th>
        <th>Δ CVaR 95% (R$ mil/dia)</th>
        <th>Carga Não Realizada (MWh/ano)</th>
        <th title="Payback simples: fluxo nominal acumulado, sem desconto.">Payback simples (anos)</th>
        <th title="LCOS calculado com taxa de desconto informada nas premissas.">LCOS descontado (R$/MWh)</th>
    </tr></thead>
    <tbody>{rows_html}</tbody>
    </table>"""


def _build_scenario_tab_content(
    tab_name: str,
    data: tuple,
    mwac: float,
    usd_brl_rate: float,
    garantia_fisica_mw: float,
) -> str:
    """Build the HTML content for one scenario tab."""
    import math
    from solar_bess_risk.config import BESS_BLOCK_SPECS

    dispatch: DispatchResult = data[0]
    pld = data[1]
    gf = data[2]
    gen = data[3]
    peak_hours = data[4]
    duration_h = data[5]
    rte = data[7] if len(data) > 7 else 1.0
    projection = _projection_from_data(data)
    risk_metrics = _risk_from_data(data)

    scenario = _scenario_from_data(data)
    if scenario is not None:
        block = BESS_BLOCK_SPECS[duration_h]
        bess_power = scenario.bess_power_mw
        bess_energy = scenario.bess_energy_mwh
        capex_brl = scenario.capex_brl
        n_blocks = round(bess_energy / block.block_energy_mwh)
    else:
        block = BESS_BLOCK_SPECS[duration_h]
        n_blocks = math.ceil(gf / block.block_power_mw)
        bess_power = n_blocks * block.block_power_mw
        bess_energy = n_blocks * block.block_energy_mwh
        capex_brl = bess_energy * 1000 * CAPEX_USD_PER_KWH[duration_h] * usd_brl_rate

    # Compute KPIs for this scenario
    exp_sem = float((dispatch.deficit_mwh * pld).sum())
    exp_com = float((dispatch.residual_deficit_mwh * pld).sum())
    injection_sem = gen - dispatch.ons_curtailment_mwh
    injection_com = dispatch.grid_injection_mwh
    net_sem = float(((injection_sem - gf) * pld).sum())
    net_com = float(((injection_com - gf) * pld).sum())
    economia = net_com - net_sem
    payback = (
        projection.payback_years
        if projection is not None and projection.payback_years is not None
        else capex_brl / economia if economia > 0 else float('inf')
    )
    lcos = projection.lcos_brl_per_mwh if projection is not None else None
    deficit_sem = dispatch.deficit_mwh.sum()
    deficit_com = dispatch.residual_deficit_mwh.sum()
    coverage = (1 - deficit_com / deficit_sem) * 100 if deficit_sem > 0 else 0
    curt_technical, curt_must_policy = _split_curtailment(dispatch)
    curt_total = float(np.sum(curt_technical))
    must_cut_total = float(np.sum(curt_must_policy))
    total_available = curt_total + must_cut_total
    gen_total = float(np.sum(gen))
    curt_recovered = total_available - float(dispatch.curtailment_lost_mwh.sum())
    curtailment_pct = (curt_total / gen_total * 100) if gen_total > 0 else 0
    must_cut_pct = (must_cut_total / gen_total * 100) if gen_total > 0 else 0
    curt_recovered_pct = (curt_recovered / total_available * 100) if total_available > 0 else 0
    missed_charge_total = float(dispatch.carga_nao_realizada_diaria_mwh.sum())
    capex_million_per_mwh = _capex_brl_million_per_mwh(capex_brl, bess_energy)
    capex_per_mwh_str = (
        f"R$ {capex_million_per_mwh:,.3f} MM/MWh"
        if capex_million_per_mwh is not None else "n/a"
    )
    payback_str = f"{payback:.1f} anos" if payback < 100 else "não atingível"
    lcos_str = f"R$ {lcos:,.0f}/MWh" if lcos is not None else "n/a"
    cvar_delta = (
        risk_metrics["cvar_95_com_bess_brl"] - risk_metrics["cvar_95_sem_bess_brl"]
        if risk_metrics else None
    )
    cvar_delta_str = f"R$ {cvar_delta / 1e3:,.1f} mil/dia" if cvar_delta is not None else "n/a"
    risk_sample_str = f"{risk_metrics['n_days']:,} dias" if risk_metrics else "n/a"

    # Build charts for this scenario
    gen_chart = _build_generation_chart(gen, gf, mwac)
    charge_chart = _build_charge_discharge_chart(dispatch, peak_hours, tab_name)
    curtailment_chart = _build_curtailment_chart(dispatch)
    deficit_chart = _build_deficit_chart(dispatch, gf)

    return f"""
    <div class="highlight-box" style="margin-bottom: 20px;">
        <strong>Dimensionamento BESS:</strong> {n_blocks} blocos &times;
        {block.block_power_mw} MW / {block.block_energy_mwh} MWh =
        <strong>{bess_power:.2f} MW / {bess_energy:.1f} MWh</strong> ({duration_h}h)
    </div>
    <div class="kpi-grid">
        <div class="kpi-item">
            <div class="value">{bess_power:.2f} MW</div>
            <div class="label">Potência BESS</div>
        </div>
        <div class="kpi-item">
            <div class="value">{bess_energy:.1f} MWh</div>
            <div class="label">Energia BESS ({duration_h}h)</div>
        </div>
        <div class="kpi-item">
            <div class="value">{capex_per_mwh_str}</div>
            <div class="label">CAPEX</div>
        </div>
        <div class="kpi-item">
            <div class="value">{coverage:.1f}%</div>
            <div class="label">Cobertura GF</div>
        </div>
        <div class="kpi-item">
            <div class="value">R$ {economia / 1e6:,.2f} MM</div>
            <div class="label">Economia Anual</div>
        </div>
        <div class="kpi-item">
            <div class="value">{payback_str}</div>
            <div class="label">Payback</div>
        </div>
        <div class="kpi-item">
            <div class="value">{lcos_str}</div>
            <div class="label">LCOS</div>
        </div>
        <div class="kpi-item">
            <div class="value">{curtailment_pct:.1f}%</div>
            <div class="label">Curtailment / Geração</div>
        </div>
        <div class="kpi-item">
            <div class="value">{must_cut_pct:.1f}%</div>
            <div class="label">Corte MUST / Geração</div>
        </div>
        <div class="kpi-item">
            <div class="value">{curt_recovered_pct:.1f}%</div>
            <div class="label">Curtailment Recuperado</div>
        </div>
        <div class="kpi-item">
            <div class="value">{cvar_delta_str}</div>
            <div class="label">Δ CVaR 95% ({risk_sample_str})</div>
        </div>
        <div class="kpi-item">
            <div class="value">{missed_charge_total:,.0f} MWh</div>
            <div class="label">Carga Não Realizada (ano)</div>
        </div>
    </div>

    <div class="card" style="box-shadow:none; border:none; padding:16px 0;">
        <h3>Geração Solar vs Garantia Física</h3>
        <div class="chart-container">{gen_chart}</div>
    </div>

    <div class="card" style="box-shadow:none; border:none; padding:16px 0;">
        <h3>Operação BESS — Carga e Descarga (Dia Típico)</h3>
        <div class="chart-container">{charge_chart}</div>
    </div>

    <div class="card" style="box-shadow:none; border:none; padding:16px 0;">
        <h3>Curtailment — Recuperado vs Perdido</h3>
        <div class="chart-container">{curtailment_chart}</div>
    </div>

    <div class="card" style="box-shadow:none; border:none; padding:16px 0;">
        <h3>Déficit de Garantia Física</h3>
        <div class="chart-container">{deficit_chart}</div>
    </div>
    """


def _build_must_section(must_results: list | None) -> str:
    """Build the MUST optimization HTML section (table + TUST assumption).

    Parameters
    ----------
    must_results : list | None
        List of ``MustOptimizationResult`` (one per scenario). ``None`` or
        empty renders nothing.

    Returns
    -------
    str
        HTML fragment, empty string when there are no results.
    """
    if not must_results:
        return ""

    from solar_bess_risk.report_charts import must_sensitivity_chart

    first = must_results[0]
    tust_note = (
        " (valor default documentado)"
        if first.tust_is_default
        else " (informado pelo usuário)"
    )

    rows = []
    for r in must_results:
        rows.append(
            "<tr>"
            f"<td>{escape(str(r.scenario_label))} ({r.duration_h}h)</td>"
            f"<td>{r.optimal_reduction_pct * 100:.0f}%</td>"
            f"<td>{r.optimal_must_mw:,.1f}</td>"
            f"<td>{r.mwac - r.optimal_must_mw:,.1f}</td>"
            f"<td>{r.optimal_net_benefit_brl_per_yr:,.0f}</td>"
            "</tr>"
        )
    table_rows = "\n".join(rows)

    charts = []
    for r in must_results:
        fig = must_sensitivity_chart(r)
        charts.append(
            f'<div class="chart-container">'
            f'{fig.to_html(full_html=False, include_plotlyjs=False)}</div>'
        )
    charts_html = "\n".join(charts)

    return f"""
<!-- Otimização de Redução de MUST -->
<div class="card">
    <h2>Otimização de Redução de MUST</h2>
    <p>
        MUST inicial = potência do projeto ({first.mwac:,.1f} MW). A redução ótima
        maximiza <strong>economia de TUST + variação do saldo líquido</strong>.
        TUST aplicado: <strong>R$ {first.tust_brl_per_kw_month:.2f}/kW·mês</strong>{tust_note}.
    </p>
    <table class="data-table">
        <thead>
            <tr>
                <th>Cenário</th>
                <th>Redução ótima</th>
                <th>MUST ótimo (MW)</th>
                <th>Capacidade abdicada (MW)</th>
                <th>Benefício líquido (R$/ano)</th>
            </tr>
        </thead>
        <tbody>
            {table_rows}
        </tbody>
    </table>
    {charts_html}
    <div class="highlight-box">
        <strong>Premissa de modelagem:</strong> a injeção é <em>capada no MUST</em>
        (excedente é curtailado, sem penalidade de ultrapassagem). A energia perdida
        é valorada hora-a-hora pelo PLD via saldo líquido — sem achatamento de preço.
    </div>
</div>
"""


def build_consultancy_report(
    results_by_key: dict[str, tuple],
    output_path: str | Path,
    *,
    mwac: float,
    usd_brl_rate: float,
    bq_submarket: str,
    garantia_fisica_mw: float,
    fc: float,
    params=None,
    charge_mode: int = 0,
    rte_metadata: dict[str, float | str] | None = None,
    must_results: list | None = None,
    must_reduction_by_key: dict[str, tuple] | None = None,
    effective_pld_factor_2026: float | None = None,
) -> str:
    """Build a consultancy-style HTML report with tabs per scenario.

    Parameters
    ----------
    results_by_key : dict
        Same format as build_html_report/build_excel_report.
    output_path : str | Path
        Output file path.
    mwac : float
        Plant AC capacity.
    usd_brl_rate : float
        Exchange rate.
    bq_submarket : str
        PLD submarket.
    garantia_fisica_mw : float
        Physical guarantee in MW.
    fc : float
        Capacity factor.
    rte_metadata : dict | None
        RTE metadata for display.

    Returns
    -------
    str
        Path to the written HTML file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    modulation_mode = getattr(params, "modulation_mode", DEFAULT_MODULATION_MODE)
    # Build overview charts (cross-scenario)
    modulation_chart = _build_modulation_comparison_chart(results_by_key, modulation_mode)
    coverage_chart = _build_coverage_chart(results_by_key)
    kpi_table = _build_comparative_summary(
        results_by_key,
        must_reduction_by_key,
        mwac,
        usd_brl_rate,
        garantia_fisica_mw,
        fc,
        modulation_mode,
    )
    params_table = _build_simulation_params_table(
        params=params,
        charge_mode=charge_mode,
        bq_submarket=bq_submarket,
        mwac=mwac,
        garantia_fisica_mw=garantia_fisica_mw,
        fc=fc,
        effective_pld_factor_2026=effective_pld_factor_2026,
    )
    must_section = _build_must_section(must_results)

    if charge_mode == 3:
        charge_mode_desc = (
            "<strong>Arbitragem Day-Ahead (Modo 3):</strong> O BESS otimiza pares "
            "marginais de carga e descarga por dia, carregando quando há descarga "
            "futura mais valiosa após RTE. A descarga acima da GF é permitida e "
            "entra no saldo líquido quando aumenta o valor econômico."
        )
    else:
        charge_mode_desc = (
            "<strong>Cobertura de Déficit (Modo 0):</strong> O BESS descarrega em qualquer "
            "hora onde a geração é inferior à Garantia Física, independente do PLD. "
            "Prioriza cobrir a GF em todas as horas de déficit."
        )

    rte_info = ""
    if rte_metadata:
        rte_items = "".join(
            f"<li>{escape(str(k))}: {escape(str(v))}</li>" for k, v in rte_metadata.items()
        )
        rte_info = f"<ul>{rte_items}</ul>"

    # Build tab buttons and content for each scenario
    tab_buttons = []
    tab_contents = []
    scenario_keys = list(results_by_key.keys())

    for i, key in enumerate(scenario_keys):
        active_class = "active" if i == 0 else ""
        display = "block" if i == 0 else "none"
        safe_id = key.replace("-", "_").replace(" ", "_")

        tab_buttons.append(
            f'<button class="tab-btn {active_class}" onclick="openTab(event, \'tab_{safe_id}\')">'
            f'{escape(key)}</button>'
        )

        content = _build_scenario_tab_content(
            key, results_by_key[key], mwac, usd_brl_rate, garantia_fisica_mw
        )
        tab_contents.append(
            f'<div id="tab_{safe_id}" class="tab-content" style="display:{display};">'
            f'{content}</div>'
        )

    tabs_buttons_html = "\n".join(tab_buttons)
    tabs_content_html = "\n".join(tab_contents)

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Relatório Executivo — Redução de Risco de Modulação com BESS</title>
<script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
<style>
:root {{
    --primary: #1a365d;
    --secondary: #2d6a4f;
    --accent: #e07c24;
    --bg: #f8fafc;
    --card-bg: #ffffff;
    --text: #1e293b;
    --text-muted: #64748b;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    background: var(--bg);
    color: var(--text);
    line-height: 1.6;
}}
.container {{ max-width: 1200px; margin: 0 auto; padding: 40px 24px; }}
header {{
    background: linear-gradient(135deg, var(--primary), #2563eb);
    color: white;
    padding: 48px 40px;
    margin-bottom: 40px;
    border-radius: 12px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.1);
}}
header h1 {{ font-size: 2em; margin-bottom: 8px; }}
header p {{ opacity: 0.9; font-size: 1.1em; }}
.card {{
    background: var(--card-bg);
    border-radius: 12px;
    padding: 32px;
    margin-bottom: 32px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border: 1px solid #e2e8f0;
}}
.card h2 {{
    color: var(--primary);
    font-size: 1.4em;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 2px solid #e2e8f0;
}}
.card h3 {{
    color: var(--text);
    font-size: 1.1em;
    margin: 16px 0 8px 0;
}}
.highlight-box {{
    background: linear-gradient(135deg, #ecfdf5, #d1fae5);
    border-left: 4px solid var(--secondary);
    padding: 20px 24px;
    border-radius: 0 8px 8px 0;
    margin: 16px 0;
}}
.highlight-box strong {{ color: var(--secondary); }}
.kpi-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 16px;
    margin: 20px 0;
}}
.kpi-item {{
    text-align: center;
    padding: 20px;
    background: #f1f5f9;
    border-radius: 8px;
}}
.kpi-item .value {{
    font-size: 1.6em;
    font-weight: 700;
    color: var(--primary);
}}
.kpi-item .label {{
    font-size: 0.85em;
    color: var(--text-muted);
    margin-top: 4px;
}}
.kpi-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 0.85em;
}}
.kpi-table th {{
    background: var(--primary);
    color: white;
    padding: 12px 8px;
    text-align: center;
    font-weight: 600;
}}
.kpi-table td {{
    padding: 10px 8px;
    text-align: center;
    border-bottom: 1px solid #e2e8f0;
}}
.kpi-table tr:hover td {{ background: #f1f5f9; }}
.params-table {{
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
}}
.params-table th {{
    width: 32%;
    text-align: left;
    color: var(--primary);
    background: #f1f5f9;
    padding: 10px 12px;
    border-bottom: 1px solid #e2e8f0;
}}
.params-table td {{
    padding: 10px 12px;
    border-bottom: 1px solid #e2e8f0;
}}
.chart-container {{ margin: 24px 0; }}
/* Tab styles */
.tab-bar {{
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    border-bottom: 2px solid #e2e8f0;
    margin-bottom: 24px;
}}
.tab-btn {{
    padding: 12px 20px;
    border: none;
    background: transparent;
    cursor: pointer;
    font-size: 0.95em;
    font-weight: 600;
    color: var(--text-muted);
    border-bottom: 3px solid transparent;
    transition: all 0.2s;
}}
.tab-btn:hover {{ color: var(--primary); background: #f1f5f9; }}
.tab-btn.active {{
    color: var(--primary);
    border-bottom-color: var(--primary);
    background: #f1f5f9;
}}
.tab-content {{ display: none; }}
.conclusion {{
    background: linear-gradient(135deg, #fef3c7, #fde68a);
    border-left: 4px solid var(--accent);
    padding: 20px 24px;
    border-radius: 0 8px 8px 0;
    margin: 16px 0;
}}
footer {{
    text-align: center;
    color: var(--text-muted);
    font-size: 0.85em;
    margin-top: 40px;
    padding-top: 20px;
    border-top: 1px solid #e2e8f0;
}}
</style>
</head>
<body>
<div class="container">

<header>
    <h1>Relatório Executivo — Risco de Modulação</h1>
    <p>Análise da redução de risco de entrega da Garantia Física com Sistema de Armazenamento (BESS)</p>
</header>

<!-- Visão Geral -->
<div class="card">
    <h2>Visão Geral do Projeto</h2>
    <div class="kpi-grid">
        <div class="kpi-item">
            <div class="value">{mwac:.0f} MW</div>
            <div class="label">Capacidade AC</div>
        </div>
        <div class="kpi-item">
            <div class="value">{fc*100:.1f}%</div>
            <div class="label">Fator de Capacidade</div>
        </div>
        <div class="kpi-item">
            <div class="value">{garantia_fisica_mw:.1f} MW</div>
            <div class="label">Garantia Física</div>
        </div>
        <div class="kpi-item">
            <div class="value">{escape(bq_submarket)}</div>
            <div class="label">Submercado</div>
        </div>
    </div>
    <div class="highlight-box">
        <strong>Modo de Operação:</strong> {charge_mode_desc}
    </div>
    {rte_info}
</div>

<!-- Parâmetros da Simulação -->
<div class="card">
    <h2>Parâmetros da Simulação</h2>
    {params_table}
</div>

<!-- Resumo Comparativo -->
<div class="card">
    <h2>Resumo Comparativo — Caso Geral (2025) vs Caso Estressado (2026)</h2>
    {kpi_table}
    <div class="chart-container">{modulation_chart}</div>
    <div class="chart-container">{coverage_chart}</div>
</div>

{must_section}

<!-- Tabs por Cenário -->
<div class="card">
    <h2>Análise Detalhada por Cenário</h2>
    <div class="tab-bar">
        {tabs_buttons_html}
    </div>
    {tabs_content_html}
</div>

<!-- Conclusão -->
<div class="card">
    <h2>Conclusão e Recomendação</h2>
    <div class="conclusion">
        <strong>Conclusão:</strong> O sistema de armazenamento BESS permite reduzir significativamente
        o risco de modulação da usina solar, descarregando nas horas de maior valor econômico
        e aproveitando curtailment que de outra forma seria perdido.
        <ul style="margin-top: 12px; padding-left: 20px;">
            <li>O BESS reduz a exposição financeira por insuficiência de garantia física</li>
            <li>A descarga dinâmica prioriza as horas de maior PLD e permite saldo positivo acima da GF</li>
            <li>Parte significativa do curtailment pode ser recuperada e monetizada</li>
            <li>A coluna "Carga Não Realizada" quantifica a limitação de carga por falta de geração solar</li>
            <li>A cobertura da garantia física aumenta substancialmente com o BESS</li>
        </ul>
    </div>
</div>

<footer>
    <p>Relatório gerado automaticamente — Solar BESS Modulation Risk Tool</p>
    <p>Submercado: {escape(bq_submarket)} | MWac: {mwac:.0f} | USD/BRL: {usd_brl_rate:.2f}</p>
</footer>

</div>

<script>
function openTab(evt, tabId) {{
    // Hide all tab contents
    var contents = document.getElementsByClassName("tab-content");
    for (var i = 0; i < contents.length; i++) {{
        contents[i].style.display = "none";
    }}
    // Remove active class from all buttons
    var buttons = document.getElementsByClassName("tab-btn");
    for (var i = 0; i < buttons.length; i++) {{
        buttons[i].classList.remove("active");
    }}
    // Show selected tab and mark button active
    document.getElementById(tabId).style.display = "block";
    evt.currentTarget.classList.add("active");
    // Trigger Plotly resize for charts in the newly visible tab
    var plots = document.getElementById(tabId).querySelectorAll('.js-plotly-plot');
    plots.forEach(function(plot) {{ Plotly.Plots.resize(plot); }});
}}
</script>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
