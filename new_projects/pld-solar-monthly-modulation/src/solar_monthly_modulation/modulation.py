"""Monthly and annual solar modulation calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd

from solar_bess_risk.data_sources import PriceProfile
from solar_bess_risk.profile import SolarProfile

from solar_monthly_modulation.adapters import load_price_series_for_year, load_solar_without_bess
from solar_monthly_modulation.constants import (
    ANNUAL_COLUMNS,
    HOURS_PER_YEAR,
    MONTHLY_COLUMNS,
    VALID_SUBMARKETS,
)
from solar_monthly_modulation.errors import ModulationValidationError
from solar_monthly_modulation.models import (
    HourlyPriceSeries,
    ModulationConfig,
    ModulationResult,
    SourceMetadata,
)


def run_modulation(config: ModulationConfig) -> ModulationResult:
    """Run monthly modulation for all configured historical PLD years.

    Parameters
    ----------
    config : ModulationConfig
        Input configuration containing CSV path, MWac, years, submarket, and PLD path.

    Returns
    -------
    ModulationResult
        Monthly and annual result tables plus source metadata.

    Raises
    ------
    ModulationValidationError
        If parameters or source arrays are invalid for calculation.
    """

    _validate_config(config)
    solar = load_solar_without_bess(config.csv_path, config.mwac)
    generation_mwh = _generation_without_bess_mwh(solar)
    monthly_frames: list[pd.DataFrame] = []
    annual_rows: list[dict[str, float | int | str]] = []
    price_sources: dict[int, str] = {}

    for year in config.years:
        prices = load_price_series_for_year(
            year,
            config.submarket,
            config.pld_base_dir,
            config.bq_service_account_path,
        )
        price_sources[year] = prices.source
        monthly_frames.append(_monthly_for_year(generation_mwh, prices, config.mwac))
        annual_rows.append(_period_row_for_timestamps(generation_mwh, prices, config.mwac, None))

    monthly = pd.concat(monthly_frames, ignore_index=True)[list(MONTHLY_COLUMNS)]
    annual = pd.DataFrame(annual_rows)[list(ANNUAL_COLUMNS)]
    metadata = SourceMetadata(
        solar_csv_filename=solar.csv_filename,
        solar_fc=solar.fc,
        garantia_fisica_mw=solar.garantia_fisica_mw,
        price_sources=price_sources,
    )
    return ModulationResult(monthly=monthly, annual=annual, source_metadata=metadata)


def calculate_monthly_modulation(
    generation_mwh: np.ndarray,
    prices: PriceProfile,
    mwac: float,
) -> pd.DataFrame:
    """Calculate month-level modulation rows for one PLD year.

    Parameters
    ----------
    generation_mwh : numpy.ndarray
        Hourly solar generation without BESS in MWh, shape ``(8760,)``.
    prices : PriceProfile
        Hourly PLD prices in BRL/MWh, shape ``(8760,)``.
    mwac : float
        Plant AC capacity in MWac.

    Returns
    -------
    pandas.DataFrame
        Monthly table with one row per calendar month.

    Raises
    ------
    ModulationValidationError
        If arrays are not 8,760 points or a period has invalid totals.
    """

    series = _price_profile_to_series(prices)
    _validate_hourly_arrays(generation_mwh, prices.prices_brl_per_mwh)
    return _monthly_for_year(generation_mwh, series, mwac)


def calculate_annual_modulation(
    generation_mwh: np.ndarray,
    prices: PriceProfile,
    mwac: float,
) -> pd.DataFrame:
    """Calculate annual modulation for one PLD year.

    Parameters
    ----------
    generation_mwh : numpy.ndarray
        Hourly solar generation without BESS in MWh, shape ``(8760,)``.
    prices : PriceProfile
        Hourly PLD prices in BRL/MWh, shape ``(8760,)``.
    mwac : float
        Plant AC capacity in MWac.

    Returns
    -------
    pandas.DataFrame
        One-row annual summary table.
    """

    series = _price_profile_to_series(prices)
    _validate_hourly_arrays(generation_mwh, prices.prices_brl_per_mwh)
    return pd.DataFrame([_period_row_for_timestamps(generation_mwh, series, mwac, None)])[
        list(ANNUAL_COLUMNS)
    ]


def calculate_modulation_for_price_series(
    generation_mwh: np.ndarray,
    prices: HourlyPriceSeries,
    mwac: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Calculate monthly and annual modulation for timestamped PLD data.

    Parameters
    ----------
    generation_mwh : numpy.ndarray
        Annual solar generation without BESS in MWh, shape ``(8760,)``.
    prices : HourlyPriceSeries
        Timestamped observed PLD prices in BRL/MWh, complete or partial year.
    mwac : float
        Plant AC capacity in MWac.

    Returns
    -------
    tuple[pandas.DataFrame, pandas.DataFrame]
        Monthly table and one-row annual summary table.
    """

    monthly = _monthly_for_year(generation_mwh, prices, mwac)
    annual = pd.DataFrame([_period_row_for_timestamps(generation_mwh, prices, mwac, None)])[
        list(ANNUAL_COLUMNS)
    ]
    return monthly, annual


