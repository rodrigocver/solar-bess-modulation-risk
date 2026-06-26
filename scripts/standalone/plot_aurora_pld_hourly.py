"""Gráfico do PLD horário (8.760h) da Aurora EOS por submercado.

Padrão: 2035, submercados SE e NE, sensibilidade central.

    python scripts/plot_aurora_pld_hourly.py
    python scripts/plot_aurora_pld_hourly.py --year 2040 --submarkets SE S NE N
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

from solar_bess_risk.data_sources import load_price_aurora_api

ROOT = Path(__file__).resolve().parents[2]
COLORS = {"SE": "#1f77b4", "S": "#2ca02c", "NE": "#d62728", "N": "#9467bd"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Gráfico PLD horário Aurora EOS.")
    parser.add_argument("--year", type=int, default=2035)
    parser.add_argument("--submarkets", nargs="+", default=["SE", "NE"])
    parser.add_argument("--sensitivity", default="central")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    idx = pd.date_range(f"{args.year}-01-01 00:00", f"{args.year}-12-31 23:00", freq="h")

    fig = go.Figure()
    print(f"PLD horário Aurora EOS {args.year} ({args.sensitivity}) — BRL/MWh:")
    for sm in args.submarkets:
        profile = load_price_aurora_api(args.year, sm, sensitivity=args.sensitivity)
        prices = profile.prices_brl_per_mwh
        if len(prices) != len(idx):
            raise SystemExit(
                f"{sm}: {len(prices)} horas (esperado {len(idx)}) — ano não-completo?"
            )
        p90 = float(pd.Series(prices).quantile(0.90))
        print(
            f"  {sm}: média={prices.mean():7.1f}  min={prices.min():6.1f}  "
            f"max={prices.max():7.1f}  P90={p90:7.1f}"
        )
        fig.add_trace(
            go.Scatter(
                x=idx,
                y=prices,
                name=sm,
                line=dict(color=COLORS.get(sm), width=0.6),
            )
        )

    fig.update_layout(
        title=(
            f"PLD horário Aurora EOS — {args.year} · {args.sensitivity} · "
            f"{' vs '.join(args.submarkets)} · 8.760 horas"
        ),
        xaxis_title="Hora do ano",
        yaxis_title="Preço (BRL/MWh, brl2025)",
        template="plotly_white",
        legend_title="Submercado",
        hovermode="x unified",
    )

    out = args.out or ROOT / "output" / (
        f"pld_aurora_{args.year}_{'_'.join(args.submarkets).lower()}_{args.sensitivity}.html"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(out, include_plotlyjs="cdn")
    print(f"\nHTML: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
