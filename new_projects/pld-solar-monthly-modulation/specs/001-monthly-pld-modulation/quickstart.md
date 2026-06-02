# Quickstart: Monthly PLD Solar Modulation

## Run With Existing Data

From the Solar+BESS repository root:

```bash
PYTHONPATH=. python new_projects/pld-solar-monthly-modulation/src/solar_monthly_modulation/cli.py \
  --csv-path solar/solar_baguacu_m2_600mw_id14.csv \
  --mwac 600 \
  --years 2021 2022 2023 2024 2025 \
  --submarket SE \
  --output-dir output/monthly_modulation
```

## Run Tests

```bash
PYTHONPATH=. pytest new_projects/pld-solar-monthly-modulation/tests
```

## Expected Outputs

```text
output/monthly_modulation/<run-id>/
├── annual_summary.csv
├── manifest.json
└── monthly_modulation.csv
```
