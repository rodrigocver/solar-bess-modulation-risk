"""Modulacao do contrato PPA flat (P90 do ano 20), sem e com BESS — Aurora Central.

Caso de uso (modulacao "real" do projeto):
  A modulacao so e calculada sobre o volume efetivamente vendido como PPA flat.
  Esse volume e o P90 do 20o ano de operacao (energia firme degradada, o cenario
  conservador que ancora o contrato). A sobra descontratada (G - C) NAO e
  modulacao — e risco de preco sobre energia nao vendida e fica fora desta conta.

Fluxo interativo:
  1. Confirma/seleciona a curva de geracao (solar/*.csv).
  2. Solicita o P90 do ano 20 em MWmed (padrao 155).

Premissa de preco: curva central ja gerada (Aurora Central, Brazil Q2 26,
2030-2059) — referida aqui como ``aurora_central``.

Para cada ano do horizonte do PPA (20 anos, 2030-2049) calcula a modulacao do
contrato flat em duas convencoes:
  - flat anual: C constante o ano todo (modulacao intradiaria + sazonal);
  - sazonalizado: C_m proporcional ao perfil do mes (isola a intradiaria).

    custo_mod = C * H * (PLD_medio_flat - PLD_ponderado_perfil)

O perfil de ponderacao e volume-neutro (injecao + corte ONS perdido), de modo
que a modulacao mede apenas FORMA. Roda dois cenarios — "sem BESS" e "com BESS"
(o BESS unico do cenario inicial do projeto: bloco 4h dimensionado pela garantia
fisica, despacho price-aware charge_mode 3, RTE Envision por ano).

Saidas em output/modulacao_contrato/:
  - CSV anual (ambas as convencoes, sem/com BESS);
  - HTML flat anual;
  - HTML sazonalizado.
"""

from __future__ import annotations

import datetime as _dt
import re
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.__main__ import _get_scenario_for_duration
from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams
from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.rte import load_rte_table
from solar_bess_risk.simulation import simulate_scenario

SOLAR_DIR = Path("solar")
DEFAULT_SOLAR_CSV = SOLAR_DIR / "solar_baguacu_m2_600mw_id8.csv"
PRICE_CSV = Path("output/curvas/curvas_preco_brazil_q2_26_central_2030_2059.csv")
PRICE_LABEL = "aurora_central"
RTE_PATH = "dados/11 - Envision.xlsx"
OUTPUT_DIR = Path("output/modulacao_contrato")
START_YEAR = 2030
PPA_TENOR_YEARS = 20
DEFAULT_P90_YEAR20_MWMED = 155.0
BESS_DURATION_H = 4

_DAYS_PER_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
_MONTH_HOURS = np.array([d * 24 for d in _DAYS_PER_MONTH])
_MONTH_EDGES = np.concatenate([[0], np.cumsum(_MONTH_HOURS)])
_MONTH_NAMES = (
    "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
)


def _monthly_slices() -> list[slice]:
    return [slice(int(_MONTH_EDGES[m]), int(_MONTH_EDGES[m + 1])) for m in range(12)]


def _mwac_from_name(path: Path) -> float:
    match = re.search(r"(\d+)\s*mw", path.name, flags=re.IGNORECASE)
    if not match:
        raise ValueError(
            f"Nao foi possivel inferir o MWac de '{path.name}'. "
            "Inclua '<NNN>mw' no nome ou ajuste manualmente."
        )
    return float(match.group(1))


