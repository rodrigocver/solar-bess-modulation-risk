"""Excel/HTML report generators — 9-tab backtest output (spec v2.0).

Functions
---------
build_excel_report(results_by_key, output_path, scenario_config) -> str
build_html_report(results_by_key, output_path, scenario_config) -> str
"""

from __future__ import annotations

from pathlib import Path
from html import escape

import numpy as np
import pandas as pd

from solar_bess_risk.config import CAPEX_USD_PER_KWH, HOURS_PER_YEAR
from solar_bess_risk.simulation import DispatchResult


def _compute_spread_column(
    charge_mwh: np.ndarray,
    discharge_mwh: np.ndarray,
    pld: np.ndarray,
) -> np.ndarray:
    """Compute positional spread: pair D[i] with C[i] within each day.

    Returns array of shape (8760,) with NaN for non-discharge hours.
    """
    spread = np.full(HOURS_PER_YEAR, np.nan)

    for day in range(365):
        start = day * 24
        end = start + 24

        charge_hours = [h for h in range(start, end) if charge_mwh[h] > 1e-10]
        discharge_hours = [h for h in range(start, end) if discharge_mwh[h] > 1e-10]

        if not discharge_hours:
            continue

        charge_plds = [pld[h] for h in charge_hours]

        for i, dh in enumerate(discharge_hours):
            if i < len(charge_hours):
                spread[dh] = pld[dh] - charge_plds[i]
            elif charge_plds:
                spread[dh] = pld[dh] - np.mean(charge_plds)
            else:
                spread[dh] = np.nan

    return spread


