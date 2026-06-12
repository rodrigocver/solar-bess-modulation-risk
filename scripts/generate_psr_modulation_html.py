"""Generate future price curves and annual solar modulation summary.

This script is intentionally standalone: it reads future hourly price sources
and the existing multi-year solar curve, then writes artifacts under ``output/``.
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

from solar_bess_risk.config import DEFAULT_MODULATION_MODE, HOURS_PER_YEAR
from solar_bess_risk.modulation import modulation_value_brl_per_mwh
from solar_bess_risk.profile import SolarProfile, load_solar_csv


SOLAR_CSV = Path("solar/solar_baguacu_m2_600mw_id8.csv")
MWAC = 600.0
START_YEAR = 2030
END_YEAR = 2059
PSR_ROOT = Path("dados/psr_2025/precos")
PSR_PRICE_START_YEAR = 2030
PSR_PRICE_END_YEAR = 2040
PSR_REPEAT_YEAR = 2040


@dataclass(frozen=True)
class PriceScenario:
    key: str
    label: str
    csv_path: Path
    output_html: Path
    output_price_curves_csv: Path
    output_summary_csv: Path
    family_label: str = "Brazil Q2 26"
    price_description: str = "curva horaria Brazil Q2 26 BRL2025"
    source_kind: str = "brazil_q2_26"
    submarket: str | None = None
    source_note: str = ""


SCENARIOS: tuple[PriceScenario, ...] = (
    PriceScenario(
        key="central",
        label="Central",
        csv_path=Path("dados/Brazil Q2 26 (Central)-bra-central-brl2025-system-1h.csv"),
        output_html=Path("output/modulacao_brazil_q2_26_central_2030_2059.html"),
        output_price_curves_csv=Path("output/curvas_preco_brazil_q2_26_central_2030_2059.csv"),
        output_summary_csv=Path("output/modulacao_brazil_q2_26_central_2030_2059.csv"),
    ),
    PriceScenario(
        key="low",
        label="Low",
        csv_path=Path("dados/Brazil Q2 26 (Low)-bra-low-brl2025-system-1h.csv"),
        output_html=Path("output/modulacao_brazil_q2_26_low_2030_2059.html"),
        output_price_curves_csv=Path("output/curvas_preco_brazil_q2_26_low_2030_2059.csv"),
        output_summary_csv=Path("output/modulacao_brazil_q2_26_low_2030_2059.csv"),
    ),
    PriceScenario(
        key="dry_hydrology",
        label="Dry Hydrology",
        csv_path=Path("dados/Brazil Q2 26 (Dry Hydrology)-bra-dryhydrology-brl2025-system-1h.csv"),
        output_html=Path("output/modulacao_brazil_q2_26_dry_hydrology_2030_2059.html"),
        output_price_curves_csv=Path("output/curvas_preco_brazil_q2_26_dry_hydrology_2030_2059.csv"),
        output_summary_csv=Path("output/modulacao_brazil_q2_26_dry_hydrology_2030_2059.csv"),
    ),
    PriceScenario(
        key="constrained_transmission",
        label="Constrained Transmission",
        csv_path=Path(
            "dados/Brazil Q2 26 (Constrained Transmission)-"
            "bra-constrainedtransmission-brl2025-system-1h.csv"
        ),
        output_html=Path("output/modulacao_brazil_q2_26_constrained_transmission_2030_2059.html"),
        output_price_curves_csv=Path(
            "output/curvas_preco_brazil_q2_26_constrained_transmission_2030_2059.csv"
        ),
        output_summary_csv=Path("output/modulacao_brazil_q2_26_constrained_transmission_2030_2059.csv"),
    ),
)


PSR_SCENARIOS: tuple[PriceScenario, ...] = tuple(
    PriceScenario(
        key=f"psr_2025_{submarket}",
        label=f"PSR 2025 {submarket.upper()}",
        csv_path=PSR_ROOT,
        output_html=Path(f"output/modulacao_psr_2025_{submarket}_2030_2059.html"),
        output_price_curves_csv=Path(f"output/curvas_preco_psr_2025_{submarket}_2030_2059.csv"),
        output_summary_csv=Path(f"output/modulacao_psr_2025_{submarket}_2030_2059.csv"),
        family_label="PSR 2025",
        price_description=(
            f"curva horaria PSR 2025 {submarket.upper()} agregada pela media das 400 series"
        ),
        source_kind="psr_2025",
        submarket=submarket,
        source_note=(
            "PSR 2025: curvas 2030-2040; para casar com os 30 anos solares, "
            "2041-2059 repetem a curva de preco de 2040. Cada hora usa a media "
            "aritmetica das 400 series do CSV anual."
        ),
    )
    for submarket in ("se", "ne", "no", "su")
)


@dataclass(frozen=True)
class AnnualModulation:
    calendar_year: int
    price_source_year: int
    price_repeated: bool
    solar_year_idx: int
    solar_year_exact: bool
    price_mean_brl_mwh: float
    price_min_brl_mwh: float
    price_max_brl_mwh: float
    solar_generation_mwh: float
    gf_energy_mwh: float
    captured_solar_brl_mwh: float
    capture_factor_pct: float
    modulation_brl_mwh_energy: float
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

    first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    sep = ";" if ";" in first_line else ","

    raw = pd.read_csv(
        path,
        sep=sep,
        skiprows=2,
        header=None,
        engine="python",
    )
    if raw.shape[1] >= 5:
        local_text = raw.iloc[:, 2].astype(str) + " " + raw.iloc[:, 3].astype(str)
        local_datetime = pd.to_datetime(
            local_text,
            format="%d/%m/%Y %H:%M:%S",
            errors="raise",
        )
        price_series = raw.iloc[:, 4]
    elif raw.shape[1] >= 3:
        local_datetime = pd.to_datetime(
            raw.iloc[:, 1].astype(str),
            format="%Y-%m-%d %H:%M:%S",
            errors="raise",
        )
        price_series = raw.iloc[:, 2]
    else:
        raise ValueError(f"Unexpected price CSV layout in {path}: {raw.shape[1]} columns.")

    df = pd.DataFrame(
        {
            "local_datetime": local_datetime,
            "price_brl_mwh": pd.to_numeric(price_series, errors="coerce"),
        }
    )
    if df["price_brl_mwh"].isna().any():
        first_bad = int(np.flatnonzero(df["price_brl_mwh"].isna().to_numpy())[0])
        raise ValueError(f"Non-numeric price on row {first_bad + 3} of {path}")

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


def _read_psr_2025_curve(path: Path) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(f"PSR price CSV not found: {path}")

    raw = pd.read_csv(path)
    if len(raw) != HOURS_PER_YEAR:
        raise ValueError(f"PSR file {path} has {len(raw)} rows; expected {HOURS_PER_YEAR}.")

    numeric = raw.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        bad_row, bad_col = np.argwhere(numeric.isna().to_numpy())[0]
        raise ValueError(f"Non-numeric PSR price at row {bad_row + 2}, column {bad_col + 1} in {path}.")

    return numeric.mean(axis=1).to_numpy(dtype=np.float64)


def _psr_2025_price_curves_by_year(
    submarket: str,
    start_year: int,
    end_year: int,
) -> tuple[dict[int, np.ndarray], dict[int, int]]:
    curves: dict[int, np.ndarray] = {}
    source_years: dict[int, int] = {}
    source_cache: dict[int, np.ndarray] = {}

    for calendar_year in range(start_year, end_year + 1):
        if calendar_year < PSR_PRICE_START_YEAR:
            raise ValueError(f"PSR 2025 source starts in {PSR_PRICE_START_YEAR}, not {calendar_year}.")
        source_year = calendar_year if calendar_year <= PSR_PRICE_END_YEAR else PSR_REPEAT_YEAR
        if source_year not in source_cache:
            path = PSR_ROOT / str(source_year) / f"psr_price_{submarket}_{source_year}.csv"
            source_cache[source_year] = _read_psr_2025_curve(path)
        curves[calendar_year] = source_cache[source_year].copy()
        source_years[calendar_year] = source_year

    return curves, source_years


def _annual_rows(
    price_curves: dict[int, np.ndarray],
    solar: SolarProfile,
    *,
    start_year: int,
    price_source_years: dict[int, int] | None = None,
) -> list[AnnualModulation]:
    if solar.generation_years_lim_mw is None:
        raise ValueError("Solar CSV must provide multi-year generation_years_lim_mw.")

    gf_energy_mwh = float(solar.garantia_fisica_mw * HOURS_PER_YEAR)
    rows: list[AnnualModulation] = []

    for calendar_year in sorted(price_curves):
        requested_solar_year = calendar_year - start_year + 1
        solar_year_idx = max(1, min(requested_solar_year, solar.n_years))
        solar_year_exact = requested_solar_year == solar_year_idx
        price_source_year = (
            price_source_years[calendar_year]
            if price_source_years is not None
            else calendar_year
        )
        price_repeated = price_source_year != calendar_year
        generation_mwh = solar.generation_years_lim_mw[solar_year_idx - 1].astype(np.float64)
        prices = price_curves[calendar_year]

        solar_generation_mwh = float(generation_mwh.sum())
        captured_total = float(np.sum(generation_mwh * prices))
        captured_solar = captured_total / solar_generation_mwh if solar_generation_mwh > 0 else math.nan
        price_mean = float(np.mean(prices))
        capture_factor = captured_solar / price_mean * 100.0 if price_mean else math.nan
        modulation = modulation_value_brl_per_mwh(
            generation_mwh,
            prices,
            gf_energy_mwh,
            DEFAULT_MODULATION_MODE,
        )
        if modulation is None:
            modulation = math.nan
        notes = []
        if solar_year_exact:
            notes.append("Curva solar exata.")
        else:
            notes.append(f"Ano solar {solar.n_years} reutilizado; CSV solar nao possui ano {requested_solar_year}.")
        if price_repeated:
            notes.append(f"Preco {price_source_year} repetido.")

        rows.append(
            AnnualModulation(
                calendar_year=calendar_year,
                price_source_year=price_source_year,
                price_repeated=price_repeated,
                solar_year_idx=solar_year_idx,
                solar_year_exact=solar_year_exact,
                price_mean_brl_mwh=price_mean,
                price_min_brl_mwh=float(np.min(prices)),
                price_max_brl_mwh=float(np.max(prices)),
                solar_generation_mwh=solar_generation_mwh,
                gf_energy_mwh=gf_energy_mwh,
                captured_solar_brl_mwh=float(captured_solar),
                capture_factor_pct=float(capture_factor),
                modulation_brl_mwh_energy=float(modulation),
                note=" ".join(notes),
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


MONTH_LABELS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _hourly_index(year: int) -> pd.DatetimeIndex:
    idx = pd.date_range(f"{year}-01-01 00:00:00", f"{year}-12-31 23:00:00", freq="h")
    if len(idx) == 8784:
        idx = idx[~((idx.month == 2) & (idx.day == 29))]
    if len(idx) != HOURS_PER_YEAR:
        raise ValueError(f"Year {year} hourly index has {len(idx)} hours; expected {HOURS_PER_YEAR}.")
    return idx


def _monthly_hourly_average(year: int, values: np.ndarray) -> np.ndarray:
    """Return a 24 x 12 matrix: typical-hour price by month for one year."""
    series = pd.Series(np.asarray(values, dtype=np.float64), index=_hourly_index(year))
    matrix = np.zeros((24, 12), dtype=np.float64)
    for month in range(1, 13):
        month_series = series[series.index.month == month]
        for hour in range(24):
            matrix[hour, month - 1] = float(month_series[month_series.index.hour == hour].mean())
    return matrix


def _typical_day_average(values: np.ndarray) -> np.ndarray:
    return np.asarray(values, dtype=np.float64).reshape(365, 24).mean(axis=0)


def _nice_price_axis(values: list[np.ndarray]) -> tuple[float, float]:
    combined = np.concatenate([np.asarray(v, dtype=np.float64).ravel() for v in values])
    lo = float(np.min(combined))
    hi = float(np.max(combined))
    span = max(hi - lo, 1.0)
    for step in (10, 25, 50, 100, 200, 500):
        if span / step <= 6:
            break
    y_min = max(0.0, math.floor(lo / step) * step)
    y_max = math.ceil(hi / step) * step
    if y_max <= y_min:
        y_max = y_min + step
    return float(y_min), float(y_max)


def _interpolate_rgb(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _heat_color(value: float, min_value: float, max_value: float) -> str:
    span = max(max_value - min_value, 1e-9)
    t = (float(value) - min_value) / span
    if t <= 0.5:
        rgb = _interpolate_rgb((224, 242, 254), (254, 243, 199), t / 0.5)
    else:
        rgb = _interpolate_rgb((254, 243, 199), (185, 28, 28), (t - 0.5) / 0.5)
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


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
    values = np.array([row.modulation_brl_mwh_energy for row in rows], dtype=float)
    ymin = min(0.0, float(values.min()))
    ymax = max(0.0, float(values.max()))
    if ymax > 0:
        ymax *= 1.08
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
        y_value = pad_top + plot_h - ((row.modulation_brl_mwh_energy - ymin) / span * plot_h)
        y = min(y_value, zero_y)
        h = max(1.0, abs(zero_y - y_value))
        color = "#0f766e" if row.modulation_brl_mwh_energy >= 0 else "#b45309"
        if not row.solar_year_exact or row.price_repeated:
            color = "#92400e"
        bars.append(
            f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{h:.2f}" '
            f'rx="2" fill="{color}"><title>{row.calendar_year}: '
            f'{_format_brl(row.modulation_brl_mwh_energy)}/MWh injetado</title></rect>'
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
      <text class="axis-label" transform="translate(18 {pad_top + plot_h / 2}) rotate(-90)" text-anchor="middle">R$/MWh injetado</text>
    </svg>
    """


