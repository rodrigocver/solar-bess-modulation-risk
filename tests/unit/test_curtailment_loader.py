"""Tests for selectable curtailment curve loading and scaling."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from solar_bess_risk.config import HOURS_PER_YEAR
from solar_bess_risk.curtailment import (
    get_curtailment_for_scenario,
    load_curtailment_profile,
)


def test_load_curtailment_csv_uses_rate_fraction(tmp_path):
    path = tmp_path / "curtailment.csv"
    rows = ["hour_of_year;curtailment_rate;curtailment_pct"]
    rows.extend(f"{i};0.25;25" for i in range(HOURS_PER_YEAR))
    path.write_text("\n".join(rows), encoding="utf-8")

    profile = load_curtailment_profile(str(path), "ignored-for-csv")

    assert profile.shape == (HOURS_PER_YEAR,)
    assert np.all(profile == pytest.approx(0.25))


def test_load_curtailment_csv_converts_pct_column(tmp_path):
    path = tmp_path / "curtailment_pct.csv"
    rows = ["hour_of_year;curtailment_pct"]
    rows.extend(f"{i};12.5" for i in range(HOURS_PER_YEAR))
    path.write_text("\n".join(rows), encoding="utf-8")

    profile = load_curtailment_profile(str(path), "ignored-for-csv")

    assert np.all(profile == pytest.approx(0.125))


def test_scaled_curtailment_is_capped_at_100_percent(tmp_path):
    path = tmp_path / "curtailment.csv"
    rows = ["hour_of_year;curtailment_rate"]
    rows.extend(f"{i};0.80" for i in range(HOURS_PER_YEAR))
    path.write_text("\n".join(rows), encoding="utf-8")
    generation = np.full(HOURS_PER_YEAR, 10.0)

    series = get_curtailment_for_scenario(
        2025,
        True,
        generation,
        path=str(path),
        factor_2025=2.0,
    )

    assert series is not None
    assert np.max(series) == pytest.approx(10.0)


def test_load_curtailment_xlsx_defaults_to_pereira_barreto_column(tmp_path):
    path = tmp_path / "curtailment.xlsx"
    rows = HOURS_PER_YEAR
    df = pd.DataFrame(
        {
            "Media Agregada Todas as Usinas": np.full(rows, 0.99),
            "Conj. Pereira Barreto": np.full(rows, 0.12),
        }
    )
    df.to_excel(path, sheet_name="2025_horario", index=False)

    profile = load_curtailment_profile(str(path), "2025_horario")

    assert np.all(profile == pytest.approx(0.12))
