"""Interactive CLI parameter prompting loop."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from solar_bess_risk.config import (
    BOUNDS_BQ_YEAR,
    BOUNDS_BESS_SIZE_RATIO_PCT,
    BOUNDS_CAPEX_USD_PER_KWH,
    BOUNDS_DEGRADATION_PCT_YR,
    BOUNDS_DISCOUNT_RATE_PCT,
    BOUNDS_ILR,
    BOUNDS_MIN_INJECTION_FLOOR_MW,
    BOUNDS_MIN_SOC_THRESHOLD_PCT,
    BOUNDS_RTE_PCT,
    BOUNDS_STORAGE_DURATION_H,
    BOUNDS_USD_BRL_RATE,
    BOUNDS_USEFUL_LIFE_YR,
    DEFAULT_BESS_SIZE_RATIOS_PCT,
    DEFAULT_BQ_AUTH_METHOD,
    DEFAULT_BQ_BILLING_PROJECT,
    DEFAULT_BQ_SUBMARKET,
    DEFAULT_BQ_YEAR,
    DEFAULT_CAPEX_USD_PER_KWH,
    DEFAULT_DEGRADATION_PCT_YR,
    DEFAULT_DISCOUNT_RATE_PCT,
    DEFAULT_ILR_VALUES,
    DEFAULT_MIN_INJECTION_FLOOR_MW,
    DEFAULT_MIN_SOC_THRESHOLD_PCT,
    DEFAULT_RTE_PCT,
    DEFAULT_STORAGE_DURATIONS_H,
    DEFAULT_USD_BRL_RATE,
    DEFAULT_USEFUL_LIFE_YR,
    VALID_BQ_AUTH_METHODS,
    VALID_BQ_SUBMARKETS,
    SimulationParams,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------


def prompt_float(
    label: str,
    unit: str,
    default: float,
    min_val: float,
    max_val: float,
) -> float:
    """Prompt for a float value with bounds validation.

    Parameters
    ----------
    label : str
        Parameter label (PT-BR).
    unit : str
        Unit label.
    default : float
        Default value.
    min_val : float
        Lower bound (inclusive unless ≈0 for exclusive).
    max_val : float
        Upper bound (inclusive).

    Returns
    -------
    float
        Validated value.
    """
    while True:
        raw = input(f"  {label} [{unit}] (padrão {default}): ").strip()
        if raw == "":
            return default
        try:
            val = float(raw)
        except ValueError:
            print(
                f"  ERRO: Parâmetro '{label}': valor '{raw}' não é numérico. "
                f"Intervalo aceito: [{min_val}, {max_val}] {unit}."
            )
            continue
        if not (min_val <= val <= max_val):
            print(
                f"  ERRO: Parâmetro '{label}': valor {val} {unit} "
                f"fora do intervalo [{min_val}, {max_val}] {unit}."
            )
            continue
        return val


def prompt_int(
    label: str,
    unit: str,
    default: int,
    min_val: int,
    max_val: int,
) -> int:
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
                f"Intervalo aceito: [{min_val}, {max_val}] {unit}."
            )
            continue
        if not (min_val <= val <= max_val):
            print(
                f"  ERRO: Parâmetro '{label}': valor {val} {unit} "
                f"fora do intervalo [{min_val}, {max_val}] {unit}."
            )
            continue
        return val


def prompt_list(
    label: str,
    unit: str,
    default: list[float],
    min_val: float,
    max_val: float,
) -> list[float]:
    """Prompt for a comma-separated list of floats with per-element bounds."""
    default_str = ",".join(str(v) for v in default)
    while True:
        raw = input(f"  {label} [{unit}] (padrão {default_str}): ").strip()
        if raw == "":
            return list(default)
        try:
            vals = [float(x.strip()) for x in raw.split(",")]
        except ValueError:
            print(
                f"  ERRO: Parâmetro '{label}': entrada inválida. "
                f"Forneça valores separados por vírgula em [{min_val}, {max_val}]."
            )
            continue
        invalid = [v for v in vals if not (min_val <= v <= max_val)]
        if invalid:
            print(
                f"  ERRO: Parâmetro '{label}': valor(es) {invalid} "
                f"fora do intervalo [{min_val}, {max_val}] {unit}."
            )
            continue
        return vals


def prompt_string_choice(
    label: str,
    default: str,
    valid: set[str],
) -> str:
    """Prompt for a string value from a set of valid choices."""
    choices_str = "/".join(sorted(valid))
    while True:
        raw = input(f"  {label} [{choices_str}] (padrão {default}): ").strip()
        if raw == "":
            return default
        if raw in valid:
            return raw
        print(
            f"  ERRO: Parâmetro '{label}': valor '{raw}' inválido. "
            f"Opções: {choices_str}."
        )


def prompt_file_path(label: str) -> str:
    """Prompt for a file path, re-prompt if not found."""
    while True:
        raw = input(f"  {label}: ").strip()
        if raw and os.path.isfile(raw):
            return raw
        print(f"  ERRO: Arquivo '{raw}' não encontrado. Tente novamente.")


# ---------------------------------------------------------------------------
# Main session
# ---------------------------------------------------------------------------


def run_session(service_account_path: str | None = None) -> SimulationParams:
    """Run the full interactive parameter collection session.

    Parameters
    ----------
    service_account_path : str | None
        Pre-set service account path from CLI flag.

    Returns
    -------
    SimulationParams
        Validated, frozen parameters.
    """
    # Section 1 — Plant & Simulation Parameters
    ilr_values = prompt_list(
        "ILR (razão de inversão)", "lista de floats",
        DEFAULT_ILR_VALUES, *BOUNDS_ILR,
    )
    bess_size_ratios_pct = prompt_list(
        "Razões de dimensionamento BESS", "% of E_solar",
        DEFAULT_BESS_SIZE_RATIOS_PCT, *BOUNDS_BESS_SIZE_RATIO_PCT,
    )
    storage_durations_h = prompt_list(
        "Duração do armazenamento", "h",
        DEFAULT_STORAGE_DURATIONS_H, *BOUNDS_STORAGE_DURATION_H,
    )
    rte_pct = prompt_float(
        "Eficiência round-trip", "%",
        DEFAULT_RTE_PCT, *BOUNDS_RTE_PCT,
    )
    degradation_pct_yr = prompt_float(
        "Taxa de degradação anual", "%/ano",
        DEFAULT_DEGRADATION_PCT_YR, *BOUNDS_DEGRADATION_PCT_YR,
    )

    # Section 2 — BESS Economic Parameters
    capex_usd_per_kwh = prompt_float(
        "CAPEX do BESS", "USD/kWh",
        DEFAULT_CAPEX_USD_PER_KWH, *BOUNDS_CAPEX_USD_PER_KWH,
    )
    usd_brl_rate = prompt_float(
        "Taxa de câmbio USD/BRL", "BRL/USD",
        DEFAULT_USD_BRL_RATE, *BOUNDS_USD_BRL_RATE,
    )
    useful_life_yr = prompt_int(
        "Vida útil", "anos",
        DEFAULT_USEFUL_LIFE_YR, *BOUNDS_USEFUL_LIFE_YR,
    )
    discount_rate_pct = prompt_float(
        "Taxa de desconto", "%/ano",
        DEFAULT_DISCOUNT_RATE_PCT, *BOUNDS_DISCOUNT_RATE_PCT,
    )

    # Section 3 — Dispatch Strategy Parameters
    min_soc_threshold_pct = prompt_float(
        "Limiar mínimo de SoC (para carga da rede)", "% da capacidade",
        DEFAULT_MIN_SOC_THRESHOLD_PCT, *BOUNDS_MIN_SOC_THRESHOLD_PCT,
    )
    min_injection_floor_mw = prompt_float(
        "Piso mínimo de injeção na rede", "MW",
        DEFAULT_MIN_INJECTION_FLOOR_MW, *BOUNDS_MIN_INJECTION_FLOOR_MW,
    )

    # Section 4 — Solar Profile (prompt handled externally in __main__)
    # Just collect whether CSV is desired — actual loading done later
    solar_csv_path: str | None = None
    use_csv_raw = input("  Carregar perfil solar de CSV? (s/N): ").strip().lower()
    if use_csv_raw == "s":
        solar_csv_path = prompt_file_path("Caminho do CSV do perfil solar")

    # Section 5 — Price Profile (BigQuery PLD — mandatory)
    bq_submarket = prompt_string_choice(
        "Submercado CCEE", DEFAULT_BQ_SUBMARKET, VALID_BQ_SUBMARKETS,
    )
    bq_year = prompt_int(
        "Ano para busca do PLD", "ano",
        DEFAULT_BQ_YEAR, *BOUNDS_BQ_YEAR,
    )

    # Section 6 — BigQuery Authentication
    bq_auth_method: str = DEFAULT_BQ_AUTH_METHOD
    bq_sa_path: str | None = service_account_path

    if not bq_sa_path:
        bq_auth_method = prompt_string_choice(
            "Método de autenticação BigQuery",
            DEFAULT_BQ_AUTH_METHOD,
            VALID_BQ_AUTH_METHODS,
        )
        if bq_auth_method == "service_account":
            bq_sa_path = prompt_file_path(
                "Caminho do arquivo JSON da conta de serviço"
            )
    else:
        bq_auth_method = "service_account"

    bq_billing_project_raw = input(
        f"  Projeto de faturação GCP (padrão {DEFAULT_BQ_BILLING_PROJECT}): "
    ).strip()
    bq_billing_project = bq_billing_project_raw or DEFAULT_BQ_BILLING_PROJECT

    params = SimulationParams(
        ilr_values=ilr_values,
        bess_size_ratios_pct=bess_size_ratios_pct,
        storage_durations_h=storage_durations_h,
        rte_pct=rte_pct,
        degradation_pct_yr=degradation_pct_yr,
        capex_usd_per_kwh=capex_usd_per_kwh,
        usd_brl_rate=usd_brl_rate,
        useful_life_yr=useful_life_yr,
        discount_rate_pct=discount_rate_pct,
        min_soc_threshold_pct=min_soc_threshold_pct,
        min_injection_floor_mw=min_injection_floor_mw,
        bq_billing_project=bq_billing_project,
        bq_submarket=bq_submarket,
        bq_year=bq_year,
        bq_auth_method=bq_auth_method,
        bq_service_account_path=bq_sa_path,
    )

    # Confirmation summary
    summary = format_confirmation_summary(params)
    print(summary)

    confirm = input("Proceed with simulation? [Y/n]: ").strip().lower()
    if confirm == "n":
        raise SystemExit("Abortado pelo usuário.")

    return params


def format_confirmation_summary(params: SimulationParams) -> str:
    """Build the confirmation summary text.

    Parameters
    ----------
    params : SimulationParams
        Validated parameters.

    Returns
    -------
    str
        Multi-line summary string.
    """
    capex_brl = params.capex_usd_per_kwh * params.usd_brl_rate
    ilr_str = ", ".join(str(v) for v in params.ilr_values)
    bess_str = ", ".join(str(int(v)) if v == int(v) else str(v) for v in params.bess_size_ratios_pct)
    dur_str = ", ".join(str(v) for v in params.storage_durations_h)

    price_label = f"BigQuery PLD {params.bq_submarket} {params.bq_year}"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "Parâmetros aceitos:",
        f"  ILR values:              {ilr_str}",
        f"  BESS size ratios (%):    {bess_str}",
        f"  Storage durations (h):   {dur_str}",
        f"  Round-trip efficiency:   {params.rte_pct} %",
        f"  Annual degradation:      {params.degradation_pct_yr} %/ano",
        f"  BESS CAPEX:              {params.capex_usd_per_kwh} USD/kWh  →  {capex_brl:,.1f} BRL/kWh (câmbio {params.usd_brl_rate})",
        f"  Useful life:             {params.useful_life_yr} anos",
        f"  Discount rate:           {params.discount_rate_pct} %/ano",
        f"  Min SoC threshold:       {params.min_soc_threshold_pct} %",
        f"  Min injection floor:     {params.min_injection_floor_mw} MW",
        f"  Price profile:           {price_label}",
        f"  Auth method:             {params.bq_auth_method}",
        f"  Scenarios to simulate:   {params.total_scenarios}  ({len(params.ilr_values)} ILRs × {len(params.bess_size_ratios_pct)} BESS sizes × {len(params.storage_durations_h)} durations)",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def prompt_heatmap_scenario(scenario_ids: list[tuple[float, float, float]]) -> int:
    """Prompt the engineer to select a scenario for the heatmap.

    Parameters
    ----------
    scenario_ids : list[tuple[float, float, float]]
        List of (ilr, bess_pct, duration_h) tuples.

    Returns
    -------
    int
        Zero-based index of the selected scenario.
    """
    print("\nCenários disponíveis:")
    for i, (ilr, bess_pct, dur_h) in enumerate(scenario_ids, 1):
        print(f"  [{i}] ILR={ilr} | BESS={bess_pct}% | Duração={dur_h}h")

    while True:
        raw = input("Digite o número do cenário (padrão 1): ").strip()
        if raw == "":
            return 0
        try:
            idx = int(raw)
        except ValueError:
            print(f"  ERRO: '{raw}' não é um número inteiro válido.")
            print("\nCenários disponíveis:")
            for i, (ilr, bess_pct, dur_h) in enumerate(scenario_ids, 1):
                print(f"  [{i}] ILR={ilr} | BESS={bess_pct}% | Duração={dur_h}h")
            continue
        if not (1 <= idx <= len(scenario_ids)):
            print(
                f"  ERRO: Cenário {idx} inválido. "
                f"Escolha entre 1 e {len(scenario_ids)}."
            )
            print("\nCenários disponíveis:")
            for i, (ilr, bess_pct, dur_h) in enumerate(scenario_ids, 1):
                print(f"  [{i}] ILR={ilr} | BESS={bess_pct}% | Duração={dur_h}h")
            continue
        return idx - 1