def _price_curve_tabs(price_curves: dict[int, np.ndarray], rows: list[AnnualModulation]) -> str:
    row_by_year = {row.calendar_year: row for row in rows}
    daily_by_year = {year: _daily_average(values) for year, values in price_curves.items()}
    typical_by_year = {year: _typical_day_average(values) for year, values in price_curves.items()}
    years = sorted(price_curves)
    groups = [years[i : i + 5] for i in range(0, len(years), 5)]

    inputs = []
    labels = []
    panels = []
    tab_css = []
    for tab_idx, group in enumerate(groups):
        tab_id = f"price-tab-{tab_idx}"
        panel_id = f"price-panel-{tab_idx}"
        first_year, last_year = group[0], group[-1]
        checked = " checked" if tab_idx == 0 else ""
        inputs.append(f'<input class="tab-input" type="radio" name="price-tabs" id="{tab_id}"{checked} />')
        labels.append(f'<label class="tab-label" for="{tab_id}">{first_year}-{last_year}</label>')
        tab_css.append(
            f"#{tab_id}:checked ~ .tab-labels label[for='{tab_id}'] {{"
            "background: var(--teal); color: #fff; border-color: var(--teal);"
            "}"
            f"#{tab_id}:checked ~ .tab-panels #{panel_id} {{ display: grid; }}"
        )

        cards = []
        for year in group:
            daily = daily_by_year[year]
            typical = typical_by_year[year]
            row = row_by_year[year]
            badge_text = "solar exato"
            badge_class = "badge"
            if row.price_repeated:
                badge_text = f"preco {row.price_source_year}"
                badge_class = "badge warn"
            if not row.solar_year_exact:
                badge_text = "solar reutilizado"
                badge_class = "badge warn"
            y_min, y_max = _nice_price_axis([daily, typical])
            y_ticks = []
            for tick in np.linspace(y_min, y_max, 5):
                y = 34 + 230 - ((float(tick) - y_min) / max(y_max - y_min, 1e-9) * 230)
                y_ticks.append(
                    f'<line class="mini-grid" x1="62" y1="{y:.2f}" x2="462" y2="{y:.2f}" />'
                    f'<line class="mini-grid" x1="558" y1="{y:.2f}" x2="858" y2="{y:.2f}" />'
                    f'<text class="mini-tick" x="54" y="{y + 4:.2f}" text-anchor="end">{_format_number(float(tick), 0)}</text>'
                    f'<text class="mini-tick" x="550" y="{y + 4:.2f}" text-anchor="end">{_format_number(float(tick), 0)}</text>'
                )
            daily_path = _line_path(daily, width=400, height=230, min_value=y_min, max_value=y_max)
            typical_path = _line_path(typical, width=300, height=230, min_value=y_min, max_value=y_max)
            month_ticks = []
            for month, label in enumerate(MONTH_LABELS):
                day_idx = pd.Timestamp(year=year, month=month + 1, day=15).dayofyear - 1
                x = 62 + 400 * day_idx / 364
                month_ticks.append(
                    f'<text class="mini-tick" x="{x:.1f}" y="292" text-anchor="middle">{label}</text>'
                )
            hour_ticks = []
            for hour in (0, 4, 8, 12, 16, 20, 23):
                x = 558 + 300 * hour / 23
                hour_ticks.append(
                    f'<text class="mini-tick" x="{x:.1f}" y="292" text-anchor="middle">{hour:02d}h</text>'
                )
            cards.append(
                f"""
                <article class="curve-card large" data-year="{year}">
                  <div class="curve-head">
                    <strong>{year}</strong>
                    <span class="{badge_class}">{badge_text}</span>
                  </div>
                  <svg viewBox="0 0 900 330" role="img" aria-label="Curvas de preco {year}">
                    <text class="chart-subtitle" x="262" y="20" text-anchor="middle">Curva anual diaria media</text>
                    <text class="chart-subtitle" x="708" y="20" text-anchor="middle">Dia tipico anual</text>
                    <rect class="mini-bg" x="62" y="34" width="400" height="230" />
                    <rect class="mini-bg" x="558" y="34" width="300" height="230" />
                    {''.join(y_ticks)}
                    <line class="mini-axis" x1="62" y1="264" x2="462" y2="264" />
                    <line class="mini-axis" x1="62" y1="34" x2="62" y2="264" />
                    <line class="mini-axis" x1="558" y1="264" x2="858" y2="264" />
                    <line class="mini-axis" x1="558" y1="34" x2="558" y2="264" />
                    <polyline fill="none" stroke="#0f766e" stroke-width="2.4" stroke-linejoin="round"
                      stroke-linecap="round" points="{daily_path}" transform="translate(62,34)" />
                    <polyline fill="none" stroke="#1d4ed8" stroke-width="2.4" stroke-linejoin="round"
                      stroke-linecap="round" points="{typical_path}" transform="translate(558,34)" />
                    {''.join(month_ticks)}
                    {''.join(hour_ticks)}
                    <text class="axis-label" x="262" y="318" text-anchor="middle">Mes</text>
                    <text class="axis-label" x="708" y="318" text-anchor="middle">Hora</text>
                    <text class="axis-label" transform="translate(18 149) rotate(-90)" text-anchor="middle">PLD (R$/MWh)</text>
                    <text class="axis-label" transform="translate(514 149) rotate(-90)" text-anchor="middle">PLD (R$/MWh)</text>
                  </svg>
                  <div class="curve-stats">
                    <span>PLD medio {_format_brl(row.price_mean_brl_mwh, 1)}</span>
                    <span>spread {_format_brl(row.modulation_brl_mwh_energy, 1)}</span>
                  </div>
                </article>
                """
            )
        panels.append(f'<div class="tab-panel" id="{panel_id}">{"".join(cards)}</div>')

    return f"""
    <div class="price-tabs">
      {''.join(inputs)}
      <div class="tab-labels">{''.join(labels)}</div>
      <div class="tab-panels">{''.join(panels)}</div>
      <style>{''.join(tab_css)}</style>
    </div>
    """


