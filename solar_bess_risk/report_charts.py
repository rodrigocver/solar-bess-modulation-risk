"""Plotly figure builders for the HTML report (v2).

Functions
---------
build_exposure_bar_chart(results) -> go.Figure
build_capex_savings_bar_chart(results, useful_life_years) -> go.Figure
build_payback_curve(results) -> go.Figure
build_var_cvar_chart(results) -> go.Figure
build_daily_distribution_chart(result) -> go.Figure
build_delta_scatter_chart(result) -> go.Figure
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from solar_bess_risk.economics import ScenarioResult


def build_exposure_bar_chart(results: list[ScenarioResult]) -> go.Figure:
    """Build grouped bar chart: exposure without vs with BESS per scenario.

    Parameters
    ----------
    results : list[ScenarioResult]
        Results for scenarios A, B, C.

    Returns
    -------
    go.Figure
        Plotly figure with grouped bars.
    """
    labels = [r.scenario.label for r in results]
    without = [r.annual_exposure_without_bess_brl for r in results]
    with_bess = [r.annual_exposure_with_bess_brl for r in results]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Sem BESS",
        x=labels,
        y=without,
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL<extra>Sem BESS</extra>",
    ))
    fig.add_trace(go.Bar(
        name="Com BESS",
        x=labels,
        y=with_bess,
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL<extra>Com BESS</extra>",
    ))
    fig.update_layout(
        title="Exposição Financeira: Sem vs Com BESS",
        yaxis_title="Exposição Financeira (BRL/ano)",
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_capex_savings_bar_chart(
    results: list[ScenarioResult], useful_life_years: int
) -> go.Figure:
    """Build grouped bar chart: CAPEX vs cumulative savings per scenario.

    Parameters
    ----------
    results : list[ScenarioResult]
        Results for scenarios A, B, C.
    useful_life_years : int
        Useful life in years for cumulative savings.

    Returns
    -------
    go.Figure
        Plotly figure with grouped bars.
    """
    labels = [r.scenario.label for r in results]
    capex_vals = [r.capex_brl for r in results]
    cumulative_savings = [r.lifetime_net_savings_brl for r in results]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="CAPEX",
        x=labels,
        y=capex_vals,
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL<extra>CAPEX</extra>",
    ))
    fig.add_trace(go.Bar(
        name="Economia Acumulada",
        x=labels,
        y=cumulative_savings,
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL<extra>Economia</extra>",
    ))
    fig.update_layout(
        title="CAPEX vs Economia Acumulada no Horizonte de Vida Útil",
        yaxis_title="BRL",
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_payback_curve(
    results: list[ScenarioResult],
    useful_life_years: int = 20,
    degradation_pct_yr: float = 0.02,
) -> go.Figure:
    """Build payback curve: cumulative savings over years per scenario.

    Parameters
    ----------
    results : list[ScenarioResult]
        Results for scenarios A, B, C. Uses useful_life from first result's params.

    Returns
    -------
    go.Figure
        Plotly figure with lines and CAPEX reference.
    """
    years = list(range(1, useful_life_years + 1))

    fig = go.Figure()
    colors = ["#1f77b4", "#ff7f0e", "#2ca02c"]

    for i, r in enumerate(results):
        cumulative = 0.0
        cum_savings = []
        for year in years:
            net = (
                r.annual_gross_savings_brl * ((1 - degradation_pct_yr) ** (year - 1))
                - r.annual_o_and_m_brl
            )
            cumulative += net
            cum_savings.append(cumulative)
        legend_name = f"Cenário {r.scenario.label}"
        if r.annual_savings_brl <= 0:
            legend_name += " (não atingível)"

        fig.add_trace(go.Scatter(
            x=years,
            y=cum_savings,
            mode="lines",
            name=legend_name,
            line=dict(color=colors[i % len(colors)]),
        ))
        # Horizontal dashed CAPEX reference line
        fig.add_trace(go.Scatter(
            x=years,
            y=[r.capex_brl] * len(years),
            mode="lines",
            name=f"CAPEX {r.scenario.label}",
            line=dict(color=colors[i % len(colors)], dash="dash"),
            showlegend=True,
        ))

    fig.update_layout(
        title="Curva de Payback: Economia Acumulada vs Anos",
        xaxis_title="Ano",
        yaxis_title="Economia Acumulada (BRL)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_var_cvar_chart(results: list[ScenarioResult]) -> go.Figure:
    """Grouped bar chart comparing VaR 95% and CVaR 95% across scenarios.

    Both metrics are expressed as daily BRL figures. The chart compares the
    tail risk with and without BESS, using the first result's sem_bess baseline
    plus each scenario's com_bess values.

    Parameters
    ----------
    results : list[ScenarioResult]
        Scenario results (including Base scenario, if present).

    Returns
    -------
    go.Figure
        Plotly figure.
    """
    labels = [r.scenario.label for r in results]

    var_sem = [r.var_95_sem_bess_brl for r in results]
    cvar_sem = [r.cvar_95_sem_bess_brl for r in results]
    var_com = [r.var_95_com_bess_brl for r in results]
    cvar_com = [r.cvar_95_com_bess_brl for r in results]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="VaR 95% Sem BESS",
        x=labels,
        y=var_sem,
        marker_color="#d62728",
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL/dia<extra>VaR Sem BESS</extra>",
    ))
    fig.add_trace(go.Bar(
        name="VaR 95% Com BESS",
        x=labels,
        y=var_com,
        marker_color="#ff7f0e",
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL/dia<extra>VaR Com BESS</extra>",
    ))
    fig.add_trace(go.Bar(
        name="CVaR 95% Sem BESS",
        x=labels,
        y=cvar_sem,
        marker_color="#8c1111",
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL/dia<extra>CVaR Sem BESS</extra>",
    ))
    fig.add_trace(go.Bar(
        name="CVaR 95% Com BESS",
        x=labels,
        y=cvar_com,
        marker_color="#e377c2",
        hovertemplate="Cenário %{x}: %{y:,.0f} BRL/dia<extra>CVaR Com BESS</extra>",
    ))
    fig.update_layout(
        title="Risco de Cauda: VaR e CVaR 95% — Sem vs Com BESS (BRL/dia)",
        yaxis_title="Saldo Diário (BRL) — mais negativo = maior risco",
        barmode="group",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_daily_distribution_chart(result: ScenarioResult) -> go.Figure:
    """Overlapping histogram of the daily net-balance distribution.

    Compares the full 365-day P&L distribution without BESS vs with BESS
    for a single scenario, making the tail-risk shift visible.

    Parameters
    ----------
    result : ScenarioResult
        A single scenario result with populated ``daily_net_sem_brl`` and
        ``daily_net_com_brl`` arrays.

    Returns
    -------
    go.Figure
        Plotly histogram figure.
    """
    sem = result.daily_net_sem_brl
    com = result.daily_net_com_brl
    if sem is None or com is None:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=sem,
        name="Sem BESS",
        opacity=0.65,
        marker_color="#d62728",
        nbinsx=40,
        hovertemplate="%{y} dias com saldo %{x:,.0f} BRL<extra>Sem BESS</extra>",
    ))
    fig.add_trace(go.Histogram(
        x=com,
        name=f"Com BESS ({result.scenario.label})",
        opacity=0.65,
        marker_color="#1f77b4",
        nbinsx=40,
        hovertemplate="%{y} dias com saldo %{x:,.0f} BRL<extra>Com BESS</extra>",
    ))
    fig.add_vline(
        x=result.var_95_sem_bess_brl,
        line_dash="dot", line_color="#d62728",
        annotation_text="VaR 95% s/ BESS",
        annotation_position="top left",
    )
    fig.add_vline(
        x=result.var_95_com_bess_brl,
        line_dash="dot", line_color="#1f77b4",
        annotation_text=f"VaR 95% c/ BESS ({result.scenario.label})",
        annotation_position="top right",
    )
    fig.update_layout(
        title=f"Distribuição do Saldo Diário — Cenário {result.scenario.label}",
        xaxis_title="Saldo Diário (BRL)",
        yaxis_title="Nº de dias",
        barmode="overlay",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig


def build_delta_scatter_chart(result: ScenarioResult) -> go.Figure:
    """Scatter plot: daily PLD delta vs daily net balance with and without BESS.

    Allows visual identification of the two stress scenarios:
    - Low delta (flat market) — BESS generates little value but CAPEX still runs.
    - High delta (high spread) — BESS captures large arbitrage but may be
      capacity-limited.

    Parameters
    ----------
    result : ScenarioResult
        A single scenario result with populated ``daily_delta``,
        ``daily_net_sem_brl``, and ``daily_net_com_brl`` arrays.

    Returns
    -------
    go.Figure
        Plotly scatter figure.
    """
    delta = result.daily_delta
    sem = result.daily_net_sem_brl
    com = result.daily_net_com_brl
    if delta is None or sem is None or com is None:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=delta,
        y=sem,
        mode="markers",
        name="Sem BESS",
        marker=dict(color="#d62728", size=5, opacity=0.6),
        hovertemplate="Delta: %{x:.1f} R$/MWh<br>Saldo: %{y:,.0f} BRL<extra>Sem BESS</extra>",
    ))
    fig.add_trace(go.Scatter(
        x=delta,
        y=com,
        mode="markers",
        name=f"Com BESS ({result.scenario.label})",
        marker=dict(color="#1f77b4", size=5, opacity=0.6),
        hovertemplate="Delta: %{x:.1f} R$/MWh<br>Saldo: %{y:,.0f} BRL<extra>Com BESS</extra>",
    ))
    p5 = float(np.percentile(delta, 5))
    p95 = float(np.percentile(delta, 95))
    fig.add_vline(x=p5, line_dash="dot", line_color="gray",
                  annotation_text="P5 (5% piores dias)")
    fig.add_vline(x=p95, line_dash="dot", line_color="green",
                  annotation_text="P95 (5% melhores dias)")

    fig.update_layout(
        title=f"Delta PLD vs Saldo Diário — Cenário {result.scenario.label}",
        xaxis_title="Delta PLD Horário (R$/MWh) — pico vs fora de pico",
        yaxis_title="Saldo Diário (BRL)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig
