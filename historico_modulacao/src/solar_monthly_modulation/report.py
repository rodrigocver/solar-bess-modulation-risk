"""CSV, HTML, and manifest output writing for monthly modulation runs."""

from __future__ import annotations

import hashlib
from html import escape
from datetime import datetime
from pathlib import Path

import pandas as pd

from solar_monthly_modulation.manifest import build_manifest, write_manifest
from solar_monthly_modulation.models import ModulationConfig, ModulationResult, WrittenOutputs


def write_outputs(
    config: ModulationConfig,
    result: ModulationResult,
    run_id: str | None = None,
) -> WrittenOutputs:
    """Write CSV tables and manifest to a run-specific folder.

    Parameters
    ----------
    config : ModulationConfig
        Run configuration.
    result : ModulationResult
        Calculated modulation outputs.
    run_id : str or None
        Optional deterministic run identifier for tests.

    Returns
    -------
    WrittenOutputs
        Paths written by the export step.
    """

    base_dir = Path(config.output_dir)
    resolved_run_id = run_id or _build_run_id(config)
    run_dir = base_dir / resolved_run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    monthly_csv = run_dir / "monthly_modulation.csv"
    annual_csv = run_dir / "annual_summary.csv"
    html_report = run_dir / "report.html"
    manifest_json = run_dir / "manifest.json"

    result.monthly.to_csv(monthly_csv, index=False)
    result.annual.to_csv(annual_csv, index=False)
    write_html_report(html_report, config, result)
    outputs = {
        "monthly_csv": str(monthly_csv),
        "annual_csv": str(annual_csv),
        "html_report": str(html_report),
        "manifest_json": str(manifest_json),
    }
    manifest = build_manifest(config, result, outputs)
    write_manifest(manifest_json, manifest)

    return WrittenOutputs(
        run_dir=run_dir,
        monthly_csv=monthly_csv,
        annual_csv=annual_csv,
        html_report=html_report,
        manifest_json=manifest_json,
    )


def write_html_report(
    path: str | Path,
    config: ModulationConfig,
    result: ModulationResult,
) -> Path:
    """Write a self-contained HTML report with monthly and annual tables.

    Parameters
    ----------
    path : str or pathlib.Path
        Destination HTML path.
    config : ModulationConfig
        Run configuration with MWac, years, and submarket.
    result : ModulationResult
        Calculated monthly and annual modulation outputs.

    Returns
    -------
    pathlib.Path
        Written HTML report path.
    """

    target = Path(path)
    target.write_text(_build_html_report(config, result), encoding="utf-8")
    return target


def _build_run_id(config: ModulationConfig) -> str:
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    payload = f"{config.csv_path}|{config.mwac}|{config.years}|{config.submarket}"
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]
    return f"monthly_modulation_{timestamp}_{digest}"


def _build_html_report(config: ModulationConfig, result: ModulationResult) -> str:
    monthly_display = _format_display_table(result.monthly)
    annual_display = _format_display_table(result.annual)
    best_month = result.monthly.sort_values("modulation_factor", ascending=False).iloc[0]
    worst_month = result.monthly.sort_values("modulation_factor", ascending=True).iloc[0]
    annual_mean = result.annual["modulation_factor"].mean()
    annual_modulation_mean = result.annual["modulation_value_brl_per_mwh"].mean()
    partial_year_note = _partial_year_note(result.annual)

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Relatório de Modulação Solar Mensal</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #18212f;
      --muted: #5a6472;
      --line: #d9dee7;
      --soft: #f4f6f9;
      --accent: #116466;
      --accent-2: #d9b44a;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #ffffff;
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.45;
    }}
    header {{
      padding: 32px 40px 24px;
      border-bottom: 1px solid var(--line);
      background: linear-gradient(180deg, #f9fbfc 0%, #ffffff 100%);
    }}
    h1 {{ margin: 0 0 8px; font-size: 28px; letter-spacing: 0; }}
    h2 {{ margin: 34px 0 12px; font-size: 20px; letter-spacing: 0; }}
    p {{ margin: 6px 0; color: var(--muted); }}
    main {{ padding: 0 40px 40px; }}
    .meta, .cards {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .item {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      background: #fff;
    }}
    .label {{
      display: block;
      font-size: 12px;
      color: var(--muted);
      margin-bottom: 4px;
    }}
    .value {{ font-size: 18px; font-weight: 700; }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      white-space: nowrap;
    }}
    th {{
      text-align: left;
      background: var(--soft);
      color: var(--ink);
      border-bottom: 1px solid var(--line);
      padding: 9px 10px;
    }}
    td {{
      border-bottom: 1px solid #edf0f4;
      padding: 8px 10px;
      text-align: right;
    }}
    td:first-child, td:nth-child(2), th:first-child, th:nth-child(2) {{
      text-align: left;
    }}
    tr:last-child td {{ border-bottom: 0; }}
    .note {{
      margin-top: 18px;
      padding: 12px 14px;
      border-left: 4px solid var(--accent);
      background: #f5faf9;
      color: var(--muted);
    }}
  </style>
