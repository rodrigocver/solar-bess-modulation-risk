"""Configuration constants, default values, validation bounds, and SimulationParams.

All physical constants and default parameter values live here.
No magic numbers anywhere else in the codebase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


# ---------------------------------------------------------------------------
# Physical & system constants
# ---------------------------------------------------------------------------

HOURS_PER_YEAR: int = 8760
PLANT_CAPACITY_MWAC: float = 1.0  # normalisation basis — always 1.0 MWac
GRID_FREQUENCY_HZ: int = 60  # Brazilian grid nominal frequency

# ---------------------------------------------------------------------------
# Default parameter values
# ---------------------------------------------------------------------------

DEFAULT_ILR_VALUES: list[float] = [1.2, 1.3, 1.4, 1.5]
DEFAULT_BESS_SIZE_RATIOS_PCT: list[float] = [
    0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100,
]
DEFAULT_STORAGE_DURATIONS_H: list[float] = [2.0]
DEFAULT_RTE_PCT: float = 85.0
DEFAULT_DEGRADATION_PCT_YR: float = 2.0
DEFAULT_CAPEX_USD_PER_KWH: float = 250.0
DEFAULT_USD_BRL_RATE: float = 5.0
DEFAULT_USEFUL_LIFE_YR: int = 15
DEFAULT_DISCOUNT_RATE_PCT: float = 10.0
DEFAULT_MIN_SOC_THRESHOLD_PCT: float = 80.0
DEFAULT_MIN_INJECTION_FLOOR_MW: float = 0.0
DEFAULT_RNG_SEED: int = 42

# Synthetic profile location — SE Brazil (Minas Gerais)
DEFAULT_SYNTHETIC_LAT: float = -22.0
DEFAULT_SYNTHETIC_LON: float = -45.0
DEFAULT_SYNTHETIC_ALT_M: float = 800.0

# BigQuery defaults
DEFAULT_BQ_BILLING_PROJECT: str = "cver-solar"
DEFAULT_BQ_SUBMARKET: str = "SE"
DEFAULT_BQ_YEAR: int = 2025
DEFAULT_BQ_AUTH_METHOD: str = "adc"

# ---------------------------------------------------------------------------
# Validation bounds — (min, max) inclusive unless noted
# ---------------------------------------------------------------------------

BOUNDS_ILR: tuple[float, float] = (1.0, 2.0)
BOUNDS_BESS_SIZE_RATIO_PCT: tuple[float, float] = (0.0, 500.0)
BOUNDS_STORAGE_DURATION_H: tuple[float, float] = (0.5, 8.0)
BOUNDS_RTE_PCT: tuple[float, float] = (0.01, 100.0)  # (0, 100] — 0 excluded
BOUNDS_DEGRADATION_PCT_YR: tuple[float, float] = (0.0, 10.0)
BOUNDS_CAPEX_USD_PER_KWH: tuple[float, float] = (0.01, 2000.0)  # (0, 2000]
BOUNDS_USD_BRL_RATE: tuple[float, float] = (0.01, 20.0)  # (0, 20]
BOUNDS_USEFUL_LIFE_YR: tuple[int, int] = (1, 30)
BOUNDS_DISCOUNT_RATE_PCT: tuple[float, float] = (0.0, 50.0)
BOUNDS_MIN_SOC_THRESHOLD_PCT: tuple[float, float] = (0.0, 100.0)
BOUNDS_MIN_INJECTION_FLOOR_MW: tuple[float, float] = (0.0, 1.0)
BOUNDS_RNG_SEED: tuple[int, int] = (0, 2**32 - 1)
BOUNDS_SYNTHETIC_LAT: tuple[float, float] = (-90.0, 90.0)
BOUNDS_SYNTHETIC_LON: tuple[float, float] = (-180.0, 180.0)
BOUNDS_SYNTHETIC_ALT_M: tuple[float, float] = (0.0, 5000.0)
BOUNDS_BQ_YEAR: tuple[int, int] = (2021, 2040)

VALID_BQ_SUBMARKETS: set[str] = {"SE", "S", "NE", "N"}
VALID_BQ_AUTH_METHODS: set[str] = {"adc", "service_account"}

# ---------------------------------------------------------------------------
# Display constants
# ---------------------------------------------------------------------------

PAYBACK_NOT_ACHIEVABLE: str = "não atingível"
LCOS_NOT_COMPUTABLE: str = "não calculável"

# ---------------------------------------------------------------------------
# SimulationParams dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SimulationParams:
    """Complete, validated configuration for a single analysis run.

    Parameters
    ----------
    plant_capacity_mwac : float
        Normalisation basis; always 1.0 MWac.
    ilr_values : list[float]
        ILR scenarios to simulate.
    bess_size_ratios_pct : list[float]
        BESS energy sizing as % of annual solar energy without BESS.
    storage_durations_h : list[float]
        Storage duration(s) in hours.
    rte_pct : float
        Round-trip efficiency in %.
    degradation_pct_yr : float
        Annual capacity degradation in %/year.
    capex_usd_per_kwh : float
        BESS CAPEX in USD/kWh.
    usd_brl_rate : float
        Exchange rate BRL/USD.
    useful_life_yr : int
        Economic useful life in years.
    discount_rate_pct : float
        Discount rate in %/year.
    min_soc_threshold_pct : float
        End-of-day SoC threshold for grid top-up in % of capacity.
    min_injection_floor_mw : float
        Minimum net grid injection during top-up hours in MW.
    rng_seed : int
        Seed for any stochastic processes.
    synthetic_profile_lat : float
        Latitude for pvlib clearsky in degrees.
    synthetic_profile_lon : float
        Longitude for pvlib clearsky in degrees.
    synthetic_profile_alt_m : float
        Altitude for pvlib Ineichen in metres.
    bq_billing_project : str
        GCP billing project for BigQuery queries.
    bq_submarket : str
        CCEE submarket for PLD price fetch.
    bq_year : int
        Year to fetch from CCEE PLD table.
    bq_auth_method : str
        BigQuery authentication method ('adc' or 'service_account').
    bq_service_account_path : str | None
        Path to service account JSON key file; None when using ADC.
    """

    plant_capacity_mwac: float = PLANT_CAPACITY_MWAC
    ilr_values: list[float] = field(default_factory=lambda: list(DEFAULT_ILR_VALUES))
    bess_size_ratios_pct: list[float] = field(
        default_factory=lambda: list(DEFAULT_BESS_SIZE_RATIOS_PCT)
    )
    storage_durations_h: list[float] = field(
        default_factory=lambda: list(DEFAULT_STORAGE_DURATIONS_H)
    )
    rte_pct: float = DEFAULT_RTE_PCT
    degradation_pct_yr: float = DEFAULT_DEGRADATION_PCT_YR
    capex_usd_per_kwh: float = DEFAULT_CAPEX_USD_PER_KWH
    usd_brl_rate: float = DEFAULT_USD_BRL_RATE
    useful_life_yr: int = DEFAULT_USEFUL_LIFE_YR
    discount_rate_pct: float = DEFAULT_DISCOUNT_RATE_PCT
    min_soc_threshold_pct: float = DEFAULT_MIN_SOC_THRESHOLD_PCT
    min_injection_floor_mw: float = DEFAULT_MIN_INJECTION_FLOOR_MW
    rng_seed: int = DEFAULT_RNG_SEED
    synthetic_profile_lat: float = DEFAULT_SYNTHETIC_LAT
    synthetic_profile_lon: float = DEFAULT_SYNTHETIC_LON
    synthetic_profile_alt_m: float = DEFAULT_SYNTHETIC_ALT_M
    bq_billing_project: str = DEFAULT_BQ_BILLING_PROJECT
    bq_submarket: str = DEFAULT_BQ_SUBMARKET
    bq_year: int = DEFAULT_BQ_YEAR
    bq_auth_method: Literal["adc", "service_account"] = DEFAULT_BQ_AUTH_METHOD
    bq_service_account_path: str | None = None

    @property
    def capex_brl_per_kwh(self) -> float:
        """CAPEX converted to BRL/kWh."""
        return self.capex_usd_per_kwh * self.usd_brl_rate

    @property
    def total_scenarios(self) -> int:
        """Total number of scenarios to simulate."""
        return (
            len(self.ilr_values)
            * len(self.bess_size_ratios_pct)
            * len(self.storage_durations_h)
        )
