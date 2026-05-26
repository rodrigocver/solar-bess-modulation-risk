# Implementation Plan: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Date**: 2026-05-15 | **Spec**: [spec.md](spec.md)

**Model version**: v2 — Garantia Física Dispatch (replaces curtailment-based model)

## Summary

A command-line Python tool that simulates a solar+BESS plant hour-by-hour across 3 fixed
scenarios (A/B/C) and delivers a single self-contained HTML report with three Plotly-based
interactive charts and a full economic summary table. The physical guarantee (garantia
física) is derived from the engineer-supplied solar CSV and MWac; it is NOT an input
parameter. BESS charging occurs only from solar excess above garantia física; BESS
discharging occurs only during the requested guarantee windows (18:00-20:00 /
17:00-20:00 / 17:00-21:00) to cover deficit below garantia física. Economic outputs —
exposure without/with BESS, savings, payback, coverage — are in BRL using a configurable
USD/BRL exchange rate for CAPEX, configurable round-trip efficiency (`rte`, default 0.85),
1.5% annual O&M over CAPEX, and 2% annual degradation by default.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- `numpy` ≥ 1.26 — vectorised hourly simulation arrays
- `pandas` ≥ 2.1 — CSV I/O, hourly time-series indexing
- `plotly` ≥ 5.20 — three interactive charts + self-contained HTML export (`include_plotlyjs="inline"`)
- `google-cloud-bigquery` ≥ 3.10 — real hourly PLD price data from CCEE table; mandatory (run aborts on unavailability)
- `pytest` ≥ 8.0 + `pytest-cov` — TDD test suite
- `hashlib`, `json`, `pathlib` — stdlib; run manifest, SHA-256 input hash, run-ID
- No web framework, no database, no GUI. No pvlib (no synthetic profile needed).

**Storage**: Local filesystem only — `output/<run-id>/report.html` + `manifest.json`; input CSVs read from user-specified paths

**Testing**: `pytest` with `pytest-cov`; reference-case tests for every economic formula; property tests for SoC bounds

**Target Platform**: Linux/macOS CLI; Python 3.11+ virtualenv

**Project Type**: CLI tool (single entry-point `python -m solar_bess_risk`)

**Performance Goals**: 3 scenarios complete in < 30 s on dual-core 8 GB laptop; vectorised NumPy dispatch loops preferred

**Constraints**: HTML report fully offline (`include_plotlyjs="inline"`); deterministic output; no magic numbers; no module > 400 lines; all public functions type-annotated with unit suffixes

**Scale/Scope**: 8,760 hourly values × 3 scenarios = ~26 k simulation steps; single-process

## Constitution Check

*Verify compliance with all Core Principles and Domain Constraints:*

- [x] **I. Brazilian Sector Compliance** — Garantia física defined per ANEEL/CCEE convention. CCEE PLD price source. All outputs reference applicable norm.
- [x] **II. No Data Fabrication** — Every default parameter documented with value and unit (FR-001). No synthetic profile. CSV filename logged in manifest and report.
- [x] **III. Test-First** — TDD enforced: failing tests written before dispatch, economics, and profile code. Reference-case tests for exposure, payback, and coverage formulas.
- [x] **IV. Reproducible Results** — JSON manifest written per run: tool version, ISO 8601 timestamp, SHA-256 of serialised parameter set, profile source (CSV filename), fc, garantia_fisica_mw, scenario definitions.
- [x] **V. Modular Python Architecture** — No module > 400 lines; public functions have PEP 484 type annotations with unit suffixes; constants in `config.py`; no circular imports.
- [x] **VI. Engineering-Quality Visualizations** — All three Plotly charts: title, axis labels with units, legend; hover tooltips with value + unit.
- [x] **VII. SI Units & Brazilian Sector Conventions** — Power: MW; energy: MWh; currency: BRL/yr; CAPEX: USD/kWh → BRL via exchange rate. Unit labels on every output.

**Gate result**: ✅ PASS

## Project Structure

### Source Code

```text
solar_bess_risk/
├── __init__.py
├── __main__.py          # Entry point: python -m solar_bess_risk
├── config.py            # All defaults, bounds, physical constants, scenario definitions
├── cli.py               # Interactive parameter prompting loop
├── profile.py           # CSV loader + garantia física computation
├── data_sources.py      # BigQuery PLD price fetcher (mandatory; DataSourceError aborts run)
├── simulation.py        # Hour-by-hour BESS dispatch engine (vectorised NumPy)
├── economics.py         # Exposure, savings, payback, coverage formulas
├── report_charts.py     # Plotly figure builders (4 chart/table functions)
├── report_export.py     # HTML assembly, summary table, top-10 hours table, file writer
└── manifest.py          # Run-ID, JSON manifest writer, SHA-256 hashing

tests/
├── unit/
│   ├── test_profile.py       # CSV loader: shape, non-negative, garantia física formula
│   ├── test_simulation.py    # SoC bounds, power limits, charge/discharge rules
│   ├── test_economics.py     # Exposure, savings, payback, coverage reference cases
│   ├── test_data_sources.py  # BQ price fetcher: auth, row validation, DataSourceError
│   └── test_manifest.py      # Manifest fields, SHA-256 reproducibility
├── integration/
│   └── test_full_run.py      # Default config end-to-end: 3 scenarios, HTML written
└── contract/
    └── test_cli_schema.py    # Parameter validation bounds contract
```

## Data Model

### Core Dataclasses

