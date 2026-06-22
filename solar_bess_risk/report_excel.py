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

from solar_bess_risk.config import (
    CAPEX_USD_PER_KWH,
    CURTAILMENT_COLUMN,
    CURTAILMENT_SHEET_2025,
    HOURS_PER_YEAR,
)
from solar_bess_risk.config import BESS_BLOCK_SPECS
from solar_bess_risk.simulation import DispatchResult


def _scenario_from_data(data: tuple):
    """Return the ScenarioDefinition appended by the main pipeline, when present."""
    if len(data) > 8 and hasattr(data[8], "bess_energy_mwh"):
        return data[8]
    return None


def _projection_from_data(data: tuple):
    """Return the CashflowProjection appended by the main pipeline, when present."""
    if len(data) > 9 and hasattr(data[9], "lcos_brl_per_mwh"):
        return data[9]
    return None


def _risk_from_data(data: tuple):
    """Return historical risk metrics appended by the main pipeline, when present."""
    if len(data) > 10 and isinstance(data[10], dict):
        return data[10]
    return None


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

    # Signed net balance:
    # Sem BESS: inverter-limited generation minus external ONS curtailment.
    # Com BESS: executed grid injection from the dispatch engine.
    curt_total_arr = dispatch.curtailment_mwh
    curt_lost_arr = dispatch.curtailment_lost_mwh
    ons_curt_arr = dispatch.ons_curtailment_mwh
    injection_sem = generation_mw - ons_curt_arr
    injection_com = dispatch.grid_injection_mwh
    saldo_liquido_sem = (injection_sem - garantia_fisica_mw) * pld
    saldo_liquido_com = (injection_com - garantia_fisica_mw) * pld
    exposicao_sem = dispatch.deficit_mwh * pld
    exposicao_com = dispatch.residual_deficit_mwh * pld
    economia = saldo_liquido_com - saldo_liquido_sem
    gf_energy_hour_mwh = np.full(HOURS_PER_YEAR, garantia_fisica_mw, dtype=np.float64)
    valor_flat_gf = gf_energy_hour_mwh * pld
    valor_capturado_sem = injection_sem * pld
    valor_capturado_com = injection_com * pld
    modulacao_sem = valor_flat_gf - valor_capturado_sem
    modulacao_com = valor_flat_gf - valor_capturado_com
    modulacao_delta = modulacao_com - modulacao_sem
    with np.errstate(divide='ignore', invalid='ignore'):
        modulacao_sem_brl_mwh_gf = np.where(
            gf_energy_hour_mwh > 1e-10,
            modulacao_sem / gf_energy_hour_mwh,
            0.0,
        )
        modulacao_com_brl_mwh_gf = np.where(
            gf_energy_hour_mwh > 1e-10,
            modulacao_com / gf_energy_hour_mwh,
            0.0,
        )
        modulacao_delta_brl_mwh_gf = np.where(
            gf_energy_hour_mwh > 1e-10,
            modulacao_delta / gf_energy_hour_mwh,
            0.0,
        )

    spread = _compute_spread_column(dispatch.charge_mwh, dispatch.discharge_mwh, pld)

    # Curtailment recuperado = total curtailment - curtailment perdido
    curtailment_recuperado = dispatch.curtailment_recovered_mwh
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
        "geracao_solar_com_bess_mw": generation_mw,
        "geracao_solar_limitada_mw": generation_mw,
        "garantia_fisica_mw": garantia_fisica_mw,
        "energia_gf_hora_mwh": gf_energy_hour_mwh,
        "injecao_sem_bess_mwh": injection_sem,
        "injecao_com_bess_mwh": injection_com,
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
        "valor_flat_gf_hora_r": valor_flat_gf,
        "valor_capturado_sem_bess_hora_r": valor_capturado_sem,
        "valor_capturado_com_bess_hora_r": valor_capturado_com,
        "modulacao_horaria_sem_bess_r": modulacao_sem,
        "modulacao_horaria_com_bess_r": modulacao_com,
        "modulacao_horaria_delta_r": modulacao_delta,
        "modulacao_sem_bess_r_mwh_gf": modulacao_sem_brl_mwh_gf,
        "modulacao_com_bess_r_mwh_gf": modulacao_com_brl_mwh_gf,
        "modulacao_delta_r_mwh_gf": modulacao_delta_brl_mwh_gf,
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

    # Keep enough decimals for auditability. Earlier versions rounded physical
    # columns to integer MW/MWh, which made manual recalculation of saldo columns
    # appear inconsistent in Excel even when the underlying formula was correct.
    financial_cols = {
        "exposicao_sem_bess_r",
        "exposicao_com_bess_r",
        "economia_hora_r",
        "saldo_liquido_horario_sem_bess_r",
        "saldo_liquido_horario_com_bess_r",
        "valor_flat_gf_hora_r",
        "valor_capturado_sem_bess_hora_r",
        "valor_capturado_com_bess_hora_r",
        "modulacao_horaria_sem_bess_r",
        "modulacao_horaria_com_bess_r",
        "modulacao_horaria_delta_r",
        "saldo_liquido_diario_sem_bess_r",
        "saldo_liquido_diario_com_bess_r",
    }
    for col in df.select_dtypes(include="float64").columns:
        if "pld" in col:
            df[col] = df[col].round(2)
        elif col in financial_cols:
            df[col] = df[col].round(2)
        else:
            df[col] = df[col].round(3)

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
    scenario=None,
    projection=None,
    risk_metrics: dict | None = None,
) -> dict:
    """Build the summary row (line 8762) for a tab."""
    economia_anual = df["economia_hora_r"].sum()
    bess_power_mw, bess_energy_mwh, capex_brl = _scenario_values(
        scenario=scenario,
        garantia_fisica_mw=garantia_fisica_mw,
        duration_h=duration_h,
        usd_brl_rate=usd_brl_rate,
    )
    fc = df["geracao_solar_com_bess_mw"].sum() / (mwac * HOURS_PER_YEAR)

    # Spread mean (only discharge hours)
    discharge_mask = df["descarga_bess_mw"] > 1e-10
    spread_mean = df.loc[discharge_mask, "spread_r_mwh"].mean() if discharge_mask.any() else 0.0

    payback = (
        projection.payback_years
        if projection is not None
        else capex_brl / economia_anual if economia_anual > 0 else None
    )
    lcos_brl_mwh = projection.lcos_brl_per_mwh if projection is not None else None
    lifetime_discharge_mwh = projection.lifetime_discharge_mwh if projection is not None else None
    projected_calendar_years = projection.projected_calendar_years if projection is not None else None
    cycle_life_reached = projection.cycle_life_reached if projection is not None else None
    lcoe_discount_rate = projection.lcoe_discount_rate if projection is not None else None
    annual_discharge_mwh = df["descarga_bess_mw"].sum()
    ciclos_ano = annual_discharge_mwh / bess_energy_mwh if bess_energy_mwh > 1e-10 else 0.0
    ciclos_vida_util = (
        lifetime_discharge_mwh / bess_energy_mwh
        if lifetime_discharge_mwh is not None and bess_energy_mwh > 1e-10
        else ciclos_ano
    )
    anos_ciclados = ciclos_vida_util / 365.0

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
    geracao_total = df["geracao_solar_com_bess_mw"].sum()
    curtailment_pct_total = (
        curtailment_total / geracao_total * 100.0 if geracao_total > 1e-10 else 0.0
    )

    # Carga não realizada (daily concept — sum of daily missed cycles)
    carga_nao_realizada_total = 0.0
    if dispatch is not None:
        carga_nao_realizada_total = float(dispatch.carga_nao_realizada_diaria_mwh.sum())

    modo_label = _mode_label(charge_mode)
    row = {
        "data_hora": "RESUMO",
        "hora_dia": "",
        "dia_ano": "",
        "descarga_ativa": "",
        "modo_operacao": modo_label,
        "geracao_solar_com_bess_mw": round(df["geracao_solar_com_bess_mw"].sum()),
        "geracao_solar_limitada_mw": round(df["geracao_solar_limitada_mw"].sum()),
        "garantia_fisica_mw": round(garantia_fisica_mw),
        "energia_gf_hora_mwh": round(df["energia_gf_hora_mwh"].sum()),
        "bess_power_mw": round(bess_power_mw),
        "bess_energy_mwh": round(bess_energy_mwh),
        "capex_brl": round(capex_brl),
        "excesso_solar_mw": round(df["excesso_solar_mw"].sum()),
        "curtailment_mw": round(curtailment_total),
        "curtailment_pct": round(curtailment_pct_total),
        "curtailment_recuperado_mw": round(curtailment_recuperado_total),
        "curtailment_recuperado_pct": round(curtailment_recuperado_pct_total),
        "curtailment_perdido_mw": round(df["curtailment_perdido_mw"].sum()),
        "carga_bess_mw": round(df["carga_bess_mw"].sum()),
        "soc_mwh": round(df["soc_mwh"].mean()),
        "descarga_bess_mw": round(df["descarga_bess_mw"].sum()),
        "ciclos_ano": round(ciclos_ano, 3),
        "ciclos_vida_util": round(ciclos_vida_util, 3),
        "anos_ciclados": round(anos_ciclados, 6),
        "carga_nao_realizada_mwh_ano": round(carga_nao_realizada_total),
        "pld_r_mwh": round(df["pld_r_mwh"].mean(), 2),
        "deficit_sem_bess_mw": round(deficit_sem),
        "deficit_com_bess_mw": round(deficit_com),
        "exposicao_sem_bess_r": round(exp_sem),
        "exposicao_com_bess_r": round(exp_com),
        "economia_hora_r": round(economia_anual),
        "saldo_liquido_horario_sem_bess_r": round(df["saldo_liquido_horario_sem_bess_r"].sum()),
        "saldo_liquido_horario_com_bess_r": round(df["saldo_liquido_horario_com_bess_r"].sum()),
        "valor_flat_gf_hora_r": round(df["valor_flat_gf_hora_r"].sum()),
        "valor_capturado_sem_bess_hora_r": round(df["valor_capturado_sem_bess_hora_r"].sum()),
        "valor_capturado_com_bess_hora_r": round(df["valor_capturado_com_bess_hora_r"].sum()),
        "modulacao_horaria_sem_bess_r": round(df["modulacao_horaria_sem_bess_r"].sum()),
        "modulacao_horaria_com_bess_r": round(df["modulacao_horaria_com_bess_r"].sum()),
        "modulacao_horaria_delta_r": round(df["modulacao_horaria_delta_r"].sum()),
        "modulacao_sem_bess_r_mwh_gf": round(df["modulacao_horaria_sem_bess_r"].sum() / (garantia_fisica_mw * HOURS_PER_YEAR), 2),
        "modulacao_com_bess_r_mwh_gf": round(df["modulacao_horaria_com_bess_r"].sum() / (garantia_fisica_mw * HOURS_PER_YEAR), 2),
        "modulacao_delta_r_mwh_gf": round(df["modulacao_horaria_delta_r"].sum() / (garantia_fisica_mw * HOURS_PER_YEAR), 2),
        "saldo_liquido_diario_sem_bess_r": round(df["saldo_liquido_horario_sem_bess_r"].sum() / 365),
        "saldo_liquido_diario_com_bess_r": round(df["saldo_liquido_horario_com_bess_r"].sum() / 365),
        "spread_r_mwh": round(spread_mean),
        "rte": rte,
        "payback_anos": round(payback, 2) if payback is not None else "",
        "lcos_brl_mwh": round(lcos_brl_mwh, 2) if lcos_brl_mwh is not None else "",
        "taxa_retorno_lcoe": round(lcoe_discount_rate, 6) if lcoe_discount_rate is not None else "",
        "descarga_bess_mwh_vida_util": round(lifetime_discharge_mwh) if lifetime_discharge_mwh is not None else "",
        "anos_calendario_projetados": (
            round(projected_calendar_years, 3) if projected_calendar_years is not None else ""
        ),
        "vida_util_por_ciclo_atingida": (
            bool(cycle_life_reached) if cycle_life_reached is not None else ""
        ),
    }
    if risk_metrics:
        row.update({
            "var_95_sem_bess_brl_dia": round(risk_metrics["var_95_sem_bess_brl"], 2),
            "cvar_95_sem_bess_brl_dia": round(risk_metrics["cvar_95_sem_bess_brl"], 2),
            "var_95_com_bess_brl_dia": round(risk_metrics["var_95_com_bess_brl"], 2),
            "cvar_95_com_bess_brl_dia": round(risk_metrics["cvar_95_com_bess_brl"], 2),
            "risco_cvar_atendido": bool(risk_metrics["risk_constraint_met"]),
            "risco_dias_amostra": int(risk_metrics["n_days"]),
        })
    return row


