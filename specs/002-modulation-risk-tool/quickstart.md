# Quickstart: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Date**: 2026-05-15

---

## Prerequisites

- Python 3.11 or higher
- A virtual environment (recommended)

```bash
python3 --version   # must be ≥ 3.11
```

---

## Install

```bash
# Clone / navigate to repo root
cd /path/to/solar-bess-modulation-risk

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Linux / macOS
# .venv\Scripts\activate.bat       # Windows

# Install dependencies
pip install -r requirements.txt
```

**`requirements.txt`** (minimum versions):
```
numpy>=1.26
pandas>=2.1
plotly>=5.20
pvlib>=0.10
google-cloud-bigquery>=3.10
pytest>=8.0
pytest-cov>=4.1
```

> **Note**: `google-cloud-bigquery` is required and must be authenticated before running.
> BigQuery is the only price data source; the run aborts with an error if unavailable.

---

## BigQuery Authentication

The tool fetches real CCEE PLD hourly prices from BigQuery when available.
Two authentication methods are supported.

### Option A — Application Default Credentials (ADC, recommended)

For GCP workstations, Cloud Shell, or machines with `gcloud` installed:

```bash
gcloud auth application-default login
```

Then run the tool normally. When prompted:
```
Usar BigQuery para preços PLD reais (CCEE)? (S/n): S
Método de autenticação BigQuery [adc/service_account] (padrão adc): [Enter]
Projeto de faturação GCP (padrão cver-solar): [Enter]
```

### Option B — Service Account JSON Key

For CI/CD pipelines or machines without `gcloud`:

```bash
# Set the path when prompted, or pass via CLI flag:
python -m solar_bess_risk --service-account /path/to/key.json
```

When prompted:
```
Método de autenticação BigQuery [adc/service_account] (padrão adc): service_account
Caminho do arquivo JSON da conta de serviço: /path/to/key.json
```

> The service account path is **never** logged, embedded in the HTML report, or
> included in the run manifest. Only the method label (`"service_account"`) is recorded.

---

## Run (default — all defaults, synthetic profile)

```bash
python -m solar_bess_risk
```

Press **Enter** at every prompt to accept all defaults. The tool will:

1. Load the synthetic pvlib solar profile (lat=−22°, lon=−45°, Ineichen clearsky)
2. Fetch BigQuery PLD prices (SE submarket, year 2025)
3. Simulate 44 scenarios (11 BESS sizes × 4 ILRs, duration = 2 h)
4. Ask which scenario to display in the heatmap (Enter = first option)
5. Write the HTML report and JSON manifest to `output/<run-id>/`

**Expected output**:
```
Solar+BESS Modulation Risk Analysis Tool v1.0.0
...
Simulating 44 scenarios...
[44/44] ILR=1.5 | BESS=100.0% | Duração=2.0h ✓
Simulation complete. Runtime: ~XX s

Generating report...
  output/20260515-143005-a1b2c3d/report.html
  output/20260515-143005-a1b2c3d/manifest.json

Done. Open report.html in any browser (works offline).
```

---

## Run with Custom Solar Profile CSV

The solar CSV must have exactly **8,760 rows**, one non-negative `float` value per row
(power in MW, normalised to your plant's MWac — the tool works with 1 MWac).

```
# my_solar.csv — no header
0.000
0.000
...
0.821
...
```

```bash
python -m solar_bess_risk
# When prompted:
#   Carregar perfil solar de CSV? (s/N): s
#   Caminho do CSV do perfil solar: /path/to/my_solar.csv
```

---

## Open the Report

After the run completes:

```bash
# Linux
xdg-open output/<run-id>/report.html

# macOS
open output/<run-id>/report.html
```

The HTML file is **fully self-contained** — all charts and data are embedded inline.
It works offline and requires no internet connection or additional software.

---

## Run Tests

```bash
# All tests with coverage
pytest --cov=solar_bess_risk tests/

# Unit tests only
pytest tests/unit/

# Contract tests only
pytest tests/contract/

# Integration (full run, creates output/)
pytest tests/integration/
```

Expected: all tests pass before any implementation task is marked complete.

---

## Project Structure (Quick Reference)

```
solar_bess_risk/
├── __main__.py      # Entry point; accepts --service-account flag
├── config.py        # All defaults, bounds, constants
├── cli.py           # Interactive prompting loop
├── profile.py       # Solar profile loading (synthetic + CSV)
├── data_sources.py  # BigQuery PLD price fetcher (mandatory)
├── simulation.py    # BESS dispatch engine
├── economics.py     # LCOS, revenue, payback
├── report_charts.py # Plotly chart builders (4 functions)
├── report_export.py # HTML assembly, summary tables, file writer
└── manifest.py      # Run manifest and SHA-256

tests/
├── unit/            # Per-module unit tests (TDD — written first)
├── integration/     # End-to-end run test
└── contract/        # CLI schema contract tests

output/              # Runtime-generated; add to .gitignore
```

---

## Reproduce a Previous Run

Every run writes a `manifest.json` with the full parameter SHA-256. To reproduce:

1. Copy the `params_sha256` from `manifest.json`.
2. Re-run the tool with the same parameters and the same `rng_seed`.
3. Identical manifest → byte-identical numerical results (SC-003).

---

## Scale Results to Your Plant

All outputs are **normalised to 1 MWac**. To scale to a 120 MWac plant:

- MWh/year values × 120
- BRL/year values × 120
- LCOS (BRL/MWh) and CF (%) are already dimensionless — no scaling needed.
- Payback (years) — no scaling needed (CAPEX and revenue scale equally).

This scaling note appears in the "Premissas e Limitações" section of the HTML report.
