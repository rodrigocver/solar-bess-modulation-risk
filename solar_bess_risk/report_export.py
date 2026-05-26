"""HTML report generator (v2).

Functions
---------
build_summary_table_html(results, useful_life_years) -> str
build_top10_table_html(df) -> str
write_report(results, prices, params, solar, output_dir) -> str
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.economics import (
    ScenarioResult,
    build_top10_peak_hours,
    payback_display,
)
from solar_bess_risk.profile import SolarProfile
from solar_bess_risk.report_charts import (
    build_capex_savings_bar_chart,
    build_exposure_bar_chart,
    build_payback_curve,
)

PREMISSAS_HTML = """
<section>
<h2>Premissas Regulatórias</h2>
<ul>
<li><strong>Garantia Física:</strong> Calculada como FC × MWac, conforme Portaria MME 101/2016 (Seção III, Art. 3º) e Portaria MME 60/2020.</li>
<li><strong>Módulo de Liquidação:</strong> Exposição calculada com base no PLD horário da CCEE (Módulo 03 - Regras de Comercialização).</li>
<li><strong>Tratamento BESS:</strong> Armazenamento atrás do medidor, sem participação no ACL como gerador, conforme ANEEL RN 1.034/2022.</li>
<li><strong>Cenários de ponta:</strong> Baseados em horários históricos de maior PLD no submercado SE.</li>
</ul>
</section>
"""


def build_summary_table_html(results: list[ScenarioResult], useful_life_years: int) -> str:
    """Build HTML table summarizing scenario results.

    Parameters
    ----------
    results : list[ScenarioResult]
        Scenarios A, B, C results.
    useful_life_years : int
        Useful life in years.

    Returns
    -------
    str
        HTML table string.
    """
    rows = ""
    for r in results:
        rows += f"""<tr>
<td>{r.scenario.label}</td>
<td>{r.scenario.duration_h}h</td>
<td>{r.bess_power_mw:.1f}</td>
<td>{r.bess_energy_mwh:.1f}</td>
<td>{r.capex_brl:,.0f}</td>
<td>{r.annual_exposure_without_bess_brl:,.0f}</td>
<td>{r.annual_exposure_with_bess_brl:,.0f}</td>
<td>{r.annual_gross_savings_brl:,.0f}</td>
<td>{r.annual_o_and_m_brl:,.0f}</td>
<td>{r.annual_savings_brl:,.0f}</td>
<td>{payback_display(r)}</td>
<td>{r.coverage_pct:.1f}%</td>
</tr>"""

    return f"""<table>
<thead><tr>
<th>Cenário</th><th>Duração</th><th>Potência (MW)</th><th>Energia (MWh)</th>
<th>CAPEX (BRL)</th><th>Exposição s/ BESS (BRL/ano)</th>
<th>Exposição c/ BESS (BRL/ano)</th><th>Economia Bruta (BRL/ano)</th>
<th>O&M (BRL/ano)</th><th>Economia Líquida Ano 1 (BRL/ano)</th>
<th>Payback (anos)</th><th>Cobertura</th>
</tr></thead>
<tbody>{rows}</tbody>
</table>"""


def build_top10_table_html(df: pd.DataFrame) -> str:
    """Convert top-10 DataFrame to HTML table.

    Parameters
    ----------
    df : pd.DataFrame
        Top-10 peak hours table.

    Returns
    -------
    str
        HTML table string.
    """
    return df.to_html(index=False, float_format="{:.2f}".format)


def write_report(
    results: list[ScenarioResult],
    prices: PriceProfile,
    params: SimulationParams,
    solar: SolarProfile,
    output_dir: str | Path,
) -> str:
    """Write full HTML report with charts, tables, and premissas.

    Parameters
    ----------
    results : list[ScenarioResult]
        All scenario results.
    prices : PriceProfile
        Price profile used.
    params : SimulationParams
        Simulation parameters.
    solar : SolarProfile
        Solar profile used.
    output_dir : str | Path
        Directory to write report.html.

    Returns
    -------
    str
        Path to written report.html.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build charts
    fig_exposure = build_exposure_bar_chart(results)
    fig_capex = build_capex_savings_bar_chart(results, params.useful_life_years)
    fig_payback = build_payback_curve(
        results,
        params.useful_life_years,
        params.bess_degradation_pct_yr,
    )

    chart_exposure_html = fig_exposure.to_html(full_html=False, include_plotlyjs="inline")
    chart_capex_html = fig_capex.to_html(full_html=False, include_plotlyjs=False)
    chart_payback_html = fig_payback.to_html(full_html=False, include_plotlyjs=False)

    # Build tables
    summary_html = build_summary_table_html(results, params.useful_life_years)
    top10_df = build_top10_peak_hours(results, prices)
    top10_html = build_top10_table_html(top10_df)

    # Assemble report
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Análise de Risco de Modulação Solar + BESS</title>
<style>
body {{ font-family: 'Segoe UI', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
th, td {{ border: 1px solid #ddd; padding: 8px; text-align: right; }}
th {{ background-color: #4CAF50; color: white; }}
tr:nth-child(even) {{ background-color: #f2f2f2; }}
h1, h2 {{ color: #333; }}
section {{ margin: 24px 0; }}
</style>
</head>
<body>
<h1>Análise de Risco de Modulação Solar + BESS</h1>

<section>
<h2>Dados de Entrada</h2>
<ul>
<li><strong>Arquivo solar:</strong> {solar.csv_filename}</li>
<li><strong>MWac:</strong> {params.mwac:.1f} MW</li>
<li><strong>Fator de Capacidade:</strong> {solar.fc:.4f}</li>
<li><strong>Garantia Física:</strong> {solar.garantia_fisica_mw:.2f} MW</li>
<li><strong>Fonte de preço:</strong> {prices.source}</li>
<li><strong>CAPEX:</strong> {params.capex_usd_per_kwh} USD/kWh × {params.usd_brl_rate} BRL/USD</li>
<li><strong>Vida útil:</strong> {params.useful_life_years} anos</li>
<li><strong>Eficiência BESS:</strong> {params.bess_roundtrip_efficiency:.1%}</li>
<li><strong>O&M BESS:</strong> {params.bess_o_and_m_pct_capex:.1%} do CAPEX ao ano</li>
<li><strong>Degradação BESS:</strong> {params.bess_degradation_pct_yr:.1%} ao ano</li>
</ul>
</section>

{PREMISSAS_HTML}

<section>
<h2>Resumo dos Cenários</h2>
{summary_html}
</section>

<section>
<h2>Exposição Financeira</h2>
{chart_exposure_html}
</section>

<section>
<h2>CAPEX vs Economia</h2>
{chart_capex_html}
</section>

<section>
<h2>Curva de Payback</h2>
{chart_payback_html}
</section>

<section>
<h2>Top 10 Horas de Ponta (por PLD)</h2>
{top10_html}
</section>

</body>
</html>"""

    report_path = output_dir / "report.html"
    report_path.write_text(html, encoding="utf-8")
    return str(report_path)
