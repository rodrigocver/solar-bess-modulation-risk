# REQUIREMENTS.md

## Source
Ingested from `specs/002-modulation-risk-tool/spec.md` (v2 — Garantia Física Dispatch Model)

## Functional Requirements

### FR-001 — Parameter Configuration
- Engineer configures: CSV path (required), MWac (required), BQ submarket (default SE), BQ year (default 2025), CAPEX USD/kWh (default 200), USD/BRL rate (default 5.0), useful life years (default 20), BESS efficiency (default 85%), O&M (default 1.5%), degradation (default 2%/yr)
- All parameters display default inline; out-of-bounds values re-prompt without aborting
- `bq_service_account_path` via `--service-account` CLI flag; excluded from manifest and confirmation summary

### FR-002 — Solar Profile Load
- CSV: exactly 8,760 rows of non-negative floats; negatives clipped to zero (night-time noise)
- Garantia física = MWac × fc; fc = annual_energy_mwh / (MWac × 8760)
- Zero-energy profile raises StructuredError

### FR-003 — Price Data (BigQuery mandatory)
- `fetch_price_bigquery()` returns 8,760 hourly PLD prices in BRL/MWh
- Run aborts immediately on any BQ error — no fallback, no partial output

### FR-004 — Three-Scenario Simulation
- Scenario A: 2h BESS, peak hours {18, 19}
- Scenario B: 4h BESS, peak hours {17, 18, 19, 20}
- BESS charges only from solar excess above garantia física, non-peak hours only
- BESS discharges only during peak hours, to cover deficit below garantia física
- SoC bounds: [0, bess_energy_mwh] always enforced

### FR-005 — Economic Outputs
- Annual exposure without/with BESS (BRL/yr)
- Annual savings (BRL/yr)
- Undiscounted payback (years); "não atingível" if > useful_life_years
- BESS CAPEX in BRL (CAPEX USD/kWh × duration_h × bess_power_mw × 1000 × USD/BRL)
- O&M: 1.5% CAPEX/yr; degradation: 2%/yr applied to savings

### FR-006 — HTML Report
- Single self-contained HTML file with Plotly.js inline
- Three interactive charts + economic summary table
- Fully offline (no CDN dependencies)

### FR-007 — Reproducibility
- JSON manifest per run: tool_version, run_id, timestamp_iso8601, params_sha256, profile_source, price_source, fc, garantia_fisica_mw, scenarios
- `bq_service_account_path` absent from manifest entirely (not even as null)

## Non-Functional Requirements
- Performance: 3 scenarios complete in < 30s on dual-core 8 GB laptop
- No module > 400 lines
- All public functions PEP 484 type-annotated with unit suffixes
- No magic numbers — all constants in config.py
