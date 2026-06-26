# PLD Solar Monthly Modulation

Command-line tool for monthly modulation analysis of a solar generation curve without BESS against historical hourly PLD from 2021 onward.

The project intentionally reuses the existing `solar_bess_risk` package as a read-only dependency for solar CSV loading and local PLD validation. No existing Solar+BESS source files are modified.

## Quick Start

From the repository root:

```bash
PYTHONPATH=. python historico_modulacao/src/solar_monthly_modulation/cli.py \
  --csv-path solar/solar_baguacu_m2_600mw_id14.csv \
  --mwac 600 \
  --years 2021 2022 2023 2024 2025 2026 \
  --submarket SE \
  --output-dir output/monthly_modulation
```

Outputs are written to a run-specific directory containing:

- `monthly_modulation.csv`
- `annual_summary.csv`
- `report.html`
- `manifest.json`

## Main Metric

For each month:

```text
captured_price_brl_per_mwh = sum(generation_mwh * pld_brl_per_mwh) / sum(generation_mwh)
flat_price_brl_per_mwh = mean(pld_brl_per_mwh)
modulation_factor = captured_price_brl_per_mwh / flat_price_brl_per_mwh
```

All energy quantities use MWh and all prices use BRL/MWh.

Years after the local CSV archive, such as 2026, are read from observed BigQuery PLD data and may be partial. The `hours` column shows the number of observed hours included in each monthly or annual aggregation.
