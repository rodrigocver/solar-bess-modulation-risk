"""Modulacao do contrato flat (150,3 MW) com BESS, em cenarios de curtailment.

Grade de cenarios:
  - BESS: 15%, 20% e 25% da energia media diaria (coverage_target_pct sobre a
    garantia fisica), blocos padrao de 4h (2,52 MW / 10,1 MWh), mais o baseline
    sem BESS;
  - Curtailment: 0%, 10% e 20% da geracao anual, escalando linearmente o perfil
    horario ``dados/curtailment_8760_conj_seriemas_i_ano_medio_total_pct.csv``
    (ano a ano, para fechar o alvo exato em cada ano solar).

Para cada combinacao, o despacho price-aware existente (charge_mode=3) roda os
30 anos de preco (curva central Brazil Q2 26, 2030-2059) com o ano solar
correspondente (year_idx 1 = 2030) e RTE Envision por ano. A modulacao do
contrato e calculada sobre a injecao pos-BESS:

    custo_mod = C * H * (PLD_medio_flat - PLD_ponderado_perfil)

A modulacao e volume-neutra: o perfil usado na ponderacao e a injecao pos-BESS
MAIS o curtailment efetivamente perdido (a perda de volume do corte e descontada
em outra linha do modelo financeiro e nao deve contaminar o spread de forma).
Sem BESS o perfil equivale a geracao cheia, tornando a modulacao invariante ao
nivel de curtailment. O valor unitario do curtailment perdido (PLD ponderado das
horas cortadas) e reportado a parte para uso consistente no modelo financeiro.

Saidas: CSV anual completo + HTML resumo em output/modulacao_contrato/.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.config import (
    HOURS_PER_YEAR,
    BESS_BLOCK_SPECS,
    SimulationParams,
    size_bess_blocks,
)
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.rte import load_rte_table
from solar_bess_risk.simulation import ScenarioDefinition, simulate_scenario

SOLAR_CSV = Path("solar/solar_baguacu_m2_600mw_id8.csv")
PRICE_CSV = Path("dados/curvas_preco/curvas_preco_brazil_q2_26_central_2030_2059.csv")
CURTAILMENT_CSV = Path("dados/curtailment_8760_conj_seriemas_i_ano_medio_total_pct.csv")
RTE_PATH = "dados/11 - Envision.xlsx"
OUTPUT_DIR = Path("output/modulacao_contrato")
MWAC = 600.0
START_YEAR = 2030
CONTRACT_MW = 150.3
BESS_DURATION_H = 4
BESS_PEAK_HOURS = frozenset({17, 18, 19, 20})
BESS_COVERAGE_PCTS = (0.15, 0.20, 0.25)
CURTAILMENT_TARGETS_PCT = (0.0, 10.0, 20.0)


def _price_curves(path: Path) -> dict[int, np.ndarray]:
    df = pd.read_csv(path)
    curves: dict[int, np.ndarray] = {}
    for col in df.columns:
        if col.startswith("price_") and col.endswith("_brl_mwh"):
            year = int(col.split("_")[1])
            values = df[col].to_numpy(dtype=np.float64)
            if values.shape[0] != HOURS_PER_YEAR:
                raise ValueError(f"{path}: coluna {col} tem {values.shape[0]} horas.")
            curves[year] = values
    if not curves:
        raise ValueError(f"{path}: nenhuma coluna price_YYYY_brl_mwh.")
    return curves


def _load_curtailment_rate(path: Path) -> np.ndarray:
    df = pd.read_csv(path, sep=";")
    rate = pd.to_numeric(df["curtailment_rate"], errors="coerce").fillna(0.0).to_numpy()
    if rate.shape[0] != HOURS_PER_YEAR:
        raise ValueError(f"{path}: {rate.shape[0]} linhas, esperado {HOURS_PER_YEAR}.")
    return np.maximum(rate.astype(np.float64), 0.0)


def _contract_modulation(
    injection_mwh: np.ndarray,
    curt_lost_mwh: np.ndarray,
    prices: np.ndarray,
    contract_mw: float,
) -> dict[str, float]:
    # perfil volume-neutro: injecao + curtailment perdido (perda de volume e
    # tratada em outra linha do modelo financeiro)
    profile_mwh = injection_mwh + curt_lost_mwh
    profile_total = float(profile_mwh.sum())
    price_mean = float(prices.mean())
    price_w = float((profile_mwh * prices).sum() / profile_total)
    spread = price_mean - price_w
    contract_energy = contract_mw * HOURS_PER_YEAR
    curt_lost_total = float(curt_lost_mwh.sum())
    curt_lost_value = (
        float((curt_lost_mwh * prices).sum() / curt_lost_total)
        if curt_lost_total > 0
        else np.nan
    )
    return {
        "injection_mwmed": float(injection_mwh.sum()) / HOURS_PER_YEAR,
        "profile_mwmed": profile_total / HOURS_PER_YEAR,
        "price_mean_brl_mwh": price_mean,
        "price_profile_weighted_brl_mwh": price_w,
        "capture_factor_pct": price_w / price_mean * 100.0,
        "spread_brl_mwh": spread,
        "mod_cost_brl": contract_energy * spread,
        "mod_cost_brl_mwh_contract": spread,
        "curt_lost_value_brl_mwh": curt_lost_value,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract-mw", type=float, default=CONTRACT_MW)
    args = parser.parse_args()
    contract_mw = args.contract_mw

    solar = load_solar_csv(str(SOLAR_CSV), MWAC)
    if solar.generation_years_lim_mw is None:
        raise ValueError("CSV solar precisa ser multi-ano.")
    prices_by_year = _price_curves(PRICE_CSV)
    base_rate = _load_curtailment_rate(CURTAILMENT_CSV)
    rte_table = load_rte_table(RTE_PATH, commissioning_year=START_YEAR)
    rte_last_year = max(rte_table)
    params = SimulationParams(csv_path=str(SOLAR_CSV), mwac=MWAC)
    gf = solar.garantia_fisica_mw

    # BESS sizing: blocos inteiros de 4h para cada cobertura alvo
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

    rows: list[dict] = []
    years = sorted(prices_by_year)
    for curt_target in CURTAILMENT_TARGETS_PCT:
        for calendar_year in years:
            solar_year_idx = min(calendar_year - START_YEAR + 1, solar.n_years)
            gen_lim, gen_bess = solar.get_year_arrays(solar_year_idx)
            gen_lim = gen_lim.astype(np.float64)
            prices = prices_by_year[calendar_year]
            rte = rte_table.get(calendar_year, rte_table[rte_last_year])

            # Curtailment escalado para fechar o alvo anual exato deste ano solar
            if curt_target > 0.0:
                base_pct = float((base_rate * gen_lim).sum() / gen_lim.sum() * 100.0)
                curt_series = base_rate * (curt_target / base_pct) * gen_lim
            else:
                curt_series = None

            # Baseline sem BESS: injecao = geracao limitada - curtailment;
            # todo o corte e perdido (perfil de modulacao = geracao cheia)
            curt_mw = (
                curt_series
                if curt_series is not None
                else np.zeros(HOURS_PER_YEAR, dtype=np.float64)
            )
            inj_no_bess = np.maximum(0.0, gen_lim - curt_mw)
            base_metrics = _contract_modulation(
                inj_no_bess, curt_mw, prices, contract_mw
            )
            rows.append(
                {
                    "curtailment_target_pct": curt_target,
                    "bess_coverage_pct": 0.0,
                    "bess_label": "sem BESS",
                    "calendar_year": calendar_year,
                    "solar_year_idx": solar_year_idx,
                    "rte": np.nan,
                    "bess_power_mw": 0.0,
                    "bess_energy_mwh": 0.0,
                    "curtailment_recovered_gwh": 0.0,
                    "curtailment_lost_gwh": float(np.sum(curt_mw)) / 1e3,
                    **base_metrics,
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
                    source=f"brazil_q2_26_central_{calendar_year}",
                    bq_submarket="-",
                    bq_year=calendar_year,
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
                # clipping perdido nao e energia da premissa de volume. O split
                # do perdido e proporcional a disponibilidade horaria (o motor
                # carrega ons+clip como um unico pool a custo zero).
                avail = dispatch.curtailment_total_available_mwh
                with np.errstate(invalid="ignore", divide="ignore"):
                    ons_share = np.where(
                        avail > 1e-12, dispatch.ons_curtailment_mwh / avail, 0.0
                    )
                curt_lost_ons = dispatch.curtailment_lost_mwh * ons_share
                metrics = _contract_modulation(
                    dispatch.grid_injection_mwh, curt_lost_ons, prices, contract_mw
                )
                rows.append(
                    {
                        "curtailment_target_pct": curt_target,
                        "bess_coverage_pct": pct * 100.0,
                        "bess_label": f"BESS {pct:.0%}",
                        "calendar_year": calendar_year,
                        "solar_year_idx": solar_year_idx,
                        "rte": rte,
                        "bess_power_mw": sizing.bess_power_mw,
                        "bess_energy_mwh": sizing.bess_energy_mwh,
                        "curtailment_recovered_gwh": float(
                            np.sum(dispatch.curtailment_recovered_mwh)
                        )
                        / 1e3,
                        "curtailment_lost_gwh": float(np.sum(curt_lost_ons)) / 1e3,
                        **metrics,
                    }
                )
        print(f"Curtailment {curt_target:.0f}%: 30 anos simulados (sem BESS + 3 BESS).")

    df = pd.DataFrame(rows)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"modulacao_contrato_bess_{contract_mw:.1f}mw_anual.csv"
    df.to_csv(csv_path, index=False, float_format="%.6f")

    html_path = OUTPUT_DIR / f"modulacao_contrato_bess_{contract_mw:.1f}mw_resumo.html"
    _write_html(df, html_path, contract_mw, bess_specs, gf)
    print(f"\nSaidas:\n  {csv_path}\n  {html_path}")


def _agg(df: pd.DataFrame, curt: float, bess: float) -> pd.Series:
    sel = df[(df.curtailment_target_pct == curt) & (df.bess_coverage_pct == bess)]
    return pd.Series(
        {
            "custo_brl_mwh": sel.mod_cost_brl_mwh_contract.mean(),
            "custo_mrs_ano": sel.mod_cost_brl.mean() / 1e6,
            "captura_pct": sel.capture_factor_pct.mean(),
            "inj_mwmed": sel.injection_mwmed.mean(),
            "curt_rec_gwh": sel.curtailment_recovered_gwh.mean(),
            "curt_lost_gwh": sel.curtailment_lost_gwh.mean(),
            "curt_lost_value": sel.curt_lost_value_brl_mwh.mean(),
        }
    )


def _write_html(
    df: pd.DataFrame,
    path: Path,
    contract_mw: float,
    bess_specs: dict,
    gf: float,
) -> None:
    bess_cols = [0.0] + [p * 100.0 for p in BESS_COVERAGE_PCTS]
    block = BESS_BLOCK_SPECS[BESS_DURATION_H]

    def fmt(v: float, d: int = 2) -> str:
        return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    def col_label(b: float) -> str:
        return "Sem BESS" if b == 0.0 else f"BESS {b:.0f}%"

    # --- matriz principal: custo de modulacao (R$/MWh contratado, media 30 anos)
    matrix_rows = []
    for curt in CURTAILMENT_TARGETS_PCT:
        cells = []
        base = _agg(df, curt, 0.0)
        for b in bess_cols:
            a = _agg(df, curt, b)
            delta = (
                ""
                if b == 0.0
                else f'<div class="delta">&minus;{fmt(base.custo_brl_mwh - a.custo_brl_mwh)} '
                f"({(base.custo_brl_mwh - a.custo_brl_mwh) / base.custo_brl_mwh * 100:.0f}%)</div>"
            )
            cells.append(
                f'<td><div class="main">{fmt(a.custo_brl_mwh)}</div>{delta}</td>'
            )
        matrix_rows.append(
            f"<tr><th>Curtailment {curt:.0f}%</th>{''.join(cells)}</tr>"
        )

    # --- tabela de detalhe por cenario
    detail_rows = []
    for curt in CURTAILMENT_TARGETS_PCT:
        for b in bess_cols:
            a = _agg(df, curt, b)
            sel = df[(df.curtailment_target_pct == curt) & (df.bess_coverage_pct == b)]
            detail_rows.append(
                "<tr>"
                f"<td>{curt:.0f}%</td><td>{col_label(b)}</td>"
                f"<td>{fmt(a.custo_brl_mwh)}</td>"
                f"<td>{fmt(a.custo_mrs_ano, 1)}</td>"
                f"<td>{fmt(a.captura_pct, 1)}%</td>"
                f"<td>{fmt(a.inj_mwmed, 1)}</td>"
                f"<td>{fmt(a.curt_rec_gwh, 1)}</td>"
                f"<td>{fmt(a.curt_lost_gwh, 1)}</td>"
                f"<td>{'&mdash;' if pd.isna(a.curt_lost_value) else fmt(a.curt_lost_value)}</td>"
                f"<td>{fmt(sel.mod_cost_brl_mwh_contract.iloc[0])} &rarr; "
                f"{fmt(sel.mod_cost_brl_mwh_contract.iloc[-1])}</td>"
                "</tr>"
            )

    # --- serie anual (uma linha por cenario)
    years = sorted(df.calendar_year.unique())
    year_head = "".join(f"<th>{y}</th>" for y in years)
    annual_rows = []
    for curt in CURTAILMENT_TARGETS_PCT:
        for b in bess_cols:
            sel = df[
                (df.curtailment_target_pct == curt) & (df.bess_coverage_pct == b)
            ].sort_values("calendar_year")
            cells = "".join(
                f"<td>{fmt(v, 1)}</td>" for v in sel.mod_cost_brl_mwh_contract
            )
            annual_rows.append(
                f"<tr><td>{curt:.0f}%</td><td>{col_label(b)}</td>{cells}</tr>"
            )

    bess_spec_rows = "".join(
        f"<tr><td>BESS {pct:.0%}</td>"
        f"<td>{fmt(pct * gf * 24.0, 0)}</td>"
        f"<td>{s.n_blocks}</td>"
        f"<td>{fmt(s.bess_power_mw, 1)}</td>"
        f"<td>{fmt(s.bess_energy_mwh, 1)}</td></tr>"
        for pct, s in bess_specs.items()
    )

    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    head_cols = "".join(f"<th>{col_label(b)}</th>" for b in bess_cols)
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Modulação do contrato {fmt(contract_mw, 1)} MW — BESS × Curtailment</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 2rem auto; max-width: 1280px;
         color: #1f2937; background: #f8fafc; }}
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
</style>
</head>
<body>
<h1>Modulação do contrato de {fmt(contract_mw, 1)} MW flat — efeito do BESS por cenário de curtailment</h1>

<div class="premissas">
<strong>Premissas</strong>
<ul>
  <li>Usina: Baguaçu id8, 600 MWac — geração média {fmt(gf, 1)} MWmed (30 anos com degradação, ano 1 = 2030).</li>
  <li>Contrato: {fmt(contract_mw, 1)} MWmed flat, 30 anos (2030–2059).</li>
  <li>Preço: curva horária Brazil Q2 26 Central 2030–2059 ({escape(str(PRICE_CSV))}).</li>
  <li>Custo de modulação = {fmt(contract_mw, 1)} MW × 8.760h × (PLD&#772; flat − PLD ponderado pelo perfil volume-neutro),
      em R$/MWh contratado. O perfil volume-neutro = injeção pós-BESS + corte ONS perdido: a modulação mede apenas
      <em>forma</em>; a perda de volume do curtailment é descontada em outra linha do modelo financeiro, valorada ao
      PLD das horas cortadas (coluna <code>curt_lost_value_brl_mwh</code> do CSV). Sem BESS, a modulação é
      invariante ao nível de curtailment por construção.</li>
  <li>BESS: blocos padrão 4h ({block.block_power_mw} MW / {block.block_energy_mwh} MWh), dimensionados por energia
      (15/20/25% × {fmt(gf, 1)} MW × 24h), despacho day-ahead com arbitragem de preço (charge_mode 3),
      RTE Envision por ano de operação (comissionamento 2030).</li>
  <li>Curtailment: perfil horário {escape(str(CURTAILMENT_CSV))} escalado ano a ano para fechar 0/10/20% da geração anual injetável;
      o BESS pode recuperar curtailment carregando nessas horas.</li>
</ul>
</div>

<h2>Custo de modulação — R$/MWh contratado (média 2030–2059)</h2>
<table>
  <tr><th></th>{head_cols}</tr>
  {''.join(matrix_rows)}
</table>
<p class="note">Entre parênteses: redução vs. sem BESS no mesmo cenário de curtailment.</p>

<h2>Especificação dos BESS (blocos padrão de {BESS_DURATION_H}h)</h2>
<table>
  <tr><th>Cenário</th><th>Alvo (MWh)</th><th>Blocos</th><th>Potência (MW)</th><th>Energia (MWh)</th></tr>
  {bess_spec_rows}
</table>

<h2>Detalhe por cenário (médias 2030–2059)</h2>
<table>
  <tr><th>Curtailment</th><th>BESS</th><th>Custo (R$/MWh contr.)</th><th>Custo (MR$/ano)</th>
      <th>Fator captura</th><th>Injeção (MWmed)</th><th>Curt. recuperado (GWh/ano)</th>
      <th>Curt. perdido (GWh/ano)</th><th>PLD do corte perdido (R$/MWh)</th>
      <th>Custo 2030 &rarr; 2059</th></tr>
  {''.join(detail_rows)}
</table>

<h2>Custo de modulação ano a ano (R$/MWh contratado)</h2>
<div class="scroll">
<table>
  <tr><th>Curt.</th><th>BESS</th>{year_head}</tr>
  {''.join(annual_rows)}
</table>
</div>

<p class="note">Gerado em {generated} por scripts/standalone/calc_modulacao_contrato_bess.py.
Despacho com previsão perfeita de PLD (limite superior do ganho de arbitragem).</p>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
