"""Contract tests for CLI schema v2 per contracts/cli-schema.md.

Tests written FIRST (TDD) — verify the external CLI interface contract.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from solar_bess_risk.config import (
    DEFAULT_BESS_O_AND_M_PCT_CAPEX,
    DEFAULT_BQ_SUBMARKET,
    DEFAULT_BQ_YEAR,
    DEFAULT_LCOE_DISCOUNT_RATE,
    DEFAULT_USD_BRL_RATE,
    DEFAULT_USEFUL_LIFE_YR,
    HOURS_PER_YEAR,
    SimulationParams,
)


@pytest.fixture
def valid_csv(tmp_path) -> str:
    """Create a valid 8760-row solar CSV."""
    csv_path = tmp_path / "solar.csv"
    values = np.random.uniform(0, 100, HOURS_PER_YEAR)
    csv_path.write_text("\n".join(f"{v:.2f}" for v in values))
    return str(csv_path)


class TestCT01DefaultValues:
    """CT-01: Enter at non-required prompts → defaults accepted."""

    def test_all_defaults_accepted(self, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: csv, 2025 curtailment target, GF coverage target, accept defaults.
        inputs = [valid_csv, "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, curtailment, _, _ = run_session()

        assert params.csv_path == valid_csv
        assert params.mwac == 600.0
        assert params.bq_submarket == DEFAULT_BQ_SUBMARKET
        assert params.bq_year == DEFAULT_BQ_YEAR
        assert params.usd_brl_rate == DEFAULT_USD_BRL_RATE
        assert params.bess_o_and_m_pct_capex == DEFAULT_BESS_O_AND_M_PCT_CAPEX
        assert params.useful_life_years == DEFAULT_USEFUL_LIFE_YR
        assert params.lcoe_discount_rate == DEFAULT_LCOE_DISCOUNT_RATE
        assert curtailment is True


class TestCT02OutOfBounds:
    """CT-02: Out-of-bounds value → ERRO message cites parameter, value, range; re-prompts."""

    def test_out_of_bounds_usd_brl_reprompts(self, capsys, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: csv, defaults through coverage, decline defaults, MWac,
        # submarket, usd=999(OOB), valid, then remaining defaults
        # (rte, life, o&m, lcoe, charge_mode, modulation_mode, curt2026).
        inputs = [
            valid_csv, "", "", "n", "100", "", "999", "5.7",
            "", "", "", "", "", "", "",
        ]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        assert params.usd_brl_rate == 5.7
        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT03NonNumeric:
    """CT-03: Non-numeric value → ERRO + reprompt."""

    def test_non_numeric_reprompts(self, capsys, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: csv, defaults through coverage, decline defaults,
        # MWac=abc then 100, rest defaults
        # (submarket, usd, rte, life, o&m, lcoe, charge_mode, modulation_mode, curt2026).
        inputs = [valid_csv, "", "", "n", "abc", "100", "", "", "", "", "", "", "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        assert params.mwac == 100.0
        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT04WrongRowCount:
    """CT-04: 8761-row solar CSV → rejected with message citing actual and expected count."""

    def test_wrong_row_count_rejected(self, capsys, tmp_path, valid_csv):
        from solar_bess_risk.cli import run_session

        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("\n".join("1.0" for _ in range(8761)))

        # Sequence: bad csv, defaults, then recovery prompts valid csv + MWac.
        inputs = [str(bad_csv), "", "", "", valid_csv, "100"]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        captured = capsys.readouterr()
        assert "8761" in captured.out or "8.761" in captured.out
        assert "8760" in captured.out or "8.760" in captured.out


class TestCT05NegativeCSVValue:
    """CT-05: Negative value in CSV → value is clamped to zero with a warning."""

    def test_negative_value_is_clamped(self, capsys, tmp_path):
        from solar_bess_risk.cli import run_session

        bad_csv = tmp_path / "neg.csv"
        values = ["1.0"] * HOURS_PER_YEAR
        values[42] = "-5.0"
        bad_csv.write_text("\n".join(values))

        # Sequence: csv, 2025 curtailment target, GF coverage target, accept defaults.
        inputs = [str(bad_csv), "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        captured = capsys.readouterr()
        assert params.csv_path == str(bad_csv)
        assert "negativos" in captured.out.lower()
        assert "zero" in captured.out.lower()


class TestCT06NonNumericCSV:
    """CT-06: Non-numeric value in CSV → ERRO cites row index and value."""

    def test_non_numeric_csv_rejected(self, capsys, tmp_path, valid_csv):
        from solar_bess_risk.cli import run_session

        bad_csv = tmp_path / "nan.csv"
        values = ["1.0"] * HOURS_PER_YEAR
        values[10] = "hello"
        bad_csv.write_text("\n".join(values))

        inputs = [str(bad_csv), "", "", "", valid_csv, "100"]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT07MissingCSVPath:
    """CT-07: Missing CSV path → run aborts with descriptive error."""

    def test_nonexistent_csv_reprompts(self, capsys, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: bad path, valid csv, defaults.
        inputs = ["/nonexistent/file.csv", valid_csv, "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT08BQAuthFailure:
    """CT-08: BQ auth failure → DataSourceError propagates, run aborts."""

    def test_bq_auth_failure_raises(self):
        from solar_bess_risk.data_sources import DataSourceError, fetch_price_bigquery

        params = SimulationParams(
            csv_path="/tmp/test.csv",
            mwac=100.0,
            bq_service_account_path="/nonexistent/key.json",
        )
        with pytest.raises(DataSourceError):
            fetch_price_bigquery(params)


class TestCT09BQWrongRowCount:
    """CT-09: BQ returns ≠ 8760 rows → aborts with actual vs expected count."""

    def test_bq_wrong_row_count(self):
        from solar_bess_risk.data_sources import DataSourceError, fetch_price_bigquery

        params = SimulationParams(csv_path="/tmp/test.csv", mwac=100.0)

        # Mock BQ returning wrong number of rows
        mock_rows = [{"pld": 100.0, "datetime": "2025-01-01T00:00:00"}] * 100
        with patch("solar_bess_risk.data_sources._get_bigquery_module") as mock_bq:
            mock_client = MagicMock()
            mock_bq.return_value.Client.return_value = mock_client
            mock_bq.return_value.QueryJobConfig = MagicMock
            mock_bq.return_value.ScalarQueryParameter = MagicMock
            mock_client.query.return_value = mock_rows
            with pytest.raises(DataSourceError, match="8760|8.760"):
                fetch_price_bigquery(params)


class TestCT10MWacNonPositive:
    """CT-10: MWac ≤ 0 → rejected with ERRO + reprompt."""

    def test_zero_mwac_rejected(self, capsys, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: csv, defaults through coverage, decline defaults,
        # mwac=0, mwac=-5, mwac=100, then remaining defaults
        # (submarket, usd, rte, life, o&m, lcoe, charge_mode, modulation_mode, curt2026).
        inputs = [valid_csv, "", "", "n", "0", "-5", "100", "", "", "", "", "", "", "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        assert params.mwac == 100.0
        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT11ConfirmationSummary:
    """CT-11: Confirmation summary shows fc and garantia_fisica_mw."""

    def test_summary_shows_fc_and_gf(self, capsys, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: csv, 2025 curtailment target, GF coverage target, accept defaults.
        inputs = [valid_csv, "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session()

        captured = capsys.readouterr()
        # Summary should mention fc and garantia física
        assert "fc" in captured.out.lower() or "fator" in captured.out.lower()
        assert "garantia" in captured.out.lower()
        assert "5.8" in captured.out
        assert "1.25%" in captured.out


class TestCT12ServiceAccountAbsent:
    """CT-12: bq_service_account_path absent from confirmation summary and manifest."""

    def test_sa_path_not_in_summary(self, capsys, valid_csv):
        from solar_bess_risk.cli import run_session

        # Sequence: csv, 2025 curtailment target, GF coverage target, accept defaults.
        inputs = [valid_csv, "", "", ""]
        with patch("builtins.input", side_effect=inputs):
            params, _, _, _ = run_session(service_account_path="/secret/key.json")

        captured = capsys.readouterr()
        assert "/secret/key.json" not in captured.out
        assert "service_account_path" not in captured.out.lower()


class TestCT13FixedMustMw:
    """CT-13: --must-mw is interpreted as final contracted MUST in MW."""

    def test_must_mw_flag_converts_to_reduction_fraction(self):
        from solar_bess_risk.__main__ import (
            _fixed_must_reduction_pct,
            _parse_fixed_must_mw,
        )

        must_mw = _parse_fixed_must_mw(["prog", "--must-mw", "540"])

        assert must_mw == 540.0
        assert _fixed_must_reduction_pct(
            fixed_must_mw=must_mw,
            mwac=600.0,
        ) == pytest.approx(0.10)

    def test_must_mw_above_project_mwac_is_rejected(self):
        from solar_bess_risk.__main__ import _fixed_must_reduction_pct

        with pytest.raises(ValueError, match="--must-mw"):
            _fixed_must_reduction_pct(fixed_must_mw=650.0, mwac=600.0)
