"""Unit tests for solar_bess_risk.profile module.

Tests written FIRST (TDD) — must FAIL until profile.py is implemented.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR, SimulationParams


class TestSyntheticProfile:
    """Synthetic pvlib-based profile generation."""

    def test_shape_is_8760(self):
        from solar_bess_risk.profile import generate_synthetic_profile

        params = SimulationParams()
        profile = generate_synthetic_profile(params)
        assert profile.generation_mw.shape == (HOURS_PER_YEAR,)

    def test_values_in_zero_one_range(self):
        from solar_bess_risk.profile import generate_synthetic_profile

        params = SimulationParams()
        profile = generate_synthetic_profile(params)
        assert np.all(profile.generation_mw >= 0.0)
        assert np.all(profile.generation_mw <= 1.0)

    def test_annual_sum_positive(self):
        from solar_bess_risk.profile import generate_synthetic_profile

        params = SimulationParams()
        profile = generate_synthetic_profile(params)
        assert profile.annual_energy_mwh > 0

    def test_deterministic_two_calls_identical(self):
        from solar_bess_risk.profile import generate_synthetic_profile

        params = SimulationParams()
        p1 = generate_synthetic_profile(params)
        p2 = generate_synthetic_profile(params)
        np.testing.assert_array_equal(p1.generation_mw, p2.generation_mw)

    def test_source_is_synthetic(self):
        from solar_bess_risk.profile import generate_synthetic_profile

        params = SimulationParams()
        profile = generate_synthetic_profile(params)
        assert profile.source == "synthetic"

    def test_annual_energy_matches_sum(self):
        from solar_bess_risk.profile import generate_synthetic_profile

        params = SimulationParams()
        profile = generate_synthetic_profile(params)
        assert abs(profile.annual_energy_mwh - float(np.sum(profile.generation_mw))) < 1e-10


class TestCSVLoader:
    """CSV solar profile loader."""

    def _write_csv(self, path: Path, values: list[str]) -> None:
        path.write_text("\n".join(values) + "\n")

    def test_valid_csv_loads(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv

        csv = tmp_path / "profile.csv"
        values = [f"{0.5}" for _ in range(HOURS_PER_YEAR)]
        self._write_csv(csv, values)
        profile = load_solar_csv(str(csv))
        assert profile.generation_mw.shape == (HOURS_PER_YEAR,)

    def test_wrong_row_count_rejected(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv

        csv = tmp_path / "bad.csv"
        values = [f"{0.5}" for _ in range(8761)]
        self._write_csv(csv, values)
        with pytest.raises(ValueError, match="8.760"):
            load_solar_csv(str(csv))

    def test_negative_value_rejected(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv

        csv = tmp_path / "neg.csv"
        values = [f"{0.5}" for _ in range(HOURS_PER_YEAR)]
        values[100] = "-0.5"
        self._write_csv(csv, values)
        with pytest.raises(ValueError, match="101"):  # 1-indexed row
            load_solar_csv(str(csv))

    def test_non_numeric_value_rejected(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv

        csv = tmp_path / "alpha.csv"
        values = [f"{0.5}" for _ in range(HOURS_PER_YEAR)]
        values[50] = "abc"
        self._write_csv(csv, values)
        with pytest.raises(ValueError, match="abc"):
            load_solar_csv(str(csv))

    def test_source_is_csv(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv

        csv = tmp_path / "ok.csv"
        values = [f"{0.5}" for _ in range(HOURS_PER_YEAR)]
        self._write_csv(csv, values)
        profile = load_solar_csv(str(csv))
        assert profile.source == "csv"

    def test_annual_energy_equals_sum(self, tmp_path):
        from solar_bess_risk.profile import load_solar_csv

        csv = tmp_path / "ok.csv"
        values = [f"{0.5}" for _ in range(HOURS_PER_YEAR)]
        self._write_csv(csv, values)
        profile = load_solar_csv(str(csv))
        expected = 0.5 * HOURS_PER_YEAR
        assert abs(profile.annual_energy_mwh - expected) < 1e-6
