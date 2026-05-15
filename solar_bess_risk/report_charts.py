"""Plotly chart builders for the HTML report.

Functions
---------
build_saturation_curve(results) -> go.Figure
build_dispatch_heatmap(dispatch, bess_cfg) -> go.Figure
build_payback_sensitivity(sensitivity_grid, params, base_price) -> go.Figure
build_operation_distribution(dispatch) -> go.Figure
"""

from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.economics import ScenarioResult
from solar_bess_risk.simulation import BESSConfig, DispatchResult


def build_saturation_curve(results: list[ScenarioResult]) -> go.Figure:
    """Build saturation curve: avoided curtailment vs BESS size, one line per ILR.

    Parameters
    ----------
    results : list[ScenarioResult]
        All scenario results.

    Returns
    -------
    go.Figure
        Plotly figure.
    """
    # Group by ILR
    ilr_data: dict[float, list[tuple[float, float, float]]] = {}
    for r in results:
        ilr, bess_pct, _dur = r.scenario_id
        avoided_mwh = r.curtailment_without_bess_mwh_yr - r.curtailment_with_bess_mwh_yr
        if ilr not in ilr_data:
            ilr_data[ilr] = []
        ilr_data[ilr].append((bess_pct, avoided_mwh, r.curtailment_avoided_pct))

    fig = go.Figure()
    for ilr in sorted(ilr_data.keys()):
        points = sorted(ilr_data[ilr], key=lambda x: x[0])
        x = [p[0] for p in points]
        y = [p[1] for p in points]
        pct = [p[2] for p in points]
        fig.add_trace(go.Scatter(
            x=x, y=y, mode="lines+markers", name=f"ILR {ilr}",
            hovertemplate=(
                "BESS: %{x}%%<br>ILR: " + str(ilr)
                + "<br>Avoided: %{y:.1f} MWh<br>%{customdata:.1f}%%<extra></extra>"
            ),
            customdata=pct,
        ))

    fig.update_layout(
        title="Curva de Saturação da Modulação",
        xaxis_title="Tamanho do BESS (% da energia solar anual sem BESS)",
        yaxis_title="Curtailment Evitado (MWh/ano)",
        legend_title="ILR",
    )
    return fig


def build_dispatch_heatmap(
    dispatch: DispatchResult, bess_cfg: BESSConfig
) -> go.Figure:
    """Build 365×24 dispatch heatmap: generation (left) and BESS dispatch (right).

    Parameters
    ----------
    dispatch : DispatchResult
        Hour-by-hour dispatch data.
    bess_cfg : BESSConfig
        BESS configuration for title labelling.

    Returns
    -------
    go.Figure
        Plotly figure with two side-by-side heatmaps.
    """
    n_days = HOURS_PER_YEAR // 24  # 365
    rte = 1.0  # display raw discharge; rte applied in economics

    # Reshape to (365, 24)
    gen = np.minimum(
        dispatch.curtailment_without_bess_mwh + dispatch.soc_mwh * 0,
        np.ones(HOURS_PER_YEAR),
    )
    # Actually: solar AC = curtailment_without_bess + clipped. Use the arrays directly.
    # Left panel: net generation = 1.0 for curtailed hours, else solar (approx from curtailment_without)
    # Simpler: use curtailment_without_bess as the generation indicator
    # For heatmap: show curtailment_without_bess as "excess generation"
    curtail_grid = dispatch.curtailment_without_bess_mwh[:n_days * 24].reshape(n_days, 24)

    # Right panel: BESS net dispatch (positive = discharge, negative = charge)
    bess_net = (dispatch.discharge_mwh - dispatch.charge_curtail_mwh - dispatch.charge_grid_mwh)
    bess_grid = bess_net[:n_days * 24].reshape(n_days, 24)

    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("Curtailment (MWh)", "Despacho BESS (MWh)"),
    )

    fig.add_trace(go.Heatmap(
        z=curtail_grid, colorscale="Viridis",
        colorbar=dict(title="MWh", x=0.45),
        hovertemplate="Dia %{y}<br>Hora %{x}<br>%{z:.3f} MWh<extra></extra>",
    ), row=1, col=1)

    fig.add_trace(go.Heatmap(
        z=bess_grid, colorscale="Viridis",
        colorbar=dict(title="MWh", x=1.0),
        hovertemplate="Dia %{y}<br>Hora %{x}<br>%{z:.3f} MWh<extra></extra>",
    ), row=1, col=2)

    fig.update_layout(
        title=(
            f"Heatmap de Despacho — ILR={bess_cfg.ilr}, "
            f"BESS={bess_cfg.bess_size_ratio_pct}%, "
            f"Duração={bess_cfg.duration_h}h"
        ),
    )
    fig.update_xaxes(title_text="Hora do dia", row=1, col=1)
    fig.update_xaxes(title_text="Hora do dia", row=1, col=2)
    fig.update_yaxes(title_text="Dia do ano", row=1, col=1)
    fig.update_yaxes(title_text="Dia do ano", row=1, col=2)

    return fig


