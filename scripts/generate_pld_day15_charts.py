"""Generate day-15 monthly PLD charts for 2025 and 2026."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.config import SimulationParams
from solar_bess_risk.__main__ import _fetch_pld_for_year


OUTPUT_PATH = Path("output/pld_dia15_2025_2026.html")
SUBMARKET = "SE"
CSV_PATH = "solar/solar_baguacu_m2_600mw_id8.csv"
MWAC = 600.0


@dataclass(frozen=True)
class YearProfile:
    year: int
    prices: np.ndarray
    source: str
    factor: float | None


def _hourly_index(year: int) -> pd.DatetimeIndex:
    idx = pd.date_range(f"{year}-01-01 00:00:00", f"{year}-12-31 23:00:00", freq="h")
    if len(idx) == 8784:
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
    return idx


def _load_profiles() -> list[YearProfile]:
    params = SimulationParams(csv_path=CSV_PATH, mwac=MWAC, bq_submarket=SUBMARKET)
    profiles: list[YearProfile] = []
    for year in (2025, 2026):
        profile, factor = _fetch_pld_for_year(year, params)
        profiles.append(
            YearProfile(
                year=year,
                prices=np.asarray(profile.prices_brl_per_mwh, dtype=float),
                source=profile.source,
                factor=factor,
            )
        )
    return profiles


def _format_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _points(values: np.ndarray, *, width: int, height: int, pad_left: int, pad_top: int, pad_bottom: int, y_min: float, y_max: float) -> str:
    plot_w = width - pad_left - 20
    plot_h = height - pad_top - pad_bottom
    span = max(y_max - y_min, 1.0)
    pts = []
    for hour, value in enumerate(values):
        x = pad_left + (plot_w * hour / 23)
        y = pad_top + plot_h - ((float(value) - y_min) / span * plot_h)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _render_chart(year: int, month: int, values: np.ndarray, global_min: float, global_max: float) -> str:
    width, height = 360, 220
    pad_left, pad_top, pad_bottom = 58, 24, 42
    plot_w = width - pad_left - 20
    plot_h = height - pad_top - pad_bottom
    y_min = max(0.0, np.floor(global_min / 50.0) * 50.0)
    y_max = np.ceil(global_max / 50.0) * 50.0
    line = _points(
        values,
        width=width,
        height=height,
        pad_left=pad_left,
        pad_top=pad_top,
        pad_bottom=pad_bottom,
        y_min=y_min,
        y_max=y_max,
    )
    y_ticks = np.linspace(y_min, y_max, 4)
    tick_svg = []
    for tick in y_ticks:
        y = pad_top + plot_h - ((float(tick) - y_min) / max(y_max - y_min, 1.0) * plot_h)
        tick_svg.append(
            f'<line class="grid" x1="{pad_left}" y1="{y:.1f}" x2="{width - 20}" y2="{y:.1f}" />'
            f'<text class="tick ytick" x="{pad_left - 8}" y="{y + 4:.1f}">{tick:.0f}</text>'
        )
    x_ticks = []
    for hour in (0, 6, 12, 18, 23):
        x = pad_left + (plot_w * hour / 23)
        x_ticks.append(
            f'<line class="tickline" x1="{x:.1f}" y1="{pad_top + plot_h}" x2="{x:.1f}" y2="{pad_top + plot_h + 5}" />'
            f'<text class="tick" x="{x:.1f}" y="{height - 18}">{hour:02d}</text>'
        )

    min_value = float(np.min(values))
    max_value = float(np.max(values))
    avg_value = float(np.mean(values))
    title = f"{month:02d}/15/{year}"
    return f"""
      <article class="chart-card">
        <div class="chart-title">
          <strong>{title}</strong>
          <span>min {_format_brl(min_value)} | med {_format_brl(avg_value)} | max {_format_brl(max_value)}</span>
        </div>
        <svg viewBox="0 0 {width} {height}" role="img" aria-label="PLD horario em {title}">
          <rect class="plot-bg" x="{pad_left}" y="{pad_top}" width="{plot_w}" height="{plot_h}" />
          {''.join(tick_svg)}
          <line class="axis" x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{pad_top + plot_h}" />
          <line class="axis" x1="{pad_left}" y1="{pad_top + plot_h}" x2="{width - 20}" y2="{pad_top + plot_h}" />
          {''.join(x_ticks)}
          <polyline class="pld-line" points="{line}" />
          <text class="axis-label y-label" transform="translate(15 {pad_top + plot_h / 2:.1f}) rotate(-90)">PLD (R$/MWh)</text>
          <text class="axis-label" x="{pad_left + plot_w / 2:.1f}" y="{height - 2}">Hora do dia</text>
        </svg>
      </article>
    """


def _render_html(profiles: list[YearProfile]) -> str:
    charts_by_year: dict[int, list[str]] = {}
    all_day_values: list[np.ndarray] = []
    for profile in profiles:
        idx = _hourly_index(profile.year)
        series = pd.Series(profile.prices, index=idx)
        charts_by_year[profile.year] = []
        for month in range(1, 13):
            day = series.loc[f"{profile.year}-{month:02d}-15"]
            values = day.to_numpy(dtype=float)
            all_day_values.append(values)
            charts_by_year[profile.year].append((month, values))

    global_min = float(min(np.min(values) for values in all_day_values))
    global_max = float(max(np.max(values) for values in all_day_values))

    sections = []
    for profile in profiles:
        factor_text = f" | fator 2026: {profile.factor:.4f}" if profile.factor is not None else ""
        charts = "\n".join(
            _render_chart(profile.year, month, values, global_min, global_max)
            for month, values in charts_by_year[profile.year]
        )
        sections.append(
            f"""
            <section>
              <div class="section-heading">
                <h2>PLD {profile.year} - dia 15 de cada mês</h2>
                <p>Fonte: {escape(profile.source)}{factor_text}</p>
              </div>
              <div class="grid">{charts}</div>
            </section>
            """
        )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>PLD horario - dia 15 de cada mês - 2025 e 2026</title>
  <style>
    :root {{
      --ink: #0f172a;
      --muted: #475569;
      --line: #2563eb;
      --grid: #dbe4f0;
      --panel: #ffffff;
      --bg: #f6f8fb;
      --border: #d8e1ee;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Arial, Helvetica, sans-serif;
    }}
    main {{
      max-width: 1640px;
      margin: 0 auto;
      padding: 28px 24px 40px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0;
      font-size: 20px;
      letter-spacing: 0;
    }}
    p {{
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .intro {{
      margin-bottom: 24px;
      padding-bottom: 18px;
      border-bottom: 1px solid var(--border);
    }}
    section + section {{ margin-top: 34px; }}
    .section-heading {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: end;
      margin-bottom: 14px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 14px;
    }}
    .chart-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      min-width: 0;
    }}
    .chart-title {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      align-items: baseline;
      margin-bottom: 8px;
      font-size: 14px;
    }}
    .chart-title span {{
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    svg {{
      display: block;
      width: 100%;
      height: auto;
    }}
    .plot-bg {{ fill: #fbfdff; }}
    .grid {{ stroke: var(--grid); stroke-width: 1; }}
    .axis, .tickline {{ stroke: #334155; stroke-width: 1.1; }}
    .pld-line {{
      fill: none;
      stroke: var(--line);
      stroke-width: 2.4;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    .tick {{
      fill: var(--muted);
      font-size: 10px;
      text-anchor: middle;
    }}
    .ytick {{ text-anchor: end; }}
    .axis-label {{
      fill: var(--muted);
      font-size: 10px;
      text-anchor: middle;
    }}
    @media (max-width: 720px) {{
      main {{ padding: 20px 12px 32px; }}
      .section-heading {{ display: block; }}
      .chart-title {{ display: block; }}
      .chart-title span {{ display: block; margin-top: 4px; white-space: normal; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="intro">
      <h1>PLD horario no dia 15 de cada mês</h1>
      <p>Submercado {SUBMARKET}. Eixo x: 24 horas do dia. Eixo y: PLD em R$/MWh. Escala y padronizada entre todos os gráficos para comparação visual.</p>
    </div>
    {''.join(sections)}
  </main>
</body>
</html>
"""


def main() -> None:
    profiles = _load_profiles()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(_render_html(profiles), encoding="utf-8")
    print(OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()
