"""Unit tests for the centralized modulation metric (energia vs garantia física)."""

from __future__ import annotations

import numpy as np
import pytest

from solar_bess_risk.config import (
    MODULATION_MODE_ENERGIA,
    MODULATION_MODE_GARANTIA_FISICA,
)
from solar_bess_risk.modulation import modulation_value_brl_per_mwh


def test_energia_mode_matches_user_identity():
    """energia = Σ(G·PLD)/ΣG − mean(PLD) == Σ((G−Gbar)·PLD)/ΣG."""
    rng = np.random.default_rng(42)
    gen = rng.uniform(0.0, 100.0, size=8760)
    pld = rng.uniform(50.0, 800.0, size=8760)

    value = modulation_value_brl_per_mwh(gen, pld, gf_energy_mwh=123.0, mode=MODULATION_MODE_ENERGIA)

    gbar = gen.mean()
    expected = float(np.sum((gen - gbar) * pld) / np.sum(gen))
    assert value == pytest.approx(expected, rel=1e-9)


def test_energia_mode_ignores_gf_energy():
    """The energia mode must not depend on the GF energy argument."""
    rng = np.random.default_rng(7)
    gen = rng.uniform(0.0, 100.0, size=8760)
    pld = rng.uniform(50.0, 800.0, size=8760)

    v1 = modulation_value_brl_per_mwh(gen, pld, gf_energy_mwh=1.0, mode=MODULATION_MODE_ENERGIA)
    v2 = modulation_value_brl_per_mwh(gen, pld, gf_energy_mwh=9e9, mode=MODULATION_MODE_ENERGIA)
    assert v1 == pytest.approx(v2, rel=1e-12)


def test_energia_is_negative_of_gf_when_gf_energy_equals_injected():
    """With energia_GF == Σinjeção, the two modes are exact negatives."""
    rng = np.random.default_rng(1)
    gen = rng.uniform(0.0, 100.0, size=8760)
    pld = rng.uniform(50.0, 800.0, size=8760)
    gf_energy = float(np.sum(gen))

    energia = modulation_value_brl_per_mwh(gen, pld, gf_energy, MODULATION_MODE_ENERGIA)
    gf = modulation_value_brl_per_mwh(gen, pld, gf_energy, MODULATION_MODE_GARANTIA_FISICA)
    assert energia == pytest.approx(-gf, rel=1e-9)


def test_energia_positive_when_capturing_above_average():
    """Generating only in the most expensive hours yields a positive premium."""
    gen = np.zeros(8760)
    pld = np.full(8760, 100.0)
    # Generate only where PLD is high.
    gen[:100] = 10.0
    pld[:100] = 500.0

    value = modulation_value_brl_per_mwh(gen, pld, gf_energy_mwh=1000.0, mode=MODULATION_MODE_ENERGIA)
    assert value is not None and value > 0


def test_both_modes_linear_in_pld():
    """Doubling PLD doubles the modulation in either mode."""
    rng = np.random.default_rng(3)
    gen = rng.uniform(0.0, 100.0, size=8760)
    pld = rng.uniform(50.0, 800.0, size=8760)
    gf_energy = 5000.0

    for mode in (MODULATION_MODE_ENERGIA, MODULATION_MODE_GARANTIA_FISICA):
        base = modulation_value_brl_per_mwh(gen, pld, gf_energy, mode)
        doubled = modulation_value_brl_per_mwh(gen, 2.0 * pld, gf_energy, mode)
        assert doubled == pytest.approx(2.0 * base, rel=1e-9)


def test_energia_returns_none_for_zero_injection():
    gen = np.zeros(8760)
    pld = np.full(8760, 100.0)
    assert modulation_value_brl_per_mwh(gen, pld, 1000.0, MODULATION_MODE_ENERGIA) is None


def test_gf_returns_none_for_zero_gf_energy():
    gen = np.ones(8760)
    pld = np.full(8760, 100.0)
    assert modulation_value_brl_per_mwh(gen, pld, 0.0, MODULATION_MODE_GARANTIA_FISICA) is None


def test_invalid_mode_raises():
    gen = np.ones(8760)
    pld = np.full(8760, 100.0)
    with pytest.raises(ValueError):
        modulation_value_brl_per_mwh(gen, pld, 1000.0, "invalid_mode")
