"""Generate day-15 monthly PLD charts for 2025 and 2026."""

from __future__ import annotations

import math
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


MONTH_NAMES_PT = [
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]

YEAR_COLORS: dict[int, str] = {
    2025: "#2563eb",  # blue
    2026: "#dc2626",  # red
}


def _nice_axis(values_list: list[np.ndarray]) -> tuple[float, float]:
    """Compute a clean Y axis range from one or more value arrays."""
    all_v = np.concatenate(values_list)
    lo, hi = float(np.min(all_v)), float(np.max(all_v))
    span = max(hi - lo, 1.0)
    for step in (10, 25, 50, 100, 200, 500, 1000):
        if span / step <= 6:
            break
    y_min = max(0.0, math.floor(lo / step) * step)
    y_max = math.ceil(hi / step) * step
    if y_max <= y_min:
        y_max = y_min + step
    return float(y_min), float(y_max)


def _polyline_pts(
    values: np.ndarray,
    *,
    plot_w: float,
    plot_h: float,
    pad_left: int,
    pad_top: int,
    y_min: float,
    y_max: float,
) -> str:
    span = max(y_max - y_min, 1.0)
    pts = []
    for hour, value in enumerate(values):
        x = pad_left + (plot_w * hour / 23)
        y = pad_top + plot_h - ((float(value) - y_min) / span * plot_h)
        pts.append(f"{x:.1f},{y:.1f}")
    return " ".join(pts)


def _render_combined_chart(month: int, values_by_year: dict[int, np.ndarray]) -> str:
    """Render a single SVG chart with one line per year."""
    width, height = 390, 240
    pad_left, pad_top, pad_bottom = 62, 28, 46
    plot_w = float(width - pad_left - 20)
    plot_h = float(height - pad_top - pad_bottom)

    y_min, y_max = _nice_axis(list(values_by_year.values()))
    span = max(y_max - y_min, 1.0)

    # Y grid lines + tick labels
    n_ticks = 5
    y_ticks = np.linspace(y_min, y_max, n_ticks)
    tick_svg = []
    for tick in y_ticks:
        y = pad_top + plot_h - ((float(tick) - y_min) / span * plot_h)
        tick_svg.append(
            f'<line class="grid-line" x1="{pad_left}" y1="{y:.1f}"'
            f' x2="{width - 20}" y2="{y:.1f}" />'
            f'<text class="tick ytick" x="{pad_left - 6}" y="{y + 4:.1f}">{tick:.0f}</text>'
        )

    # X tick marks
    x_ticks = []
    for hour in (0, 6, 12, 18, 23):
        x = pad_left + (plot_w * hour / 23)
        x_ticks.append(
            f'<line class="tickline" x1="{x:.1f}" y1="{pad_top + plot_h}"'
            f' x2="{x:.1f}" y2="{pad_top + plot_h + 5}" />'
            f'<text class="tick" x="{x:.1f}" y="{pad_top + plot_h + 17:.1f}">{hour:02d}h</text>'
        )

    # Data polylines
    lines_svg = []
    for year in sorted(values_by_year):
        color = YEAR_COLORS.get(year, "#64748b")
        pts = _polyline_pts(
            values_by_year[year],
            plot_w=plot_w, plot_h=plot_h,
            pad_left=pad_left, pad_top=pad_top,
            y_min=y_min, y_max=y_max,
        )
        lines_svg.append(
            f'<polyline fill="none" stroke="{color}" stroke-width="2.2"'
            f' stroke-linecap="round" stroke-linejoin="round" points="{pts}" />'
        )

    # Legend (inside plot, top-right)
    legend_items = []
    legend_x = width - 24
    for i, year in enumerate(sorted(values_by_year)):
        color = YEAR_COLORS.get(year, "#64748b")
        lx = legend_x - 52
        ly = pad_top + 6 + i * 16
        legend_items.append(
            f'<line x1="{lx}" y1="{ly + 5}" x2="{lx + 14}" y2="{ly + 5}"'
            f' stroke="{color}" stroke-width="2.2" stroke-linecap="round"/>'
            f'<text x="{lx + 18}" y="{ly + 9}" fill="#1e293b"'
            f' font-size="10" font-weight="700" font-family="Arial,sans-serif">{year}</text>'
        )

    # Per-year stats block (below chart title)
    stats_parts = []
    for year in sorted(values_by_year):
        v = values_by_year[year]
        color = YEAR_COLORS.get(year, "#64748b")
        stats_parts.append(
            f'<span style="color:{color};font-weight:700">{year}</span>'
            f' med {_format_brl(float(np.mean(v)))}&nbsp;'
            f'[{_format_brl(float(np.min(v)))}–{_format_brl(float(np.max(v)))}]'
        )
    stats_html = "&ensp;|&ensp;".join(stats_parts)
    month_name = MONTH_NAMES_PT[month - 1]

    return f"""
      <article class="chart-card">
        <div class="chart-title"><strong>{month_name}</strong></div>
        <div class="chart-stats">{stats_html}</div>
        <svg viewBox="0 0 {width} {height}" role="img" aria-label="PLD horario {month_name}">
          <rect class="plot-bg" x="{pad_left}" y="{pad_top}" width="{plot_w:.0f}" height="{plot_h:.0f}" />
          {''.join(tick_svg)}
          <line class="axis" x1="{pad_left}" y1="{pad_top}" x2="{pad_left}" y2="{pad_top + plot_h:.0f}" />
          <line class="axis" x1="{pad_left}" y1="{pad_top + plot_h:.0f}" x2="{width - 20}" y2="{pad_top + plot_h:.0f}" />
          {''.join(x_ticks)}
          {''.join(lines_svg)}
          {''.join(legend_items)}
          <text class="axis-label" transform="translate(13 {pad_top + plot_h / 2:.1f}) rotate(-90)">R$/MWh</text>
        </svg>
      </article>
    """


