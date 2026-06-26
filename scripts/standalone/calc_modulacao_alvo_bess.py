"""Modulacao alvo (35/50/75 R$/MWh) x curtailment (10/20%) x BESS (15/20/25%).

Pipeline em duas etapas, baseado no cenario central Brazil Q2 26 e no perfil
horario de curtailment conj. seriemas I (ano medio):

1) Curvas de modulacao alvo: para cada alvo M em ``MOD_TARGETS_BRL_MWH`` a
   curva horaria de PLD de cada ano (2030-2059) e escalada por um fator
   uniforme k, com cada hora limitada ao intervalo regulatorio
   [PLD_FLOOR, PLD_CEILING], ate o custo de modulacao sem BESS atingir M:

       custo_mod = PLD_medio - PLD_ponderado_pela_geracao_solar  (= M, por ano)

   O fator e resolvido por bissecao (o clamp quebra a linearidade; o custo e
   monotono em k). Mesma metodologia de ``_scale_pld_to_target_modulation``
   do pitch agent (.agents/bess_pitch_agent.py).

2) Cenarios curtailment x BESS: para cada familia de curvas (M), cada nivel
   de curtailment anual (perfil seriemas escalado ano a ano para fechar o
   alvo exato) e cada BESS (blocos de 4h dimensionados por energia diaria),
   o despacho price-aware (charge_mode=3) roda os 30 anos. Reporta:

   - modulacao posterior com BESS: spread volume-neutro
     PLD_medio - PLD_ponderado por (injecao pos-BESS + corte ONS perdido);
   - curtailment posterior com BESS: corte ONS perdido apos recuperacao
     pelo BESS, em GWh/ano e % da geracao anual injetavel.

Sem BESS a modulacao e invariante ao curtailment por construcao (perfil
volume-neutro = geracao cheia) e fecha exatamente no alvo M de cada curva.

Saidas em output/modulacao_alvo/:
  - curvas_preco_central_mod{M}_2030_2059.csv  (formato price_YYYY_brl_mwh,
    reutilizavel pelos demais scripts do projeto)
  - fatores_escala_pld.csv
  - modulacao_alvo_bess_anual.csv
  - resumo_modulacao_alvo_bess.html
"""

from __future__ import annotations