def _build_hourly_dataframe(
    dispatch: DispatchResult,
    pld: np.ndarray,
    garantia_fisica_mw: float,
    generation_mw: np.ndarray,
    peak_hours: frozenset[int],
    year_label: int,
) -> pd.DataFrame:
    """Build the 8760-row DataFrame for one tab."""
    # Timestamps
    dt_index = pd.date_range(
        f"{year_label}-01-01 00:00:00",
        periods=HOURS_PER_YEAR,
        freq="h",
    )

    hora_dia = np.array([h % 24 for h in range(HOURS_PER_YEAR)], dtype=np.int32)
    dia_ano = np.array([h // 24 + 1 for h in range(HOURS_PER_YEAR)], dtype=np.int32)
    is_discharging = dispatch.discharge_mwh > 1e-10

    excesso_solar = np.maximum(0.0, generation_mw - dispatch.curtailment_mwh - garantia_fisica_mw)

    exposicao_sem = dispatch.deficit_mwh * pld
    exposicao_com = dispatch.residual_deficit_mwh * pld
    economia = exposicao_sem - exposicao_com

    # Signed net balance:
    # Sem BESS: injection = gen - curtailment (all curtailment lost)
    # Com BESS: injection = gen - charge - curt_lost + discharge
    curt_total_arr = dispatch.curtailment_mwh
    curt_lost_arr = dispatch.curtailment_lost_mwh
    injection_sem = generation_mw - curt_total_arr
    injection_com = generation_mw - dispatch.charge_mwh - curt_lost_arr + dispatch.discharge_mwh
    saldo_liquido_sem = (injection_sem - garantia_fisica_mw) * pld
    saldo_liquido_com = (injection_com - garantia_fisica_mw) * pld

    spread = _compute_spread_column(dispatch.charge_mwh, dispatch.discharge_mwh, pld)

    # Curtailment recuperado = total curtailment - curtailment perdido
    curtailment_recuperado = np.maximum(0.0, dispatch.curtailment_mwh - dispatch.curtailment_lost_mwh)
    # Percentual de curtailment recuperado / curtailment total
    with np.errstate(divide='ignore', invalid='ignore'):
        curtailment_recuperado_pct = np.where(
            dispatch.curtailment_mwh > 1e-10,
            curtailment_recuperado / dispatch.curtailment_mwh * 100.0,
            0.0,
        )
        curtailment_pct = np.where(
            generation_mw > 1e-10,
            dispatch.curtailment_mwh / generation_mw * 100.0,
            0.0,
        )

    df = pd.DataFrame({
        "data_hora": dt_index,
        "hora_dia": hora_dia,
        "dia_ano": dia_ano,
        "descarga_ativa": is_discharging,
        "geracao_solar_mw": generation_mw,
        "garantia_fisica_mw": garantia_fisica_mw,
        "excesso_solar_mw": excesso_solar,
        "curtailment_mw": dispatch.curtailment_mwh,
        "curtailment_pct": curtailment_pct,
        "curtailment_recuperado_mw": curtailment_recuperado,
        "curtailment_recuperado_pct": curtailment_recuperado_pct,
        "curtailment_perdido_mw": dispatch.curtailment_lost_mwh,
        "carga_bess_mw": dispatch.charge_mwh,
        "soc_mwh": dispatch.soc_mwh,
        "descarga_bess_mw": dispatch.discharge_mwh,
        "pld_r_mwh": pld,
        "deficit_sem_bess_mw": dispatch.deficit_mwh,
        "deficit_com_bess_mw": dispatch.residual_deficit_mwh,
        "exposicao_sem_bess_r": exposicao_sem,
        "exposicao_com_bess_r": exposicao_com,
        "economia_hora_r": economia,
        "saldo_liquido_horario_sem_bess_r": saldo_liquido_sem,
        "saldo_liquido_horario_com_bess_r": saldo_liquido_com,
        "saldo_liquido_diario_sem_bess_r": np.nan,
        "saldo_liquido_diario_com_bess_r": np.nan,
        "spread_r_mwh": spread,
    })

    # Daily saldo: sum per day, shown only at hora 23 (last hour of each day)
    daily_sem = saldo_liquido_sem.reshape(365, 24).sum(axis=1)
    daily_com = saldo_liquido_com.reshape(365, 24).sum(axis=1)
    daily_sem_at_23 = np.full(HOURS_PER_YEAR, np.nan)
    daily_com_at_23 = np.full(HOURS_PER_YEAR, np.nan)
    daily_sem_at_23[23::24] = daily_sem
    daily_com_at_23[23::24] = daily_com
    df["saldo_liquido_diario_sem_bess_r"] = daily_sem_at_23
    df["saldo_liquido_diario_com_bess_r"] = daily_com_at_23

    # Round: PLD keeps 2 decimals; all other float columns to 0
    for col in df.select_dtypes(include="float64").columns:
        if "pld" in col:
            df[col] = df[col].round(2)
        else:
            df[col] = df[col].round(0)

    return df


def _build_summary_row(
    df: pd.DataFrame,
    garantia_fisica_mw: float,
    duration_h: int,
    usd_brl_rate: float,
    mwac: float,
    rte: float = 1.0,
    dispatch: "DispatchResult | None" = None,
    charge_mode: int = 0,
) -> dict:
    """Build the summary row (line 8762) for a tab."""
    economia_anual = df["economia_hora_r"].sum()
    bess_power_mw = garantia_fisica_mw
    bess_energy_mwh = bess_power_mw * duration_h
    capex_usd = bess_energy_mwh * 1000 * CAPEX_USD_PER_KWH[duration_h]
    capex_brl = capex_usd * usd_brl_rate
    fc = df["geracao_solar_mw"].sum() / (mwac * HOURS_PER_YEAR)

    # Spread mean (only discharge hours)
    discharge_mask = df["descarga_bess_mw"] > 1e-10
    spread_mean = df.loc[discharge_mask, "spread_r_mwh"].mean() if discharge_mask.any() else 0.0

    payback = capex_brl / economia_anual if economia_anual > 0 else None

    coverage_energia = 0.0
    deficit_sem = df["deficit_sem_bess_mw"].sum()
    deficit_com = df["deficit_com_bess_mw"].sum()
    if deficit_sem > 0:
        coverage_energia = 1 - (deficit_com / deficit_sem)

    reducao_exposicao = 0.0
    exp_sem = df["exposicao_sem_bess_r"].sum()
    exp_com = df["exposicao_com_bess_r"].sum()
    if exp_sem > 0:
        reducao_exposicao = 1 - (exp_com / exp_sem)

    curtailment_total = df["curtailment_mw"].sum()
    curtailment_recuperado_total = df["curtailment_recuperado_mw"].sum()
    curtailment_recuperado_pct_total = (
        curtailment_recuperado_total / curtailment_total * 100.0 if curtailment_total > 1e-10 else 0.0
    )
    geracao_total = df["geracao_solar_mw"].sum()
    curtailment_pct_total = (
        curtailment_total / geracao_total * 100.0 if geracao_total > 1e-10 else 0.0
    )

    # Carga não realizada (daily concept — sum of daily missed cycles)
    carga_nao_realizada_total = 0.0
    if dispatch is not None:
        carga_nao_realizada_total = float(dispatch.carga_nao_realizada_diaria_mwh.sum())

    modo_label = (
        "Arbitragem de PLD — descarrega nas N horas de maior PLD do dia"
        if charge_mode == 3
        else "Cobertura de Déficit — descarrega em qualquer hora com geração < GF"
    )
    row = {
        "data_hora": "RESUMO",
        "hora_dia": "",
        "dia_ano": "",
        "descarga_ativa": "",
        "modo_operacao": modo_label,
        "geracao_solar_mw": round(df["geracao_solar_mw"].sum()),
        "garantia_fisica_mw": round(garantia_fisica_mw),
        "excesso_solar_mw": round(df["excesso_solar_mw"].sum()),
        "curtailment_mw": round(curtailment_total),
        "curtailment_pct": round(curtailment_pct_total),
        "curtailment_recuperado_mw": round(curtailment_recuperado_total),
        "curtailment_recuperado_pct": round(curtailment_recuperado_pct_total),
        "curtailment_perdido_mw": round(df["curtailment_perdido_mw"].sum()),
        "carga_bess_mw": round(df["carga_bess_mw"].sum()),
        "soc_mwh": round(df["soc_mwh"].mean()),
        "descarga_bess_mw": round(df["descarga_bess_mw"].sum()),
        "carga_nao_realizada_mwh_ano": round(carga_nao_realizada_total),
        "pld_r_mwh": round(df["pld_r_mwh"].mean(), 2),
        "deficit_sem_bess_mw": round(deficit_sem),
        "deficit_com_bess_mw": round(deficit_com),
        "exposicao_sem_bess_r": round(exp_sem),
        "exposicao_com_bess_r": round(exp_com),
        "economia_hora_r": round(economia_anual),
        "saldo_liquido_horario_sem_bess_r": round(df["saldo_liquido_horario_sem_bess_r"].sum()),
        "saldo_liquido_horario_com_bess_r": round(df["saldo_liquido_horario_com_bess_r"].sum()),
        "saldo_liquido_diario_sem_bess_r": round(df["saldo_liquido_horario_sem_bess_r"].sum() / 365),
        "saldo_liquido_diario_com_bess_r": round(df["saldo_liquido_horario_com_bess_r"].sum() / 365),
        "spread_r_mwh": round(spread_mean),
        "rte": rte,
    }
    return row


def build_excel_report(
    results_by_key: dict[str, tuple],
    output_path: str | Path,
    mwac: float,
    usd_brl_rate: float,
    charge_mode: int = 0,
) -> str:
    """Build the 9-tab Excel report.

    Parameters
    ----------
    results_by_key : dict
        Keys are tab names (e.g. "2025-2h"). Values are tuples of:
        (dispatch, pld, garantia_fisica_mw, generation_mw, peak_hours, duration_h, year_label[, rte])
    output_path : str | Path
        Path for the output .xlsx file.
    mwac : float
        Plant AC capacity in MW.
    usd_brl_rate : float
        Exchange rate USD→BRL.

    Returns
    -------
    str
        Path to the written Excel file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(str(output_path), engine="openpyxl") as writer:
        for tab_name, data in results_by_key.items():
            dispatch, pld, gf, gen, peak_hours, duration_h, year_label = data[:7]
            rte = data[7] if len(data) > 7 else 1.0

            df = _build_hourly_dataframe(dispatch, pld, gf, gen, peak_hours, year_label)
            summary = _build_summary_row(df, gf, duration_h, usd_brl_rate, mwac, rte=rte, dispatch=dispatch, charge_mode=charge_mode)
            summary_df = pd.DataFrame([summary])
            full_df = pd.concat([df, summary_df], ignore_index=True)

            full_df.to_excel(writer, sheet_name=tab_name, index=False, freeze_panes=(1, 0))

    return str(output_path)


def build_html_report(
    results_by_key: dict[str, tuple],
    output_path: str | Path,
    mwac: float,
    usd_brl_rate: float,
    *,
    bq_submarket: str,
    charge_mode: int = 0,
    rte_metadata: dict[str, float | str] | None = None,
) -> str:
    """Build a self-contained HTML report with one section per backtest tab."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    detail_sections: list[str] = []
    float_formatter = lambda x: f"{x:,.4f}"

    for tab_name, data in results_by_key.items():
        dispatch, pld, gf, gen, peak_hours, duration_h, year_label = data[:7]
        rte = data[7] if len(data) > 7 else 1.0
        df = _build_hourly_dataframe(dispatch, pld, gf, gen, peak_hours, year_label)
        summary = _build_summary_row(df, gf, duration_h, usd_brl_rate, mwac, rte=rte, dispatch=dispatch, charge_mode=charge_mode)
        summary["cenario"] = tab_name
        summary["capex_usd_kwh"] = CAPEX_USD_PER_KWH[duration_h]
        summary_rows.append(summary)

        full_df = pd.concat([df, pd.DataFrame([summary])], ignore_index=True)
        detail_sections.append(
            "<details>"
            f"<summary>{escape(tab_name)} - serie horaria completa</summary>"
            f"{full_df.to_html(index=False, classes='hourly', float_format=float_formatter)}"
            "</details>"
        )

    summary_df = pd.DataFrame(summary_rows)
    preferred = [
        "cenario", "modo_operacao", "geracao_solar_mw", "garantia_fisica_mw", "capex_usd_kwh",
        "excesso_solar_mw", "curtailment_mw", "curtailment_pct",
        "curtailment_recuperado_mw", "curtailment_recuperado_pct", "curtailment_perdido_mw",
        "carga_bess_mw", "descarga_bess_mw", "carga_nao_realizada_mwh_ano",
        "pld_r_mwh",
        "deficit_sem_bess_mw", "deficit_com_bess_mw",
        "exposicao_sem_bess_r", "exposicao_com_bess_r",
        "saldo_liquido_horario_sem_bess_r", "saldo_liquido_horario_com_bess_r",
        "saldo_liquido_diario_sem_bess_r", "saldo_liquido_diario_com_bess_r",
        "economia_hora_r", "spread_r_mwh", "rte",
    ]
    summary_df = summary_df[[c for c in preferred if c in summary_df.columns]]

    rte_html = ""
    if rte_metadata:
        rte_html = "".join(
            f"<li><strong>{escape(str(k))}:</strong> {escape(str(v))}</li>"
            for k, v in rte_metadata.items()
        )

    charge_mode_label = (
        "Arbitragem de PLD — descarrega nas N horas de maior PLD do dia"
        if charge_mode == 3
        else "Cobertura de Déficit — descarrega em qualquer hora com geração < GF"
    )
    html = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Backtest Solar + BESS</title>
<style>
body {{ font-family: Arial, sans-serif; margin: 24px; color: #222; }}
h1, h2 {{ color: #123; }}
table {{ border-collapse: collapse; width: 100%; margin: 16px 0; font-size: 12px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; text-align: right; }}
th {{ background: #24466f; color: white; position: sticky; top: 0; }}
td:first-child, th:first-child {{ text-align: left; }}
details {{ margin: 18px 0; }}
summary {{ cursor: pointer; font-weight: 700; padding: 8px 0; }}
.hourly {{ font-size: 11px; }}
.note {{ max-width: 960px; line-height: 1.45; }}
</style>
</head>
<body>
<h1>Backtest Solar + BESS</h1>
<section class="note">
<h2>Premissas do Run</h2>
<ul>
<li><strong>Submercado PLD:</strong> {escape(bq_submarket)}</li>
<li><strong>MWac:</strong> {mwac:,.2f}</li>
<li><strong>USD/BRL:</strong> {usd_brl_rate:,.4f}</li>
<li><strong>CAPEX por duração:</strong> 2h={CAPEX_USD_PER_KWH[2]:.2f}, 4h={CAPEX_USD_PER_KWH[4]:.2f} USD/kWh</li>
<li><strong>Modo BESS:</strong> {escape(charge_mode_label)}</li>
{rte_html}
</ul>
<p>Exposição financeira é calculada em base 24h, conforme decisão de modelo do projeto.</p>
</section>
<section>
<h2>Resumo</h2>
{summary_df.to_html(index=False, classes='summary', float_format=float_formatter)}
</section>
<section>
<h2>Séries Horárias</h2>
{''.join(detail_sections)}
</section>
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
