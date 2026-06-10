"""Generate PSR price curves and annual solar modulation summary.

This script is intentionally standalone: it reads the PSR hourly price CSV and
the existing multi-year solar curve, then writes new artifacts under ``output/``.
It does not change the main simulation/reporting pipeline.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR
from solar_bess_risk.profile import SolarProfile, load_solar_csv


PRICE_CSV = Path("dados/Brazil Q2 26 (Central)-bra-central-brl2025-system-1h.csv")
SOLAR_CSV = Path("solar/solar_baguacu_m2_600mw_id8.csv")
MWAC = 600.0
START_YEAR = 2030
END_YEAR = 2060

OUTPUT_HTML = Path("output/modulacao_psr_2030_2060.html")
OUTPUT_PRICE_CURVES_CSV = Path("output/curvas_preco_psr_2030_2060.csv")
OUTPUT_SUMMARY_CSV = Path("output/modulacao_psr_2030_2060.csv")


@dataclass(frozen=True)
class AnnualModulation:
    calendar_year: int
    solar_year_idx: int
    solar_year_exact: bool
    price_mean_brl_mwh: float
    price_min_brl_mwh: float
    price_max_brl_mwh: float
    solar_generation_mwh: float
    gf_energy_mwh: float
    captured_vs_gf_brl_mwh: float
    captured_solar_brl_mwh: float
    capture_factor_pct: float
    modulation_brl_mwh_gf: float
    note: str


def _format_number(value: float, digits: int = 2) -> str:
    if value is None or not np.isfinite(value):
        return "n/a"
    text = f"{value:,.{digits}f}"
    return text.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_brl(value: float, digits: int = 2) -> str:
    return f"R$ {_format_number(value, digits)}"


def _read_price_input(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Price CSV not found: {path}")

    df = pd.read_csv(
        path,
        sep=";",
        skiprows=2,
        names=["utc_date", "utc_time", "local_date", "local_time", "price_brl_mwh", "extra"],
        engine="python",
    )
    df = df.drop(columns=["extra"])
    df["price_brl_mwh"] = pd.to_numeric(df["price_brl_mwh"], errors="coerce")
    if df["price_brl_mwh"].isna().any():
        first_bad = int(np.flatnonzero(df["price_brl_mwh"].isna().to_numpy())[0])
        raise ValueError(f"Non-numeric price on row {first_bad + 3} of {path}")

    local_text = df["local_date"].astype(str) + " " + df["local_time"].astype(str)
    df["local_datetime"] = pd.to_datetime(
        local_text,
        format="%d/%m/%Y %H:%M:%S",
        errors="raise",
    )
    return df[["local_datetime", "price_brl_mwh"]].sort_values("local_datetime")


def _price_curves_by_year(path: Path, start_year: int, end_year: int) -> dict[int, np.ndarray]:
    df = _read_price_input(path)
    curves: dict[int, np.ndarray] = {}

    for year in range(start_year, end_year + 1):
        year_df = df[df["local_datetime"].dt.year == year].copy()
        if year_df.empty:
            raise ValueError(f"Price CSV does not contain local calendar year {year}.")

        is_feb29 = (year_df["local_datetime"].dt.month == 2) & (year_df["local_datetime"].dt.day == 29)
        year_df = year_df.loc[~is_feb29]
        if len(year_df) != HOURS_PER_YEAR:
            raise ValueError(
                f"Year {year} has {len(year_df)} hourly prices after Feb-29 normalization; "
                f"expected {HOURS_PER_YEAR}."
            )
        curves[year] = year_df["price_brl_mwh"].to_numpy(dtype=np.float64)

    return curves


def _modulation_value_brl_per_mwh(
    injection_mwh: np.ndarray,
    pld_brl_per_mwh: np.ndarray,
    gf_energy_mwh: float,
) -> float:
    if gf_energy_mwh <= 1e-10:
        raise ValueError("GF energy must be positive to calculate modulation.")
    captured_vs_gf = float(np.sum(injection_mwh * pld_brl_per_mwh) / gf_energy_mwh)
    return float(np.mean(pld_brl_per_mwh) - captured_vs_gf)


def _annual_rows(
    price_curves: dict[int, np.ndarray],
    solar: SolarProfile,
    *,
    start_year: int,
) -> list[AnnualModulation]:
    if solar.generation_years_lim_mw is None:
        raise ValueError("Solar CSV must provide multi-year generation_years_lim_mw.")

    gf_energy_mwh = float(solar.garantia_fisica_mw * HOURS_PER_YEAR)
    rows: list[AnnualModulation] = []

    for calendar_year in sorted(price_curves):
        requested_solar_year = calendar_year - start_year + 1
        solar_year_idx = max(1, min(requested_solar_year, solar.n_years))
        solar_year_exact = requested_solar_year == solar_year_idx
        generation_mwh = solar.generation_years_lim_mw[solar_year_idx - 1].astype(np.float64)
        prices = price_curves[calendar_year]

        solar_generation_mwh = float(generation_mwh.sum())
        captured_total = float(np.sum(generation_mwh * prices))
        captured_vs_gf = captured_total / gf_energy_mwh
        captured_solar = captured_total / solar_generation_mwh if solar_generation_mwh > 0 else math.nan
        price_mean = float(np.mean(prices))
        capture_factor = captured_solar / price_mean * 100.0 if price_mean else math.nan
        modulation = _modulation_value_brl_per_mwh(generation_mwh, prices, gf_energy_mwh)
        note = (
            "Curva solar exata."
            if solar_year_exact
            else f"Ano solar {solar.n_years} reutilizado; CSV solar nao possui ano {requested_solar_year}."
        )

        rows.append(
            AnnualModulation(
                calendar_year=calendar_year,
                solar_year_idx=solar_year_idx,
                solar_year_exact=solar_year_exact,
                price_mean_brl_mwh=price_mean,
                price_min_brl_mwh=float(np.min(prices)),
                price_max_brl_mwh=float(np.max(prices)),
                solar_generation_mwh=solar_generation_mwh,
                gf_energy_mwh=gf_energy_mwh,
                captured_vs_gf_brl_mwh=captured_vs_gf,
                captured_solar_brl_mwh=float(captured_solar),
                capture_factor_pct=float(capture_factor),
                modulation_brl_mwh_gf=modulation,
                note=note,
            )
        )

    return rows


def _write_price_curves_csv(price_curves: dict[int, np.ndarray], path: Path) -> None:
    data: dict[str, np.ndarray] = {
        "hour_of_year": np.arange(1, HOURS_PER_YEAR + 1, dtype=int),
    }
    for year, values in sorted(price_curves.items()):
        data[f"price_{year}_brl_mwh"] = values
    pd.DataFrame(data).to_csv(path, index=False, float_format="%.6f")


def _write_summary_csv(rows: list[AnnualModulation], path: Path) -> None:
    pd.DataFrame([row.__dict__ for row in rows]).to_csv(path, index=False, float_format="%.6f")


def _daily_average(values: np.ndarray) -> np.ndarray:
    return values.reshape(365, 24).mean(axis=1)


def _line_path(
    values: np.ndarray,
    *,
    width: float,
    height: float,
    min_value: float,
    max_value: float,
) -> str:
    span = max(max_value - min_value, 1e-9)
    denom = max(len(values) - 1, 1)
    points = []
    for idx, value in enumerate(values):
        x = width * idx / denom
        y = height - ((float(value) - min_value) / span * height)
        points.append(f"{x:.2f},{y:.2f}")
    return " ".join(points)


def _bar_chart(rows: list[AnnualModulation]) -> str:
    width, height = 980, 330
    pad_left, pad_top, pad_right, pad_bottom = 66, 30, 24, 58
    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    values = np.array([row.modulation_brl_mwh_gf for row in rows], dtype=float)
    ymin = min(0.0, float(values.min()))
    ymax = float(values.max()) * 1.08
    if ymax <= ymin:
        ymax = ymin + 1.0
    span = ymax - ymin
    zero_y = pad_top + plot_h - ((0.0 - ymin) / span * plot_h)
    bar_gap = 4.0
    bar_w = max(4.0, plot_w / len(rows) - bar_gap)

    bars = []
    labels = []
    for i, row in enumerate(rows):
        x = pad_left + i * (plot_w / len(rows)) + bar_gap / 2
        y = pad_top + plot_h - ((row.modulation_brl_mwh_gf - ymin) / span * plot_h)
        h = max(1.0, zero_y - y)
        color = "#0f766e" if row.solar_year_exact else "#b45309"
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" '
            f'rx="2" fill="{color}"><title>{row.calendar_year}: '
            f'{_format_brl(row.modulation_brl_mwh_gf)}/MWh GF</title></rect>'
        )
        if i % 2 == 0 or i == len(rows) - 1:
            labels.append(
                f'<text class="axis-text" x="{x + bar_w / 2:.2f}" y="{height - 30}" '
                f'text-anchor="middle">{row.calendar_year}</text>'
            )

    ticks = []
    for tick in np.linspace(ymin, ymax, 5):
        y = pad_top + plot_h - ((float(tick) - ymin) / span * plot_h)
        ticks.append(
            f'<line class="grid" x1="{pad_left}" y1="{y:.2f}" x2="{width - pad_right}" y2="{y:.2f}" />'
            f'<text class="axis-text" x="{pad_left - 8}" y="{y + 4:.2f}" text-anchor="end">'
            f'{_format_number(float(tick), 0)}</text>'
        )

    return f"""
    <svg class="wide-chart" viewBox="0 0 {width} {height}" role="img" aria-label="Modulacao anual">
      <rect class="plot-bg" x="{pad_left}" y="{pad_top}" width="{plot_w}" height="{plot_h}" />
      {''.join(ticks)}
      <line class="axis" x1="{pad_left}" y1="{zero_y:.2f}" x2="{width - pad_right}" y2="{zero_y:.2f}" />
      {''.join(bars)}
      {''.join(labels)}
      <text class="axis-label" x="{width / 2}" y="{height - 8}" text-anchor="middle">Ano calendario</text>
      <text class="axis-label" transform="translate(18 {pad_top + plot_h / 2}) rotate(-90)" text-anchor="middle">R$/MWh GF</text>
    </svg>
    """


def _price_curve_cards(price_curves: dict[int, np.ndarray], rows: list[AnnualModulation]) -> str:
    row_by_year = {row.calendar_year: row for row in rows}
    all_daily = {year: _daily_average(values) for year, values in price_curves.items()}
    global_min = min(float(v.min()) for v in all_daily.values())
    global_max = max(float(v.max()) for v in all_daily.values())

    cards = []
    for year, daily in sorted(all_daily.items()):
        row = row_by_year[year]
        color = "#0f766e" if row.solar_year_exact else "#b45309"
        path = _line_path(daily, width=260, height=112, min_value=global_min, max_value=global_max)
        badge = "solar exato" if row.solar_year_exact else "solar reutilizado"
        cards.append(
            f"""
            <article class="curve-card" data-year="{year}">
              <div class="curve-head">
                <strong>{year}</strong>
                <span class="badge {'warn' if not row.solar_year_exact else ''}">{badge}</span>
              </div>
              <svg viewBox="0 0 300 156" role="img" aria-label="Curva diaria media de preco {year}">
                <rect class="mini-bg" x="28" y="16" width="260" height="112" />
                <line class="mini-axis" x1="28" y1="128" x2="288" y2="128" />
                <line class="mini-axis" x1="28" y1="16" x2="28" y2="128" />
                <polyline fill="none" stroke="{color}" stroke-width="1.9" stroke-linejoin="round"
                  stroke-linecap="round" points="{path}" transform="translate(28,16)" />
                <text class="mini-tick" x="28" y="145">Jan</text>
                <text class="mini-tick" x="151" y="145" text-anchor="middle">Jul</text>
                <text class="mini-tick" x="288" y="145" text-anchor="end">Dez</text>
              </svg>
              <div class="curve-stats">
                <span>med {_format_brl(row.price_mean_brl_mwh, 1)}</span>
                <span>mod {_format_brl(row.modulation_brl_mwh_gf, 1)}</span>
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def _summary_table(rows: list[AnnualModulation]) -> str:
    trs = []
    for row in rows:
        exact = "Sim" if row.solar_year_exact else "Nao"
        tr_class = ' class="warn-row"' if not row.solar_year_exact else ""
        trs.append(
            f"""
            <tr{tr_class}>
              <td>{row.calendar_year}</td>
              <td>{row.solar_year_idx}</td>
              <td>{exact}</td>
              <td>{_format_brl(row.price_mean_brl_mwh)}</td>
              <td>{_format_brl(row.captured_solar_brl_mwh)}</td>
              <td>{_format_number(row.capture_factor_pct, 1)}%</td>
              <td>{_format_brl(row.modulation_brl_mwh_gf)}</td>
              <td>{_format_number(row.solar_generation_mwh, 0)}</td>
              <td>{escape(row.note)}</td>
            </tr>
            """
        )

    return f"""
    <table>
      <thead>
        <tr>
          <th>Ano</th>
          <th>Ano solar</th>
          <th>Exato</th>
          <th>PLD medio</th>
          <th>Preco capturado solar</th>
          <th>Fator captura</th>
          <th>Modulacao</th>
          <th>Geracao solar MWh</th>
          <th>Observacao</th>
        </tr>
      </thead>
      <tbody>{''.join(trs)}</tbody>
    </table>
    """


