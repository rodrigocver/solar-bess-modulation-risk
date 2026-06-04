"""Interactive CLI parameter prompting loop (v2 — Garantia Física model).

Functions
---------
run_session(service_account_path=None) -> SimulationParams
"""

from __future__ import annotations

import os

from solar_bess_risk.config import (
    CURTAILMENT_ASSUMPTION_PCT_2026,
    DEFAULT_BQ_SUBMARKET,
    DEFAULT_BESS_O_AND_M_PCT_CAPEX,
    DEFAULT_CURTAILMENT_FACTOR_2026,
    DEFAULT_LCOE_DISCOUNT_RATE,
    DEFAULT_PLD_FACTOR_2026,
    DEFAULT_RTE_PATH,
    DEFAULT_USD_BRL_RATE,
    DEFAULT_USEFUL_LIFE_YR,
    HOURS_PER_YEAR,
    PARAM_BOUNDS,
    VALID_BQ_SUBMARKETS,
    SimulationParams,
)
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.rte import load_rte_table

# ── Defaults fixos do projeto padrão ──────────────────────────────────────────
DEFAULT_CSV_PATH = "solar/solar_getulina_ii_m8_450mw_id5.csv"
DEFAULT_MWAC = 450.0
# ──────────────────────────────────────────────────────────────────────────────


def _prompt_float(label: str, unit: str, default: float, lo: float, hi: float) -> float:
    """Prompt for a float value with bounds validation."""
    while True:
        raw = input(f"  {label} [{unit}] (padrão {default}): ").strip()
        if raw == "":
            return default
        try:
            val = float(raw)
        except ValueError:
            print(
                f"  ERRO: Parâmetro '{label}': valor '{raw}' não é numérico. "
                f"Intervalo aceito: [{lo}, {hi}] {unit}."
            )
            continue
        if not (lo <= val <= hi):
            print(
                f"  ERRO: Parâmetro '{label}': valor {val} {unit} "
                f"fora do intervalo [{lo}, {hi}] {unit}; re-enter."
            )
            continue
        return val


def _prompt_int(label: str, unit: str, default: int, lo: int, hi: int) -> int:
    """Prompt for an integer value with bounds validation."""
    while True:
        raw = input(f"  {label} [{unit}] (padrão {default}): ").strip()
        if raw == "":
            return default
        try:
            val = int(raw)
        except ValueError:
            print(
                f"  ERRO: Parâmetro '{label}': valor '{raw}' não é inteiro. "
                f"Intervalo aceito: [{lo}, {hi}] {unit}."
            )
            continue
        if not (lo <= val <= hi):
            print(
                f"  ERRO: Parâmetro '{label}': valor {val} {unit} "
                f"fora do intervalo [{lo}, {hi}] {unit}; re-enter."
            )
            continue
        return val


def _prompt_submarket(default: str = DEFAULT_BQ_SUBMARKET) -> str:
    """Prompt for CCEE submarket selection."""
    choices = "/".join(sorted(VALID_BQ_SUBMARKETS))
    while True:
        raw = input(f"  Submercado BQ [{choices}] (padrão {default}): ").strip()
        if raw == "":
            return default
        if raw.upper() in VALID_BQ_SUBMARKETS:
            return raw.upper()
        print(f"  ERRO: Submercado inválido '{raw}'. Opções: {choices}.")


def _prompt_csv_path(default: str = DEFAULT_CSV_PATH) -> str:
    """Prompt for solar CSV file path.

    Defaults to the configured project CSV path.
    Enter sem digitar aceita o default.
    """
    while True:
        raw = input(f"  Caminho do CSV solar (padrão: {default}): ").strip()
        path = raw if raw else default
        if not os.path.isfile(path):
            print(f"  ERRO: Arquivo '{path}' não encontrado.")
            continue
        return path


def _prompt_mwac(default: float = DEFAULT_MWAC) -> float:
    """Prompt for plant AC capacity.

    Defaults to the configured project MWac. Enter sem digitar aceita o default.
    """
    lo, hi = PARAM_BOUNDS["mwac"]
    while True:
        raw = input(f"  Capacidade MWac (padrão: {default}): ").strip()
        if not raw:
            return default
        try:
            val = float(raw)
        except ValueError:
            print(
                f"  ERRO: Parâmetro 'MWac': valor '{raw}' não é numérico. "
                f"Intervalo aceito: [{lo}, {hi}] MW."
            )
            continue
        if not (lo <= val <= hi):
            print(
                f"  ERRO: Parâmetro 'MWac': valor {val} MW "
                f"fora do intervalo [{lo}, {hi}] MW; re-enter."
            )
            continue
        return val