</head>
<body>
  <header>
    <h1>Relatório de Modulação Solar Mensal</h1>
    <p>Curva de geração sem BESS contra PLD horário histórico local.</p>
    <section class="meta">
      <div class="item"><span class="label">CSV solar</span><span class="value">{escape(result.source_metadata.solar_csv_filename)}</span></div>
      <div class="item"><span class="label">Submercado</span><span class="value">{escape(config.submarket)}</span></div>
      <div class="item"><span class="label">Anos</span><span class="value">{escape(", ".join(str(y) for y in config.years))}</span></div>
      <div class="item"><span class="label">Capacidade</span><span class="value">{config.mwac:,.2f} MWac</span></div>
    </section>
  </header>
  <main>
    <section class="cards">
      <div class="item"><span class="label">Fator médio anual</span><span class="value">{annual_mean:.4f}</span></div>
      <div class="item"><span class="label">Modulação média anual</span><span class="value">{annual_modulation_mean:,.2f} BRL/MWh</span></div>
      <div class="item"><span class="label">Melhor mês</span><span class="value">{int(best_month["year"])}-{int(best_month["month"]):02d} · {best_month["modulation_factor"]:.4f}</span></div>
      <div class="item"><span class="label">Pior mês</span><span class="value">{int(worst_month["year"])}-{int(worst_month["month"]):02d} · {worst_month["modulation_factor"]:.4f}</span></div>
      <div class="item"><span class="label">Energia média anual</span><span class="value">{result.annual["generation_mwh"].mean():,.1f} MWh</span></div>
    </section>

    <h2>Resultados Mês a Mês</h2>
    <div class="table-wrap">
      {monthly_display.to_html(index=False, escape=True)}
    </div>

    <h2>Agregado Anual</h2>
    {partial_year_note}
    <div class="table-wrap">
      {annual_display.to_html(index=False, escape=True)}
    </div>

    <div class="note">
      Fórmula: preço capturado = soma(geração MWh × PLD BRL/MWh) / soma(geração MWh);
      fator de modulação = preço capturado / PLD médio simples do período.
    </div>
  </main>
</body>
</html>
"""


def _format_display_table(df: pd.DataFrame) -> pd.DataFrame:
    display = df.copy()
    formats = {
        "generation_mwh": "{:,.1f}",
        "flat_price_brl_per_mwh": "{:,.2f}",
        "captured_price_brl_per_mwh": "{:,.2f}",
        "modulation_value_brl_per_mwh": "{:,.2f}",
        "weighted_revenue_brl": "{:,.2f}",
        "modulation_factor": "{:.4f}",
        "generation_per_mwac_mwh_per_mwac": "{:,.2f}",
    }
    for column, fmt in formats.items():
        if column in display.columns:
            display[column] = display[column].map(lambda value, f=fmt: f.format(value))
    return display.rename(columns=_DISPLAY_COLUMNS)


def _partial_year_note(annual: pd.DataFrame) -> str:
    partial = annual[annual["hours"] < 8760]
    if partial.empty:
        return ""
    labels = ", ".join(
        f"{int(row.year)} ({int(row.hours)} horas)" for row in partial.itertuples()
    )
    return (
        '<p class="note">Anos parciais usam apenas horas observadas no PLD: '
        f"{escape(labels)}.</p>"
    )


_DISPLAY_COLUMNS = {
    "year": "Ano",
    "month": "Mês",
    "hours": "Horas",
    "generation_mwh": "Geração (MWh)",
    "flat_price_brl_per_mwh": "PLD médio (BRL/MWh)",
    "captured_price_brl_per_mwh": "Preço capturado (BRL/MWh)",
    "modulation_value_brl_per_mwh": "Modulação (BRL/MWh)",
    "weighted_revenue_brl": "Receita ponderada (BRL)",
    "modulation_factor": "Fator de modulação",
    "generation_per_mwac_mwh_per_mwac": "Geração específica (MWh/MWac)",
    "price_source": "Fonte PLD",
}