def _summary_table(rows: list[AnnualModulation]) -> str:
    trs = []
    for row in rows:
        exact = "Sim" if row.solar_year_exact else "Nao"
        price_repeated = "Sim" if row.price_repeated else "Nao"
        tr_class = ' class="warn-row"' if (not row.solar_year_exact or row.price_repeated) else ""
        trs.append(
            f"""
            <tr{tr_class}>
              <td>{row.calendar_year}</td>
              <td>{row.price_source_year}</td>
              <td>{price_repeated}</td>
              <td>{row.solar_year_idx}</td>
              <td>{exact}</td>
              <td>{_format_brl(row.price_mean_brl_mwh)}</td>
              <td>{_format_brl(row.captured_solar_brl_mwh)}</td>
              <td>{_format_number(row.capture_factor_pct, 1)}%</td>
              <td>{_format_brl(row.modulation_brl_mwh_energy)}</td>
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
          <th>Ano preco</th>
          <th>Preco repetido</th>
          <th>Ano solar</th>
          <th>Exato</th>
          <th>PLD medio</th>
          <th>Preco capturado solar</th>
          <th>Fator captura</th>
          <th>Modulacao por energia</th>
          <th>Geracao solar MWh</th>
          <th>Observacao</th>
        </tr>
      </thead>
      <tbody>{''.join(trs)}</tbody>
    </table>
    """


def _render_html(
    rows: list[AnnualModulation],
    price_curves: dict[int, np.ndarray],
    solar: SolarProfile,
    scenario: PriceScenario,
) -> str:
    exact_rows = [row for row in rows if row.solar_year_exact]
    reused_rows = [row for row in rows if not row.solar_year_exact]
    repeated_price_rows = [row for row in rows if row.price_repeated]
    first = rows[0]
    last_exact = exact_rows[-1] if exact_rows else rows[-1]
    avg_pld_exact = float(np.mean([row.price_mean_brl_mwh for row in exact_rows])) if exact_rows else math.nan
    avg_spread_exact = (
        float(np.mean([row.modulation_brl_mwh_energy for row in exact_rows]))
        if exact_rows
        else math.nan
    )
    max_mod = max(rows, key=lambda row: row.modulation_brl_mwh_energy)
    min_mod = min(rows, key=lambda row: row.modulation_brl_mwh_energy)

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

    source_note_html = ""
    if scenario.source_note:
        source_note_html = f"""
        <section class="notice">
          <strong>Fonte de preco:</strong> {escape(scenario.source_note)}
        </section>
        """

    if repeated_price_rows and not source_note_html:
        years = ", ".join(str(row.calendar_year) for row in repeated_price_rows)
        source_note_html = f"""
        <section class="notice">
          <strong>Fonte de preco:</strong>
          {escape(years)} reutilizam o ano de preco indicado na tabela anual.
        </section>
        """

    payload = {
        "price_scenario": scenario.label,
        "price_family": scenario.family_label,
        "price_source": str(scenario.csv_path),
        "price_source_kind": scenario.source_kind,
        "price_submarket": scenario.submarket,
        "solar_csv": str(SOLAR_CSV),
        "mwac": MWAC,
        "start_year": START_YEAR,
        "end_year": END_YEAR,
        "hours_per_year": HOURS_PER_YEAR,
        "curtailment_mwh": 0.0,
        "modulation_mode": DEFAULT_MODULATION_MODE,
        "modulation_formula": "sum(solar_injection * PLD) / sum(solar_injection) - mean(PLD)",
        "source_note": scenario.source_note,
        "price_curves_csv": str(scenario.output_price_curves_csv),
        "summary_csv": str(scenario.output_summary_csv),
    }

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Modulacao {escape(scenario.family_label)} {escape(scenario.label)} {START_YEAR}-{END_YEAR}</title>
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
    .mini-grid {{ stroke: #edf3f1; stroke-width: 1; }}
    .axis, .mini-axis {{ stroke: #91a4a1; stroke-width: 1; }}
    .axis-text, .axis-label, .mini-tick {{
      fill: var(--muted);
      font-size: 11px;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .axis-label {{ font-weight: 700; }}
    .chart-subtitle {{
      fill: #334542;
      font-size: 13px;
      font-weight: 700;
      font-family: Arial, Helvetica, sans-serif;
    }}
    .price-tabs {{
      margin-top: 12px;
    }}
    .tab-input {{
      position: absolute;
      opacity: 0;
      pointer-events: none;
    }}
    .tab-labels {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-bottom: 14px;
    }}
    .tab-label {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px 12px;
      background: #fff;
      color: var(--muted);
      cursor: pointer;
      font-weight: 700;
      font-size: 13px;
    }}
    .tab-panels {{
      min-height: 640px;
    }}
    .tab-panel {{
      display: none;
      grid-template-columns: 1fr;
      gap: 16px;
    }}
    .curve-card {{
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px 14px 10px;
      background: #fff;
    }}
    .curve-head, .curve-stats {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
    }}
    .curve-head strong {{ font-size: 15px; }}
    .curve-card.large .curve-head strong {{ font-size: 18px; }}
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
      margin: 8px 0 4px;
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
    <h1>Modulacao {escape(scenario.family_label)} {escape(scenario.label)} {START_YEAR}-{END_YEAR}</h1>
    <p>
      Calculo simplificado com {escape(scenario.price_description)}, Ano Solar 1 = {START_YEAR},
      injecao solar sem BESS por <code>{escape(str(SOLAR_CSV))}</code> e curtailment zero.
      A modulacao segue a formula atual do projeto por energia: preco capturado pela injecao solar menos PLD medio.
    </p>
    <div class="kpis">
      <div class="kpi"><span>Cenario de preco</span><strong>{escape(scenario.label)}</strong></div>
      <div class="kpi"><span>Horizonte solicitado</span><strong>{START_YEAR}-{END_YEAR}</strong></div>
      <div class="kpi"><span>Solar exato</span><strong>{START_YEAR}-{last_exact.calendar_year}</strong></div>
      <div class="kpi"><span>GF usada</span><strong>{_format_number(solar.garantia_fisica_mw, 2)} MW</strong></div>
      <div class="kpi"><span>PLD medio exato</span><strong>{_format_brl(avg_pld_exact)}</strong></div>
      <div class="kpi"><span>Spread medio exato</span><strong>{_format_brl(avg_spread_exact)}</strong></div>
    </div>
  </header>
  <main>
    {warning_html}
    {source_note_html}
    <section>
      <h2>Valor de modulacao por ano</h2>
      {_bar_chart(rows)}
      <div class="footnote">
        Maior premio: {max_mod.calendar_year} ({_format_brl(max_mod.modulation_brl_mwh_energy)}/MWh injetado).
        Menor premio: {min_mod.calendar_year} ({_format_brl(min_mod.modulation_brl_mwh_energy)}/MWh injetado).
      </div>
    </section>
    <section>
      <h2>Curvas de preco</h2>
      <p class="footnote">
        Os calculos usam as 8.760 horas de cada ano. As abas agrupam 5 anos por vez
        e cada ano traz dois graficos: a curva anual media diaria por mes e, ao lado,
        o dia tipico anual com eixo X de 0h a 23h e eixo Y em PLD. O CSV gerado
        preserva a curva horaria completa por ano.
      </p>
      {_price_curve_tabs(price_curves, rows)}
    </section>
    <section>
      <h2>Tabela anual</h2>
      <div class="table-wrap">{_summary_table(rows)}</div>
      <div class="footnote">
        Arquivos gerados: <code>{escape(str(scenario.output_price_curves_csv))}</code> e
        <code>{escape(str(scenario.output_summary_csv))}</code>.
      </div>
    </section>
  </main>
  <script type="application/json" id="run-metadata">{escape(json.dumps(payload, ensure_ascii=False, indent=2))}</script>
</body>
</html>
"""


def main() -> None:
    solar = load_solar_csv(str(SOLAR_CSV), MWAC)
    for scenario in SCENARIOS + PSR_SCENARIOS:
        scenario.output_html.parent.mkdir(parents=True, exist_ok=True)
        if scenario.source_kind == "psr_2025":
            if scenario.submarket is None:
                raise ValueError(f"PSR scenario {scenario.key} must define a submarket.")
            price_curves, price_source_years = _psr_2025_price_curves_by_year(
                scenario.submarket,
                START_YEAR,
                END_YEAR,
            )
        else:
            price_curves = _price_curves_by_year(scenario.csv_path, START_YEAR, END_YEAR)
            price_source_years = {year: year for year in price_curves}

        rows = _annual_rows(
            price_curves,
            solar,
            start_year=START_YEAR,
            price_source_years=price_source_years,
        )

        _write_price_curves_csv(price_curves, scenario.output_price_curves_csv)
        _write_summary_csv(rows, scenario.output_summary_csv)
        scenario.output_html.write_text(
            _render_html(rows, price_curves, solar, scenario),
            encoding="utf-8",
        )

        exact_count = sum(1 for row in rows if row.solar_year_exact)
        print(f"[{scenario.label}] Generated {scenario.output_html}")
        print(f"[{scenario.label}] Generated {scenario.output_price_curves_csv}")
        print(f"[{scenario.label}] Generated {scenario.output_summary_csv}")
        print(f"[{scenario.label}] Exact solar-year rows: {exact_count}/{len(rows)}")


if __name__ == "__main__":
    main()