import argparse
import datetime as _dt
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.config import (
    BESS_BLOCK_SPECS,
    HOURS_PER_YEAR,
    PLD_CEILING_BRL_PER_MWH,
    PLD_FLOOR_BRL_PER_MWH,
    SimulationParams,
    size_bess_blocks,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.rte import load_rte_table
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

# ---------------------------------------------------------------------------
# PREMISSAS — edite aqui para reaproveitar a analise
# ---------------------------------------------------------------------------

PRICE_RAW_CSV = Path("dados/Brazil Q2 26 (Central)-bra-central-brl2025-system-1h.csv")
CURTAILMENT_CSV = Path("dados/curtailment_8760_conj_seriemas_i_ano_medio_total_pct.csv")
SOLAR_CSV = Path("solar/solar_baguacu_m2_600mw_id8.csv")
RTE_PATH = "dados/11 - Envision.xlsx"
OUTPUT_DIR = Path("output/modulacao_alvo")

MWAC = 600.0
START_YEAR = 2030
END_YEAR = 2059

# Alvos de custo de modulacao sem BESS (R$/MWh), fechados ano a ano.
MOD_TARGETS_BRL_MWH = (35.0, 50.0, 75.0)
# Alvos de curtailment anual (% da geracao injetavel), fechados ano a ano.
CURTAILMENT_TARGETS_PCT = (10.0, 20.0)
# BESS como fracao da energia media diaria (coverage sobre GF x 24h).
BESS_COVERAGE_PCTS = (0.15, 0.20, 0.25)
BESS_DURATION_H = 4
BESS_PEAK_HOURS = frozenset({17, 18, 19, 20})

PLD_FLOOR = PLD_FLOOR_BRL_PER_MWH      # 57,31 R$/MWh
PLD_CEILING = PLD_CEILING_BRL_PER_MWH  # 1.611,04 R$/MWh


# ---------------------------------------------------------------------------
# Leitura de dados
# ---------------------------------------------------------------------------


def _read_price_input(path: Path) -> pd.DataFrame:
    """Le o CSV horario bruto Aurora (Brazil Q2 26) em hora local."""
    if not path.exists():
        raise FileNotFoundError(f"Price CSV not found: {path}")
    first_line = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    sep = ";" if ";" in first_line else ","
    raw = pd.read_csv(path, sep=sep, skiprows=2, header=None, engine="python")
    if raw.shape[1] < 5:
        raise ValueError(f"Unexpected price CSV layout in {path}: {raw.shape[1]} columns.")
    local_text = raw.iloc[:, 2].astype(str) + " " + raw.iloc[:, 3].astype(str)
    local_datetime = pd.to_datetime(local_text, format="%d/%m/%Y %H:%M:%S", errors="raise")
    df = pd.DataFrame(
        {
            "local_datetime": local_datetime,
            "price_brl_mwh": pd.to_numeric(raw.iloc[:, 4], errors="coerce"),
        }
    )
    if df["price_brl_mwh"].isna().any():
        first_bad = int(np.flatnonzero(df["price_brl_mwh"].isna().to_numpy())[0])
        raise ValueError(f"Non-numeric price on row {first_bad + 3} of {path}")
    return df.sort_values("local_datetime")


def _price_curves_by_year(path: Path, start_year: int, end_year: int) -> dict[int, np.ndarray]:
    """Curvas de 8.760h por ano calendario local, sem 29/02."""
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


def _load_curtailment_rate(path: Path) -> np.ndarray:
    df = pd.read_csv(path, sep=";")
    rate = pd.to_numeric(df["curtailment_rate"], errors="coerce").fillna(0.0).to_numpy()
    if rate.shape[0] != HOURS_PER_YEAR:
        raise ValueError(f"{path}: {rate.shape[0]} linhas, esperado {HOURS_PER_YEAR}.")
    return np.maximum(rate.astype(np.float64), 0.0)


# ---------------------------------------------------------------------------
# Etapa 1 — escala do PLD para o custo de modulacao alvo
# ---------------------------------------------------------------------------


def _mod_cost_brl_mwh(profile_mwh: np.ndarray, prices: np.ndarray) -> float:
    """Custo de modulacao = PLD medio - PLD ponderado pelo perfil (R$/MWh)."""
    total = float(profile_mwh.sum())
    return float(prices.mean() - (prices * profile_mwh).sum() / total)


def scale_pld_to_target_cost(
    prices: np.ndarray,
    weights_mwh: np.ndarray,
    target_cost_brl_mwh: float,
    floor: float = PLD_FLOOR,
    ceiling: float = PLD_CEILING,
) -> tuple[np.ndarray, float]:
    """Escala o PLD por fator uniforme k com clamp [piso, teto] ate o custo de
    modulacao (ponderado por ``weights_mwh``) atingir o alvo. Bissecao em k.
    """
    p = np.asarray(prices, dtype=np.float64)

    def cost(k: float) -> float:
        return _mod_cost_brl_mwh(weights_mwh, np.clip(p * k, floor, ceiling))

    k_lo, k_hi = 0.0, 1.0
    iters = 0
    while cost(k_hi) < target_cost_brl_mwh and k_hi < 1e6 and iters < 200:
        k_hi *= 2.0
        iters += 1
    if cost(k_hi) < target_cost_brl_mwh:
        raise ValueError(
            f"Alvo de modulacao {target_cost_brl_mwh} R$/MWh inalcancavel dentro do teto do PLD."
        )
    for _ in range(80):
        k_mid = 0.5 * (k_lo + k_hi)
        if cost(k_mid) < target_cost_brl_mwh:
            k_lo = k_mid
        else:
            k_hi = k_mid
    k = 0.5 * (k_lo + k_hi)
    return np.clip(p * k, floor, ceiling), k


def build_target_curves(
    base_curves: dict[int, np.ndarray],
    solar,
) -> tuple[dict[float, dict[int, np.ndarray]], pd.DataFrame]:
    """Para cada alvo, escala a curva de cada ano; retorna curvas + fatores."""
    curves_by_target: dict[float, dict[int, np.ndarray]] = {}
    factor_rows: list[dict] = []
    for target in MOD_TARGETS_BRL_MWH:
        per_year: dict[int, np.ndarray] = {}
        for year in sorted(base_curves):
            solar_year_idx = min(year - START_YEAR + 1, solar.n_years)
            gen_lim, _ = solar.get_year_arrays(solar_year_idx)
            gen_lim = gen_lim.astype(np.float64)
            base = base_curves[year]
            scaled, k = scale_pld_to_target_cost(base, gen_lim, target)
            per_year[year] = scaled
            factor_rows.append(
                {
                    "mod_target_brl_mwh": target,
                    "calendar_year": year,
                    "k_factor": k,
                    "pld_mean_base": float(base.mean()),
                    "pld_mean_scaled": float(scaled.mean()),
                    "pld_min_scaled": float(scaled.min()),
                    "pld_max_scaled": float(scaled.max()),
                    "hours_at_floor": int((scaled <= PLD_FLOOR + 1e-9).sum()),
                    "hours_at_ceiling": int((scaled >= PLD_CEILING - 1e-9).sum()),
                    "mod_cost_base_brl_mwh": _mod_cost_brl_mwh(gen_lim, base),
                    "mod_cost_scaled_brl_mwh": _mod_cost_brl_mwh(gen_lim, scaled),
                }
            )
        curves_by_target[target] = per_year
    return curves_by_target, pd.DataFrame(factor_rows)


# ---------------------------------------------------------------------------
# Etapa 2 — cenarios curtailment x BESS
# ---------------------------------------------------------------------------


def _modulation_metrics(
    injection_mwh: np.ndarray,
    curt_lost_mwh: np.ndarray,
    prices: np.ndarray,
    gen_year_mwh: float,
) -> dict[str, float]:
    """Spread volume-neutro (modulacao) + curtailment pos-BESS de um ano."""
    profile_mwh = injection_mwh + curt_lost_mwh
    price_mean = float(prices.mean())
    price_w = float((profile_mwh * prices).sum() / profile_mwh.sum())
    curt_lost_total = float(curt_lost_mwh.sum())
    curt_lost_value = (
        float((curt_lost_mwh * prices).sum() / curt_lost_total) if curt_lost_total > 0 else np.nan
    )
    return {
        "injection_mwmed": float(injection_mwh.sum()) / HOURS_PER_YEAR,
        "price_mean_brl_mwh": price_mean,
        "price_profile_weighted_brl_mwh": price_w,
        "capture_factor_pct": price_w / price_mean * 100.0,
        "mod_cost_brl_mwh": price_mean - price_w,
        "curt_lost_gwh": curt_lost_total / 1e3,
        "curt_lost_pct_gen": curt_lost_total / gen_year_mwh * 100.0,
        "curt_lost_value_brl_mwh": curt_lost_value,
    }


def run_scenarios(
    curves_by_target: dict[float, dict[int, np.ndarray]],
    base_rate: np.ndarray,
    solar,
    rte_table: dict[int, float],
    params: SimulationParams,
    bess_specs: dict[float, object],
) -> pd.DataFrame:
    rows: list[dict] = []
    rte_last_year = max(rte_table)
    for target, curves in curves_by_target.items():
        for curt_target in CURTAILMENT_TARGETS_PCT:
            for year in sorted(curves):
                solar_year_idx = min(year - START_YEAR + 1, solar.n_years)
                gen_lim, _ = solar.get_year_arrays(solar_year_idx)
                gen_lim = gen_lim.astype(np.float64)
                gen_year_mwh = float(gen_lim.sum())
                prices = curves[year]
                rte = rte_table.get(year, rte_table[rte_last_year])

                # Curtailment escalado para fechar o alvo anual exato deste ano
                base_pct = float((base_rate * gen_lim).sum() / gen_year_mwh * 100.0)
                curt_series = base_rate * (curt_target / base_pct) * gen_lim

                # Baseline sem BESS: todo o corte e perdido
                inj_no_bess = np.maximum(0.0, gen_lim - curt_series)
                rows.append(
                    {
                        "mod_target_brl_mwh": target,
                        "curtailment_target_pct": curt_target,
                        "bess_coverage_pct": 0.0,
                        "bess_label": "sem BESS",
                        "calendar_year": year,
                        "solar_year_idx": solar_year_idx,
                        "rte": np.nan,
                        "bess_power_mw": 0.0,
                        "bess_energy_mwh": 0.0,
                        "curt_recovered_gwh": 0.0,
                        **_modulation_metrics(inj_no_bess, curt_series, prices, gen_year_mwh),
                    }
                )

                for pct in BESS_COVERAGE_PCTS:
                    sizing = bess_specs[pct]
                    scenario = ScenarioDefinition(
                        label=f"BESS{pct:.0%}",
                        peak_hours=BESS_PEAK_HOURS,
                        duration_h=BESS_DURATION_H,
                        bess_power_mw=sizing.bess_power_mw,
                        bess_energy_mwh=sizing.bess_energy_mwh,
                        capex_brl=0.0,
                        rte=rte,
                        charge_mode=3,
                    )
                    price_profile = PriceProfile(
                        prices_brl_per_mwh=prices,
                        source=f"central_mod{target:.0f}_{year}",
                        bq_submarket="-",
                        bq_year=year,
                    )
                    dispatch = simulate_scenario(
                        solar,
                        price_profile,
                        scenario,
                        params,
                        curtailment_series=curt_series,
                        solar_year_idx=solar_year_idx,
                    )
                    # Apenas o corte ONS perdido volta ao perfil de modulacao;
                    # clipping perdido nao e energia da premissa de volume.
                    avail = dispatch.curtailment_total_available_mwh
                    with np.errstate(invalid="ignore", divide="ignore"):
                        ons_share = np.where(
                            avail > 1e-12, dispatch.ons_curtailment_mwh / avail, 0.0
                        )
                    curt_lost_ons = dispatch.curtailment_lost_mwh * ons_share
                    rows.append(
                        {
                            "mod_target_brl_mwh": target,
                            "curtailment_target_pct": curt_target,
                            "bess_coverage_pct": pct * 100.0,
                            "bess_label": f"BESS {pct:.0%}",
                            "calendar_year": year,
                            "solar_year_idx": solar_year_idx,
                            "rte": rte,
                            "bess_power_mw": sizing.bess_power_mw,
                            "bess_energy_mwh": sizing.bess_energy_mwh,
                            "curt_recovered_gwh": float(
                                np.sum(dispatch.curtailment_recovered_mwh)
                            )
                            / 1e3,
                            **_modulation_metrics(
                                dispatch.grid_injection_mwh, curt_lost_ons, prices, gen_year_mwh
                            ),
                        }
                    )
            print(
                f"  mod alvo {target:.0f} R$/MWh | curtailment {curt_target:.0f}%: "
                f"{len(curves)} anos simulados (sem BESS + {len(BESS_COVERAGE_PCTS)} BESS)."
            )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Saidas
# ---------------------------------------------------------------------------


def _write_price_curves_csv(curves: dict[int, np.ndarray], path: Path) -> None:
    data: dict[str, np.ndarray] = {"hour_of_year": np.arange(1, HOURS_PER_YEAR + 1, dtype=int)}
    for year, values in sorted(curves.items()):
        data[f"price_{year}_brl_mwh"] = values
    pd.DataFrame(data).to_csv(path, index=False, float_format="%.6f")


def _fmt(v: float, d: int = 2) -> str:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "&mdash;"
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _agg(df: pd.DataFrame, target: float, curt: float, bess: float) -> pd.Series:
    sel = df[
        (df.mod_target_brl_mwh == target)
        & (df.curtailment_target_pct == curt)
        & (df.bess_coverage_pct == bess)
    ]
    return pd.Series(
        {
            "mod_cost": sel.mod_cost_brl_mwh.mean(),
            "curt_lost_pct": sel.curt_lost_pct_gen.mean(),
            "curt_lost_gwh": sel.curt_lost_gwh.mean(),
            "curt_rec_gwh": sel.curt_recovered_gwh.mean(),
            "captura": sel.capture_factor_pct.mean(),
            "inj_mwmed": sel.injection_mwmed.mean(),
            "curt_lost_value": sel.curt_lost_value_brl_mwh.mean(),
            "mod_first": sel.sort_values("calendar_year").mod_cost_brl_mwh.iloc[0],
            "mod_last": sel.sort_values("calendar_year").mod_cost_brl_mwh.iloc[-1],
        }
    )


def write_html(
    df: pd.DataFrame,
    factors: pd.DataFrame,
    path: Path,
    bess_specs: dict,
    gf: float,
    n_years_used: int,
) -> None:
    bess_cols = [0.0] + [p * 100.0 for p in BESS_COVERAGE_PCTS]
    block = BESS_BLOCK_SPECS[BESS_DURATION_H]

    def col_label(b: float) -> str:
        return "Sem BESS" if b == 0.0 else f"BESS {b:.0f}%"

    # --- etapa 1: resumo da escala por alvo
    factor_rows_html = []
    for target in MOD_TARGETS_BRL_MWH:
        sel = factors[factors.mod_target_brl_mwh == target]
        factor_rows_html.append(
            "<tr>"
            f"<td>R$ {_fmt(target, 0)}/MWh</td>"
            f"<td>{_fmt(sel.k_factor.mean(), 3)} ({_fmt(sel.k_factor.min(), 3)}&ndash;{_fmt(sel.k_factor.max(), 3)})</td>"
            f"<td>{_fmt(sel.pld_mean_base.mean(), 0)} &rarr; {_fmt(sel.pld_mean_scaled.mean(), 0)}</td>"
            f"<td>{_fmt(sel.pld_min_scaled.min(), 2)}</td>"
            f"<td>{_fmt(sel.hours_at_floor.mean(), 0)}</td>"
            f"<td>{_fmt(sel.mod_cost_scaled_brl_mwh.mean(), 2)}</td>"
            "</tr>"
        )

    head_cols = "".join(f"<th>{col_label(b)}</th>" for b in bess_cols)

    # --- matriz modulacao pos-BESS
    mod_rows_html = []
    for target in MOD_TARGETS_BRL_MWH:
        for curt in CURTAILMENT_TARGETS_PCT:
            base = _agg(df, target, curt, 0.0)
            cells = []
            for b in bess_cols:
                a = _agg(df, target, curt, b)
                delta = (
                    ""
                    if b == 0.0
                    else f'<div class="delta">&minus;{_fmt(base.mod_cost - a.mod_cost)} '
                    f"({(base.mod_cost - a.mod_cost) / base.mod_cost * 100:.0f}%)</div>"
                )
                cells.append(f'<td><div class="main">{_fmt(a.mod_cost)}</div>{delta}</td>')
            mod_rows_html.append(
                f"<tr><th>Mod. {target:.0f} &middot; Curt. {curt:.0f}%</th>{''.join(cells)}</tr>"
            )

    # --- matriz curtailment pos-BESS
    curt_rows_html = []
    for target in MOD_TARGETS_BRL_MWH:
        for curt in CURTAILMENT_TARGETS_PCT:
            cells = []
            for b in bess_cols:
                a = _agg(df, target, curt, b)
                cells.append(
                    f'<td><div class="main">{_fmt(a.curt_lost_pct, 1)}%</div>'
                    f'<div class="delta">{_fmt(a.curt_lost_gwh, 1)} GWh/ano</div></td>'
                )
            curt_rows_html.append(
                f"<tr><th>Mod. {target:.0f} &middot; Curt. {curt:.0f}%</th>{''.join(cells)}</tr>"
            )

    # --- detalhe por cenario
    detail_rows_html = []
    for target in MOD_TARGETS_BRL_MWH:
        for curt in CURTAILMENT_TARGETS_PCT:
            for b in bess_cols:
                a = _agg(df, target, curt, b)
                detail_rows_html.append(
                    "<tr>"
                    f"<td>{target:.0f}</td><td>{curt:.0f}%</td><td>{col_label(b)}</td>"
                    f"<td>{_fmt(a.mod_cost)}</td>"
                    f"<td>{_fmt(a.captura, 1)}%</td>"
                    f"<td>{_fmt(a.inj_mwmed, 1)}</td>"
                    f"<td>{_fmt(a.curt_rec_gwh, 1)}</td>"
                    f"<td>{_fmt(a.curt_lost_gwh, 1)}</td>"
                    f"<td>{_fmt(a.curt_lost_pct, 1)}%</td>"
                    f"<td>{_fmt(a.curt_lost_value)}</td>"
                    f"<td>{_fmt(a.mod_first, 1)} &rarr; {_fmt(a.mod_last, 1)}</td>"
                    "</tr>"
                )

    # --- ano a ano (modulacao pos-BESS), em <details>
    years = sorted(df.calendar_year.unique())
    year_head = "".join(f"<th>{y}</th>" for y in years)
    annual_rows_html = []
    for target in MOD_TARGETS_BRL_MWH:
        for curt in CURTAILMENT_TARGETS_PCT:
            for b in bess_cols:
                sel = df[
                    (df.mod_target_brl_mwh == target)
                    & (df.curtailment_target_pct == curt)
                    & (df.bess_coverage_pct == b)
                ].sort_values("calendar_year")
                cells = "".join(f"<td>{_fmt(v, 1)}</td>" for v in sel.mod_cost_brl_mwh)
                annual_rows_html.append(
                    f"<tr><td>{target:.0f}</td><td>{curt:.0f}%</td>"
                    f"<td>{col_label(b)}</td>{cells}</tr>"
                )

    bess_spec_rows = "".join(
        f"<tr><td>BESS {pct:.0%}</td>"
        f"<td>{_fmt(pct * gf * 24.0, 0)}</td>"
        f"<td>{s.n_blocks}</td>"
        f"<td>{_fmt(s.bess_power_mw, 1)}</td>"
        f"<td>{_fmt(s.bess_energy_mwh, 1)}</td></tr>"
        for pct, s in bess_specs.items()
    )

    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Modulação alvo × Curtailment × BESS — cenário central Brazil Q2 26</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 2rem auto; max-width: 1280px;
         color: #1f2937; background: #f8fafc; padding: 0 1rem; }}
  h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem; }}
  table {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1);
           margin-top: .75rem; }}
  th, td {{ border: 1px solid #e5e7eb; padding: .5rem .9rem; text-align: right;
            font-size: .9rem; white-space: nowrap; }}
  th {{ background: #0f766e; color: #fff; font-weight: 600; }}
  tr th:first-child {{ background: #115e59; }}
  .main {{ font-size: 1.05rem; font-weight: 700; }}
  .delta {{ font-size: .78rem; color: #0f766e; }}
  .premissas {{ background: #fff; border: 1px solid #e5e7eb; padding: 1rem 1.25rem;
                border-radius: 6px; font-size: .9rem; }}
  .premissas li {{ margin: .2rem 0; }}
  .note {{ color: #6b7280; font-size: .8rem; margin-top: .5rem; }}
  .scroll {{ overflow-x: auto; }}
  details {{ margin-top: 1rem; }}
  summary {{ cursor: pointer; font-weight: 600; }}
</style>
</head>
<body>
<h1>Modulação alvo × Curtailment × BESS — cenário central Brazil Q2 26 ({START_YEAR}&ndash;{END_YEAR})</h1>

<div class="premissas">
<strong>Premissas</strong>
<ul>
  <li>Preço base: curva horária <code>{escape(str(PRICE_RAW_CSV.name))}</code> (hora local, sem 29/02), anos {START_YEAR}&ndash;{END_YEAR}.</li>
  <li>Curvas de modulação alvo: PLD de cada ano escalado por fator uniforme k (bissecção), com clamp ao
      intervalo regulatório [R$ {_fmt(PLD_FLOOR)} ; R$ {_fmt(PLD_CEILING)}]/MWh, até o custo de modulação sem BESS
      (PLD médio &minus; PLD ponderado pela geração solar) fechar exatamente em R$ 35, 50 e 75/MWh em cada ano.</li>
  <li>Usina: Baguaçu id8, {MWAC:.0f} MWac — GF {_fmt(gf, 1)} MWmed ({n_years_used} anos com degradação, ano 1 = {START_YEAR}).</li>
  <li>Curtailment: perfil horário <code>{escape(str(CURTAILMENT_CSV.name))}</code> escalado ano a ano para fechar
      {' e '.join(f'{c:.0f}%' for c in CURTAILMENT_TARGETS_PCT)} da geração anual injetável; o BESS pode recuperar
      curtailment carregando nessas horas.</li>
  <li>BESS: blocos padrão {BESS_DURATION_H}h ({block.block_power_mw} MW / {block.block_energy_mwh} MWh), dimensionados por energia
      ({' / '.join(f'{p:.0%}' for p in BESS_COVERAGE_PCTS)} × GF × 24h), despacho day-ahead com arbitragem de preço
      (charge_mode 3, previsão perfeita), RTE Envision por ano de operação (comissionamento {START_YEAR}).</li>
  <li>Modulação pós-BESS = PLD médio &minus; PLD ponderado pelo perfil volume-neutro (injeção pós-BESS + corte ONS
      perdido). A perda de volume do corte é linha separada, valorada ao PLD das horas cortadas
      (<code>curt_lost_value_brl_mwh</code> no CSV).</li>
  <li>Curtailment pós-BESS = corte ONS perdido após recuperação pelo BESS, em % da geração anual injetável.</li>
</ul>
</div>

<h2>Etapa 1 — Curvas de modulação alvo (escala do PLD, média {START_YEAR}&ndash;{END_YEAR})</h2>
<table>
  <tr><th>Alvo</th><th>Fator k médio (mín&ndash;máx)</th><th>PLD médio base &rarr; escalado (R$/MWh)</th>
      <th>PLD mínimo (R$/MWh)</th><th>Horas/ano no piso</th><th>Modulação s/ BESS obtida (R$/MWh)</th></tr>
  {''.join(factor_rows_html)}
</table>
<p class="note">O piso de R$ {_fmt(PLD_FLOOR)}/MWh limita a queda dos preços nas horas solares; o fator k é
resolvido por ano para fechar o alvo exato. Curvas completas em <code>curvas_preco_central_mod{{35,50,75}}_{START_YEAR}_{END_YEAR}.csv</code>.</p>

<h2>Modulação posterior com BESS — R$/MWh (média {START_YEAR}&ndash;{END_YEAR})</h2>
<table>
  <tr><th>Cenário</th>{head_cols}</tr>
  {''.join(mod_rows_html)}
</table>
<p class="note">Entre parênteses: redução vs. sem BESS no mesmo cenário. Sem BESS a modulação fecha no alvo por construção
(perfil volume-neutro = geração cheia, invariante ao curtailment).</p>

<h2>Curtailment posterior com BESS — % da geração anual (média {START_YEAR}&ndash;{END_YEAR})</h2>
<table>
  <tr><th>Cenário</th>{head_cols}</tr>
  {''.join(curt_rows_html)}
</table>
<p class="note">Valor principal: corte ONS perdido após recuperação pelo BESS (% da geração injetável); abaixo, o volume em GWh/ano.</p>

<h2>Especificação dos BESS (blocos padrão de {BESS_DURATION_H}h)</h2>
<table>
  <tr><th>Cenário</th><th>Alvo (MWh)</th><th>Blocos</th><th>Potência (MW)</th><th>Energia (MWh)</th></tr>
  {bess_spec_rows}
</table>

<h2>Detalhe por cenário (médias {START_YEAR}&ndash;{END_YEAR})</h2>
<div class="scroll">
<table>
  <tr><th>Mod. alvo</th><th>Curt.</th><th>BESS</th><th>Modulação (R$/MWh)</th><th>Fator captura</th>
      <th>Injeção (MWmed)</th><th>Curt. recuperado (GWh/ano)</th><th>Curt. perdido (GWh/ano)</th>
      <th>Curt. perdido (% ger.)</th><th>PLD do corte perdido (R$/MWh)</th><th>Modulação {START_YEAR} &rarr; {END_YEAR}</th></tr>
  {''.join(detail_rows_html)}
</table>
</div>

<details>
<summary>Modulação pós-BESS ano a ano (R$/MWh)</summary>
<div class="scroll">
<table>
  <tr><th>Mod.</th><th>Curt.</th><th>BESS</th>{year_head}</tr>
  {''.join(annual_rows_html)}
</table>
</div>
</details>

<p class="note">Gerado em {generated} por scripts/standalone/calc_modulacao_alvo_bess.py.
Despacho com previsão perfeita de PLD (limite superior do ganho de arbitragem).
Resultados anuais completos em <code>modulacao_alvo_bess_anual.csv</code>; fatores de escala em
<code>fatores_escala_pld.csv</code>.</p>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Roda apenas 2 anos por cenario (teste rapido).",
    )
    args = parser.parse_args()

    solar = load_solar_csv(str(SOLAR_CSV), MWAC)
    if solar.generation_years_lim_mw is None:
        raise ValueError("CSV solar precisa ser multi-ano.")
    gf = solar.garantia_fisica_mw
    params = SimulationParams(csv_path=str(SOLAR_CSV), mwac=MWAC)
    rte_table = load_rte_table(RTE_PATH, commissioning_year=START_YEAR)
    base_rate = _load_curtailment_rate(CURTAILMENT_CSV)

    end_year = START_YEAR + 1 if args.quick else END_YEAR
    print(f"Lendo curva de preco central {START_YEAR}-{end_year}...")
    base_curves = _price_curves_by_year(PRICE_RAW_CSV, START_YEAR, end_year)

    # BESS sizing
    bess_specs = {}
    block = BESS_BLOCK_SPECS[BESS_DURATION_H]
    for pct in BESS_COVERAGE_PCTS:
        sizing = size_bess_blocks(gf, BESS_DURATION_H, coverage_target_pct=pct)
        bess_specs[pct] = sizing
        print(
            f"BESS {pct:.0%}: alvo {pct * gf * 24.0:,.0f} MWh -> {sizing.n_blocks} blocos "
            f"({block.block_power_mw} MW / {block.block_energy_mwh} MWh) = "
            f"{sizing.bess_power_mw:,.1f} MW / {sizing.bess_energy_mwh:,.1f} MWh"
        )

    # Etapa 1 — curvas de modulacao alvo
    print("Etapa 1: escalando PLD para os alvos de modulacao...")
    curves_by_target, factors = build_target_curves(base_curves, solar)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    factors_path = OUTPUT_DIR / "fatores_escala_pld.csv"
    factors.to_csv(factors_path, index=False, float_format="%.6f")
    for target, curves in curves_by_target.items():
        out = OUTPUT_DIR / f"curvas_preco_central_mod{target:.0f}_{START_YEAR}_{end_year}.csv"
        _write_price_curves_csv(curves, out)
        sel = factors[factors.mod_target_brl_mwh == target]
        print(
            f"  alvo {target:.0f} R$/MWh: k medio {sel.k_factor.mean():.3f} "
            f"({sel.k_factor.min():.3f}-{sel.k_factor.max():.3f}), "
            f"PLD medio {sel.pld_mean_base.mean():.0f} -> {sel.pld_mean_scaled.mean():.0f} R$/MWh, "
            f"horas/ano no piso {sel.hours_at_floor.mean():.0f} -> {out.name}"
        )

    # Etapa 2 — cenarios curtailment x BESS
    print("Etapa 2: simulando cenarios curtailment x BESS...")
    df = run_scenarios(curves_by_target, base_rate, solar, rte_table, params, bess_specs)
    csv_path = OUTPUT_DIR / "modulacao_alvo_bess_anual.csv"
    df.to_csv(csv_path, index=False, float_format="%.6f")

    html_path = OUTPUT_DIR / "resumo_modulacao_alvo_bess.html"
    write_html(df, factors, html_path, bess_specs, gf, n_years_used=len(base_curves))
    print(f"\nSaidas:\n  {factors_path}\n  {csv_path}\n  {html_path}")


if __name__ == "__main__":
    main()
