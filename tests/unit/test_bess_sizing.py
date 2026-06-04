"""Unit tests for GF-daily-coverage BESS block sizing (config.size_bess_blocks)."""

from __future__ import annotations

import math

import pytest

from solar_bess_risk.backtest import build_scenarios
from solar_bess_risk.config import (
    BESS_BLOCK_SPECS,
    PARAM_BOUNDS,
    SimulationParams,
    size_bess_blocks,
)


GF = 134.0
DURATION = 4


def _block(duration_h: int = DURATION):
    return BESS_BLOCK_SPECS[duration_h]


def test_legacy_power_sizing_when_target_none():
    """coverage_target_pct=None reproduces the legacy power-based block count."""
    block = _block()
    sizing = size_bess_blocks(GF, DURATION, None)

    expected_blocks = math.ceil(GF / block.block_power_mw)
    assert sizing.n_blocks == expected_blocks
    assert sizing.bess_power_mw == pytest.approx(expected_blocks * block.block_power_mw)
    assert sizing.bess_energy_mwh == pytest.approx(expected_blocks * block.block_energy_mwh)


def test_coverage_sizing_rounds_blocks_up():
    """A coverage target sizes by energy and rounds the block count up."""
    block = _block()
    target = 0.5
    sizing = size_bess_blocks(GF, DURATION, target)

    energy_target = target * GF * 24.0
    expected_blocks = math.ceil(energy_target / block.block_energy_mwh)
    assert sizing.n_blocks == expected_blocks
    assert sizing.bess_energy_mwh == pytest.approx(expected_blocks * block.block_energy_mwh)


def test_realized_coverage_at_least_target():
    """Because blocks are rounded up, realised coverage is never below the target."""
    for target in (0.05, 0.17, 0.5, 1.0, 2.0):
        sizing = size_bess_blocks(GF, DURATION, target)
        realized = sizing.bess_energy_mwh / (GF * 24.0)
        assert realized >= target - 1e-9


def test_higher_target_never_fewer_blocks():
    """Sizing is monotonic in the coverage target."""
    prev = 0
    for target in (0.1, 0.2, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0):
        n = size_bess_blocks(GF, DURATION, target).n_blocks
        assert n >= prev
        prev = n


def test_minimum_one_block():
    """A tiny target still yields at least one block."""
    sizing = size_bess_blocks(GF, DURATION, 1e-6)
    assert sizing.n_blocks >= 1


def test_build_scenarios_uses_legacy_sizing_by_default():
    """Default params (target None) keep the historical 54-block / 545.4 MWh sizing."""
    params = SimulationParams(csv_path="/tmp/solar.csv", mwac=450.0, usd_brl_rate=5.0)
    assert params.gf_daily_coverage_target_pct is None

    scenarios = build_scenarios(GF, params)
    by_dur = {s.duration_h: s for s in scenarios}

    legacy = size_bess_blocks(GF, 4, None)
    assert by_dur[4].bess_power_mw == pytest.approx(legacy.bess_power_mw)
    assert by_dur[4].bess_energy_mwh == pytest.approx(legacy.bess_energy_mwh)


def test_build_scenarios_honors_coverage_target():
    """A coverage target flows through build_scenarios into scenario energy."""
    params = SimulationParams(
        csv_path="/tmp/solar.csv",
        mwac=450.0,
        usd_brl_rate=5.0,
        gf_daily_coverage_target_pct=0.5,
    )
    scenarios = build_scenarios(GF, params)
    by_dur = {s.duration_h: s for s in scenarios}

    expected = size_bess_blocks(GF, 4, 0.5)
    assert by_dur[4].bess_energy_mwh == pytest.approx(expected.bess_energy_mwh)
    realized = by_dur[4].bess_energy_mwh / (GF * 24.0)
    assert realized >= 0.5 - 1e-9


def test_coverage_target_out_of_bounds_rejected():
    """SimulationParams validates the coverage target against PARAM_BOUNDS."""
    lo, hi = PARAM_BOUNDS["gf_daily_coverage_target_pct"]
    with pytest.raises(ValueError):
        SimulationParams(
            csv_path="/tmp/solar.csv",
            mwac=450.0,
            gf_daily_coverage_target_pct=hi + 0.5,
        )