def _prompt_solar_curve() -> tuple[Path, float]:
    """Confirma/seleciona a curva de geracao (passo 0, antes do P90)."""
    curves = sorted(SOLAR_DIR.glob("*.csv"))
    if not curves:
        raise FileNotFoundError(f"Nenhuma curva solar em {SOLAR_DIR}/.")
    try:
        default_idx = curves.index(DEFAULT_SOLAR_CSV)
    except ValueError:
        default_idx = 0

    print("\nCurvas de geracao disponiveis:")
    for i, c in enumerate(curves):
        marca = "  (padrao)" if i == default_idx else ""
        print(f"  [{i}] {c.name}{marca}")
    try:
        resp = input(
            f"Selecione a curva de geracao [Enter = {curves[default_idx].name}]: "
        ).strip()
    except EOFError:
        resp = ""
    if resp == "":
        chosen = curves[default_idx]
    elif resp.isdigit() and 0 <= int(resp) < len(curves):
        chosen = curves[int(resp)]
    else:
        candidate = SOLAR_DIR / resp
        chosen = candidate if candidate.exists() else curves[default_idx]

    mwac = _mwac_from_name(chosen)
    print(f"Curva confirmada: {chosen.name} (MWac inferido = {mwac:.0f}).")
    return chosen, mwac


def _prompt_p90_year20(default: float = DEFAULT_P90_YEAR20_MWMED) -> float:
    """Solicita o P90 do ano 20 em MWmed (passo apos a confirmacao da curva)."""
    try:
        resp = input(
            f"Informe o P90 do ano 20 (MWmed) — volume flat do PPA "
            f"[Enter = {default:.1f}]: "
        ).strip().replace(",", ".")
    except EOFError:
        resp = ""
    if resp == "":
        print(f"P90 ano 20 = {default:.1f} MWmed (padrao).")
        return default
    try:
        value = float(resp)
    except ValueError:
        print(f"Valor invalido; usando padrao {default:.1f} MWmed.")
        return default
    if value <= 0:
        print(f"Valor deve ser > 0; usando padrao {default:.1f} MWmed.")
        return default
    print(f"P90 ano 20 = {value:.1f} MWmed.")
    return value


def _price_curves(path: Path) -> dict[int, np.ndarray]:
    df = pd.read_csv(path)
    curves: dict[int, np.ndarray] = {}
    for col in df.columns:
        if col.startswith("price_") and col.endswith("_brl_mwh"):
            year = int(col.split("_")[1])
            values = df[col].to_numpy(dtype=np.float64)
            if values.shape[0] != HOURS_PER_YEAR:
                raise ValueError(
                    f"{path}: coluna {col} tem {values.shape[0]} horas; "
                    f"esperado {HOURS_PER_YEAR}."
                )
            curves[year] = values
    if not curves:
        raise ValueError(f"{path}: nenhuma coluna price_YYYY_brl_mwh encontrada.")
    return curves


def _contract_modulation_year(
    profile_mwh: np.ndarray,
    prices: np.ndarray,
    contract_mw: float,
    slices: list[slice],
) -> dict[str, float]:
    """Custo de modulacao do contrato flat para um ano, ambas as convencoes.

    profile_mwh : perfil volume-neutro de ponderacao (injecao + corte perdido).
    """
    profile_total = float(profile_mwh.sum())
    price_mean = float(prices.mean())
    price_w = float((profile_mwh * prices).sum() / profile_total)
    contract_energy = contract_mw * HOURS_PER_YEAR

    cost_flat = contract_energy * (price_mean - price_w)

    cost_sazo = 0.0
    for sl in slices:
        p_m = prices[sl]
        pr_m = profile_mwh[sl]
        h_m = float(p_m.shape[0])
        prof_m = float(pr_m.sum())
        if prof_m <= 0:
            continue
        price_mean_m = float(p_m.mean())
        price_w_m = float((pr_m * p_m).sum() / prof_m)
        c_m = contract_mw * (prof_m / profile_total) * (HOURS_PER_YEAR / h_m)
        cost_sazo += c_m * h_m * (price_mean_m - price_w_m)

    return {
        "profile_mwmed": profile_total / HOURS_PER_YEAR,
        "price_mean_brl_mwh": price_mean,
        "price_weighted_brl_mwh": price_w,
        "capture_factor_pct": price_w / price_mean * 100.0,
        "mod_flat_brl": cost_flat,
        "mod_flat_brl_mwh": cost_flat / contract_energy,
        "mod_sazo_brl": cost_sazo,
        "mod_sazo_brl_mwh": cost_sazo / contract_energy,
        "seasonal_component_brl": cost_flat - cost_sazo,
    }