def _prompt_curtailment() -> bool:
    """Prompt whether to include curtailment analysis."""
    raw = input("  Deseja incluir análise de curtailment? [s/N]: ").strip().lower()
    return raw in ("s", "sim", "y", "yes")


def _prompt_charge_mode() -> int:
    """Prompt for BESS dispatch mode with clear explanation of each option."""
    print()
    print("  Modo de operação do BESS:")
    print()
    print("    [0] Cobertura de Déficit")
    print("        O BESS descarrega em qualquer hora onde a geração < Garantia Física,")
    print("        sem considerar o PLD da hora. Prioriza cobrir a GF em todas as horas")
    print("        de déficit, inclusive as mais baratas.")
    print()
    print("    [3] Arbitragem de Preço  (Recomendado)")
    print("        O BESS otimiza carga e descarga no horizonte day-ahead,")
    print("        pareando carga barata com descarga futura mais valiosa.")
    print("        Permite venda acima da GF quando isso melhora o saldo líquido.")
    print()
    while True:
        raw = input("  Selecione o modo [0/3] (padrão: 3): ").strip()
        if raw == "" or raw == "3":
            return 3
        if raw == "0":
            return 0
        print("  ERRO: opção inválida. Digite 0 ou 3.")


def _prompt_rte_path(default: str = DEFAULT_RTE_PATH) -> str:
    """Prompt for RTE Excel file path (confirmation of default)."""
    raw = input(f"  Caminho do arquivo RTE (padrão: {default}): ").strip()
    return raw if raw else default