def _scenario_values(
    *,
    scenario,
    garantia_fisica_mw: float,
    duration_h: int,
    usd_brl_rate: float,
) -> tuple[float, float, float]:
    """Return executed BESS power, energy, and CAPEX for report metadata."""
    if scenario is not None:
        return scenario.bess_power_mw, scenario.bess_energy_mwh, scenario.capex_brl

    import math

    block = BESS_BLOCK_SPECS[duration_h]
    n_blocks = math.ceil(garantia_fisica_mw / block.block_power_mw)
    bess_power_mw = n_blocks * block.block_power_mw
    bess_energy_mwh = n_blocks * block.block_energy_mwh
    capex_brl = bess_energy_mwh * 1000 * CAPEX_USD_PER_KWH[duration_h] * usd_brl_rate
    return bess_power_mw, bess_energy_mwh, capex_brl


def _mode_label(charge_mode: int) -> str:
    """Return the display label for the selected operation mode."""
    return (
        "Arbitragem day-ahead — pareia carga barata com descarga futura de maior PLD"
        if charge_mode == 3
        else "Cobertura de Déficit — descarrega em qualquer hora com geração < GF"
    )


def _pld_base_label(params, bq_submarket: str) -> str:
    """Return a human-readable PLD source label for the HTML report."""
    if params is None:
        return f"submercado {bq_submarket}"
    pld_path = getattr(params, "pld_path", None)
    pld_source_year = getattr(params, "pld_source_year", 2025)
    if pld_path:
        return f"{pld_path} (ano fonte {pld_source_year}, submercado {bq_submarket})"
    return (
        f"dados/pld/pld_horario_2025.csv como base 2025 para {bq_submarket}; "
        "2026 usa BigQuery observado + projecao sobre a base 2025"
    )


