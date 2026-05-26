"""Plotly figure builders for the HTML report (v2).

Functions
---------
build_exposure_bar_chart(results) -> go.Figure
build_capex_savings_bar_chart(results, useful_life_years) -> go.Figure
build_payback_curve(results) -> go.Figure
"""

from __future__ import annotations

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
