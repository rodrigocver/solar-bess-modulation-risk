from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from solar_bess_risk.data_sources import PriceProfile

from solar_monthly_modulation.adapters import load_solar_without_bess
from solar_monthly_modulation.constants import HOURS_PER_YEAR
from solar_monthly_modulation.errors import ModulationValidationError
from solar_monthly_modulation.manifest import build_manifest
from solar_monthly_modulation.models import (
    HourlyPriceSeries,
    ModulationConfig,
    ModulationResult,
    SourceMetadata,
)
from solar_monthly_modulation.modulation import (
    calculate_annual_modulation,
    calculate_modulation_for_price_series,
    calculate_monthly_modulation,
)


def _prices(year: int = 2021) -> PriceProfile:
    arr = np.full(HOURS_PER_YEAR, 100.0)
    arr[0:744] = 200.0
    return PriceProfile(arr, f"local_pld_SE_{year}", "SE", year)


def test_monthly_modulation_uses_gf_referenced_price():
    generation = np.ones(HOURS_PER_YEAR)
    generation[0:744] = 2.0
    prices = _prices()

    monthly = calculate_monthly_modulation(generation, prices, mwac=10.0)
    january = monthly.loc[monthly["month"] == 1].iloc[0]

    # Modulação referenciada à garantia física: GF_mw = média horária anual,
    # energia de GF do mês = GF_mw × horas do mês; captura = receita / energia_GF.
    gf_mw = float(np.mean(generation))
    gf_energy_jan = gf_mw * 744
    expected_revenue = 1488.0 * 200.0
    expected_captured = expected_revenue / gf_energy_jan

    assert january["hours"] == 744
    assert january["generation_mwh"] == 1488.0
    assert january["flat_price_brl_per_mwh"] == 200.0
    assert january["captured_price_brl_per_mwh"] == expected_captured
    assert january["modulation_value_brl_per_mwh"] == 200.0 - expected_captured
    assert january["weighted_revenue_brl"] == expected_revenue
    assert january["modulation_factor"] == expected_captured / 200.0
    assert january["generation_per_mwac_mwh_per_mwac"] == 148.8


def test_annual_modulation_matches_manual_weighted_average():
    generation = np.ones(HOURS_PER_YEAR)
    prices_arr = np.full(HOURS_PER_YEAR, 100.0)
    prices_arr[:100] = 300.0
    prices = PriceProfile(prices_arr, "synthetic_reference", "SE", 2021)

    annual = calculate_annual_modulation(generation, prices, mwac=20.0).iloc[0]
    expected_revenue = float(np.sum(generation * prices_arr))
    expected_captured = expected_revenue / HOURS_PER_YEAR
    expected_flat = float(np.mean(prices_arr))

    assert annual["weighted_revenue_brl"] == expected_revenue
    assert annual["captured_price_brl_per_mwh"] == expected_captured
    assert annual["flat_price_brl_per_mwh"] == expected_flat
    assert annual["modulation_value_brl_per_mwh"] == expected_flat - expected_captured
    assert annual["modulation_factor"] == expected_captured / expected_flat


def test_zero_month_generation_raises_structured_error():
    generation = np.ones(HOURS_PER_YEAR)
    generation[0:744] = 0.0

    with pytest.raises(ModulationValidationError, match="2021-01"):
        calculate_monthly_modulation(generation, _prices(), mwac=10.0)


def test_partial_observed_price_series_uses_available_months_only():
    generation = np.ones(HOURS_PER_YEAR)
    timestamps = pd.date_range("2026-01-01 00:00:00", "2026-02-02 23:00:00", freq="h")
    prices = pd.Series(np.full(len(timestamps), 100.0), index=timestamps)
    series = HourlyPriceSeries(
        year=2026,
        submarket="SE",
        timestamps=timestamps,
        prices_brl_per_mwh=prices,
        source="bigquery_observed_pld_SE_2026",
    )

    monthly, annual = calculate_modulation_for_price_series(generation, series, mwac=10.0)

    assert monthly["month"].tolist() == [1, 2]
    assert monthly["hours"].tolist() == [744, 48]
    assert annual.iloc[0]["hours"] == 792
    assert annual.iloc[0]["generation_mwh"] == 792.0
    assert annual.iloc[0]["price_source"] == "bigquery_observed_pld_SE_2026"


def test_legacy_multi_year_avg_generation_loader_fallback(tmp_path):
    solar_csv = tmp_path / "legacy.csv"
    rows = [";month;day;hour;minute;avg_generation"]
    for index in range(HOURS_PER_YEAR * 2):
        hour = index % 24
        day = (index // 24) % 365 + 1
        rows.append(f"{index};1;{day};{hour};0;2.0")
    solar_csv.write_text("\n".join(rows), encoding="utf-8")

    solar = load_solar_without_bess(str(solar_csv), mwac=10.0)

    assert solar.n_years == 2
    assert solar.generation_mw.shape == (HOURS_PER_YEAR,)
    assert solar.annual_energy_mwh == HOURS_PER_YEAR * 2.0


def test_manifest_contains_hash_and_formulas(tmp_path):
    solar_csv = tmp_path / "solar.csv"
    solar_csv.write_text("generation\n1\n", encoding="utf-8")
    config = ModulationConfig(
        csv_path=str(solar_csv),
        mwac=1.0,
        years=(2021,),
        submarket="SE",
        pld_base_dir="dados/pld",
        output_dir=str(tmp_path),
    )
    result = ModulationResult(
        monthly=calculate_monthly_modulation(np.ones(HOURS_PER_YEAR), _prices(), 1.0),
        annual=calculate_annual_modulation(np.ones(HOURS_PER_YEAR), _prices(), 1.0),
        source_metadata=SourceMetadata(
            solar_csv_filename="solar.csv",
            solar_fc=1.0,
            garantia_fisica_mw=1.0,
            price_sources={2021: "local_pld_SE_2021"},
        ),
    )

    manifest = build_manifest(
        config,
        result,
        {"monthly_csv": "monthly.csv", "annual_csv": "annual.csv"},
        created_at="2026-06-01T00:00:00+00:00",
    )

    assert manifest["tool_version"]
    assert manifest["input_hashes"]["solar_csv_sha256"]
    assert "captured_price_brl_per_mwh" in manifest["formulas"]
    assert json.dumps(manifest)