def run_ppa_modulation_report(
    solar,
    contract_mw: float,
    output_dir: Path,
    *,
    rte_table: dict[int, float] | None = None,
    params=None,
) -> tuple[Path, Path, Path]:
    """Compute PPA modulation report (flat + sazonalizado) and write outputs.

    Callable by the main pipeline after solar and RTE are already loaded.
    Returns (csv_path, flat_html_path, sazo_html_path).
    """
    if solar.generation_years_lim_mw is None:
        raise ValueError("CSV solar precisa ser multi-ano (gen_lim_mw).")

    prices_by_year = _price_curves(PRICE_CSV)
    if rte_table is None:
        rte_table = load_rte_table(RTE_PATH, commissioning_year=START_YEAR)
    rte_last = max(rte_table)
    if params is None:
        params = SimulationParams(
            csv_path=str(solar.csv_filename),
            mwac=float(solar.garantia_fisica_mw / solar.fc),
        )
    gf = float(solar.garantia_fisica_mw)
    slices = _monthly_slices()

    base_scenario = _get_scenario_for_duration(
        BESS_DURATION_H, gf, params.usd_brl_rate,
        rte=rte_table.get(START_YEAR, rte_table[rte_last]), charge_mode=3,
    )
    print(
        f"  [PPA Modulação] GF={gf:.1f} MWmed | contrato flat={contract_mw:.1f} MWmed "
        f"({contract_mw / gf * 100:.0f}% da GF) | "
        f"BESS {base_scenario.bess_power_mw:.1f} MW / {base_scenario.bess_energy_mwh:.1f} MWh"
    )

    years = [y for y in sorted(prices_by_year) if y < START_YEAR + PPA_TENOR_YEARS]
    rows: list[dict] = []

    for calendar_year in years:
        solar_year_idx = min(calendar_year - START_YEAR + 1, solar.n_years)
        gen_lim, _gen_bess = solar.get_year_arrays(solar_year_idx)
        gen_lim = gen_lim.astype(np.float64)
        prices = prices_by_year[calendar_year]
        rte = rte_table.get(calendar_year, rte_table[rte_last])

        base_metrics = _contract_modulation_year(gen_lim, prices, contract_mw, slices)
        rows.append({
            "cenario": "sem BESS",
            "calendar_year": calendar_year,
            "solar_year_idx": solar_year_idx,
            "rte": np.nan,
            **base_metrics,
        })

        scenario = _get_scenario_for_duration(
            BESS_DURATION_H, gf, params.usd_brl_rate, rte=rte, charge_mode=3,
        )
        price_profile = PriceProfile(
            prices_brl_per_mwh=prices,
            source=f"{PRICE_LABEL}_{calendar_year}",
            bq_submarket="-",
            bq_year=calendar_year,
        )
        dispatch = simulate_scenario(
            solar, price_profile, scenario, params,
            curtailment_series=None, solar_year_idx=solar_year_idx,
        )
        bess_metrics = _contract_modulation_year(
            np.asarray(dispatch.grid_injection_mwh, dtype=np.float64),
            prices, contract_mw, slices,
        )
        rows.append({
            "cenario": "com BESS",
            "calendar_year": calendar_year,
            "solar_year_idx": solar_year_idx,
            "rte": rte,
            **bess_metrics,
        })

    df = pd.DataFrame(rows)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = f"modulacao_contrato_ppa_{contract_mw:.0f}mw_{PRICE_LABEL}"
    csv_path = output_dir / f"{slug}_anual.csv"
    df.to_csv(csv_path, index=False, float_format="%.6f")

    summary = (
        df.groupby("cenario")[["mod_flat_brl_mwh", "mod_sazo_brl_mwh",
                               "mod_flat_brl", "mod_sazo_brl",
                               "capture_factor_pct"]]
        .mean()
    )
    flat_html = output_dir / f"{slug}_flat_anual.html"
    sazo_html = output_dir / f"{slug}_sazonalizado.html"
    _write_report_html(
        df, summary, flat_html, contract_mw, gf, base_scenario,
        convention="flat", years=years,
    )
    _write_report_html(
        df, summary, sazo_html, contract_mw, gf, base_scenario,
        convention="sazo", years=years,
    )

    sem = summary.loc["sem BESS"]
    com = summary.loc["com BESS"]
    print(
        f"  [PPA Modulação] flat: sem BESS={sem.mod_flat_brl_mwh:.1f} "
        f"→ com BESS={com.mod_flat_brl_mwh:.1f} R$/MWh "
        f"(redução {sem.mod_flat_brl_mwh - com.mod_flat_brl_mwh:.1f})"
    )
    return csv_path, flat_html, sazo_html


