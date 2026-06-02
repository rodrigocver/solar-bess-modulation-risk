from __future__ import annotations

import pandas as pd

from solar_monthly_modulation.cli import main


def test_cli_writes_expected_csvs(tmp_path):
    solar_csv = tmp_path / "solar.csv"
    rows = ["avg_generation"] + ["1.0"] * 8760
    solar_csv.write_text("\n".join(rows), encoding="utf-8")
    pld_dir = tmp_path / "pld"
    pld_dir.mkdir()

    records = []
    for timestamp in pd.date_range("2021-01-01 00:00:00", "2021-12-31 23:00:00", freq="h"):
        records.append(
            {
                "MES_REFERENCIA": int(timestamp.strftime("%Y%m")),
                "SUBMERCADO": "SUDESTE",
                "PERIODO_COMERCIALIZACAO": 1,
                "DIA": timestamp.strftime("%d"),
                "HORA": timestamp.hour,
                "PLD_HORA": 100.0,
            }
        )
    pd.DataFrame(records).to_csv(pld_dir / "pld_horario_2021.csv", sep=";", index=False)

    exit_code = main(
        [
            "--csv-path",
            str(solar_csv),
            "--mwac",
            "10",
            "--years",
            "2021",
            "--submarket",
            "SE",
            "--pld-base-dir",
            str(pld_dir),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )

    assert exit_code == 0
    run_dirs = list((tmp_path / "out").iterdir())
    assert len(run_dirs) == 1
    monthly = pd.read_csv(run_dirs[0] / "monthly_modulation.csv")
    annual = pd.read_csv(run_dirs[0] / "annual_summary.csv")

    assert len(monthly) == 12
    assert len(annual) == 1
    assert monthly["generation_mwh"].sum() == 8760.0
    assert annual.iloc[0]["modulation_factor"] == 1.0
    html = (run_dirs[0] / "report.html").read_text(encoding="utf-8")
    assert "Resultados Mês a Mês" in html
    assert "Agregado Anual" in html
    assert "Modulação (BRL/MWh)" in html
    assert (run_dirs[0] / "manifest.json").exists()