def _render_html(profiles: list[YearProfile]) -> str:
    # Organise per month → per year
    month_data: dict[int, dict[int, np.ndarray]] = {m: {} for m in range(1, 13)}
    sources: dict[int, str] = {}
    for profile in profiles:
        idx = _hourly_index(profile.year)
        series = pd.Series(profile.prices, index=idx)
        sources[profile.year] = profile.source
        for month in range(1, 13):
            day = series.loc[f"{profile.year}-{month:02d}-15"]
            month_data[month][profile.year] = day.to_numpy(dtype=float)

    charts = "\n".join(
        _render_combined_chart(month, month_data[month]) for month in range(1, 13)
    )

    sources_html = "&ensp;|&ensp;".join(
        f'<span style="color:{YEAR_COLORS.get(yr, "#64748b")};font-weight:700">{yr}</span>'
        f": {escape(src)}"
        for yr, src in sorted(sources.items())
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
      --panel: #ffffff;
      --bg: #f6f8fb;
      --border: #d8e1ee;
      --grid-color: #dbe4f0;
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
    h1 {{ margin: 0 0 6px; font-size: 26px; }}
    p {{ margin: 4px 0 0; color: var(--muted); font-size: 13px; }}
    .intro {{
      margin-bottom: 22px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }}
    .chart-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(330px, 1fr));
      gap: 14px;
    }}
    .chart-card {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      min-width: 0;
    }}
    .chart-title {{ font-size: 15px; font-weight: 700; margin-bottom: 3px; }}
    .chart-stats {{
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 8px;
      line-height: 1.6;
    }}
    svg {{ display: block; width: 100%; height: auto; }}
    .plot-bg {{ fill: #fbfdff; }}
    .grid-line {{ stroke: var(--grid-color); stroke-width: 1; fill: none; }}
    .axis, .tickline {{ stroke: #334155; stroke-width: 1.1; fill: none; }}
    .tick {{
      fill: var(--muted);
      font-size: 10px;
      text-anchor: middle;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .ytick {{ text-anchor: end; }}
    .axis-label {{
      fill: var(--muted);
      font-size: 10px;
      text-anchor: middle;
      font-family: Arial, Helvetica, sans-serif;
    }}
    @media (max-width: 720px) {{
      main {{ padding: 16px 10px 28px; }}
    }}
  </style>
</head>
<body>
  <main>
    <div class="intro">
      <h1>PLD horário no dia 15 de cada mês — 2025 e 2026</h1>
      <p>Submercado {SUBMARKET}. Eixo x: hora do dia. Eixo y: R$/MWh (escala ajustada ao intervalo real de cada mês).</p>
      <p style="margin-top:6px">{sources_html}</p>
    </div>
    <div class="chart-grid">{charts}</div>
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