def build_payback_sensitivity(
    sensitivity_grid: np.ndarray,
    params: SimulationParams,
    base_price_brl_per_mwh: float,
) -> go.Figure:
    """Build 10×10 payback sensitivity heatmap.

    Parameters
    ----------
    sensitivity_grid : np.ndarray
        10×10 payback values from ``compute_payback_sensitivity``.
    params : SimulationParams
        Simulation parameters (for axis labels).
    base_price_brl_per_mwh : float
        Base PLD price in BRL/MWh.

    Returns
    -------
    go.Figure
        Plotly figure.
    """
    price_factors = np.linspace(0.5, 1.5, 10)
    capex_factors = np.linspace(0.5, 1.5, 10)

    price_labels = [f"{base_price_brl_per_mwh * f:.0f}" for f in price_factors]
    capex_labels = [f"{params.capex_usd_per_kwh * f:.0f}" for f in capex_factors]

    # Cap display at 50 years for readability
    display_grid = np.where(np.isinf(sensitivity_grid), 50.0, sensitivity_grid)
    display_grid = np.minimum(display_grid, 50.0)

    fig = go.Figure(go.Heatmap(
        z=display_grid,
        x=capex_labels,
        y=price_labels,
        colorscale="Viridis",
        colorbar=dict(title="Payback (anos)"),
        hovertemplate=(
            "CAPEX: %{x} USD/kWh<br>"
            "Preço: %{y} BRL/MWh<br>"
            "Payback: %{z:.1f} anos<extra></extra>"
        ),
    ))

    fig.update_layout(
        title="Análise de Sensibilidade do Payback",
        xaxis_title="CAPEX (USD/kWh)",
        yaxis_title="Preço PLD (BRL/MWh)",
    )
    return fig


def build_operation_distribution(dispatch: DispatchResult) -> go.Figure:
    """Build stacked bar chart of hourly BESS operation distribution.

    Parameters
    ----------
    dispatch : DispatchResult
        Hour-by-hour dispatch data.

    Returns
    -------
    go.Figure
        Plotly figure.
    """
    n_days = HOURS_PER_YEAR // 24

    # Aggregate by hour-of-day across all 365 days
    charge_curtail_by_hour = np.zeros(24)
    charge_grid_by_hour = np.zeros(24)
    discharge_by_hour = np.zeros(24)

    for hod in range(24):
        indices = np.arange(hod, HOURS_PER_YEAR, 24)
        charge_curtail_by_hour[hod] = float(np.sum(dispatch.charge_curtail_mwh[indices]))
        charge_grid_by_hour[hod] = float(np.sum(dispatch.charge_grid_mwh[indices]))
        discharge_by_hour[hod] = float(np.sum(dispatch.discharge_mwh[indices]))

    hours = list(range(24))

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=hours, y=charge_curtail_by_hour, name="Carga (curtailment)",
        hovertemplate="Hora %{x}<br>%{y:.1f} MWh<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=hours, y=charge_grid_by_hour, name="Carga (grid top-up)",
        hovertemplate="Hora %{x}<br>%{y:.1f} MWh<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=hours, y=discharge_by_hour, name="Descarga",
        hovertemplate="Hora %{x}<br>%{y:.1f} MWh<extra></extra>",
    ))

    fig.update_layout(
        title="Distribuição Horária de Operação do BESS",
        xaxis_title="Hora do dia",
        yaxis_title="Energia (MWh)",
        barmode="stack",
    )
    return fig
