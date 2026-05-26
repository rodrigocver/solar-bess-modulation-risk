"""Curtailment profile loader from XLSX data.

Functions
---------
load_curtailment_profile(path, sheet, col) -> np.ndarray
get_curtailment_for_scenario(year, enabled, path) -> np.ndarray | None
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from solar_bess_risk.config import (
    CURTAILMENT_COLUMN,
    CURTAILMENT_SHEET_2025,
    CURTAILMENT_SHEET_2026,
    DEFAULT_CURTAILMENT_PATH,
    HOURS_PER_YEAR,
)


def load_curtailment_profile(
    path: str,
    sheet: str,
    col: str = CURTAILMENT_COLUMN,
) -> np.ndarray:
    """Load a curtailment profile from an Excel sheet.

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
        # Try column by position (O = index 14)
        if df.shape[1] > 14:
            values = pd.to_numeric(df.iloc[:, 14], errors="coerce").fillna(0.0).to_numpy()
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

    # Take first 8760 values, clamp negatives to 0
    result = values[:HOURS_PER_YEAR].astype(np.float64)
    result = np.maximum(result, 0.0)
    return result


def get_curtailment_for_scenario(
    year: int,
    enabled: bool,
    solar_generation_mw: np.ndarray,
    path: str = DEFAULT_CURTAILMENT_PATH,
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

    Returns
    -------
    np.ndarray | None
        8760-element array in MW or None if curtailment disabled.
    """
    if not enabled:
        return None

    if year == 2026:
        sheet = CURTAILMENT_SHEET_2026
    else:
        # 2025 and accumulated use 2025_horario
        sheet = CURTAILMENT_SHEET_2025

    curtailment_pct = load_curtailment_profile(path, sheet)
    return curtailment_pct * solar_generation_mw