def _render_html(rows: list[AnnualModulation], price_curves: dict[int, np.ndarray], solar: SolarProfile) -> str:
    exact_rows = [row for row in rows if row.solar_year_exact]
    reused_rows = [row for row in rows if not row.solar_year_exact]
    first = rows[0]
    last_exact = exact_rows[-1] if exact_rows else rows[-1]
    avg_mod_exact = float(np.mean([row.modulation_brl_mwh_gf for row in exact_rows])) if exact_rows else math.nan
    max_mod = max(rows, key=lambda row: row.modulation_brl_mwh_gf)
    min_mod = min(rows, key=lambda row: row.modulation_brl_mwh_gf)

    warning_html = ""
    if reused_rows:
        years = ", ".join(str(row.calendar_year) for row in reused_rows)
        warning_html = f"""
        <section class="notice">
          <strong>Atencao ao horizonte solar:</strong>
          o arquivo solar tem {solar.n_years} anos horarios. Com Ano Solar 1 = {START_YEAR},
          os anos exatos cobrem {START_YEAR}-{START_YEAR + solar.n_years - 1}.
          Para manter o pedido ate {END_YEAR}, {escape(years)} foi incluido reutilizando
          o Ano Solar {solar.n_years}; a linha fica marcada como nao exata.
        </section>
        """

    payload = {
        "price_csv": str(PRICE_CSV),
        "solar_csv": str(SOLAR_CSV),
        "mwac": MWAC,
        "start_year": START_YEAR,
        "end_year": END_YEAR,
        "hours_per_year": HOURS_PER_YEAR,
        "curtailment_mwh": 0.0,
        "modulation_formula": "mean(PLD) - sum(solar_injection * PLD) / GF_energy",
        "price_curves_csv": str(OUTPUT_PRICE_CURVES_CSV),
        "summary_csv": str(OUTPUT_SUMMARY_CSV),
    }

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Modulacao PSR 2030-2060</title>
  <style>
    :root {{
      --ink: #16201f;
      --muted: #5f6f6d;
      --line: #d8e1df;
      --panel: #f7faf9;
      --teal: #0f766e;
      --amber: #b45309;
      --blue: #1d4ed8;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background: #ffffff;
      font: 14px/1.45 Arial, Helvetica, sans-serif;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
    }}
    h1 {{
      margin: 0 0 10px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 14px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    p {{ margin: 0; color: var(--muted); max-width: 980px; }}
    main {{ padding: 24px 32px 38px; }}
    section {{ margin: 0 0 28px; }}
    .kpis {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .kpi {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      background: var(--panel);
      min-height: 78px;
    }}
    .kpi span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 5px;
    }}
    .kpi strong {{ font-size: 21px; }}
    .notice {{
      border: 1px solid #f2c88f;
      background: #fff8ed;
      color: #5f3506;
      border-radius: 8px;
      padding: 12px 14px;
    }}
    .wide-chart {{
      width: 100%;
      max-width: 1120px;
      height: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
    }}
    .plot-bg, .mini-bg {{ fill: #fbfdfc; }}
    .grid {{ stroke: #e4ecea; stroke-width: 1; }}
    .axis, .mini-axis {{ stroke: #91a4a1; stroke-width: 1; }}
    .axis-text, .axis-label, .mini-tick {{
      fill: var(--muted);
      font-size: 11px;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .axis-label {{ font-weight: 700; }}
    .curves {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
      gap: 12px;
    }}
    .curve-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px 10px 8px;
      background: #fff;
    }}
    .curve-head, .curve-stats {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .curve-head strong {{ font-size: 15px; }}
    .badge {{
      border: 1px solid #b7d5d0;
      color: var(--teal);
      border-radius: 999px;
      padding: 2px 8px;
      font-size: 11px;
      white-space: nowrap;
    }}
    .badge.warn {{
      color: var(--amber);
      border-color: #f2c88f;
    }}
    .curve-card svg {{
      display: block;
      width: 100%;
      height: auto;
      margin: 5px 0 2px;
    }}
    .curve-stats {{
      color: var(--muted);
      font-size: 12px;
    }}
    .table-wrap {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
    }}
    th, td {{
      padding: 9px 10px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }}
    th {{
      background: var(--panel);
      color: #334542;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    th:first-child, td:first-child,
    th:last-child, td:last-child {{ text-align: left; }}
    td:last-child {{
      white-space: normal;
      min-width: 260px;
      color: var(--muted);
    }}
    tr.warn-row td {{ background: #fffaf2; }}
    .footnote {{
      color: var(--muted);
      font-size: 12px;
      margin-top: 10px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Modulacao PSR 2030-2060</h1>
    <p>
      Calculo simplificado com curva horaria PSR BRL2025, Ano Solar 1 = {START_YEAR},
      injecao solar sem BESS por <code>{escape(str(SOLAR_CSV))}</code> e curtailment zero.
      A modulacao segue a formula do projeto: PLD medio menos valor capturado pela injecao solar sobre a energia de GF.
    </p>
    <div class="kpis">
      <div class="kpi"><span>Fonte de preco</span><strong>PSR Q2 26</strong></div>
      <div class="kpi"><span>Horizonte solicitado</span><strong>{START_YEAR}-{END_YEAR}</strong></div>
      <div class="kpi"><span>Solar exato</span><strong>{START_YEAR}-{last_exact.calendar_year}</strong></div>
      <div class="kpi"><span>GF usada</span><strong>{_format_number(solar.garantia_fisica_mw, 2)} MW</strong></div>
      <div class="kpi"><span>Modulacao media exata</span><strong>{_format_brl(avg_mod_exact)}</strong></div>
    </div>
  </header>
  <main>
    {warning_html}
    <section>
      <h2>Valor de modulacao por ano</h2>
      {_bar_chart(rows)}
      <div class="footnote">
        Maior valor: {max_mod.calendar_year} ({_format_brl(max_mod.modulation_brl_mwh_gf)}/MWh GF).
        Menor valor: {min_mod.calendar_year} ({_format_brl(min_mod.modulation_brl_mwh_gf)}/MWh GF).
      </div>
    </section>
    <section>
      <h2>Curvas de preco</h2>
      <p class="footnote">
        Os calculos usam as 8.760 horas de cada ano. As mini-curvas abaixo exibem a media diaria
        para leitura visual; o CSV gerado preserva a curva horaria completa por ano.
      </p>
      <div class="curves">{_price_curve_cards(price_curves, rows)}</div>
    </section>
    <section>
      <h2>Tabela anual</h2>
      <div class="table-wrap">{_summary_table(rows)}</div>
      <div class="footnote">
        Arquivos gerados: <code>{escape(str(OUTPUT_PRICE_CURVES_CSV))}</code> e
        <code>{escape(str(OUTPUT_SUMMARY_CSV))}</code>.
      </div>
    </section>
  </main>
  <script type="application/json" id="run-metadata">{escape(json.dumps(payload, ensure_ascii=False, indent=2))}</script>
</body>
</html>
"""


def main() -> None:
    OUTPUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    price_curves = _price_curves_by_year(PRICE_CSV, START_YEAR, END_YEAR)
    solar = load_solar_csv(str(SOLAR_CSV), MWAC)
    rows = _annual_rows(price_curves, solar, start_year=START_YEAR)

    _write_price_curves_csv(price_curves, OUTPUT_PRICE_CURVES_CSV)
    _write_summary_csv(rows, OUTPUT_SUMMARY_CSV)
    OUTPUT_HTML.write_text(_render_html(rows, price_curves, solar), encoding="utf-8")

    exact_count = sum(1 for row in rows if row.solar_year_exact)
    print(f"Generated {OUTPUT_HTML}")
    print(f"Generated {OUTPUT_PRICE_CURVES_CSV}")
    print(f"Generated {OUTPUT_SUMMARY_CSV}")
    print(f"Exact solar-year rows: {exact_count}/{len(rows)}")


if __name__ == "__main__":
    main()
