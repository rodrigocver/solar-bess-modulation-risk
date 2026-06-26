# Research: Monthly PLD Solar Modulation

## Decision: Reuse existing loaders as adapters

**Rationale**: `solar_bess_risk.profile.load_solar_csv` already validates generation length, clamps small negative generation to zero, handles single and dual-column files, and computes capacity factor. `solar_bess_risk.data_sources.load_price_local_pld` already validates local CCEE PLD CSV files and normalizes leap years to 8,760 hours.

**Alternatives considered**: Rewriting CSV and PLD parsing was rejected because it would duplicate validated logic and increase divergence from the current project.

## Decision: Report captured price and modulation factor by month

**Rationale**: Captured price is the generation-weighted PLD. The modulation factor is captured price divided by flat PLD, which directly expresses premium or discount against the simple monthly market average.

**Alternatives considered**: Reporting only revenue was rejected because it hides whether the result comes from profile shape or total generation volume.

## Decision: CSV-first outputs with manifest

**Rationale**: CSV files satisfy the immediate analytical workflow and can be opened in spreadsheet tools. A JSON manifest satisfies reproducibility without requiring a heavier HTML report.

**Alternatives considered**: HTML and Excel outputs were deferred to keep v1 scoped and avoid introducing new formatting dependencies.
