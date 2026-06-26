"""Gera a curva mensal de curtailment realizado 2025 vs 2026 (jan-mai).

Fonte: ``dados/media_agregada_horaria_2025_2026.xlsx`` (taxa horária de
curtailment realizada ONS por conjunto, 0-1). 2025 = ano cheio; 2026 = dados
realizados até 16/mai/2026 (último mês fechado = maio).

Metodologia (mesma de ``solar_bess_risk.__main__``): curtailment mensal
ponderado por energia, ``Σ(taxa_h · geração_h) / Σ(geração_h)``, usando o
perfil ``gen_lim_mw`` de Baguaçu (ano 1) como peso de geração. Resultado em %.

Saída: ``output/curvas/curtailment_mensal_2025_2026.html`` (auto-contido).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parents[2]
CURTAILMENT_XLSX = ROOT / "dados" / "media_agregada_horaria_2025_2026.xlsx"
SOLAR_CSV = ROOT / "solar" / "solar_baguacu_m2_600mw_id8.csv"
OUTPUT = ROOT / "output" / "curvas" / "curtailment_mensal_2025_2026.html"

SHEETS = {2025: "2025_horario", 2026: "2026_horario"}
PRIMARY_COL = "Conj. Pereira Barreto"          # conjunto do projeto (default config)
AGG_COL = "Media Agregada Todas as Usinas"     # referência: todas as usinas

MONTHS_PT = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
             "Jul", "Ago", "Set", "Out", "Nov", "Dez"]


def _fmt(value: float, decimals: int = 1) -> str:
    return f"{value:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _load_generation_weights() -> dict[tuple[int, int, int], float]:
    """Perfil de geração (gen_lim_mw, ano 1) indexado por (mês, dia, hora)."""
    solar = pd.read_csv(SOLAR_CSV)
    year1 = solar[solar["year_idx"] == int(solar["year_idx"].min())].copy()
    gen = pd.to_numeric(year1["gen_lim_mw"], errors="coerce").fillna(0.0).clip(lower=0.0)
    year1 = year1.assign(genw=gen)
    return {
        (int(r.month), int(r.day), int(r.hour)): float(r.genw)
        for r in year1.itertuples(index=False)
    }


def _monthly_weighted(df: pd.DataFrame, col: str, gen_map: dict) -> pd.DataFrame:
    """Curtailment mensal ponderado por energia para uma coluna de taxa."""
    rate = pd.to_numeric(df[col], errors="coerce").fillna(0.0).clip(lower=0.0, upper=1.0)
    gen = np.array([
        gen_map.get((int(m), int(d), int(h)), 0.0)
        for m, d, h in zip(df["Mês"], df["Dia"], df["Hora"])
    ])
    work = pd.DataFrame({
        "month": df["Mês"].astype(int),
        "curt_mwh": rate.to_numpy() * gen,
        "gen_mwh": gen,
    })
    grp = work.groupby("month", as_index=False).agg(
        curt_mwh=("curt_mwh", "sum"), gen_mwh=("gen_mwh", "sum")
    )
    grp["pct"] = np.where(grp["gen_mwh"] > 0, grp["curt_mwh"] / grp["gen_mwh"] * 100.0, 0.0)
    return grp


def _annual_weighted(df: pd.DataFrame, col: str, gen_map: dict) -> float:
    m = _monthly_weighted(df, col, gen_map)
    total_gen = m["gen_mwh"].sum()
    return float(m["curt_mwh"].sum() / total_gen * 100.0) if total_gen > 0 else 0.0


def main() -> None:
    gen_map = _load_generation_weights()

    data: dict[int, dict[str, pd.DataFrame]] = {}
    annual: dict[int, dict[str, float]] = {}
    for year, sheet in SHEETS.items():
        df = pd.read_excel(CURTAILMENT_XLSX, sheet_name=sheet)
        data[year] = {
            "primary": _monthly_weighted(df, PRIMARY_COL, gen_map),
            "agg": _monthly_weighted(df, AGG_COL, gen_map),
        }
        annual[year] = {
            "primary": _annual_weighted(df, PRIMARY_COL, gen_map),
            "agg": _annual_weighted(df, AGG_COL, gen_map),
        }

    colors = {2025: "#2364aa", 2026: "#e76f51"}
    fig = go.Figure()

    # Série primária (conjunto do projeto) — linha sólida
    for year in (2025, 2026):
        m = data[year]["primary"]
        fig.add_trace(go.Scatter(
            x=[MONTHS_PT[i - 1] for i in m["month"]],
            y=m["pct"],
            mode="lines+markers",
            name=f"{year} · Conj. Pereira Barreto",
            line=dict(color=colors[year], width=3),
            marker=dict(size=8),
            customdata=np.stack([m["curt_mwh"], m["gen_mwh"]], axis=-1),
            hovertemplate=(
                f"<b>{year} · Pereira Barreto</b><br>"
                "Mês: %{x}<br>Curtailment: %{y:.2f}%<br>"
                "Cortado: %{customdata[0]:,.0f} MWh · Gerável: %{customdata[1]:,.0f} MWh"
                "<extra></extra>"
            ),
        ))

    # Referência: média agregada de todas as usinas — linha tracejada
    for year in (2025, 2026):
        m = data[year]["agg"]
        fig.add_trace(go.Scatter(
            x=[MONTHS_PT[i - 1] for i in m["month"]],
            y=m["pct"],
            mode="lines+markers",
            name=f"{year} · Média agregada (todas)",
            line=dict(color=colors[year], width=2, dash="dot"),
            marker=dict(size=6, symbol="diamond"),
            opacity=0.65,
            visible="legendonly",
            hovertemplate=(
                f"<b>{year} · Média agregada</b><br>"
                "Mês: %{x}<br>Curtailment: %{y:.2f}%<extra></extra>"
            ),
        ))

    # Destaca que maio/2026 é mês parcial (dados até 16/05).
    may26 = data[2026]["primary"]
    may_pct = float(may26.loc[may26["month"] == 5, "pct"].iloc[0]) if (may26["month"] == 5).any() else None
    if may_pct is not None:
        fig.add_annotation(
            x="Mai", y=may_pct,
            text="maio/2026 parcial<br>(até 16/05)",
            showarrow=True, arrowhead=2, ax=-50, ay=-40,
            font=dict(size=11, color="#9c3a1f"),
            bgcolor="rgba(255,255,255,0.85)", bordercolor="#e76f51",
        )

    fig.update_xaxes(
        title_text="Mês",
        categoryorder="array",
        categoryarray=MONTHS_PT,
    )
    fig.update_yaxes(title_text="Curtailment (% da energia gerável)", rangemode="tozero")

    fig.update_layout(
        title=(
            "Curtailment mensal realizado — 2025 vs 2026<br>"
            "<sup>Conj. Pereira Barreto, ponderado por energia (geração Baguaçu gen_lim). "
            f"Média anual 2025 = {_fmt(annual[2025]['primary'], 1)}% · "
            f"2026 (jan–mai) = {_fmt(annual[2026]['primary'], 1)}%. "
            "2026 com dados realizados até 16/mai. Média agregada (todas as usinas) na legenda.</sup>"
        ),
        template="plotly_white",
        height=640,
        margin=dict(l=70, r=40, t=110, b=60),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.04, xanchor="left", x=0),
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(OUTPUT, include_plotlyjs="inline", full_html=True)

    print(f"Arquivo: {OUTPUT}")
    for year in (2025, 2026):
        print(f"{year}: anual Pereira Barreto = {annual[year]['primary']:.2f}% | "
              f"agregada = {annual[year]['agg']:.2f}%")
        m = data[year]["primary"]
        print("  mensal PB %:", ", ".join(
            f"{MONTHS_PT[int(r.month)-1]}={r.pct:.1f}" for r in m.itertuples(index=False)
        ))


if __name__ == "__main__":
    main()
