"""Interactive CLI parameter prompting loop (v2 — Garantia Física model).

Functions
---------
run_session(service_account_path=None) -> SimulationParams
"""

from __future__ import annotations

import os

from solar_bess_risk.config import (
    DEFAULT_BQ_SUBMARKET,
    DEFAULT_BESS_O_AND_M_PCT_CAPEX,
    DEFAULT_CURTAILMENT_FACTOR_2026,
    DEFAULT_CURTAILMENT_PATH,
    DEFAULT_CURTAILMENT_TARGET_PCT_2025,
    DEFAULT_CURTAILMENT_TARGET_PCT_2026,
    DEFAULT_LCOE_DISCOUNT_RATE,
    DEFAULT_MODULATION_MODE,
    DEFAULT_PLD_FACTOR_2026,
    DEFAULT_RTE_PATH,
    DEFAULT_USD_BRL_RATE,
    DEFAULT_USEFUL_LIFE_YR,
    HOURS_PER_YEAR,
    MODULATION_MODE_ENERGIA,
    MODULATION_MODE_GARANTIA_FISICA,
    PARAM_BOUNDS,
    VALID_BQ_SUBMARKETS,
    SimulationParams,
)
from solar_bess_risk.profile import load_solar_csv
from solar_bess_risk.rte import load_rte_table

# ── Defaults fixos do projeto padrão ──────────────────────────────────────────
DEFAULT_CSV_PATH = "solar/solar_baguacu_m2_600mw_id8.csv"
DEFAULT_MWAC = 600.0
# Cobertura diária da GF sugerida na CLI.
DEFAULT_CLI_GF_DAILY_COVERAGE_PCT = 0.15
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


def _prompt_coverage_target() -> float | None:
    """Prompt for the desired GF daily coverage target.

    Returns
    -------
    float | None
        Target coverage as a fraction (e.g. 0.5 for 50%). Defaults to the project
        standard (20%) when the user just presses Enter. Accepts a percentage
        value (0-200).
    """
    lo, hi = PARAM_BOUNDS["gf_daily_coverage_target_pct"]
    while True:
        raw = input(
            "  Cobertura diaria da GF desejada [%] "
            f"(padrão {DEFAULT_CLI_GF_DAILY_COVERAGE_PCT * 100:.0f}%): "
        ).strip()
        if raw == "":
            return DEFAULT_CLI_GF_DAILY_COVERAGE_PCT
        try:
            pct = float(raw.replace(",", "."))
        except ValueError:
            print(f"  ERRO: valor '{raw}' nao e numerico.")
            continue
        frac = pct / 100.0
        if not (lo <= frac <= hi):
            print(f"  ERRO: {pct}% fora de [{lo*100:.0f}%, {hi*100:.0f}%].")
            continue
        return frac


DEFAULT_P90_YEAR20_MWMED: float = 155.0


def _prompt_p90_year20(default: float = DEFAULT_P90_YEAR20_MWMED) -> float:
    """Prompt for the P90 of year 20 (flat PPA contract volume in MWmed)."""
    while True:
        try:
            raw = input(
                f"  P90 do ano 20 do PPA (volume flat do contrato) "
                f"[MWmed] (padrão {default:.1f}): "
            ).strip().replace(",", ".")
        except EOFError:
            return default
        if raw == "":
            return default
        try:
            value = float(raw)
        except ValueError:
            print(f"  ERRO: '{raw}' não é um número válido.")
            continue
        if value <= 0:
            print("  ERRO: o valor deve ser maior que zero.")
            continue
        return value


def _prompt_rte_path(default: str = DEFAULT_RTE_PATH) -> str:
    """Prompt for RTE Excel file path (confirmation of default)."""
    raw = input(f"  Caminho do arquivo RTE (padrão: {default}): ").strip()
    return raw if raw else default


def _prompt_curtailment_path(default: str = DEFAULT_CURTAILMENT_PATH) -> str:
    """Prompt for curtailment curve file path."""
    while True:
        try:
            raw = input(f"  Caminho da curva de curtailment (padrão: {default}): ").strip()
        except (EOFError, StopIteration):
            return default
        path = raw if raw else default
        if not os.path.isfile(path):
            print(f"  ERRO: Arquivo '{path}' não encontrado.")
            continue
        return path