def _validate_config(config: ModulationConfig) -> None:
    if config.mwac <= 0:
        raise ModulationValidationError(f"MWac deve ser > 0; recebido {config.mwac}.")
    if not config.years:
        raise ModulationValidationError("Ao menos um ano de PLD deve ser informado.")
    if config.submarket.upper() not in VALID_SUBMARKETS:
        raise ModulationValidationError(
            f"Submercado inválido: {config.submarket}. Use um de {sorted(VALID_SUBMARKETS)}."
        )


def _generation_without_bess_mwh(solar: SolarProfile) -> np.ndarray:
    generation = solar.generation_lim_mw
    if generation is None:
        generation = solar.generation_mw
    arr = np.asarray(generation, dtype=np.float64)
    if arr.shape != (HOURS_PER_YEAR,):
        raise ModulationValidationError(
            f"Curva solar deve conter {HOURS_PER_YEAR} horas; recebido shape={arr.shape}."
        )
    if np.any(arr < 0):
        raise ModulationValidationError("Curva solar sem BESS contém valores negativos.")
    return arr.copy()


def _monthly_for_year(
    generation_mwh: np.ndarray,
    prices: HourlyPriceSeries,
    mwac: float,
) -> pd.DataFrame:
    _validate_price_series(generation_mwh, prices)
    rows: list[dict[str, float | int | str]] = []
    for month in sorted(set(prices.timestamps.month)):
        rows.append(_period_row_for_timestamps(generation_mwh, prices, mwac, int(month)))
    return pd.DataFrame(rows)[list(MONTHLY_COLUMNS)]


def _period_row_for_timestamps(
    annual_generation_mwh: np.ndarray,
    prices: HourlyPriceSeries,
    mwac: float,
    month: int | None,
) -> dict[str, float | int | str]:
    timestamps = prices.timestamps
    price_slice = prices.prices_brl_per_mwh
    if month is not None:
        mask = timestamps.month == month
        timestamps = timestamps[mask]
        price_slice = price_slice.loc[timestamps]
    generation_mwh = _generation_for_timestamps(
        annual_generation_mwh,
        prices.year,
        timestamps,
    )
    price_values = price_slice.to_numpy(dtype=np.float64)
    _validate_period(generation_mwh, price_values, prices.year, month)

    generation_total_mwh = float(np.sum(generation_mwh))
    weighted_revenue_brl = float(np.sum(generation_mwh * price_values))
    flat_price_brl_per_mwh = float(np.mean(price_values))

    # Modulação referenciada à garantia física (obrigação de entrega), não à
    # energia gerada. GF_mw = média horária da geração anual; a energia de GF do
    # período = GF_mw × horas do período. A energia injetada apenas abate o custo:
    #   modulação = PLD_médio − Σ(geração × PLD) / energia_GF
    # No agregado anual sem curtailment, energia_GF == geração total e o resultado
    # coincide com a captura ponderada pela geração; em meses de alta/baixa geração
    # a referência à GF revela a sobre/sub-entrega frente à obrigação.
    garantia_fisica_mw = float(np.mean(annual_generation_mwh))
    gf_energy_mwh = garantia_fisica_mw * len(generation_mwh)
    captured_price_brl_per_mwh = weighted_revenue_brl / gf_energy_mwh
    modulation_value_brl_per_mwh = (
        flat_price_brl_per_mwh - captured_price_brl_per_mwh
    )
    modulation_factor = captured_price_brl_per_mwh / flat_price_brl_per_mwh
    generation_per_mwac = generation_total_mwh / mwac

    row: dict[str, float | int | str] = {
        "year": prices.year,
        "hours": int(len(generation_mwh)),
        "generation_mwh": generation_total_mwh,
        "flat_price_brl_per_mwh": flat_price_brl_per_mwh,
        "captured_price_brl_per_mwh": captured_price_brl_per_mwh,
        "modulation_value_brl_per_mwh": modulation_value_brl_per_mwh,
        "weighted_revenue_brl": weighted_revenue_brl,
        "modulation_factor": modulation_factor,
        "generation_per_mwac_mwh_per_mwac": generation_per_mwac,
        "price_source": prices.source,
    }
    if month is not None:
        row["month"] = month
    return row


