"""Round-trip efficiency (RTE) per year loader.

Functions
---------
load_rte_table(path, commissioning_year) -> dict[int, float]
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from solar_bess_risk.config import (
    DEFAULT_RTE_COMMISSIONING_YEAR,
    DEFAULT_RTE_PATH,
)

RTE_COLUMN = "RTE_PMI"
ANO_COLUMN = "Ano"
ENVISION_RTE_FILENAME = "11 - Envision.xlsx"
ENVISION_TYPICAL_BLOCK_MWH = 10.1
ENVISION_PCS_MVA = 2.52


def get_rte_metadata(path: str = DEFAULT_RTE_PATH) -> dict[str, float | str] | None:
    """Return fixed battery metadata for known RTE source files."""
    if Path(path).name == ENVISION_RTE_FILENAME:
        return {
            "rte_source_file": ENVISION_RTE_FILENAME,
            "typical_block_mwh": ENVISION_TYPICAL_BLOCK_MWH,
            "pcs_mva": ENVISION_PCS_MVA,
        }
    return None


def load_rte_table(
    path: str = DEFAULT_RTE_PATH,
    commissioning_year: int = DEFAULT_RTE_COMMISSIONING_YEAR,
) -> dict[int, float]:
    """Load per-year RTE from the Envision Excel file.

    The Excel column ``Ano`` is 0-based BESS age (0 = first year of operation).
    Calendar year = commissioning_year + Ano.

    Parameters
    ----------
    path : str
        Path to the Excel file (default: ``dados/11 - Envision.xlsx``).
    commissioning_year : int
        Calendar year when the BESS enters operation. Defaults to 2025.

    Returns
    -------
    dict[int, float]
        Mapping of calendar year → RTE_PMI (fraction, e.g. 0.862).

    Raises
    ------
    FileNotFoundError
        If the Excel file does not exist.
    ValueError
        If the required columns are missing.
    """
    try:
        df = pd.read_excel(path)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Arquivo de RTE não encontrado: '{path}'"
        )
    except Exception as exc:
        raise ValueError(f"Erro ao ler arquivo de RTE '{path}': {exc}") from exc

    missing = {ANO_COLUMN, RTE_COLUMN} - set(df.columns)
    if missing:
        raise ValueError(
            f"Colunas ausentes em '{path}': {sorted(missing)}. "
            f"Colunas disponíveis: {list(df.columns)}"
        )

    df = df[[ANO_COLUMN, RTE_COLUMN]].dropna()
    df[ANO_COLUMN] = pd.to_numeric(df[ANO_COLUMN], errors="coerce").astype("Int64")
    df[RTE_COLUMN] = pd.to_numeric(df[RTE_COLUMN], errors="coerce")
    df = df.dropna()

    return {
        int(commissioning_year + row[ANO_COLUMN]): float(row[RTE_COLUMN])
        for _, row in df.iterrows()
    }


def load_bess_degradation_df(path: str = DEFAULT_RTE_PATH) -> pd.DataFrame:
    """Load the Envision Excel file containing Ano, SOH, RTE_PMI columns.

    Parameters
    ----------
    path : str
        Path to the Excel file (default: ``dados/11 - Envision.xlsx``).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns 'Ano', 'SOH', 'RTE_PMI'.
    """
    try:
        df = pd.read_excel(path)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"Arquivo de RTE/degradação não encontrado: '{path}'"
        )
    except Exception as exc:
        raise ValueError(f"Erro ao ler arquivo de RTE/degradação '{path}': {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]
    required = {"Ano", "SOH", "RTE_PMI"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Colunas ausentes para degradação em '{path}': {sorted(missing)}. "
            f"Colunas disponíveis: {list(df.columns)}"
        )

    df = df[["Ano", "SOH", "RTE_PMI"]].dropna()
    df["Ano"] = pd.to_numeric(df["Ano"], errors="coerce")
    df["SOH"] = pd.to_numeric(df["SOH"], errors="coerce")
    df["RTE_PMI"] = pd.to_numeric(df["RTE_PMI"], errors="coerce")
    df = df.dropna()

    return df


def load_soh_table(
    path: str = DEFAULT_RTE_PATH,
    commissioning_year: int = DEFAULT_RTE_COMMISSIONING_YEAR,
) -> dict[int, float]:
    """Load per-year battery SOH from the Envision Excel file.

    The Excel column ``Ano`` is 0-based BESS age (0 = first year of operation).
    Calendar year = commissioning_year + Ano.
    """
    df = load_bess_degradation_df(path)
    return {
        int(commissioning_year + row["Ano"]): float(row["SOH"])
        for _, row in df.iterrows()
    }
