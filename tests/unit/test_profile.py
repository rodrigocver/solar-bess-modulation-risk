"""Unit tests for solar_bess_risk.profile — CSV loader and garantia física (v2)."""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR


@pytest.fixture
def valid_csv(tmp_path) -> str:
    """Create a valid 8760-row CSV with deterministic values."""
    csv_path = tmp_path / "solar.csv"
    values = []
    for h in range(HOURS_PER_YEAR):
        hour_of_day = h % 24
        if 6 <= hour_of_day <= 18:
            values.append(f"{50.0 + 30.0 * np.sin(np.pi * (hour_of_day - 6) / 12):.4f}")
        else:
            values.append("0.0000")
    csv_path.write_text("\n".join(values))
    return str(csv_path)


class TestLoadSolarCSV:
    """Tests for load_solar_csv function."""

    def test_shape_is_8760(self, valid_csv):
        from solar_bess_risk.profile import load_solar_csv
        profile = load_solar_csv(valid_csv, mwac=100.0)
        assert profile.generation_mw.shape == (HOURS_PER_YEAR,)

    def test_all_values_non_negative(self, valid_csv):
        from solar_bess_risk.profile import load_solar_csv
        profile = load_solar_csv(valid_csv, mwac=100.0)
        assert np.all(profile.generation_mw >= 0)

    def test_annual_energy_equals_sum(self, valid_csv):
        from solar_bess_risk.profile import load_solar_csv
        profile = load_solar_csv(valid_csv, mwac=100.0)
        assert abs(profile.annual_energy_mwh - float(np.sum(profile.generation_mw))) < 1e-10

    def test_fc_formula(self, valid_csv):
        from solar_bess_risk.profile import load_solar_csv
        mwac = 100.0
        profile = load_solar_csv(valid_csv, mwac=mwac)
        expected_fc = profile.annual_energy_mwh / (mwac * HOURS_PER_YEAR)
        assert abs(profile.fc - expected_fc) < 1e-10

    def test_garantia_fisica_formula(self, valid_csv):
        from solar_bess_risk.profile import load_solar_csv
        mwac = 100.0
        profile = load_solar_csv(valid_csv, mwac=mwac)
        expected_gf = mwac * profile.fc
        assert abs(profile.garantia_fisica_mw - expected_gf) < 1e-10

    def test_csv_filename_is_basename(self, valid_csv):
        from solar_bess_risk.profile import load_solar_csv
        profile = load_solar_csv(valid_csv, mwac=100.0)
        assert profile.csv_filename == os.path.basename(valid_csv)

    def test_rejects_wrong_row_count(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("\n".join("1.0" for _ in range(100)))
        with pytest.raises(ValueError, match="8760|8.760"):
            load_solar_csv(str(bad_csv), mwac=100.0)

    def test_rejects_non_numeric_row(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv
        bad_csv = tmp_path / "nan.csv"
        values = ["1.0"] * HOURS_PER_YEAR
        values[42] = "hello"
        bad_csv.write_text("\n".join(values))
        with pytest.raises(ValueError, match="42|43"):
            load_solar_csv(str(bad_csv), mwac=100.0)

    def test_clamps_negative_row_to_zero(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv
        bad_csv = tmp_path / "neg.csv"
        values = ["1.0"] * HOURS_PER_YEAR
        values[10] = "-5.0"
        bad_csv.write_text("\n".join(values))
        profile = load_solar_csv(str(bad_csv), mwac=100.0)
        assert profile.generation_mw[10] == 0.0
        assert np.all(profile.generation_mw >= 0)

    def test_zero_energy_profile_raises(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv, StructuredError
        zero_csv = tmp_path / "zero.csv"
        zero_csv.write_text("\n".join("0.0" for _ in range(HOURS_PER_YEAR)))
        with pytest.raises((ValueError, RuntimeError, StructuredError)):
            load_solar_csv(str(zero_csv), mwac=100.0)