def _prompt_modulation_mode(default: str = DEFAULT_MODULATION_MODE) -> str:
    """Prompt for how the modulação metric is computed.

    Returns
    -------
    str
        ``MODULATION_MODE_ENERGIA`` or ``MODULATION_MODE_GARANTIA_FISICA``.
        Defaults to ``default`` when the user just presses Enter.
    """
    print()
    print("  Cálculo da modulação:")
    print()
    print("    [energia] Prêmio de Captura por Energia  (Recomendado)")
    print("        Modulação ponderada pela energia injetada:")
    print("        Σ(injeção × PLD) / Σ(injeção) − PLD_médio.")
    print("        Sinal: positivo = bom (captura acima da média).")
    print()
    print("    [gf] Custo de Modulação pela Garantia Física")
    print("        Referênciado à obrigação de entrega (GF):")
    print("        PLD_médio − Σ(injeção × PLD) / energia_GF.")
    print("        Sinal: positivo = custo (captura abaixo da média).")
    print()
    default_label = "energia" if default == MODULATION_MODE_ENERGIA else "gf"
    while True:
        raw = input(f"  Selecione o modo [energia/gf] (padrão: {default_label}): ").strip().lower()
        if raw == "":
            return default
        if raw in ("energia", "e"):
            return MODULATION_MODE_ENERGIA
        if raw in ("gf", "garantia", "garantia_fisica"):
            return MODULATION_MODE_GARANTIA_FISICA
        print("  ERRO: opção inválida. Digite 'energia' ou 'gf'.")


