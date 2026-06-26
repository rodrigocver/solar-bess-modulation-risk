"""Export reusable Aurora curtailment curves for Seriemas cluster_23.

The Aurora databook is monthly by scenario/cluster. This script exports:

- an annual weighted-average curtailment curve for Low/Central/High;
- a monthly curve with CNF/ENE/total splits.

Both outputs use ``CURTAILMENT_MWH / CAN_PRODUCTION`` as the average cut metric.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
INPUT_PATH = ROOT / "dados" / "Aurora_Q2_26_BRA_Grid_Curtailment_Forecast_Data.xlsx"
OUTPUT_ANNUAL = ROOT / "dados" / "aurora_seriemas_cluster23_curtailment_annual.csv"
OUTPUT_MONTHLY = ROOT / "dados" / "aurora_seriemas_cluster23_curtailment_monthly.csv"

SCENARIO_SHEETS = {
    "low": "Low Scenario",
    "central": "Central Scenario",
    "high": "High Scenario",
}

TARGET_CLUSTER = "cluster_23"


def _load_sheet(sheet_name: str) -> pd.DataFrame:
    df = pd.read_excel(INPUT_PATH, sheet_name=sheet_name, header=1)
    unnamed = [col for col in df.columns if str(col).startswith("Unnamed")]
    return df.drop(columns=unnamed, errors="ignore")


def _aggregate(df: pd.DataFrame, group_cols: list[str], scenario: str) -> pd.DataFrame:
    grouped = (
        df.groupby(group_cols, dropna=False)[
            ["CAN_PRODUCTION", "CURTAILMENT_MWH_CNF", "CURTAILMENT_MWH_ENE", "CURTAILMENT_MWH"]
        ]
        .sum()
        .reset_index()
    )
    grouped.insert(0, "scenario", scenario)
    grouped["curtailment_pct"] = grouped["CURTAILMENT_MWH"] / grouped["CAN_PRODUCTION"]
    grouped["curtailment_cnf_pct"] = grouped["CURTAILMENT_MWH_CNF"] / grouped["CAN_PRODUCTION"]
    grouped["curtailment_ene_pct"] = grouped["CURTAILMENT_MWH_ENE"] / grouped["CAN_PRODUCTION"]
    return grouped.rename(
        columns={
            "YEAR": "year",
            "MONTH": "month",
            "CAN_PRODUCTION": "can_production_mwh",
            "CURTAILMENT_MWH_CNF": "curtailment_cnf_mwh",
            "CURTAILMENT_MWH_ENE": "curtailment_ene_mwh",
            "CURTAILMENT_MWH": "curtailment_mwh",
        }
    )


def build_curves() -> tuple[pd.DataFrame, pd.DataFrame]:
    annual_frames: list[pd.DataFrame] = []
    monthly_frames: list[pd.DataFrame] = []
    for scenario, sheet_name in SCENARIO_SHEETS.items():
        df = _load_sheet(sheet_name)
        cluster = df[df["CLUSTER"].astype(str).str.lower() == TARGET_CLUSTER].copy()
        annual_frames.append(_aggregate(cluster, ["YEAR"], scenario))
        monthly_frames.append(_aggregate(cluster, ["YEAR", "MONTH"], scenario))
    annual = pd.concat(annual_frames, ignore_index=True)
    monthly = pd.concat(monthly_frames, ignore_index=True)
    return annual, monthly


def main() -> None:
    annual, monthly = build_curves()
    annual.to_csv(OUTPUT_ANNUAL, index=False)
    monthly.to_csv(OUTPUT_MONTHLY, index=False)
    print(f"Annual: {OUTPUT_ANNUAL}")
    print(f"Monthly: {OUTPUT_MONTHLY}")
    summary = annual.groupby("scenario").apply(
        lambda g: pd.Series(
            {
                "mean_curtailment_pct": g["curtailment_mwh"].sum() / g["can_production_mwh"].sum(),
                "mean_cnf_pct": g["curtailment_cnf_mwh"].sum() / g["can_production_mwh"].sum(),
                "mean_ene_pct": g["curtailment_ene_mwh"].sum() / g["can_production_mwh"].sum(),
            }
        ),
        include_groups=False,
    )
    print(summary.round(4).to_string())


if __name__ == "__main__":
    main()
