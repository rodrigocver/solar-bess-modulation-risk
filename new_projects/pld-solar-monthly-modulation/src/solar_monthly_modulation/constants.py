"""Constants for monthly solar modulation analysis."""

from __future__ import annotations

from typing import Final

TOOL_VERSION: Final[str] = "0.1.0"
HOURS_PER_YEAR: Final[int] = 8760
DEFAULT_YEARS: Final[tuple[int, ...]] = (2021, 2022, 2023, 2024, 2025, 2026)
DEFAULT_SUBMARKET: Final[str] = "SE"
DEFAULT_PLD_BASE_DIR: Final[str] = "dados/pld"
DEFAULT_OUTPUT_DIR: Final[str] = "output/monthly_modulation"
VALID_SUBMARKETS: Final[frozenset[str]] = frozenset({"SE", "S", "NE", "N"})

MONTHLY_COLUMNS: Final[tuple[str, ...]] = (
    "year",
    "month",
    "hours",
    "generation_mwh",
    "flat_price_brl_per_mwh",
    "captured_price_brl_per_mwh",
    "modulation_value_brl_per_mwh",
    "weighted_revenue_brl",
    "modulation_factor",
    "generation_per_mwac_mwh_per_mwac",
    "price_source",
)

ANNUAL_COLUMNS: Final[tuple[str, ...]] = (
    "year",
    "hours",
    "generation_mwh",
    "flat_price_brl_per_mwh",
    "captured_price_brl_per_mwh",
    "modulation_value_brl_per_mwh",
    "weighted_revenue_brl",
    "modulation_factor",
    "generation_per_mwac_mwh_per_mwac",
    "price_source",
)

FORMULAS: Final[dict[str, str]] = {
    "weighted_revenue_brl": "sum(generation_mwh_h * pld_brl_per_mwh_h)",
    "captured_price_brl_per_mwh": (
        "weighted_revenue_brl / sum(generation_mwh_h)"
    ),
    "flat_price_brl_per_mwh": "mean(pld_brl_per_mwh_h)",
    "modulation_value_brl_per_mwh": (
        "flat_price_brl_per_mwh - captured_price_brl_per_mwh"
    ),
    "modulation_factor": (
        "captured_price_brl_per_mwh / flat_price_brl_per_mwh"
    ),
    "generation_per_mwac_mwh_per_mwac": "generation_mwh / mwac",
}