def run_session(service_account_path: str | None = None) -> tuple:
    """Run the streamlined interactive parameter collection session.

    Only three questions are asked interactively: (1) solar CSV path,
    (2) target ONS curtailment for 2025, and (3) desired GF daily coverage.
    Every other parameter is shown as a defaults block and accepted with a
    single confirmation (``Seguir com o padrão? [S/n]``). Answering ``n`` falls
    back to per-parameter prompts for the remaining defaults.

    Returns
    -------
    tuple[SimulationParams, bool, str, int]
        Parameters, whether curtailment is enabled, RTE file path, and charge_mode.
    """
    # ── Pergunta 1: caminho do CSV solar ─────────────────────────────────────
    csv_path = _prompt_csv_path()

    # ── Pergunta 2: curtailment ONS alvo (2025) ──────────────────────────────
    # Curtailment fica sempre ativado; a série realizada de 2025 é escalada para
    # atingir este alvo (o fator vs 2025 é calculado depois de carregar o solar).
    curtailment_enabled = True
    ct_lo, ct_hi = PARAM_BOUNDS["curtailment_target_pct_2025"]
    curtailment_target_pct_2025 = _prompt_float(
        "Curtailment ONS alvo",
        "% da geração",
        DEFAULT_CURTAILMENT_TARGET_PCT_2025,
        ct_lo,
        ct_hi,
    )

    # ── Pergunta 3: cobertura diária da GF desejada ──────────────────────────
    print()
    print("  ── Dimensionamento do BESS ──")
    gf_daily_coverage_target_pct = _prompt_coverage_target()

    # ── Pergunta 4: P90 do ano 20 (volume flat do PPA) ───────────────────────
    print()
    print("  ── Contrato PPA ──")
    p90_year20_mwmed = _prompt_p90_year20()

    # ── Defaults do projeto padrão (apresentados de uma vez) ─────────────────
    mwac = DEFAULT_MWAC
    bq_submarket = DEFAULT_BQ_SUBMARKET
    usd_brl = DEFAULT_USD_BRL_RATE
    rte_path = DEFAULT_RTE_PATH
    curtailment_path = DEFAULT_CURTAILMENT_PATH
    useful_life = DEFAULT_USEFUL_LIFE_YR
    bess_om = DEFAULT_BESS_O_AND_M_PCT_CAPEX
    lcoe_discount_rate = DEFAULT_LCOE_DISCOUNT_RATE
    charge_mode = 3
    pld_factor_2026 = DEFAULT_PLD_FACTOR_2026
    curtailment_factor_2026 = DEFAULT_CURTAILMENT_FACTOR_2026
    curtailment_target_pct_2026 = DEFAULT_CURTAILMENT_TARGET_PCT_2026
    modulation_mode = DEFAULT_MODULATION_MODE

    print("\n  ━━━ Demais parâmetros (padrão do projeto) ━━━")
    print(f"  Capacidade MWac:       {mwac:.0f}")
    print(f"  Submercado BQ:         {bq_submarket}")
    print(f"  Taxa câmbio USD/BRL:   {usd_brl}")
    print(f"  Arquivo RTE:           {rte_path}")
    print(f"  Curva curtailment:     {curtailment_path}")
    print(f"  Vida útil:             {useful_life} anos")
    print(f"  O&M anual BESS:        {bess_om:.2%} do CAPEX")
    print(f"  Taxa LCOS/LCOE:        {lcoe_discount_rate:.1%} ao ano")
    print("  Modo BESS:             Arbitragem de PLD (modo 3)")
    modul_label = "Energia (prêmio de captura)" if modulation_mode == MODULATION_MODE_ENERGIA else "Garantia física (custo)"
    print(f"  Cálculo modulação:     {modul_label}")
    print(f"  Curtailment alvo 2026: {curtailment_target_pct_2026:.0f}% da geração")

    aceitar = input("\n  Seguir com o padrão? [S/n]: ").strip().lower()
    if aceitar in ("n", "nao", "não", "no"):
        print("\n  ── Ajuste dos parâmetros ──")
        mwac = _prompt_mwac(mwac)
        bq_submarket = _prompt_submarket(bq_submarket)
        rate_lo, rate_hi = PARAM_BOUNDS["usd_brl_rate"]
        usd_brl = _prompt_float("Taxa de câmbio USD/BRL", "BRL/USD", usd_brl, rate_lo, rate_hi)
        rte_path = _prompt_rte_path(rte_path)
        life_lo, life_hi = int(PARAM_BOUNDS["useful_life_years"][0]), int(PARAM_BOUNDS["useful_life_years"][1])
        useful_life = _prompt_int("Vida útil", "anos", useful_life, life_lo, life_hi)
        om_lo, om_hi = PARAM_BOUNDS["bess_o_and_m_pct_capex"]
        bess_om = _prompt_float("O&M anual BESS", "fração do CAPEX", bess_om, om_lo, om_hi)
        lcoe_lo, lcoe_hi = PARAM_BOUNDS["lcoe_discount_rate"]
        lcoe_discount_rate = _prompt_float(
            "Taxa de retorno para LCOS/LCOE", "fração/ano", lcoe_discount_rate, lcoe_lo, lcoe_hi
        )
        charge_mode = _prompt_charge_mode()
        modulation_mode = _prompt_modulation_mode(modulation_mode)
        ct26_lo, ct26_hi = PARAM_BOUNDS["curtailment_target_pct_2026"]
        curtailment_target_pct_2026 = _prompt_float(
            "Curtailment ONS alvo 2026", "% da geração",
            curtailment_target_pct_2026, ct26_lo, ct26_hi,
        )
        curtailment_path = _prompt_curtailment_path(curtailment_path)

    # Carrega e valida CSV imediatamente para mostrar fc/garantia_fisica
    try:
        profile = load_solar_csv(csv_path, mwac)
    except (ValueError, RuntimeError) as exc:
        print(f"  ERRO: {exc}")
        while True:
            csv_path = _prompt_csv_path()
            mwac = _prompt_mwac(mwac)
            try:
                profile = load_solar_csv(csv_path, mwac)
                break
            except (ValueError, RuntimeError) as exc2:
                print(f"  ERRO: {exc2}")

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
    print("  Curtailment:      Ativado")
    print(f"  Curva curt.:      {curtailment_path}")
    modo_label = "Arbitragem de PLD (modo 3)" if charge_mode == 3 else "Cobertura de Déficit (modo 0)"
    print(f"  Modo BESS:        {modo_label}")
    modul_resumo = "Energia (prêmio de captura)" if modulation_mode == MODULATION_MODE_ENERGIA else "Garantia física (custo)"
    print(f"  Cálculo modulação: {modul_resumo}")
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
    print(f"  O&M anual BESS:   {bess_om:.2%} do CAPEX")
    print(f"  Taxa LCOS/LCOE:   {lcoe_discount_rate:.1%} ao ano")
    print(f"  Fator Curt. 2026: {curtailment_factor_2026:.4f}")
    if gf_daily_coverage_target_pct is not None:
        print(f"  Cobertura GF/dia: {gf_daily_coverage_target_pct:.1%} (dimensiona por energia)")
    else:
        print("  Cobertura GF/dia: dimensionamento por potência (padrão)")
    print(
        f"  Curtailment alvo 2025: {curtailment_target_pct_2025:.0f}% da geração "
        "(fator vs realizado calculado após carregar o perfil solar)"
    )
    print(
        f"  Curtailment alvo 2026: {curtailment_target_pct_2026:.0f}% da geração "
        "(fator vs 2025 calculado após carregar o perfil solar)"
    )

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
        curtailment_target_pct_2026=curtailment_target_pct_2026,
        curtailment_target_pct_2025=curtailment_target_pct_2025,
        curtailment_path=curtailment_path,
        gf_daily_coverage_target_pct=gf_daily_coverage_target_pct,
        modulation_mode=modulation_mode,
    )
    return params, curtailment_enabled, rte_path, charge_mode, p90_year20_mwmed
