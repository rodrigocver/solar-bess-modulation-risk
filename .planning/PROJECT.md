# PROJECT.md

## Project
Solar+BESS Modulation Risk Analysis Tool

## One-liner
A CLI tool that simulates a solar+BESS plant across three fixed dispatch scenarios and delivers a self-contained HTML report with interactive Plotly charts and full economic metrics in BRL.

## Problem
Renewable energy project engineers need to quantify the financial exposure from missing the physical guarantee (garantia física) during peak hours without BESS support — and evaluate whether a BESS investment reduces that exposure enough to justify the CAPEX. The analysis must be traceable, reproducible, and compliant with Brazilian sector norms (ANEEL/CCEE).

## Solution
The tool derives garantia física directly from an engineer-supplied solar CSV and MWac value, fetches mandatory hourly CCEE PLD prices from BigQuery, and runs three fixed BESS dispatch scenarios (A: 2 h, B: 3 h, C: 4 h) with vectorised NumPy simulation. It outputs a single offline HTML report (Plotly inline), a JSON run manifest with SHA-256 parameter fingerprint, and 10 economic metrics per scenario including coverage %, payback years, and annual savings in BRL.

## Stack
- **Python 3.11+** — CLI entry point via `python -m solar_bess_risk`
- **NumPy ≥ 1.26** — vectorised 8,760-step hourly dispatch arrays
- **Pandas ≥ 2.1** — CSV I/O and hourly time-series indexing
- **Plotly ≥ 5.20** — three interactive charts; `include_plotlyjs="inline"` (no CDN)
- **google-cloud-bigquery ≥ 3.10** — mandatory CCEE PLD price source; run aborts on failure
- **pytest ≥ 8.0 + pytest-cov** — TDD test suite (unit, contract, integration)
- **hashlib / json / pathlib** — stdlib; run manifest, SHA-256 input fingerprint, run-ID

## Constraints
- HTML report must be fully self-contained — no CDN references, no network required to open
- BigQuery is the sole price data source; no CSV fallback; run aborts immediately on BQ failure
- Solar CSV is required input (no synthetic profile); must have exactly 8,760 rows of non-negative numeric values
- garantia física is derived (`mwac × fc`), never entered as a parameter
- No module may exceed 400 lines; all public functions must have PEP 484 type annotations with unit suffixes
- No magic numbers — all constants live in `config.py`
- `bq_service_account_path` must be excluded from manifest.json and parameter SHA-256 hash entirely (not even as null)
- Output is deterministic: two runs with identical inputs must produce byte-identical numerical results

## Success Criteria
- Engineer can start tool, accept all defaults (except CSV path + MWac), and receive a complete HTML report in < 30 s (simulation scope)
- Invalid inputs (out-of-range, non-numeric, wrong CSV shape) are rejected with descriptive `ERRO:` messages and re-prompt without aborting
- BigQuery auth or network failure aborts run immediately with no partial output written
- HTML report contains exactly 3 Plotly charts (exposure bar, CAPEX vs savings bar, payback curve) and 2 tables (10-metric scenario summary + top-10 peak hours)
- All economic formulas match hand-calculated reference cases (exposure, payback, coverage %)
- SoC never violates bounds [0, bess_energy_mwh] across all 8,760 hours in all 3 scenarios
- Run manifest (manifest.json) is written per run with all required fields and deterministic SHA-256

## Source Docs
- specs/002-modulation-risk-tool/spec.md (SPEC)
- specs/002-modulation-risk-tool/plan.md (PRD)
- specs/002-modulation-risk-tool/data-model.md (SPEC)
- specs/002-modulation-risk-tool/research.md (ADR)
- specs/002-modulation-risk-tool/tasks.md (DOC)
