"""Contract tests for CLI schema per contracts/cli-schema.md.

Tests written FIRST (TDD) — must FAIL until cli.py is implemented.
These tests verify the external CLI interface contract.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from solar_bess_risk.config import (
    DEFAULT_BESS_SIZE_RATIOS_PCT,
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
    HOURS_PER_YEAR,
    SimulationParams,
)


class TestCT01DefaultValues:
    """CT-01: Pressing Enter at every prompt produces exact default values."""

    def test_all_defaults_accepted(self):
        from solar_bess_risk.cli import run_session

        # Simulate Enter at every prompt (empty strings)
        inputs = [""] * 30  # more than enough Enter presses
        with patch("builtins.input", side_effect=inputs):
            params = run_session()

        assert params.ilr_values == DEFAULT_ILR_VALUES
        assert params.bess_size_ratios_pct == DEFAULT_BESS_SIZE_RATIOS_PCT
        assert params.storage_durations_h == DEFAULT_STORAGE_DURATIONS_H
        assert params.rte_pct == DEFAULT_RTE_PCT
        assert params.degradation_pct_yr == DEFAULT_DEGRADATION_PCT_YR
        assert params.capex_usd_per_kwh == DEFAULT_CAPEX_USD_PER_KWH
        assert params.usd_brl_rate == DEFAULT_USD_BRL_RATE
        assert params.useful_life_yr == DEFAULT_USEFUL_LIFE_YR
        assert params.discount_rate_pct == DEFAULT_DISCOUNT_RATE_PCT
        assert params.min_soc_threshold_pct == DEFAULT_MIN_SOC_THRESHOLD_PCT
        assert params.min_injection_floor_mw == DEFAULT_MIN_INJECTION_FLOOR_MW
        assert params.bq_submarket == DEFAULT_BQ_SUBMARKET
        assert params.bq_year == DEFAULT_BQ_YEAR
        assert params.bq_auth_method == "adc"


class TestCT02OutOfBounds:
    """CT-02: Out-of-bounds value triggers ERRO and re-prompts."""

    def test_out_of_bounds_rte_reprompts(self, capsys):
        from solar_bess_risk.cli import prompt_float

        # First give 150 (out of range), then give valid 85
        inputs = iter(["150", "85"])
        with patch("builtins.input", side_effect=inputs):
            val = prompt_float("Eficiência round-trip", "%", 85.0, 0.01, 100.0)
        assert val == 85.0
        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT03NonNumeric:
    """CT-03: Non-numeric value at float prompt triggers ERRO and re-prompts."""

    def test_non_numeric_reprompts(self, capsys):
        from solar_bess_risk.cli import prompt_float

        inputs = iter(["abc", "85"])
        with patch("builtins.input", side_effect=inputs):
            val = prompt_float("Eficiência round-trip", "%", 85.0, 0.01, 100.0)
        assert val == 85.0
        captured = capsys.readouterr()
        assert "ERRO" in captured.out


class TestCT10CapexCurrencies:
    """CT-10: Confirmation summary shows CAPEX in both USD/kWh and BRL/kWh."""

    def test_capex_dual_currency_in_summary(self):
        from solar_bess_risk.cli import format_confirmation_summary

        params = SimulationParams()
        summary = format_confirmation_summary(params)
        assert "USD/kWh" in summary
        assert "BRL/kWh" in summary


class TestCT15ServiceAccountAbsent:
    """CT-15: Service account path absent from confirmation summary."""

    def test_sa_path_not_in_summary(self):
        from solar_bess_risk.cli import format_confirmation_summary

        params = SimulationParams(
            bq_auth_method="service_account",
            bq_service_account_path="/secret/key.json",
        )
        summary = format_confirmation_summary(params)
        assert "/secret/key.json" not in summary
        assert "service_account_path" not in summary.lower()