def main() -> None:
    print("=" * 72)
    print("  Modulacao de contrato PPA (P90 ano 20) — sem e com BESS — "
          f"{PRICE_LABEL}")
    print("=" * 72)

    solar_csv, mwac = _prompt_solar_curve()
    contract_mw = _prompt_p90_year20()

    solar = load_solar_csv(str(solar_csv), mwac)
    rte_table = load_rte_table(RTE_PATH, commissioning_year=START_YEAR)
    params = SimulationParams(csv_path=str(solar_csv), mwac=mwac)

    csv_path, flat_html, sazo_html = run_ppa_modulation_report(
        solar, contract_mw, OUTPUT_DIR, rte_table=rte_table, params=params,
    )
    print(f"\nSaidas:\n  {csv_path}\n  {flat_html}\n  {sazo_html}")


def _fmt(v: float, d: int = 2) -> str:
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _write_report_html(
    df: pd.DataFrame,
    summary: pd.DataFrame,
    path: Path,
    contract_mw: float,
    gf: float,
    scenario,
    *,
    convention: str,
    years: list[int],
) -> None:
    is_flat = convention == "flat"
    conv_label = "Flat anual" if is_flat else "Sazonalizado"
    conv_desc = (
        "C constante todas as horas do ano — captura modulação intradiária + sazonal."
        if is_flat
        else "C_m proporcional ao perfil de cada mês — isola a modulação intradiária."
    )
    col_brl_mwh = "mod_flat_brl_mwh" if is_flat else "mod_sazo_brl_mwh"
    col_brl = "mod_flat_brl" if is_flat else "mod_sazo_brl"

    sem = summary.loc["sem BESS"]
    com = summary.loc["com BESS"]
    reducao = sem[col_brl_mwh] - com[col_brl_mwh]
    reducao_pct = (reducao / sem[col_brl_mwh] * 100.0) if sem[col_brl_mwh] else 0.0

    cards = f"""
    <div class="cards">
      <div class="card"><div class="lab">Modulação sem BESS</div>
        <div class="val">R$ {_fmt(sem[col_brl_mwh])}/MWh</div>
        <div class="sub">{_fmt(sem[col_brl] / 1e6, 1)} MM/ano</div></div>
      <div class="card"><div class="lab">Modulação com BESS</div>
        <div class="val">R$ {_fmt(com[col_brl_mwh])}/MWh</div>
        <div class="sub">{_fmt(com[col_brl] / 1e6, 1)} MM/ano</div></div>
      <div class="card hl"><div class="lab">Redução de modulação (BESS)</div>
        <div class="val">R$ {_fmt(reducao)}/MWh</div>
        <div class="sub">{_fmt(reducao_pct, 0)}% &middot; {_fmt((sem[col_brl] - com[col_brl]) / 1e6, 1)} MM/ano</div></div>
    </div>"""

    year_head = "".join(f"<th>{y}</th>" for y in years)
    annual_rows = ""
    for cen in ("sem BESS", "com BESS"):
        sel = df[df.cenario == cen].sort_values("calendar_year")
        cells = "".join(f"<td>{_fmt(v, 1)}</td>" for v in sel[col_brl_mwh])
        annual_rows += f"<tr><th>{cen}</th>{cells}</tr>"

    generated = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Modulação PPA {_fmt(contract_mw, 0)} MW — {conv_label} — aurora_central</title>
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 2rem auto; max-width: 1280px;
         color: #1f2937; background: #f8fafc; }}
  h1 {{ font-size: 1.45rem; margin-bottom: .25rem; }}
  h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
  .cards {{ display: flex; gap: 1rem; margin: 1.25rem 0; flex-wrap: wrap; }}
  .card {{ background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
           padding: 1rem 1.25rem; min-width: 220px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .card.hl {{ border-color: #0f766e; background: #ecfdf5; }}
  .card .lab {{ font-size: .82rem; color: #6b7280; }}
  .card .val {{ font-size: 1.5rem; font-weight: 700; margin: .25rem 0; }}
  .card .sub {{ font-size: .82rem; color: #0f766e; }}
  table {{ border-collapse: collapse; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1);
           margin-top: .75rem; }}
  th, td {{ border: 1px solid #e5e7eb; padding: .45rem .8rem; text-align: right;
            font-size: .88rem; white-space: nowrap; }}
  th {{ background: #0f766e; color: #fff; font-weight: 600; }}
  tr th:first-child {{ background: #115e59; text-align: left; }}
  .premissas {{ background: #fff; border: 1px solid #e5e7eb; padding: 1rem 1.25rem;
                border-radius: 6px; font-size: .88rem; }}
  .premissas li {{ margin: .2rem 0; }}
  .scroll {{ overflow-x: auto; }}
  .note {{ color: #6b7280; font-size: .8rem; margin-top: .5rem; }}
</style>
</head>
<body>
<h1>Modulação do contrato PPA — {conv_label}</h1>
<p class="note">{conv_desc}</p>
{cards}

<h2>Modulação por ano (R$/MWh contratado)</h2>
<div class="scroll"><table>
<thead><tr><th>Cenário</th>{year_head}</tr></thead>
<tbody>{annual_rows}</tbody>
</table></div>

<h2>Premissas</h2>
<div class="premissas">
<ul>
  <li>Volume contratado (flat PPA): <strong>{_fmt(contract_mw, 1)} MWmed</strong> = P90 do ano 20
      ({_fmt(contract_mw / gf * 100, 0)}% da garantia física {_fmt(gf, 1)} MWmed). Apenas este volume é modulado;
      a sobra descontratada (G − C) é risco de preço e fica fora desta conta.</li>
  <li>Horizonte do PPA: {years[0]}–{years[-1]} ({len(years)} anos).</li>
  <li>Preço: curva central já gerada (<code>aurora_central</code> — {escape(str(PRICE_CSV))}).</li>
  <li>Custo de modulação = C × 8.760h × (PLD&#772; flat − PLD ponderado pelo perfil volume-neutro),
      em R$/MWh contratado. Convenção <strong>{conv_label.lower()}</strong>: {escape(conv_desc)}</li>
  <li>BESS (cenário inicial do projeto): bloco {BESS_DURATION_H}h
      ({_fmt(scenario.bess_power_mw, 1)} MW / {_fmt(scenario.bess_energy_mwh, 1)} MWh),
      despacho day-ahead com arbitragem de preço (charge_mode 3), RTE Envision por ano de operação.
      Cenário único (sem grade de sensibilidade).</li>
</ul>
</div>
<p class="note">Gerado em {generated}.</p>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")


if __name__ == "__main__":
    main()