```python
@dataclass
class SimulationParams:
    csv_path: str               # required — no default
    mwac: float                 # required — no default
    bq_year: int = 2025
    bq_submarket: str = "SE"
    capex_usd_per_kwh: float = 200.0
    usd_brl_rate: float = 5.0
    useful_life_years: int = 20
    rte: float = 0.85           # round-trip efficiency for h-rule check
    bq_service_account_path: str | None = None  # excluded from SHA-256

@dataclass
class SolarProfile:
    generation_mw: np.ndarray   # shape (8760,), all ≥ 0
    annual_energy_mwh: float
    fc: float                   # annual_energy_mwh / (mwac * 8760)
    garantia_fisica_mw: float   # mwac * fc
    csv_filename: str

@dataclass
class PriceProfile:
    prices_brl_per_mwh: np.ndarray  # shape (8760,), all ≥ 0
    source: str                     # "bigquery_pld_{submarket}_{year}"
    bq_submarket: str
    bq_year: int

@dataclass
class ScenarioDefinition:
    label: str                  # "A", "B", or "C"
    peak_hours: frozenset[int]  # e.g. {17, 18, 19, 20}
    duration_h: int             # 2, 3, or 4
    bess_power_mw: float        # = garantia_fisica_mw
    bess_energy_mwh: float      # = garantia_fisica_mw * duration_h
    capex_brl: float

@dataclass
class DispatchResult:
    soc_mwh: np.ndarray         # shape (8760,), SoC at end of each hour
    charge_mwh: np.ndarray      # shape (8760,)
    discharge_mwh: np.ndarray   # shape (8760,)  (= dispatch to grid in peak hours)
    grid_injection_mwh: np.ndarray  # shape (8760,)
    deficit_mwh: np.ndarray     # shape (8760,), >0 only in peak hours
    residual_deficit_mwh: np.ndarray  # shape (8760,), deficit not covered by BESS

@dataclass
class ScenarioResult:
    scenario: ScenarioDefinition
    dispatch: DispatchResult
    fc: float
    garantia_fisica_mw: float
    bess_energy_mwh: float
    bess_power_mw: float
    capex_brl: float
    annual_exposure_without_bess_brl: float
    annual_exposure_with_bess_brl: float
    annual_savings_brl: float
    payback_years: float | None   # None if annual_savings ≤ 0
    coverage_pct: float           # 0-100
```

### Three Fixed Scenarios (defined in config.py)

| Label | peak_hours         | duration_h |
|-------|--------------------|------------|
| A     | {18: 1.0, 19: 1.0}                    | 2          |
| B     | {17: 1.0, 18: 1.0, 19: 1.0} | 3          |
| C     | {17: 1.0, 18: 1.0, 19: 1.0, 20: 1.0} | 4 |

For each: `bess_power_mw = garantia_fisica_mw`, `bess_energy_mwh = garantia_fisica_mw × duration_h`

### Dispatch Rules (per FR-006)

**Pre-computation per scenario**: `min_PLD_peak = min(prices[h] for h where h%24 IN peak_hours)`

**Each hour h (0..8759)**:
- `hour_of_day = h % 24`
- If `generation_h > garantia_fisica_mw` and `hour_of_day NOT in peak_hours`:
  - `excess_h = generation_h − garantia_fisica_mw`
  - h-rule: if `rte × min_PLD_peak > prices[h]`:
    - `charge_h = min(excess_h, bess_energy_mwh − soc_h)`  *(no bess_power_mw cap on charge)*
    - `soc_{h+1} = soc_h + charge_h`
    - `grid_injection_h = generation_h − charge_h`
  - else (h-rule fails — sell excess directly):
    - `charge_h = 0`; `soc_{h+1} = soc_h`; `grid_injection_h = generation_h`
- Elif `hour_of_day IN peak_hours`:
  - `deficit_h = max(0, garantia_fisica_mw − generation_h)`
  - `dispatch_h = min(deficit_h, bess_power_mw, soc_h)`  *(discharge still capped by bess_power_mw)*
  - `residual_deficit_h = deficit_h − dispatch_h`
  - `soc_{h+1} = soc_h − dispatch_h`
  - `grid_injection_h = generation_h + dispatch_h`
- Else (idle):
  - `soc_{h+1} = soc_h`
  - `grid_injection_h = generation_h`

**Invariants**: `0 ≤ soc_h ≤ bess_energy_mwh`; `charge_h × discharge_h = 0` (never both in same hour)

### Economic Formulas (per FR-007, FR-008)

```
annual_exposure_without_bess = Σ(deficit_h × PLD_h)            for h in the guarantee window
annual_exposure_with_bess    = Σ(residual_deficit_h × PLD_h)   for h in the guarantee window
annual_savings               = exposure_without − exposure_with
payback_years                = capex_brl / annual_savings       (None if annual_savings ≤ 0)
coverage_pct                 = (1 − exposure_with/exposure_without) × 100
capex_brl                    = bess_energy_mwh × capex_usd_per_kwh × 1000 × usd_brl_rate
```

## Implementation Strategy

**MVP scope (Phases 1–4)**: Engineer can configure, load CSV, fetch BQ prices, run 3 simulations, receive HTML report.

**Phase order**: Setup → Foundational → US1 (config+profile) → US2 (simulation) → US3 (economics) → US4 (report) → Polish

## Complexity Tracking

| Module | Projected Lines | Justification |
|--------|----------------|---------------|
| `report_charts.py` | ~300 | 3 chart builders + top-10 table |
| `report_export.py` | ~200 | HTML assembly + summary table + writer |
| `simulation.py` | ~200 | 3-scenario loop + dispatch + invariant checks |