def _validate_hourly_arrays(generation_mwh: np.ndarray, prices_brl_per_mwh: np.ndarray) -> None:
    if generation_mwh.shape != (HOURS_PER_YEAR,):
        raise ModulationValidationError(
            f"Geração deve conter {HOURS_PER_YEAR} horas; recebido shape={generation_mwh.shape}."
        )
    if prices_brl_per_mwh.shape != (HOURS_PER_YEAR,):
        raise ModulationValidationError(
            f"PLD deve conter {HOURS_PER_YEAR} horas; recebido shape={prices_brl_per_mwh.shape}."
        )
    if np.any(generation_mwh < 0):
        raise ModulationValidationError("Geração contém valores negativos.")
    if np.any(prices_brl_per_mwh < 0):
        raise ModulationValidationError("PLD contém valores negativos.")


def _validate_price_series(generation_mwh: np.ndarray, prices: HourlyPriceSeries) -> None:
    if generation_mwh.shape != (HOURS_PER_YEAR,):
        raise ModulationValidationError(
            f"Geração deve conter {HOURS_PER_YEAR} horas; recebido shape={generation_mwh.shape}."
        )
    if prices.prices_brl_per_mwh.empty:
        raise ModulationValidationError(f"PLD {prices.year}: série observada vazia.")
    if len(prices.timestamps) != len(prices.prices_brl_per_mwh):
        raise ModulationValidationError(f"PLD {prices.year}: timestamps e preços desalinhados.")
    if not prices.timestamps.is_monotonic_increasing:
        raise ModulationValidationError(f"PLD {prices.year}: timestamps fora de ordem.")
    if np.any(generation_mwh < 0):
        raise ModulationValidationError("Geração contém valores negativos.")
    if (prices.prices_brl_per_mwh < 0).any():
        raise ModulationValidationError(f"PLD {prices.year}: preços negativos.")


def _validate_period(
    generation_mwh: np.ndarray,
    prices_brl_per_mwh: np.ndarray,
    year: int,
    month: int | None,
) -> None:
    label = f"{year}-{month:02d}" if month is not None else str(year)
    if len(generation_mwh) != len(prices_brl_per_mwh):
        raise ModulationValidationError(
            f"Período {label}: geração e PLD têm tamanhos diferentes."
        )
    if float(np.sum(generation_mwh)) <= 0:
        raise ModulationValidationError(f"Período {label}: geração total é zero.")
    if float(np.mean(prices_brl_per_mwh)) <= 0:
        raise ModulationValidationError(f"Período {label}: PLD médio é não positivo.")


def _hourly_index(year: int) -> pd.DatetimeIndex:
    index = pd.date_range(f"{year}-01-01 00:00:00", f"{year}-12-31 23:00:00", freq="h")
    leap_day = (index.month == 2) & (index.day == 29)
    return index[~leap_day]


def _price_profile_to_series(prices: PriceProfile) -> HourlyPriceSeries:
    timestamps = _hourly_index(prices.bq_year)
    return HourlyPriceSeries(
        year=prices.bq_year,
        submarket=prices.bq_submarket,
        timestamps=timestamps,
        prices_brl_per_mwh=pd.Series(prices.prices_brl_per_mwh, index=timestamps),
        source=prices.source,
    )


def _generation_for_timestamps(
    annual_generation_mwh: np.ndarray,
    year: int,
    timestamps: pd.DatetimeIndex,
) -> np.ndarray:
    expected = _hourly_index(year)
    positions = expected.get_indexer(timestamps)
    if (positions < 0).any():
        raise ModulationValidationError(f"PLD {year}: timestamp fora do ano esperado.")
    return annual_generation_mwh[positions]