def run_session(service_account_path: str | None = None) -> tuple:
    """Run the full interactive parameter collection session.

    Returns
    -------
    tuple[SimulationParams, bool, str, int]
        Parameters, whether curtailment is enabled, RTE file path, and charge_mode.
    """
    # 0. Curtailment prompt (first, per spec §8.1)
    curtailment_enabled = _prompt_curtailment()

    # 0b. BESS dispatch mode
    charge_mode = _prompt_charge_mode()

    # 1. CSV path — project default
    csv_path = _prompt_csv_path()

    # 2. MWac — project default
    mwac = _prompt_mwac()

    # Carrega e valida CSV imediatamente para mostrar fc/garantia_fisica
    try:
        profile = load_solar_csv(csv_path, mwac)
    except (ValueError, RuntimeError) as exc:
        print(f"  ERRO: {exc}")
        while True:
            csv_path = _prompt_csv_path()
            mwac = _prompt_mwac()
            try:
                profile = load_solar_csv(csv_path, mwac)
                break
            except (ValueError, RuntimeError) as exc2:
                print(f"  ERRO: {exc2}")

    # 3. Parâmetros opcionais com defaults
    bq_submarket = _prompt_submarket()
    rate_lo, rate_hi = PARAM_BOUNDS["usd_brl_rate"]
    usd_brl = _prompt_float("Taxa de câmbio USD/BRL", "BRL/USD", DEFAULT_USD_BRL_RATE, rate_lo, rate_hi)
    rte_path = _prompt_rte_path()
    life_lo, life_hi = int(PARAM_BOUNDS["useful_life_years"][0]), int(PARAM_BOUNDS["useful_life_years"][1])
    useful_life = _prompt_int("Vida útil", "anos", DEFAULT_USEFUL_LIFE_YR, life_lo, life_hi)
    om_lo, om_hi = PARAM_BOUNDS["bess_o_and_m_pct_capex"]
    bess_om = _prompt_float(
        "O&M anual BESS",
        "fração do CAPEX",
        DEFAULT_BESS_O_AND_M_PCT_CAPEX,
        om_lo,
        om_hi,
    )
    lcoe_lo, lcoe_hi = PARAM_BOUNDS["lcoe_discount_rate"]
    lcoe_discount_rate = _prompt_float(
        "Taxa de retorno para LCOS/LCOE",
        "fração/ano",
        DEFAULT_LCOE_DISCOUNT_RATE,
        lcoe_lo,
        lcoe_hi,
    )

    # 4. Fatores de preenchimento de dados de 2026
    print()
    print("  ── Fatores para preenchimento de 2026 ──")
    print("  (Enter = usar default; 0 = usar valor do campo)")
    pld_lo, pld_hi = PARAM_BOUNDS["pld_factor_2026"]
    raw_pld_factor = input(
        f"  Fator PLD 2026 (multiplica base 2025; Enter = auto via BigQuery): "
    ).strip()
    if raw_pld_factor == "":
        pld_factor_2026: float | None = DEFAULT_PLD_FACTOR_2026
    else:
        try:
            v = float(raw_pld_factor)
        except ValueError:
            print(f"  ERRO: valor '{raw_pld_factor}' não é numérico; usando auto.")
            pld_factor_2026 = DEFAULT_PLD_FACTOR_2026
        else:
            if not (pld_lo <= v <= pld_hi):
                print(f"  ERRO: fator {v} fora de [{pld_lo}, {pld_hi}]; usando auto.")
                pld_factor_2026 = DEFAULT_PLD_FACTOR_2026
            else:
                pld_factor_2026 = v

    curt_lo, curt_hi = PARAM_BOUNDS["curtailment_factor_2026"]
    curtailment_factor_2026 = _prompt_float(
        "Fator curtailment 2026 (multiplica perfil previsao_futura)",
        "fração",
        DEFAULT_CURTAILMENT_FACTOR_2026,
        curt_lo,
        curt_hi,
    )

    # Load RTE table for summary display (best-effort)
    rte_preview: dict[int, float] = {}
    try:
        rte_preview = load_rte_table(rte_path)
    except (FileNotFoundError, ValueError):
        pass

    # Resumo antes de rodar
    print("\n  ━━━ Resumo dos Parâmetros ━━━")
    print(f"  CSV:              {csv_path}")
    print(f"  MWac:             {mwac}")
    print(f"  fc:               {profile.fc:.4f}")
    print(f"  Garantia Física:  {profile.garantia_fisica_mw:.2f} MW")
    print(f"  Submercado:       {bq_submarket}")
    print(f"  USD/BRL:          {usd_brl}")
    print(f"  Curtailment:      {'Ativado' if curtailment_enabled else 'Desativado'}")
    modo_label = "Arbitragem de PLD (modo 3)" if charge_mode == 3 else "Cobertura de Déficit (modo 0)"
    print(f"  Modo BESS:        {modo_label}")
    print(f"  Arquivo RTE:      {rte_path}")
    if rte_preview:
        first_yr = min(rte_preview)
        last_yr = max(rte_preview)
        print(
            f"  RTE por ano:      {first_yr}={rte_preview[first_yr]:.4f} ... "
            f"{last_yr}={rte_preview[last_yr]:.4f} ({len(rte_preview)} anos)"
        )
    else:
        print("  RTE por ano:      não carregado (fallback params)")
    print(f"  Vida útil:        {useful_life} anos")
    print(f"  O&M anual BESS:   {bess_om:.1%} do CAPEX")
    print(f"  Taxa LCOS/LCOE:   {lcoe_discount_rate:.1%} ao ano")
    if pld_factor_2026 is not None:
        print(f"  Fator PLD 2026:   {pld_factor_2026:.4f} (manual)")
    else:
        print("  Fator PLD 2026:   auto (BigQuery)")
    print(f"  Fator Curt. 2026: {curtailment_factor_2026:.4f}")
    print(f"  Premissa curt. 2026: {CURTAILMENT_ASSUMPTION_PCT_2026:.1f} (fator planilha previsao_futura)")

    params = SimulationParams(
        csv_path=csv_path,
        mwac=mwac,
        bq_submarket=bq_submarket,
        usd_brl_rate=usd_brl,
        useful_life_years=useful_life,
        bess_o_and_m_pct_capex=bess_om,
        lcoe_discount_rate=lcoe_discount_rate,
        bq_service_account_path=service_account_path,
        pld_factor_2026=pld_factor_2026,
        curtailment_factor_2026=curtailment_factor_2026,
    )
    return params, curtailment_enabled, rte_path, charge_mode
