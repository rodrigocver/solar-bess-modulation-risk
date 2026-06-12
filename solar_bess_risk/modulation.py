"""Modulation metric — captured-price premium (energy) or cost (garantia física).

Single source of truth for the modulação scalar (R$/MWh). Two modes are
supported, selected by ``SimulationParams.modulation_mode``:

- ``"energia"`` (default): energy-weighted capture premium

      mod = Σ(injeção_h × PLD_h) / Σ(injeção_h) − PLD_médio

  Positive = the plant captures *above* the simple average price (good).

- ``"garantia_fisica"`` (legacy): cost referenced to the physical-guarantee
  energy

      mod = PLD_médio − Σ(injeção_h × PLD_h) / energia_GF

  Positive = the plant captures *below* the average referenced to the delivery
  obligation (cost).
"""

from __future__ import annotations

import numpy as np

from solar_bess_risk.config import (
    DEFAULT_MODULATION_MODE,
    MODULATION_MODE_ENERGIA,
    MODULATION_MODE_GARANTIA_FISICA,
    VALID_MODULATION_MODES,
)


def modulation_value_brl_per_mwh(
    injection_mwh: np.ndarray,
    pld_brl_per_mwh: np.ndarray,
    gf_energy_mwh: float,
    mode: str = DEFAULT_MODULATION_MODE,
) -> float | None:
    """Return the modulation metric in BRL/MWh for the selected mode.

    Parameters
    ----------
    injection_mwh : np.ndarray
        Hourly grid injection (or generation) in MWh.
    pld_brl_per_mwh : np.ndarray
        Hourly PLD in BRL/MWh.
    gf_energy_mwh : float
        Garantia física energy over the period (GF_mw × horas). Only used by the
        ``"garantia_fisica"`` mode.
    mode : str
        ``"energia"`` (default) or ``"garantia_fisica"``.

    Returns
    -------
    float | None
        Modulation in BRL/MWh, or ``None`` when the relevant normaliser
        (injected energy in ``"energia"`` mode, GF energy in
        ``"garantia_fisica"`` mode) is zero.

    Raises
    ------
    ValueError
        If ``mode`` is not a recognised modulation mode.
    """
    if mode not in VALID_MODULATION_MODES:
        raise ValueError(
            f"modulation_mode={mode!r} inválido; use um de "
            f"{sorted(VALID_MODULATION_MODES)}."
        )

    injection = np.asarray(injection_mwh, dtype=np.float64)
    pld = np.asarray(pld_brl_per_mwh, dtype=np.float64)

    if mode == MODULATION_MODE_ENERGIA:
        total_injection = float(np.sum(injection))
        if total_injection <= 1e-10:
            return None
        captured = float(np.sum(injection * pld) / total_injection)
        return float(captured - np.mean(pld))

    # MODULATION_MODE_GARANTIA_FISICA (legacy)
    if gf_energy_mwh <= 1e-10:
        return None
    captured_vs_gf = float(np.sum(injection * pld) / gf_energy_mwh)
    return float(np.mean(pld) - captured_vs_gf)


__all__ = [
    "modulation_value_brl_per_mwh",
    "MODULATION_MODE_ENERGIA",
    "MODULATION_MODE_GARANTIA_FISICA",
]
