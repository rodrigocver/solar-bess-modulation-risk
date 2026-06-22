"""Curtailment profile loader from CSV/XLSX data.

Functions
---------
load_curtailment_profile(path, sheet, col) -> np.ndarray
get_curtailment_for_scenario(year, enabled, path) -> np.ndarray | None
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from solar_bess_risk.config import (
    CURTAILMENT_COLUMN,
    CURTAILMENT_SHEET_2025,
    DEFAULT_CURTAILMENT_PATH,
    HOURS_PER_YEAR,
)


def _normalise_fraction(values: np.ndarray, *, label: str, is_percent: bool = False) -> np.ndarray:
    """Return curtailment values as fractions clipped to the physical interval."""
    result = values.astype(np.float64)
    result = np.maximum(result, 0.0)
    if is_percent or (result.size and float(np.nanmax(result)) > 1.0):
        if result.size and float(np.nanmax(result)) > 100.0:
            raise ValueError(
                f"Curtailment '{label}' possui valor acima de 100% "
                f"({float(np.nanmax(result)):.4f})."
            )
        result = result / 100.0
    return np.minimum(result, 1.0)


def _load_curtailment_csv(path: str) -> np.ndarray:
    """Load an 8760-hour curtailment fraction profile from CSV."""
    try:
        df = pd.read_csv(path, sep=None, engine="python")
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Arquivo de curtailment não encontrado: '{path}'"
        )
    except Exception as exc:
        raise ValueError(f"Erro ao ler CSV de curtailment '{path}': {exc}") from exc

    preferred = ("curtailment_rate", "curtailment_fraction", "curtailment_pct")
    column = next((name for name in preferred if name in df.columns), None)
    if column is None:
        numeric_columns = [
            col for col in df.columns
            if pd.to_numeric(df[col], errors="coerce").notna().sum() == len(df)
        ]
        if len(numeric_columns) == 1:
            column = numeric_columns[0]
        else:
            raise ValueError(
                f"CSV de curtailment '{path}' deve conter uma coluna "
                "'curtailment_rate' ou 'curtailment_pct'. "
                f"Colunas disponíveis: {list(df.columns)}"
            )

    values = pd.to_numeric(df[column], errors="coerce").fillna(0.0).to_numpy()
    if len(values) < HOURS_PER_YEAR:
        raise ValueError(
            f"Curtailment CSV '{path}': {len(values)} linhas, "
            f"esperado >= {HOURS_PER_YEAR}."
        )
    return _normalise_fraction(
        values[:HOURS_PER_YEAR],
        label=f"{path}:{column}",
        is_percent=column.endswith("_pct"),
    )


def load_curtailment_profile(
    path: str,
    sheet: str,
    col: str = CURTAILMENT_COLUMN,
) -> np.ndarray:
    """Load a curtailment profile from a CSV file or Excel sheet.

    Parameters
    ----------
    path : str
        Path to the Excel file.
    sheet : str
        Sheet name to read.
    col : str
        Column name containing curtailment as a fraction (0.0–1.0, e.g. 0.05 = 5%).

    Returns
    -------
    np.ndarray
        Array of shape (8760,) with curtailment as a fraction per hour.
        Multiply by solar generation MW to get curtailment in MW.

    Raises
    ------
    FileNotFoundError
        If the Excel file does not exist.
    ValueError
        If the column is missing or row count != 8760.
    """
    suffix = Path(path).suffix.lower()
    if suffix == ".csv":
        return _load_curtailment_csv(path)

    try:
        df = pd.read_excel(path, sheet_name=sheet)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Arquivo de curtailment não encontrado: '{path}'"
        )
    except Exception as exc:
        raise ValueError(
            f"Erro ao ler aba '{sheet}' de '{path}': {exc}"
        ) from exc

    if col not in df.columns:
        # Try column by position (L = index 11), current Pereira Barreto source.
        if df.shape[1] > 11:
            values = pd.to_numeric(df.iloc[:, 11], errors="coerce").fillna(0.0).to_numpy()
        else:
            raise ValueError(
                f"Coluna '{col}' não encontrada na aba '{sheet}' de '{path}'. "
                f"Colunas disponíveis: {list(df.columns)}"
            )
    else:
        values = pd.to_numeric(df[col], errors="coerce").fillna(0.0).to_numpy()

    if len(values) < HOURS_PER_YEAR:
        raise ValueError(
            f"Curtailment aba '{sheet}': {len(values)} linhas, esperado >= {HOURS_PER_YEAR}."
        )

    return _normalise_fraction(values[:HOURS_PER_YEAR], label=f"{path}:{sheet}:{col}")


def _scale_curtailment_profile(curtailment_pct: np.ndarray, factor: float) -> np.ndarray:
    """Apply a target factor without allowing hourly curtailment above 100%."""
    scaled = np.asarray(curtailment_pct, dtype=np.float64) * factor
    if np.any(scaled > 1.0):
        max_before = float(np.max(scaled))
        print(
            "  AVISO: curva de curtailment fatorada excedeu 100% em algumas horas "
            f"(máx. {max_before * 100:.1f}%). Limitando a 100%."
        )
    return np.clip(scaled, 0.0, 1.0)


def get_curtailment_for_scenario(
    year: int,
    enabled: bool,
    solar_generation_mw: np.ndarray,
    path: str = DEFAULT_CURTAILMENT_PATH,
    factor_2026: float = 1.0,
    factor_2025: float = 1.0,
) -> np.ndarray | None:
    """Get the curtailment profile in MW for a given backtest year.

    Parameters
    ----------
    year : int
        Backtest year (2025, 2026, or any acumulado year → uses 2025 sheet).
    enabled : bool
        Whether curtailment analysis is active.
    solar_generation_mw : np.ndarray
        Solar generation array (8760,) in MW. Used to convert pct→MW.
    path : str
        Path to curtailment Excel file.
    factor_2026 : float
        Scalar multiplier applied to the 2025 realized ONS curtailment profile
        to build the 2026 profile (= target 2026 % / realized 2025 %).  Only
        applied when ``year == 2026``.
    factor_2025 : float
        Scalar multiplier applied to the 2025 realized ONS curtailment profile
        so its annual curtailment/generation ratio reaches the configured 2025
        target (= target 2025 % / realized 2025 %).  Applied to ``year == 2025``
        and accumulated years (which anchor on the 2025 shape).

    Returns
    -------
    np.ndarray | None
        8760-element array in MW or None if curtailment disabled.
    """
    if not enabled:
        return None

    # 2025, 2026 and accumulated years all anchor on the 2025 realized ONS shape.
    # For 2026 the profile is scaled by ``factor_2026`` so the annual
    # curtailment/generation ratio reaches the configured 2026 target. For 2025
    # (and accumulated years) ``factor_2025`` scales it to the 2025 target.
    curtailment_pct = load_curtailment_profile(path, CURTAILMENT_SHEET_2025)
    if year == 2026 and factor_2026 != 1.0:
        curtailment_pct = _scale_curtailment_profile(curtailment_pct, factor_2026)
    elif year != 2026 and factor_2025 != 1.0:
        curtailment_pct = _scale_curtailment_profile(curtailment_pct, factor_2025)
    return curtailment_pct * solar_generation_mw
