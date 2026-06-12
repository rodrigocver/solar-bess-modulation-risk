"""Configuration constants, default values, validation bounds, and SimulationParams.

All physical constants and default parameter values live here.
No magic numbers anywhere else in the codebase.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import NamedTuple


# ---------------------------------------------------------------------------
# Physical & system constants
# ---------------------------------------------------------------------------

HOURS_PER_YEAR: int = 8760

# ---------------------------------------------------------------------------
# Scenario template definitions (A / B / C)
# ---------------------------------------------------------------------------


class ScenarioTemplate(NamedTuple):
    """Static scenario definition — profile-dependent fields computed later."""

    label: str
    peak_hours: frozenset[int]
    duration_h: int
    peak_hour_weights: dict[int, float]


SCENARIO_TEMPLATES: list[ScenarioTemplate] = [
    ScenarioTemplate(
        label="A",
        peak_hours=frozenset({18, 19}),
        duration_h=2,
        peak_hour_weights={18: 1.0, 19: 1.0},
    ),
    ScenarioTemplate(
        label="B",
        peak_hours=frozenset({17, 18, 19, 20}),
        duration_h=4,
        peak_hour_weights={17: 1.0, 18: 1.0, 19: 1.0, 20: 1.0},
    ),
]

PEAK_HOURS_BY_LABEL: dict[str, frozenset[int]] = {
    t.label: t.peak_hours for t in SCENARIO_TEMPLATES
}

# ---------------------------------------------------------------------------
# Default parameter values
# ---------------------------------------------------------------------------

DEFAULT_BQ_YEAR: int = 2025
DEFAULT_BQ_SUBMARKET: str = "SE"
DEFAULT_CAPEX_USD_KWH: float = 200.0  # legacy — kept for backtest.py compat
DEFAULT_USD_BRL_RATE: float = 5.80
DEFAULT_USEFUL_LIFE_YR: int = 20
DEFAULT_BESS_ROUNDTRIP_EFFICIENCY: float = 0.85
DEFAULT_BESS_O_AND_M_PCT_CAPEX: float = 0.0125
DEFAULT_LCOE_DISCOUNT_RATE: float = 0.1

# ---------------------------------------------------------------------------
# Modulation metric mode
# ---------------------------------------------------------------------------

# How the modulação metric (R$/MWh) is computed:
#
#   "energia"          → prêmio de captura ponderado pela energia.
#                        mod = Σ(injeção_h × PLD_h) / Σ(injeção_h) − PLD_médio
#                        Sinal: positivo = bom (a usina captura acima da média).
#
#   "garantia_fisica"  → custo de modulação referenciado à garantia física.
#                        mod = PLD_médio − Σ(injeção_h × PLD_h) / energia_GF
#                        Sinal: positivo = custo (captura abaixo da média).
#
# O modo "energia" é o padrão atual; "garantia_fisica" preserva o cálculo legado.
MODULATION_MODE_ENERGIA: str = "energia"
MODULATION_MODE_GARANTIA_FISICA: str = "garantia_fisica"
VALID_MODULATION_MODES: frozenset[str] = frozenset(
    {MODULATION_MODE_ENERGIA, MODULATION_MODE_GARANTIA_FISICA}
)
DEFAULT_MODULATION_MODE: str = MODULATION_MODE_ENERGIA

# ---------------------------------------------------------------------------
# MUST reduction optimizer (feature 003)
# ---------------------------------------------------------------------------

# Default project transmission usage tariff (TUSTg). Project-specific value
# SHOULD be supplied by the user; this documented default is applied otherwise.
DEFAULT_TUST_BRL_PER_KW_MONTH: float = 7.23  # R$/kW.month
MONTHS_PER_YEAR: int = 12               # months/year (TUST annualisation)
KW_PER_MW: int = 1000                   # kW/MW (TUST annualisation)

# MUST reduction grid sweep (fraction of project power abdicated)
MUST_SWEEP_MAX_PCT: float = 0.40        # fraction (0-1)
MUST_SWEEP_STEP_PCT: float = 0.02       # fraction (0-1)

# ---------------------------------------------------------------------------
# 2026 data-fill factors
# ---------------------------------------------------------------------------

# Scalar multiplier applied to the 2025 PLD base when filling unobserved 2026
# hours.  None → auto-calculated from the ratio of observed 2026 vs 2025 PLD.
DEFAULT_PLD_FACTOR_2026: float | None = None

# Scalar multiplier applied to the curtailment profile loaded for 2026.
# 1.0 = use the profile as-is; e.g. 0.8 = 20% lower curtailment in 2026.
# Computed at runtime as ``curtailment_target_pct_2026 / realized_2025_ons_pct``.
DEFAULT_CURTAILMENT_FACTOR_2026: float = 1.0

# Target ONS curtailment for 2026 as a percentage of generation. The 2026
# curtailment profile is the 2025 realized ONS shape scaled so the annual
# curtailment/generation ratio reaches this target.
DEFAULT_CURTAILMENT_TARGET_PCT_2026: float = 20.0

# Scalar multiplier applied to the 2025 realized ONS curtailment profile so its
# annual curtailment/generation ratio reaches ``curtailment_target_pct_2025``.
# Computed at runtime as ``curtailment_target_pct_2025 / realized_2025_ons_pct``.
DEFAULT_CURTAILMENT_FACTOR_2025: float = 1.0

# Target ONS curtailment for 2025 as a percentage of generation. The 2025
# realized ONS shape is scaled so the annual curtailment/generation ratio
# reaches this target (default 10%).
DEFAULT_CURTAILMENT_TARGET_PCT_2025: float = 10.0

# PLD regulatory floor and ceiling (R$/MWh). Used to clamp scaled PLD series
# when stressing/relaxing the modulation in the simplified pitch dashboard.
PLD_FLOOR_BRL_PER_MWH: float = 57.31
PLD_CEILING_BRL_PER_MWH: float = 1611.04

# Curtailment factor assumption embedded in the previsao_futura sheet of
# media_agregada_horaria_2025_2026.xlsx — informational/metadata only.
CURTAILMENT_ASSUMPTION_PCT_2026: float = 9.2

# ---------------------------------------------------------------------------
# Risk matrix (PLD × curtailment sensitivity grid)
# ---------------------------------------------------------------------------

# Additive sensitivity feature: expands the 2025 base scenario across a grid of
# PLD multipliers and curtailment targets. Does NOT alter the existing 2025/2026
# scenarios — it is a standalone report (output/.../matriz_risco.html).

# PLD multipliers applied to the 2025 base PLD profile (1.0 = 2025 as-is).
RISK_MATRIX_PLD_FACTORS: tuple[float, ...] = (1.0, 1.25, 1.5, 1.75, 2.0)

# Target annual curtailment/generation percentages. The 2025 base curtailment
# profile is scaled so each column reaches its target (first ≈ current 2025).
RISK_MATRIX_CURTAILMENT_TARGETS_PCT: tuple[float, ...] = (15.0, 20.0, 25.0, 30.0)

# Duration (hours) of the BESS scenario used by the risk matrix.
RISK_MATRIX_DURATION_H: int = 4

# ---------------------------------------------------------------------------
# CAPEX fixo por duração (spec v2.0 — não é mais parâmetro do usuário)
# ---------------------------------------------------------------------------

CAPEX_USD_PER_KWH: dict[int, float] = {
    2: 164.57,
    4: 151.79,
}

# ---------------------------------------------------------------------------
# BESS block sizing (typical module dimensions)
# ---------------------------------------------------------------------------


class BessBlockSpec(NamedTuple):
    """Typical BESS module/block specification."""

    duration_h: int
    block_power_mw: float   # MVA (≈MW) per block
    block_energy_mwh: float  # MWh per block


BESS_BLOCK_SPECS: dict[int, BessBlockSpec] = {
    2: BessBlockSpec(duration_h=2, block_power_mw=4.54, block_energy_mwh=10.1),
    4: BessBlockSpec(duration_h=4, block_power_mw=2.52, block_energy_mwh=10.1),
}

# Default GF daily coverage target. None -> size by power (legacy behaviour:
# n_blocks = ceil(gf / block_power_mw)). A fraction (0-2) -> size by energy so the
# BESS stores that share of one day of garantia fisica (gf x 24 MWh).
DEFAULT_GF_DAILY_COVERAGE_TARGET_PCT: float | None = None


class BessSizing(NamedTuple):
    """Resolved BESS sizing for a duration scenario."""

    n_blocks: int
    bess_power_mw: float
    bess_energy_mwh: float


def size_bess_blocks(
    garantia_fisica_mw: float,
    duration_h: int,
    coverage_target_pct: float | None = None,
) -> BessSizing:
    """Size the BESS in whole blocks for a given duration.

    Two sizing modes:

    - ``coverage_target_pct is None`` (legacy): size by power so the BESS can
      sustain the garantia fisica, ``n_blocks = ceil(gf / block_power_mw)``.
    - ``coverage_target_pct`` given: size by energy so the BESS stores that share
      of one day of garantia fisica, ``n_blocks = ceil(coverage * gf * 24 /
      block_energy_mwh)``. Block count is rounded up, so the realised coverage is
      always >= the requested target.

    Parameters
    ----------
    garantia_fisica_mw : float
        Physical guarantee in MW.
    duration_h : int
        BESS duration in hours; selects the block spec.
    coverage_target_pct : float | None
        Target daily GF coverage as a fraction (e.g. 0.5 = 50%). ``None`` selects
        the legacy power-based sizing.

    Returns
    -------
    BessSizing
        Whole-block count plus resulting power (MW) and energy (MWh).
    """
    block = BESS_BLOCK_SPECS[duration_h]
    if coverage_target_pct is None:
        n_blocks = math.ceil(garantia_fisica_mw / block.block_power_mw)
    else:
        energy_target_mwh = coverage_target_pct * garantia_fisica_mw * 24.0
        n_blocks = math.ceil(energy_target_mwh / block.block_energy_mwh)
    n_blocks = max(1, n_blocks)
    return BessSizing(
        n_blocks=n_blocks,
        bess_power_mw=n_blocks * block.block_power_mw,
        bess_energy_mwh=n_blocks * block.block_energy_mwh,
    )

# ---------------------------------------------------------------------------
# Curtailment
# ---------------------------------------------------------------------------

DEFAULT_CURTAILMENT_PATH: str = "dados/media_agregada_horaria_2025_2026.xlsx"
DEFAULT_RTE_PATH: str = "dados/11 - Envision.xlsx"
DEFAULT_RTE_COMMISSIONING_YEAR: int = 2025
CURTAILMENT_COLUMN: str = "Media Agregada Todas as Usinas"
CURTAILMENT_SHEET_2025: str = "2025_horario"
CURTAILMENT_SHEET_2026: str = "previsao_futura"

# ---------------------------------------------------------------------------
# Backtest years
# ---------------------------------------------------------------------------

BACKTEST_YEARS: list[int] = [2025, 2026]
DURATIONS: list[int] = [4]

# ---------------------------------------------------------------------------
# Validation bounds — (min, max) inclusive
# ---------------------------------------------------------------------------

PARAM_BOUNDS: dict[str, tuple[float, float]] = {
    "mwac": (0.01, 10_000.0),
    "bq_year": (2000, 2100),
    "capex_usd_per_kwh": (0.01, 5_000.0),
    "usd_brl_rate": (0.01, 100.0),
    "useful_life_years": (1, 100),
    "bess_roundtrip_efficiency": (0.01, 1.0),
    "bess_o_and_m_pct_capex": (0.0, 1.0),
    "lcoe_discount_rate": (0.0, 1.0),
    "tust_brl_per_kw_month": (0.0, 1000.0),
    "must_reduction_pct": (0.0, 1.0),
    "must_sweep_max_pct": (0.0, 1.0),
    "must_sweep_step_pct": (1e-6, 1.0),
    "pld_factor_2026": (0.0, 100.0),
    "curtailment_factor_2026": (0.0, 100.0),
    "curtailment_target_pct_2026": (0.0, 100.0),
    "curtailment_factor_2025": (0.0, 100.0),
    "curtailment_target_pct_2025": (0.0, 100.0),
    "gf_daily_coverage_target_pct": (0.0, 2.0),
}

VALID_BQ_SUBMARKETS: set[str] = {"SE", "S", "NE", "N"}

# ---------------------------------------------------------------------------
# Display constants
# ---------------------------------------------------------------------------

PAYBACK_NOT_ACHIEVABLE: str = "não atingível"

# ---------------------------------------------------------------------------
# SimulationParams dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationParams:
    """Complete, validated configuration for a single analysis run.

    Parameters
    ----------
    csv_path : str
        Path to solar generation CSV (8,760 rows). Required.
    mwac : float
        Plant AC capacity in MW. Required.
    bq_year : int
        Year to fetch from CCEE PLD BigQuery table.
    bq_submarket : str
        CCEE submarket for PLD price fetch.
    capex_usd_per_kwh : float
        BESS capital cost in USD/kWh.
    usd_brl_rate : float
        Exchange rate BRL/USD.
    useful_life_years : int
        Economic useful life in years (undiscounted payback horizon).
    bq_service_account_path : str | None
        Path to service account JSON key; None when using ADC.
        Excluded from SHA-256 hash and manifest.
    tust_brl_per_kw_month : float
        Project transmission usage tariff (TUSTg) in R$/kW.month. Used by the
        MUST reduction optimizer; defaults to the documented project default.
    must_sweep_max_pct : float
        Maximum MUST reduction fraction (0-1) explored by the optimizer sweep.
    must_sweep_step_pct : float
        Step of the MUST reduction sweep grid as a fraction (0-1).
    pld_factor_2026 : float | None
        Scalar multiplier applied to the 2025 PLD base when filling unobserved
        2026 hours.  None → factor is auto-calculated from BigQuery observed data.
    curtailment_factor_2026 : float
        Scalar multiplier applied to the 2025 realized ONS curtailment profile to
        build the 2026 profile. Computed at runtime as
        ``curtailment_target_pct_2026 / realized_2025_ons_pct``.  Default 1.0.
    curtailment_target_pct_2026 : float
        Target ONS curtailment for 2026 as a percentage of generation (default
        20%). Drives ``curtailment_factor_2026`` relative to the 2025 realized
        ONS curtailment.
    curtailment_assumption_pct_2026 : float
        Curtailment factor assumption used when building the previsao_futura
        sheet (aba da media_agregada_horaria_2025_2026.xlsx). Purely informational
        — displayed in the report but does not alter the simulation computation.
    """

    csv_path: str
    mwac: float
    bq_year: int = DEFAULT_BQ_YEAR
    bq_submarket: str = DEFAULT_BQ_SUBMARKET
    capex_usd_per_kwh: float = DEFAULT_CAPEX_USD_KWH
    usd_brl_rate: float = DEFAULT_USD_BRL_RATE
    useful_life_years: int = DEFAULT_USEFUL_LIFE_YR
    bess_roundtrip_efficiency: float = DEFAULT_BESS_ROUNDTRIP_EFFICIENCY
    bess_o_and_m_pct_capex: float = DEFAULT_BESS_O_AND_M_PCT_CAPEX
    lcoe_discount_rate: float = DEFAULT_LCOE_DISCOUNT_RATE
    bq_service_account_path: str | None = None
    tust_brl_per_kw_month: float = DEFAULT_TUST_BRL_PER_KW_MONTH
    must_sweep_max_pct: float = MUST_SWEEP_MAX_PCT
    must_sweep_step_pct: float = MUST_SWEEP_STEP_PCT
    pld_factor_2026: float | None = DEFAULT_PLD_FACTOR_2026
    curtailment_factor_2026: float = DEFAULT_CURTAILMENT_FACTOR_2026
    curtailment_target_pct_2026: float = DEFAULT_CURTAILMENT_TARGET_PCT_2026
    curtailment_factor_2025: float = DEFAULT_CURTAILMENT_FACTOR_2025
    curtailment_target_pct_2025: float = DEFAULT_CURTAILMENT_TARGET_PCT_2025
    curtailment_assumption_pct_2026: float = CURTAILMENT_ASSUMPTION_PCT_2026
    gf_daily_coverage_target_pct: float | None = DEFAULT_GF_DAILY_COVERAGE_TARGET_PCT
    modulation_mode: str = DEFAULT_MODULATION_MODE

    def __post_init__(self) -> None:
        """Validate MUST/TUST optimizer fields against documented bounds.

        Raises
        ------
        ValueError
            If ``tust_brl_per_kw_month``, ``must_sweep_max_pct`` or
            ``must_sweep_step_pct`` fall outside ``PARAM_BOUNDS``.
        """
        if self.modulation_mode not in VALID_MODULATION_MODES:
            raise ValueError(
                f"ERRO: modulation_mode={self.modulation_mode!r} inválido; "
                f"use um de {sorted(VALID_MODULATION_MODES)}."
            )
        for field_name, value in (
            ("tust_brl_per_kw_month", self.tust_brl_per_kw_month),
            ("must_sweep_max_pct", self.must_sweep_max_pct),
            ("must_sweep_step_pct", self.must_sweep_step_pct),
            ("curtailment_factor_2026", self.curtailment_factor_2026),
            ("curtailment_target_pct_2026", self.curtailment_target_pct_2026),
            ("curtailment_factor_2025", self.curtailment_factor_2025),
            ("curtailment_target_pct_2025", self.curtailment_target_pct_2025),
            *((("pld_factor_2026", self.pld_factor_2026),) if self.pld_factor_2026 is not None else ()),
            *(
                (("gf_daily_coverage_target_pct", self.gf_daily_coverage_target_pct),)
                if self.gf_daily_coverage_target_pct is not None
                else ()
            ),
        ):
            lo, hi = PARAM_BOUNDS[field_name]
            if not (lo <= value <= hi):
                raise ValueError(
                    f"ERRO: {field_name}={value} fora dos limites "
                    f"[{lo}, {hi}]."
                )
