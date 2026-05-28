"""Unit tests for Excel report calculations."""

from __future__ import annotations

import numpy as np

from solar_bess_risk.config import HOURS_PER_YEAR
from solar_bess_risk.report_excel import _build_hourly_dataframe, _build_summary_row
from solar_bess_risk.simulation import DispatchResult


def test_curtailment_recuperado_pct_is_fraction_not_0_100_scale():
    """Recovered curtailment ratio must stay in the 0..1 scale."""
    generation = np.full(HOURS_PER_YEAR, 10.0)
    curtailment = np.zeros(HOURS_PER_YEAR)
    curtailment_lost = np.zeros(HOURS_PER_YEAR)
    curtailment[12] = 10.0
    curtailment_lost[12] = 3.0

    dispatch = DispatchResult(
        soc_mwh=np.zeros(HOURS_PER_YEAR),
        charge_mwh=np.zeros(HOURS_PER_YEAR),
        discharge_mwh=np.zeros(HOURS_PER_YEAR),
        grid_injection_mwh=generation.copy(),
        deficit_mwh=np.zeros(HOURS_PER_YEAR),
        residual_deficit_mwh=np.zeros(HOURS_PER_YEAR),
        curtailment_mwh=curtailment,
        curtailment_lost_mwh=curtailment_lost,
        carga_nao_realizada_diaria_mwh=np.zeros(365),
    )

    df = _build_hourly_dataframe(
        dispatch,
        np.full(HOURS_PER_YEAR, 100.0),
        garantia_fisica_mw=5.0,
        generation_mw=generation,
        peak_hours=frozenset({18, 19}),
        year_label=2026,
    )
    summary = _build_summary_row(
        df,
        garantia_fisica_mw=5.0,
        duration_h=2,
        usd_brl_rate=5.0,
        mwac=10.0,
        dispatch=dispatch,
    )

    assert df.loc[12, "curtailment_recuperado_pct"] == 0.7
    assert summary["curtailment_recuperado_pct"] == 0.7
    assert df["curtailment_recuperado_pct"].max() <= 1.0


def test_curtailment_recuperado_pct_is_clipped_to_one():
    """Data anomalies cannot push recovered curtailment ratio above 1."""
    generation = np.full(HOURS_PER_YEAR, 10.0)
    curtailment = np.zeros(HOURS_PER_YEAR)
    curtailment_lost = np.zeros(HOURS_PER_YEAR)
    curtailment[12] = 10.0
    curtailment_lost[12] = -2.0

    dispatch = DispatchResult(
        soc_mwh=np.zeros(HOURS_PER_YEAR),
        charge_mwh=np.zeros(HOURS_PER_YEAR),
        discharge_mwh=np.zeros(HOURS_PER_YEAR),
        grid_injection_mwh=generation.copy(),
        deficit_mwh=np.zeros(HOURS_PER_YEAR),
        residual_deficit_mwh=np.zeros(HOURS_PER_YEAR),
        curtailment_mwh=curtailment,
        curtailment_lost_mwh=curtailment_lost,
        carga_nao_realizada_diaria_mwh=np.zeros(365),
    )

    df = _build_hourly_dataframe(
        dispatch,
        np.full(HOURS_PER_YEAR, 100.0),
        garantia_fisica_mw=5.0,
        generation_mw=generation,
        peak_hours=frozenset({18, 19}),
        year_label=2026,
    )

    assert df.loc[12, "curtailment_recuperado_pct"] == 1.0
