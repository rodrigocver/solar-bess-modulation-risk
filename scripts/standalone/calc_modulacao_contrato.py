"""Valoracao da modulacao de um contrato flat parcialmente lastreado em geracao solar.

Caso: usina gera G_h (curva horaria multi-ano); vende C MWmed flat. Na CCEE a
posicao liquida horaria (G_h - C) e liquidada ao preco horario. O custo de
modulacao do contrato e a diferenca entre entregar C "na curva de geracao" e
entregar C flat:

    custo_mod = C * H * (preco_medio_flat - preco_ponderado_geracao)

Dois casos sao calculados:
  - flat anual: C constante em todas as horas do ano;
  - sazonalizado: C_m = C * (geracao_mes / geracao_ano), flat dentro do mes
    (isola a componente intradiaria/horaria; a diferenca para o flat anual e a
    componente sazonal).

A sobra descontratada (G - C) e valorada ao preco ponderado pela geracao e
reportada separadamente — e risco de preco, nao modulacao.

Saidas em output/modulacao_contrato/.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.config import HOURS_PER_YEAR
from solar_bess_risk.profile import load_solar_csv

SOLAR_CSV = Path("solar/solar_baguacu_m2_600mw_id8.csv")
PRICE_CSV = Path("dados/curvas_preco/curvas_preco_brazil_q2_26_central_2030_2059.csv")
OUTPUT_DIR = Path("output/modulacao_contrato")
MWAC = 600.0
START_YEAR = 2030
CONTRACT_MW = 150.3

# Limites de horas por mes em um ano nao bissexto de 8760h (mesma convencao do
# restante do pipeline: curva solar e de preco sem 29/02).
_DAYS_PER_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_MONTH_HOURS = np.array([d * 24 for d in _DAYS_PER_MONTH])
_MONTH_EDGES = np.concatenate([[0], np.cumsum(_MONTH_HOURS)])


def _price_curves(path: Path) -> dict[int, np.ndarray]:
    df = pd.read_csv(path)
    curves: dict[int, np.ndarray] = {}
    for col in df.columns:
        if col.startswith("price_") and col.endswith("_brl_mwh"):
            year = int(col.split("_")[1])
            values = df[col].to_numpy(dtype=np.float64)
            if values.shape[0] != HOURS_PER_YEAR:
                raise ValueError(f"{path}: coluna {col} tem {values.shape[0]} horas; esperado {HOURS_PER_YEAR}.")
            curves[year] = values
    if not curves:
        raise ValueError(f"{path}: nenhuma coluna price_YYYY_brl_mwh encontrada.")
    return curves


def _monthly_slices() -> list[slice]:
    return [slice(int(_MONTH_EDGES[m]), int(_MONTH_EDGES[m + 1])) for m in range(12)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-mw", type=float, default=CONTRACT_MW)
    parser.add_argument("--solar-csv", type=Path, default=SOLAR_CSV)
    parser.add_argument("--price-csv", type=Path, default=PRICE_CSV)
    args = parser.parse_args()

    contract_mw = args.contract_mw
    solar = load_solar_csv(str(args.solar_csv), MWAC)
    if solar.generation_years_lim_mw is None:
        raise ValueError("CSV solar precisa ser multi-ano (gen_lim_mw).")
    prices_by_year = _price_curves(args.price_csv)
    slices = _monthly_slices()

    annual_rows: list[dict] = []
    monthly_rows: list[dict] = []

    for calendar_year in sorted(prices_by_year):
        solar_year_idx = min(calendar_year - START_YEAR + 1, solar.n_years)
        gen = solar.generation_years_lim_mw[solar_year_idx - 1].astype(np.float64)
        prices = prices_by_year[calendar_year]

        gen_year_mwh = float(gen.sum())
        price_mean_year = float(prices.mean())
        price_w_year = float((prices * gen).sum() / gen_year_mwh)

        # flat anual: C em todas as horas do ano vs C na curva de geracao anual
        contract_energy_mwh = contract_mw * HOURS_PER_YEAR
        cost_flat_total = contract_energy_mwh * (price_mean_year - price_w_year)
        # sazonalizado: C_m proporcional a geracao do mes, flat dentro do mes
        # (somatorio mensal captura apenas a componente intradiaria/horaria)
        cost_sazo_total = 0.0
        for m, sl in enumerate(slices, start=1):
            p_m = prices[sl]
            g_m = gen[sl]
            h_m = float(p_m.shape[0])
            gen_m_mwh = float(g_m.sum())
            price_mean_m = float(p_m.mean())
            price_w_m = float((p_m * g_m).sum() / gen_m_mwh) if gen_m_mwh > 0 else np.nan

            # custo da entrega flat anual no mes: C flat vs C na curva intra-mes
            cost_flat_m = contract_mw * h_m * (price_mean_m - price_w_m)
            # entrega sazonalizada na geracao: C_m flat no mes
            c_m = contract_mw * (gen_m_mwh / gen_year_mwh) * (HOURS_PER_YEAR / h_m)
            cost_sazo_m = c_m * h_m * (price_mean_m - price_w_m)
            cost_sazo_total += cost_sazo_m

            monthly_rows.append(
                {
                    "calendar_year": calendar_year,
                    "month": m,
                    "hours": int(h_m),
                    "contract_flat_mw": contract_mw,
                    "contract_sazo_mw": c_m,
                    "gen_mwmed": gen_m_mwh / h_m,
                    "price_mean_brl_mwh": price_mean_m,
                    "price_gen_weighted_brl_mwh": price_w_m,
                    "spread_brl_mwh": price_mean_m - price_w_m,
                    "mod_cost_flat_brl": cost_flat_m,
                    "mod_cost_sazo_brl": cost_sazo_m,
                }
            )

        surplus_mwmed = gen_year_mwh / HOURS_PER_YEAR - contract_mw
        surplus_revenue = (gen_year_mwh - contract_energy_mwh) * price_w_year

        annual_rows.append(
            {
                "calendar_year": calendar_year,
                "solar_year_idx": solar_year_idx,
                "gen_mwmed": gen_year_mwh / HOURS_PER_YEAR,
                "contract_mw": contract_mw,
                "contracting_level_pct": contract_mw / (gen_year_mwh / HOURS_PER_YEAR) * 100.0,
                "price_mean_brl_mwh": price_mean_year,
                "price_gen_weighted_brl_mwh": price_w_year,
                "capture_factor_pct": price_w_year / price_mean_year * 100.0,
                "spread_brl_mwh": price_mean_year - price_w_year,
                "mod_cost_flat_brl": cost_flat_total,
                "mod_cost_flat_brl_mwh_contract": cost_flat_total / contract_energy_mwh,
                "mod_cost_sazo_brl": cost_sazo_total,
                "mod_cost_sazo_brl_mwh_contract": cost_sazo_total / contract_energy_mwh,
                "seasonal_component_brl": cost_flat_total - cost_sazo_total,
                "surplus_mwmed": surplus_mwmed,
                "surplus_revenue_brl": surplus_revenue,
            }
        )

    annual = pd.DataFrame(annual_rows)
    monthly = pd.DataFrame(monthly_rows)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    tag = args.price_csv.stem.replace("curvas_preco_", "")
    annual_path = OUTPUT_DIR / f"modulacao_contrato_{contract_mw:.1f}mw_anual_{tag}.csv"
    monthly_path = OUTPUT_DIR / f"modulacao_contrato_{contract_mw:.1f}mw_mensal_{tag}.csv"
    annual.to_csv(annual_path, index=False, float_format="%.6f")
    monthly.to_csv(monthly_path, index=False, float_format="%.6f")

    def _window(df: pd.DataFrame, n_years: int | None = None) -> pd.Series:
        sel = df if n_years is None else df.head(n_years)
        energy = contract_mw * HOURS_PER_YEAR * len(sel)
        return pd.Series(
            {
                "anos": f"{sel['calendar_year'].iloc[0]}-{sel['calendar_year'].iloc[-1]}",
                "custo flat (MR$/ano)": sel["mod_cost_flat_brl"].mean() / 1e6,
                "custo flat (R$/MWh contratado)": sel["mod_cost_flat_brl"].sum() / energy,
                "custo sazo (R$/MWh contratado)": sel["mod_cost_sazo_brl"].sum() / energy,
                "spread medio (R$/MWh)": sel["spread_brl_mwh"].mean(),
                "fator captura medio (%)": sel["capture_factor_pct"].mean(),
            }
        )

    print(f"\nContrato flat: {contract_mw:.1f} MWmed | geracao media: {annual['gen_mwmed'].mean():.1f} MWmed "
          f"| nivel de contratacao medio: {annual['contracting_level_pct'].mean():.1f}%")
    print(f"Premissa de preco: {args.price_csv}")
    summary = pd.DataFrame(
        {
            "20 anos": _window(annual, 20),
            "30 anos": _window(annual),
        }
    )
    print()
    print(summary.to_string(float_format=lambda v: f"{v:,.2f}"))
    print(f"\nSaidas:\n  {annual_path}\n  {monthly_path}")


if __name__ == "__main__":
    main()
