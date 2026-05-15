"""HTML report assembly: summary tables and self-contained HTML export.

Functions
---------
build_summary_table_html(results) -> str
build_topup_summary_table_html(results, prices) -> str
write_report(figures, table_html, topup_table_html, results, params, output_dir) -> Path
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import plotly.io as pio

from solar_bess_risk.config import (
    LCOS_NOT_COMPUTABLE,
    PAYBACK_NOT_ACHIEVABLE,
    SimulationParams,
)
from solar_bess_risk.economics import ScenarioResult

if TYPE_CHECKING:
    import plotly.graph_objects as go

    from solar_bess_risk.data_sources import PriceProfile


def build_summary_table_html(results: list[ScenarioResult]) -> str:
    """Build 13-column HTML summary table.

    Parameters
    ----------
    results : list[ScenarioResult]
        All scenario results.

    Returns
    -------
    str
        HTML table string.
    """
    headers = [
        "ILR",
        "BESS (%)",
        "Duração (h)",
        "Curtailment s/ BESS (MWh/ano)",
        "Curtailment c/ BESS (MWh/ano)",
        "Curtailment Evitado (%)",
        "CF Efetivo (%)",
        "Ciclos Equivalentes/ano",
        "Receita Incremental (BRL/ano)",
        "Energia Curtailment (MWh/ano)",
        "Energia Grid (MWh/ano)",
        "LCOS (BRL/MWh)",
        "Payback (anos)",
    ]

    rows = []
    for r in results:
        ilr, bess_pct, dur_h = r.scenario_id
        lcos_str = LCOS_NOT_COMPUTABLE if r.lcos_brl_per_mwh is None else f"{r.lcos_brl_per_mwh:,.2f}"
        payback_str = PAYBACK_NOT_ACHIEVABLE if r.payback_yr is None else f"{r.payback_yr:,.1f}"
        rows.append(
            f"<tr>"
            f"<td>{ilr}</td>"
            f"<td>{bess_pct}</td>"
            f"<td>{dur_h}</td>"
            f"<td>{r.curtailment_without_bess_mwh_yr:,.1f}</td>"
            f"<td>{r.curtailment_with_bess_mwh_yr:,.1f}</td>"
            f"<td>{r.curtailment_avoided_pct:,.1f}</td>"
            f"<td>{r.effective_cf_pct:,.2f}</td>"
            f"<td>{r.equivalent_cycles_yr:,.1f}</td>"
            f"<td>{r.incremental_revenue_brl_yr:,.2f}</td>"
            f"<td>{r.energy_from_curtail_mwh_yr:,.1f}</td>"
            f"<td>{r.energy_from_grid_mwh_yr:,.1f}</td>"
            f"<td>{lcos_str}</td>"
            f"<td>{payback_str}</td>"
            f"</tr>"
        )

    header_html = "".join(f"<th>{h}</th>" for h in headers)
    return (
        '<table class="summary-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


def build_topup_summary_table_html(
    results: list[ScenarioResult],
    prices: PriceProfile,
) -> str:
    """Build top-up summary table: top-5 most frequent slots per scenario.

    Parameters
    ----------
    results : list[ScenarioResult]
        All scenario results.
    prices : PriceProfile
        Price profile for average PLD computation.

    Returns
    -------
    str
        HTML table string.
    """
    # Compute average PLD per hour-of-day
    avg_pld_by_hour = np.zeros(24)
    n_days = len(prices.prices_brl_per_mwh) // 24
    for hod in range(24):
        indices = np.arange(hod, len(prices.prices_brl_per_mwh), 24)
        avg_pld_by_hour[hod] = float(np.mean(prices.prices_brl_per_mwh[indices]))

    headers = ["ILR", "BESS (%)", "Duração (h)", "Top-Up Slots", "PLD Médio (BRL/MWh)"]
    rows = []
    for r in results:
        ilr, bess_pct, dur_h = r.scenario_id
        slots = r.top_up_hour_slots[:5]
        if not slots:
            rows.append(
                f"<tr><td>{ilr}</td><td>{bess_pct}</td><td>{dur_h}</td>"
                f"<td>—</td><td>—</td></tr>"
            )
            continue
        slots_str = ", ".join(slots)
        # Average PLD for those slots
        slot_hours = [int(s.split(":")[0]) for s in slots]
        avg_pld = float(np.mean([avg_pld_by_hour[h] for h in slot_hours]))
        rows.append(
            f"<tr><td>{ilr}</td><td>{bess_pct}</td><td>{dur_h}</td>"
            f"<td>{slots_str}</td><td>{avg_pld:,.2f}</td></tr>"
        )

    header_html = "".join(f"<th>{h}</th>" for h in headers)
    return (
        '<table class="topup-table">'
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
    )


PREMISSAS_HTML = """
<div class="premissas">
<h2>Premissas e Limitações</h2>
<ul>
<li>Todos os resultados normalizados para 1 MWac de capacidade inversor.</li>
<li>Perfil solar sintético gerado via pvlib (Ineichen clearsky) — não representa condições reais de um site específico.</li>
<li>Preços PLD horários obtidos do BigQuery (CCEE/Infomercado).</li>
<li>Despacho horário simplificado: carga prioritária de curtailment, descarga greedy, top-up opcional da rede.</li>
<li>Degradação linear do BESS aplicada no cálculo do LCOS.</li>
<li>CAPEX convertido de USD para BRL pela taxa de câmbio configurada.</li>
<li>Sem modelagem de perdas de transmissão, O&M, ou impostos.</li>
</ul>
</div>
"""


def write_report(
    figures: list[go.Figure],
    table_html: str,
    topup_table_html: str,
    results: list[ScenarioResult],
    params: SimulationParams,
    output_dir: Path,
) -> Path:
    """Assemble and write self-contained HTML report.

    Parameters
    ----------
    figures : list[go.Figure]
        List of Plotly figures to embed.
    table_html : str
        Summary table HTML.
    topup_table_html : str
        Top-up summary table HTML.
    results : list[ScenarioResult]
        All scenario results.
    params : SimulationParams
        Simulation parameters.
    output_dir : Path
        Output directory path.

    Returns
    -------
    Path
        Path to the written HTML file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "report.html"

    chart_divs = []
    for fig in figures:
        chart_divs.append(pio.to_html(fig, include_plotlyjs=False, full_html=False))

    # Get plotly.js inline
    import plotly.graph_objects as _go

    plotly_js = pio.to_html(
        _go.Figure(), include_plotlyjs=True, full_html=False
    ).split("</script>")[0] + "</script>"

    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Solar+BESS Modulation Risk Report</title>
{plotly_js}
<style>
body {{ font-family: Arial, sans-serif; margin: 20px; }}
h1 {{ color: #2c3e50; }}
h2 {{ color: #34495e; }}
.summary-table, .topup-table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
.summary-table th, .summary-table td,
.topup-table th, .topup-table td {{ border: 1px solid #ddd; padding: 8px; text-align: right; }}
.summary-table th, .topup-table th {{ background-color: #2c3e50; color: white; }}
.summary-table tr:nth-child(even), .topup-table tr:nth-child(even) {{ background-color: #f2f2f2; }}
.premissas {{ background-color: #fef9e7; padding: 15px; border-left: 4px solid #f39c12; margin: 20px 0; }}
</style>
</head>
<body>
<h1>Solar+BESS Modulation Risk Analysis</h1>
<p>Normalizado para 1 MWac | ILRs: {params.ilr_values} | Durações: {params.storage_durations_h}h</p>

<h2>Curva de Saturação</h2>
{chart_divs[0] if len(chart_divs) > 0 else ""}

<h2>Heatmap de Despacho</h2>
{chart_divs[1] if len(chart_divs) > 1 else ""}

<h2>Sensibilidade do Payback</h2>
{chart_divs[2] if len(chart_divs) > 2 else ""}

<h2>Distribuição Horária</h2>
{chart_divs[3] if len(chart_divs) > 3 else ""}

<h2>Resumo dos Cenários</h2>
{table_html}

<h2>Resumo de Top-Up</h2>
{topup_table_html}

{PREMISSAS_HTML}

</body>
</html>"""

    report_path.write_text(html, encoding="utf-8")
    return report_path
