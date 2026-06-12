"""Generate an HTML report for the 8760-hour curtailment profile."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots


INPUT = Path("dados/curtailment_8760_conj_seriemas_i_ano_medio_total_pct.csv")
SOLAR_INPUT = Path("solar/solar_baguacu_m2_600mw_id8.csv")
OUTPUT = Path("output/curtailment_8760_conj_seriemas_i_ano_medio_total_pct.html")


def _fmt(value: float, decimals: int = 2) -> str:
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def main() -> None:
    df = pd.read_csv(INPUT, sep=";")
    solar = pd.read_csv(SOLAR_INPUT)
    required = {"hour_of_year", "month", "day", "hour_of_day", "curtailment_rate", "curtailment_pct"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    if len(df) != 8760:
        raise ValueError(f"Expected 8760 rows, got {len(df)}")
    if len(solar) % 8760 != 0:
        raise ValueError(f"Expected solar rows to be a multiple of 8760, got {len(solar)}")
    for col in ("year_idx", "gen_lim_mw"):
        if col not in solar.columns:
            raise ValueError(f"Missing solar column: {col}")

    df["curtailment_pct"] = pd.to_numeric(df["curtailment_pct"], errors="raise")
    df["curtailment_rate"] = pd.to_numeric(df["curtailment_rate"], errors="raise")
    df["timestamp"] = pd.date_range("2025-01-01 00:00:00", periods=len(df), freq="h")
    df["day_of_year"] = df["hour_of_year"] // 24 + 1

    avg_pct = float(df["curtailment_pct"].mean())
    max_pct = float(df["curtailment_pct"].max())
    p95_pct = float(df["curtailment_pct"].quantile(0.95))
    nonzero_hours = int((df["curtailment_pct"] > 0).sum())
    nonzero_pct = nonzero_hours / len(df) * 100.0
    daylight = df[df["hour_of_day"].between(5, 19)]
    daylight_avg_pct = float(daylight["curtailment_pct"].mean())

    rate = df["curtailment_rate"].to_numpy()
    weighted_rows: list[dict[str, float]] = []
    for year_idx, year_df in solar.groupby("year_idx", sort=True):
        gen = pd.to_numeric(year_df["gen_lim_mw"], errors="raise").to_numpy()
        curtailed_mwh = float((gen * rate).sum())
        generation_mwh = float(gen.sum())
        weighted_rows.append({
            "year_idx": int(year_idx),
            "generation_mwh": generation_mwh,
            "curtailed_mwh": curtailed_mwh,
            "weighted_pct": curtailed_mwh / generation_mwh * 100.0,
        })
    weighted = pd.DataFrame(weighted_rows)
    weighted_first20 = weighted[weighted["year_idx"] <= 20]
    energy_weighted_pct = float(weighted["curtailed_mwh"].sum() / weighted["generation_mwh"].sum() * 100.0)
    energy_weighted_first20_pct = float(
        weighted_first20["curtailed_mwh"].sum() / weighted_first20["generation_mwh"].sum() * 100.0
    )
    curtailed_first20_mwm = float(weighted_first20["curtailed_mwh"].sum() / (8760 * len(weighted_first20)))
    generation_first20_mwm = float(weighted_first20["generation_mwh"].sum() / (8760 * len(weighted_first20)))

    hourly = df.groupby("hour_of_day", as_index=False)["curtailment_pct"].mean()
    year1_solar = solar[solar["year_idx"] == int(solar["year_idx"].min())].copy()
    year1_solar = year1_solar.reset_index(drop=True)
    df["baguacu_gen_lim_mw"] = pd.to_numeric(year1_solar["gen_lim_mw"], errors="raise")
    df["curtailed_baguacu_mwh"] = df["baguacu_gen_lim_mw"] * df["curtailment_rate"]
    monthly = (
        df.groupby("month", as_index=False)
        .agg(generation_mwh=("baguacu_gen_lim_mw", "sum"), curtailed_mwh=("curtailed_baguacu_mwh", "sum"))
    )
    monthly["curtailment_energy_pct"] = monthly["curtailed_mwh"] / monthly["generation_mwh"] * 100.0
    heat = (
        df.pivot_table(
            index="month",
            columns="hour_of_day",
            values="curtailment_pct",
            aggfunc="mean",
        )
        .sort_index()
    )

    fig = make_subplots(
        rows=4,
        cols=1,
        row_heights=[0.34, 0.22, 0.18, 0.26],
        vertical_spacing=0.08,
        subplot_titles=(
            "Curva horaria 8760",
            "Media por hora do dia",
            "Curtailment mensal ponderado por energia de Baguacu",
            "Heatmap: mes x hora do dia",
        ),
    )

    fig.add_trace(
        go.Scattergl(
            x=df["timestamp"],
            y=df["curtailment_pct"],
            mode="lines",
            name="Curtailment horario",
            line=dict(color="#2364aa", width=1.2),
            hovertemplate=(
                "Data/hora: %{x|%d/%m %H:%M}<br>"
                "Curtailment: %{y:.3f}%<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )
    fig.add_hline(
        y=avg_pct,
        line_dash="dash",
        line_color="#c0392b",
        annotation_text=f"media 8760 = {_fmt(avg_pct, 3)}%",
        annotation_position="top right",
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=hourly["hour_of_day"],
            y=hourly["curtailment_pct"],
            name="Media por hora",
            marker_color="#2a9d8f",
            hovertemplate="Hora: %{x}:00<br>Media: %{y:.3f}%<extra></extra>",
        ),
        row=2,
        col=1,
    )

    fig.add_trace(
        go.Bar(
            x=monthly["month"],
            y=monthly["curtailment_energy_pct"],
            name="Energia curtailed / geracao",
            marker_color="#e9c46a",
            hovertemplate=(
                "Mes: %{x}<br>"
                "Curtailment energia: %{y:.3f}%<br>"
                "Geracao: %{customdata[0]:,.0f} MWh<br>"
                "Cortado: %{customdata[1]:,.0f} MWh<extra></extra>"
            ),
            customdata=monthly[["generation_mwh", "curtailed_mwh"]],
        ),
        row=3,
        col=1,
    )

    fig.add_trace(
        go.Heatmap(
            z=heat.values,
            x=list(heat.columns),
            y=list(heat.index),
            colorscale="Viridis",
            colorbar=dict(title="%"),
            name="Mes x hora",
            hovertemplate="Mes: %{y}<br>Hora: %{x}:00<br>Media: %{z:.3f}%<extra></extra>",
        ),
        row=4,
        col=1,
    )

    fig.update_xaxes(title_text="Data/hora", row=1, col=1)
    fig.update_xaxes(title_text="Hora do dia", dtick=1, row=2, col=1)
    fig.update_xaxes(title_text="Mes", dtick=1, row=3, col=1)
    fig.update_xaxes(title_text="Hora do dia", dtick=1, row=4, col=1)
    fig.update_yaxes(title_text="Curtailment (%)", row=1, col=1)
    fig.update_yaxes(title_text="Curtailment (%)", row=2, col=1)
    fig.update_yaxes(title_text="Curtailment (%)", row=3, col=1)
    fig.update_yaxes(title_text="Mes", dtick=1, row=4, col=1)

    fig.update_layout(
        title=(
            "Curtailment 8760 - conjunto Seriemas I<br>"
            f"<sup>Energia curtailed Baguaçu gen_lim 20 anos: {_fmt(energy_weighted_first20_pct, 3)}% "
            f"({_fmt(curtailed_first20_mwm, 3)} MWm de {_fmt(generation_first20_mwm, 3)} MWm) | "
            f"Todos 30 anos: {_fmt(energy_weighted_pct, 3)}% | "
            f"Media simples 8760: {_fmt(avg_pct, 3)}% | "
            f"Media horas 05-19: {_fmt(daylight_avg_pct, 3)}% | "
            f"P95: {_fmt(p95_pct, 3)}% | Max: {_fmt(max_pct, 3)}% | "
            f"Horas > 0: {nonzero_hours} ({_fmt(nonzero_pct, 1)}%)</sup>"
        ),
        template="plotly_white",
        height=1200,
        margin=dict(l=70, r=40, t=100, b=60),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUTPUT, include_plotlyjs="inline", full_html=True)

    print(f"Arquivo: {OUTPUT}")
    print(f"curtailment_energia_baguacu_gen_lim_20anos_pct={energy_weighted_first20_pct:.6f}")
    print(f"curtailment_energia_baguacu_gen_lim_30anos_pct={energy_weighted_pct:.6f}")
    print(f"geracao_baguacu_gen_lim_20anos_mwm={generation_first20_mwm:.6f}")
    print(f"curtailed_baguacu_gen_lim_20anos_mwm={curtailed_first20_mwm:.6f}")
    print(f"media_simples_8760_pct={avg_pct:.6f}")
    print(f"media_05_19_pct={daylight_avg_pct:.6f}")
    print(f"p95_pct={p95_pct:.6f}")
    print(f"max_pct={max_pct:.6f}")
    print(f"horas_com_curtailment={nonzero_hours}")


if __name__ == "__main__":
    main()