def _curtailment_base_label(params) -> str:
    """Return a human-readable curtailment source label for the HTML report."""
    if params is None:
        return "n/a"
    return (
        f"{getattr(params, 'curtailment_path', 'n/a')} | "
        f"aba {CURTAILMENT_SHEET_2025} | coluna {CURTAILMENT_COLUMN} | "
        "percentual ponderado por geracao limitada"
    )


def _add_excel_only_columns(
    df: pd.DataFrame,
    *,
    dispatch: DispatchResult,
    scenario,
    garantia_fisica_mw: float,
    duration_h: int,
    usd_brl_rate: float,
    rte: float,
    charge_mode: int,
) -> pd.DataFrame:
    """Add Excel-only metadata and daily missed-charge columns."""
    work = df.copy()
    bess_power_mw, bess_energy_mwh, capex_brl = _scenario_values(
        scenario=scenario,
        garantia_fisica_mw=garantia_fisica_mw,
        duration_h=duration_h,
        usd_brl_rate=usd_brl_rate,
    )

    work["modo_operacao"] = pd.NA
    work["bess_power_mw"] = np.nan
    work["bess_energy_mwh"] = np.nan
    work["capex_brl"] = np.nan
    work["rte"] = np.nan

    work.loc[0, "modo_operacao"] = _mode_label(charge_mode)
    work.loc[0, "bess_power_mw"] = round(bess_power_mw)
    work.loc[0, "bess_energy_mwh"] = round(bess_energy_mwh)
    work.loc[0, "capex_brl"] = round(capex_brl)
    work.loc[0, "rte"] = rte

    daily_missed = np.full(HOURS_PER_YEAR, np.nan)
    daily_missed[23::24] = dispatch.carga_nao_realizada_diaria_mwh
    work["carga_nao_realizada_mwh_dia"] = np.round(daily_missed, 0)
    return work


