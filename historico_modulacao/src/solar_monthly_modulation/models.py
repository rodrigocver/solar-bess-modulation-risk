"""Data models for monthly solar modulation analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ModulationConfig:
    """Configuration for one monthly modulation run.

    Parameters
    ----------
    csv_path : str
        Solar generation CSV path.
    mwac : float
        Plant AC capacity in MWac.
    years : tuple[int, ...]
        Historical PLD years to evaluate.
    submarket : str
        CCEE submarket code.
    pld_base_dir : str
        Directory containing local PLD files.
    output_dir : str
        Base directory for exported run artifacts.
    bq_service_account_path : str or None
        Optional service account JSON path for BigQuery PLD reads.
    """

    csv_path: str
    mwac: float
    years: tuple[int, ...]
    submarket: str
    pld_base_dir: str
    output_dir: str
    bq_service_account_path: str | None = None


@dataclass(frozen=True)
class HourlyPriceSeries:
    """Hourly PLD prices with timestamps.

    Parameters
    ----------
    year : int
        PLD calendar year.
    submarket : str
        CCEE submarket code.
    timestamps : pandas.DatetimeIndex
        Strictly ordered timestamps for observed prices.
    prices_brl_per_mwh : pandas.Series
        Hourly PLD prices in BRL/MWh aligned to ``timestamps``.
    source : str
        Source label for auditability.
    """

    year: int
    submarket: str
    timestamps: pd.DatetimeIndex
    prices_brl_per_mwh: pd.Series
    source: str


@dataclass(frozen=True)
class SourceMetadata:
    """Metadata inherited from validated source loaders.

    Parameters
    ----------
    solar_csv_filename : str
        Basename of the solar generation CSV.
    solar_fc : float
        Capacity factor from the existing solar loader.
    garantia_fisica_mw : float
        Physical guarantee in MW from the existing solar loader.
    price_sources : dict[int, str]
        Mapping of year to PLD source label.
    """

    solar_csv_filename: str
    solar_fc: float
    garantia_fisica_mw: float
    price_sources: dict[int, str]


@dataclass(frozen=True)
class ModulationResult:
    """Calculated monthly and annual modulation outputs.

    Parameters
    ----------
    monthly : pandas.DataFrame
        Monthly output table with unit-labelled columns.
    annual : pandas.DataFrame
        Annual output table with unit-labelled columns.
    source_metadata : SourceMetadata
        Source and loader metadata for auditability.
    """

    monthly: pd.DataFrame
    annual: pd.DataFrame
    source_metadata: SourceMetadata


@dataclass(frozen=True)
class WrittenOutputs:
    """Paths written for a completed run.

    Parameters
    ----------
    run_dir : pathlib.Path
        Run-specific output directory.
    monthly_csv : pathlib.Path
        Monthly CSV output path.
    annual_csv : pathlib.Path
        Annual CSV output path.
    html_report : pathlib.Path
        HTML report output path.
    manifest_json : pathlib.Path
        Manifest JSON output path.
    """

    run_dir: Path
    monthly_csv: Path
    annual_csv: Path
    html_report: Path
    manifest_json: Path
