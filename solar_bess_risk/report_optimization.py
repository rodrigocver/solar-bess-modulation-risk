"""HTML report for BESS block optimization results."""

from __future__ import annotations

from html import escape
from pathlib import Path

import pandas as pd


RECOMMENDED_COLUMNS = [
    "cenario",
    "capex_scenario",
    "n_blocos",
    "bess_power_mw",
    "bess_energy_mwh",
    "capex_brl",
    "economia_liquida_anual_brl",
    "payback_anos",
    "lcos_brl_mwh",
    "roi_vida_util",
    "ranking_retorno",
    "ranking_payback",
]


DETAIL_COLUMNS = [
    "cenario",
    "capex_scenario",
    "n_blocos",
    "multiplo_blocos_gf",
    "bess_power_mw",
    "bess_energy_mwh",
    "capex_brl",
    "payback_anos",
    "lcos_brl_mwh",
    "roi_vida_util",
    "projecao_rte_completa",
    "recomendado",
]


def build_block_optimization_html(
    detail: pd.DataFrame,
    recommended: pd.DataFrame,
    output_path: str | Path,
) -> str:
    """Write a compact standalone HTML report for block-count optimization."""
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    recommended_view = _prepare_table(recommended, RECOMMENDED_COLUMNS)
    detail_view = _prepare_table(
        detail.sort_values(["cenario", "capex_scenario", "ranking_retorno", "n_blocos"]),
        DETAIL_COLUMNS,
    )

    html = f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <title>Otimização de Blocos BESS</title>
  <style>
    body {{
      font-family: Arial, Helvetica, sans-serif;
      margin: 28px;
      color: #17202a;
      background: #f7f9fb;
    }}
    h1, h2 {{ margin-bottom: 8px; }}
    .subtitle {{ color: #566573; margin-top: 0; }}
    .panel {{
      background: #fff;
      border: 1px solid #d8dee6;
      border-radius: 6px;
      padding: 18px;
      margin: 18px 0;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      font-size: 13px;
      background: #fff;
    }}
    th, td {{
      border: 1px solid #dfe5ec;
      padding: 7px 8px;
      text-align: right;
      white-space: nowrap;
    }}
    th {{
      background: #eaf0f6;
      color: #1f2d3d;
      position: sticky;
      top: 0;
    }}
    td:first-child, th:first-child,
    td:nth-child(2), th:nth-child(2) {{
      text-align: left;
    }}
    .table-wrap {{ overflow-x: auto; }}
  </style>
</head>
<body>
  <h1>Otimização de Blocos BESS</h1>
  <p class="subtitle">
    Sensibilidade de CAPEX aplicada sobre a mesma lógica operacional day-ahead.
    As recomendações usam payback e ROI com projeção RTE ano a ano para os candidatos top-N.
  </p>

  <section class="panel">
    <h2>Recomendação por Cenário e CAPEX</h2>
    <div class="table-wrap">
      {recommended_view.to_html(index=False, escape=False)}
    </div>
  </section>

  <section class="panel">
    <h2>Detalhe dos Candidatos</h2>
    <div class="table-wrap">
      {detail_view.to_html(index=False, escape=False)}
    </div>
  </section>
</body>
</html>
"""
    output.write_text(html, encoding="utf-8")
    return str(output)


def _prepare_table(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Select and format known report columns for HTML display."""
    if df.empty:
        return pd.DataFrame(columns=columns)

    view = df[[col for col in columns if col in df.columns]].copy()
    for col in view.columns:
        if col in {
            "capex_brl",
            "economia_liquida_anual_brl",
        }:
            view[col] = view[col].map(_fmt_brl)
        elif col in {
            "bess_power_mw",
            "bess_energy_mwh",
            "multiplo_blocos_gf",
            "payback_anos",
            "lcos_brl_mwh",
            "roi_vida_util",
        }:
            view[col] = view[col].map(_fmt_float)
        elif col in {"projecao_rte_completa", "recomendado"}:
            view[col] = view[col].map(lambda value: "Sim" if bool(value) else "Não")
        else:
            view[col] = view[col].map(lambda value: escape(str(value)))
    return view


def _fmt_brl(value) -> str:
    if pd.isna(value):
        return ""
    return f"R$ {float(value):,.0f}".replace(",", ".")


def _fmt_float(value) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