def _build_charge_diagnostics(
    results_by_key: dict[str, tuple],
    usd_brl_rate: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build charge-miss diagnostics summary and daily detail tables."""
    summary_rows: list[dict] = []
    daily_rows: list[dict] = []

    for tab_name, data in results_by_key.items():
        dispatch, pld, gf, gen, _peak_hours, duration_h, year_label = data[:7]
        rte = data[7] if len(data) > 7 else 1.0
        scenario = _scenario_from_data(data)
        projection = _projection_from_data(data)
        bess_power_mw, bess_energy_mwh, _capex_brl = _scenario_values(
            scenario=scenario,
            garantia_fisica_mw=gf,
            duration_h=duration_h,
            usd_brl_rate=usd_brl_rate,
        )

        cause_totals = {
            "sem_spread_economico_mwh": 0.0,
            "limite_potencia_ou_janela_mwh": 0.0,
            "capacidade_nao_economica_mwh": 0.0,
        }
        bottleneck_totals = {
            "gargalo_potencia_carga_mwh": 0.0,
            "gargalo_janela_descarga_mwh": 0.0,
            "potencial_extensao_d1_ate_05_mwh": 0.0,
            "potencial_extensao_d1_total_mwh": 0.0,
        }
        days_with_miss = 0

        for day in range(365):
            start = day * 24
            stop = start + 24
            next_start = stop
            next_stop = min(next_start + 24, HOURS_PER_YEAR)
            day_discharge = float(dispatch.discharge_mwh[start:stop].sum())
            missed_mwh = max(0.0, bess_energy_mwh - day_discharge)
            if missed_mwh <= 1e-9:
                continue

            days_with_miss += 1
            day_pld = pld[start:stop]
            day_gen = gen[start:stop]
            day_curt = dispatch.curtailment_mwh[start:stop]
            day_charge = dispatch.charge_mwh[start:stop]
            day_dis = dispatch.discharge_mwh[start:stop]
            next_day_pld = pld[next_start:next_stop]
            next_day_curt = dispatch.curtailment_mwh[next_start:next_stop]

            cause, metrics = _classify_daily_charge_miss(
                missed_mwh=missed_mwh,
                rte=float(rte),
                bess_energy_mwh=bess_energy_mwh,
                bess_power_mw=bess_power_mw,
                day_pld=day_pld,
                day_gen=day_gen,
                day_curt=day_curt,
                day_charge=day_charge,
                day_discharge=day_dis,
                next_day_pld=next_day_pld,
                next_day_curt=next_day_curt,
            )
            cause_totals[cause] += missed_mwh
            for key in bottleneck_totals:
                bottleneck_totals[key] += float(metrics[key])
            daily_rows.append({
                "cenario": tab_name,
                "ano": year_label,
                "dia_ano": day + 1,
                "carga_nao_realizada_mwh_dia": round(missed_mwh, 3),
                "descarga_bess_mwh_dia": round(day_discharge, 3),
                "causa_dominante": cause.replace("_mwh", ""),
                **metrics,
            })

        total_generation = float(np.sum(gen))
        total_curtailment = float(np.sum(dispatch.curtailment_mwh))
        recovered_curtailment = float(np.sum(dispatch.curtailment_mwh - dispatch.curtailment_lost_mwh))
        total_missed = sum(cause_totals.values())
        theoretical_cycle = bess_energy_mwh * 365.0
        annual_discharge_mwh = float(np.sum(dispatch.discharge_mwh))
        ciclos_ano = annual_discharge_mwh / bess_energy_mwh if bess_energy_mwh > 1e-9 else 0.0
        lifetime_discharge_mwh = (
            projection.lifetime_discharge_mwh
            if projection is not None and projection.lifetime_discharge_mwh is not None
            else annual_discharge_mwh
        )
        projected_calendar_years = projection.projected_calendar_years if projection is not None else None
        cycle_life_reached = projection.cycle_life_reached if projection is not None else None
        ciclos_vida_util = lifetime_discharge_mwh / bess_energy_mwh if bess_energy_mwh > 1e-9 else 0.0

        summary_rows.append({
            "cenario": tab_name,
            "ano": year_label,
            "duration_h": duration_h,
            "bess_power_mw": round(bess_power_mw, 3),
            "bess_energy_mwh": round(bess_energy_mwh, 3),
            "descarga_bess_mwh_ano": round(annual_discharge_mwh, 3),
            "ciclos_ano": round(ciclos_ano, 3),
            "ciclos_vida_util": round(ciclos_vida_util, 3),
            "anos_ciclados": round(ciclos_vida_util / 365.0, 6),
            "anos_calendario_projetados": (
                round(projected_calendar_years, 3) if projected_calendar_years is not None else ""
            ),
            "vida_util_por_ciclo_atingida": (
                bool(cycle_life_reached) if cycle_life_reached is not None else ""
            ),
            "carga_nao_realizada_mwh_ano": round(total_missed, 3),
            "carga_nao_realizada_pct_ciclo_teorico": round(
                total_missed / theoretical_cycle * 100.0 if theoretical_cycle > 1e-9 else 0.0, 3
            ),
            "dias_com_carga_nao_realizada": days_with_miss,
            **{key: round(value, 3) for key, value in cause_totals.items()},
            **{key: round(value, 3) for key, value in bottleneck_totals.items()},
            "curtailment_considerado_mwh": round(total_curtailment, 3),
            "curtailment_pct_geracao": round(
                total_curtailment / total_generation * 100.0 if total_generation > 1e-9 else 0.0, 3
            ),
            "curtailment_recuperado_mwh": round(recovered_curtailment, 3),
            "curtailment_recuperado_pct": round(
                recovered_curtailment / total_curtailment * 100.0 if total_curtailment > 1e-9 else 0.0, 3
            ),
        })

    return pd.DataFrame(summary_rows), pd.DataFrame(daily_rows)


def _classify_daily_charge_miss(
    *,
    missed_mwh: float,
    rte: float,
    bess_energy_mwh: float,
    bess_power_mw: float,
    day_pld: np.ndarray,
    day_gen: np.ndarray,
    day_curt: np.ndarray,
    day_charge: np.ndarray,
    day_discharge: np.ndarray,
    next_day_pld: np.ndarray,
    next_day_curt: np.ndarray,
) -> tuple[str, dict]:
    """Classify the dominant reason why a day did not complete a full BESS cycle."""
    charge_power_mw = bess_power_mw
    profitable_charge_input = 0.0
    charge_power_spill_input = 0.0
    profitable_discharge_slots: set[int] = set()
    d1_until_05_input = 0.0
    d1_total_input = 0.0

    for charge_h in range(5, 24):
        raw_available_charge = max(0.0, float(day_gen[charge_h] + day_curt[charge_h]))
        available_charge = min(charge_power_mw, raw_available_charge)
        future_profitable = [
            discharge_h for discharge_h in range(charge_h + 1, 24)
            if float(day_curt[discharge_h]) <= 1e-10
            and rte * float(day_pld[discharge_h]) > float(day_pld[charge_h])
        ]
        if future_profitable:
            profitable_charge_input += available_charge
            profitable_discharge_slots.update(future_profitable)
            charge_power_spill_input += max(0.0, raw_available_charge - charge_power_mw)
        elif len(next_day_pld) > 0:
            d1_profitable = [
                h for h in range(len(next_day_pld))
                if float(next_day_curt[h]) <= 1e-10
                and rte * float(next_day_pld[h]) > float(day_pld[charge_h])
            ]
            if d1_profitable:
                d1_total_input += available_charge
                if any(h < 5 for h in d1_profitable):
                    d1_until_05_input += available_charge

    profitable_output = profitable_charge_input * rte
    discharge_window_output = len(profitable_discharge_slots) * bess_power_mw
    charge_power_spill_output = charge_power_spill_input * rte
    discharge_window_gap = max(0.0, profitable_output - discharge_window_output)
    d1_until_05_output = d1_until_05_input * rte
    d1_total_output = d1_total_input * rte

    if profitable_output <= 1e-9:
        cause = "sem_spread_economico_mwh"
    elif min(profitable_output, discharge_window_output) + 1e-9 < bess_energy_mwh:
        cause = "limite_potencia_ou_janela_mwh"
    else:
        cause = "capacidade_nao_economica_mwh"

    metrics = {
        "energia_economica_carregavel_mwh_dia": round(profitable_output, 3),
        "janela_descarga_economica_mwh_dia": round(discharge_window_output, 3),
        "gargalo_potencia_carga_mwh": round(charge_power_spill_output, 3),
        "gargalo_janela_descarga_mwh": round(discharge_window_gap, 3),
        "potencial_extensao_d1_ate_05_mwh": round(d1_until_05_output, 3),
        "potencial_extensao_d1_total_mwh": round(d1_total_output, 3),
        "horas_descarga_economicas_qtd": len(profitable_discharge_slots),
        "carga_bess_mwh_dia": round(float(np.sum(day_charge)), 3),
        "descarga_max_horaria_mwh": round(float(np.max(day_discharge)), 3),
        "pld_min_dia": round(float(np.min(day_pld)), 2),
        "pld_max_dia": round(float(np.max(day_pld)), 2),
    }
    return cause, metrics


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
            scenario = _scenario_from_data(data)
            projection = _projection_from_data(data)
            risk_metrics = _risk_from_data(data)

            df = _build_hourly_dataframe(dispatch, pld, gf, gen, peak_hours, year_label)
            excel_df = _add_excel_only_columns(
                df,
                dispatch=dispatch,
                scenario=scenario,
                garantia_fisica_mw=gf,
                duration_h=duration_h,
                usd_brl_rate=usd_brl_rate,
                rte=rte,
                charge_mode=charge_mode,
            )
            summary = _build_summary_row(
                df, gf, duration_h, usd_brl_rate, mwac,
                rte=rte, dispatch=dispatch, charge_mode=charge_mode, scenario=scenario,
                projection=projection, risk_metrics=risk_metrics,
            )
            for metadata_col in ("modo_operacao", "bess_power_mw", "bess_energy_mwh", "capex_brl", "rte"):
                summary[metadata_col] = ""
            summary.pop("carga_nao_realizada_mwh_ano", None)
            summary["carga_nao_realizada_mwh_dia"] = ""
            summary_df = pd.DataFrame([summary])
            full_df = pd.concat([excel_df, summary_df], ignore_index=True)

            full_df.to_excel(writer, sheet_name=tab_name, index=False, freeze_panes=(1, 0))

        diagnostics_summary, diagnostics_daily = _build_charge_diagnostics(
            results_by_key,
            usd_brl_rate=usd_brl_rate,
        )
        diagnostics_summary.to_excel(writer, sheet_name="diagnostico_carga", index=False)
        diagnostics_daily.to_excel(writer, sheet_name="diagnostico_diario", index=False)

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
    params=None,
) -> str:
    """Build a self-contained HTML report with one section per backtest tab."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict] = []
    float_formatter = lambda x: f"{x:,.4f}"

    for tab_name, data in results_by_key.items():
        dispatch, pld, gf, gen, peak_hours, duration_h, year_label = data[:7]
        rte = data[7] if len(data) > 7 else 1.0
        scenario = _scenario_from_data(data)
        projection = _projection_from_data(data)
        risk_metrics = _risk_from_data(data)
        df = _build_hourly_dataframe(dispatch, pld, gf, gen, peak_hours, year_label)
        summary = _build_summary_row(
            df, gf, duration_h, usd_brl_rate, mwac,
            rte=rte, dispatch=dispatch, charge_mode=charge_mode, scenario=scenario,
            projection=projection, risk_metrics=risk_metrics,
        )
        summary["cenario"] = tab_name
        summary["capex_usd_kwh"] = CAPEX_USD_PER_KWH[duration_h]
        summary_rows.append(summary)



    summary_df = pd.DataFrame(summary_rows)
    preferred = [
        "cenario", "modo_operacao", "geracao_solar_com_bess_mw", "geracao_solar_limitada_mw",
        "garantia_fisica_mw", "energia_gf_hora_mwh", "capex_usd_kwh",
        "bess_power_mw", "bess_energy_mwh", "capex_brl",
        "injecao_sem_bess_mwh", "injecao_com_bess_mwh",
        "excesso_solar_mw", "curtailment_mw", "curtailment_pct",
        "curtailment_recuperado_mw", "curtailment_recuperado_pct", "curtailment_perdido_mw",
        "carga_bess_mw", "descarga_bess_mw", "ciclos_ano", "ciclos_vida_util", "anos_ciclados",
        "carga_nao_realizada_mwh_ano",
        "pld_r_mwh",
        "deficit_sem_bess_mw", "deficit_com_bess_mw",
        "exposicao_sem_bess_r", "exposicao_com_bess_r",
        "saldo_liquido_horario_sem_bess_r", "saldo_liquido_horario_com_bess_r",
        "valor_flat_gf_hora_r",
        "valor_capturado_sem_bess_hora_r", "valor_capturado_com_bess_hora_r",
        "modulacao_horaria_sem_bess_r", "modulacao_horaria_com_bess_r",
        "modulacao_horaria_delta_r",
        "modulacao_sem_bess_r_mwh_gf", "modulacao_com_bess_r_mwh_gf",
        "modulacao_delta_r_mwh_gf",
        "saldo_liquido_diario_sem_bess_r", "saldo_liquido_diario_com_bess_r",
        "economia_hora_r", "spread_r_mwh", "rte",
        "payback_anos", "lcos_brl_mwh", "taxa_retorno_lcoe", "descarga_bess_mwh_vida_util",
        "anos_calendario_projetados", "vida_util_por_ciclo_atingida",
        "var_95_sem_bess_brl_dia", "cvar_95_sem_bess_brl_dia",
        "var_95_com_bess_brl_dia", "cvar_95_com_bess_brl_dia",
        "risco_cvar_atendido", "risco_dias_amostra",
    ]
    summary_df = summary_df[[c for c in preferred if c in summary_df.columns]]

    rte_html = ""
    if rte_metadata:
        rte_html = "".join(
            f"<li><strong>{escape(str(k))}:</strong> {escape(str(v))}</li>"
            for k, v in rte_metadata.items()
        )

    charge_mode_label = (
        "Arbitragem day-ahead — pareia carga barata com descarga futura de maior PLD"
        if charge_mode == 3
        else "Cobertura de Déficit — descarrega em qualquer hora com geração < GF"
    )
    pld_base = _pld_base_label(params, bq_submarket)
    curtailment_base = _curtailment_base_label(params)
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
.note {{ max-width: 960px; line-height: 1.45; }}
</style>
</head>
<body>
<h1>Backtest Solar + BESS</h1>
<section class="note">
<h2>Premissas do Run</h2>
<ul>
<li><strong>Submercado PLD:</strong> {escape(bq_submarket)}</li>
<li><strong>Base PLD:</strong> {escape(pld_base)}</li>
<li><strong>Base curtailment ONS:</strong> {escape(curtailment_base)}</li>
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
<!-- series horarias removidas — disponíveis no Excel -->
</body>
</html>"""

    output_path.write_text(html, encoding="utf-8")
    return str(output_path)
