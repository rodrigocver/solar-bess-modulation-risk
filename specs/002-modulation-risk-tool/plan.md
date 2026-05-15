# Implementation Plan: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Date**: 2026-05-15 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/002-modulation-risk-tool/spec.md`

## Summary

A command-line Python tool that simulates a solar+BESS plant hour-by-hour across 44 scenarios
(11 BESS energy size ratios × 4 ILR values × configurable storage durations) and delivers
a single self-contained HTML report with four Plotly-based interactive charts and a full
economic summary table. BESS sizing is expressed as a percentage of estimated annual solar
energy without BESS; rated power follows from energy capacity ÷ duration. A hybrid
curtailment-first dispatch strategy with optional grid top-up charging (when end-of-day SoC
< configured threshold) is simulated chronologically. Economic outputs — LCOS, incremental
revenue, and payback — are computed in BRL using a configurable USD/BRL exchange rate for
CAPEX. All results are fully reproducible via a seeded RNG and a JSON run manifest.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**:
- `numpy` ≥ 1.26 — vectorised hourly simulation arrays
- `pandas` ≥ 2.1 — CSV I/O, hourly time-series indexing
- `plotly` ≥ 5.20 — four interactive charts + self-contained HTML export (`include_plotlyjs="inline"`)
- `pvlib` ≥ 0.10 — deterministic synthetic solar profile generation (clearsky, lat ≈ −22°, lon ≈ −45°, 60 Hz grid)
- `google-cloud-bigquery` ≥ 3.10 — real hourly PLD price data from CCEE table; mandatory (run aborts on unavailability)
- `pytest` ≥ 8.0 + `pytest-cov` — TDD test suite
- `hashlib`, `json`, `pathlib`, `uuid` — stdlib; run manifest, SHA-256 input hash, run-ID
- No web framework, no database, no GUI

**Storage**: Local filesystem only — `output/<run-id>/report.html` + `manifest.json`; input CSVs read from user-specified paths

**Testing**: `pytest` with `pytest-cov`; reference-case tests for every economic formula; property tests for SoC bounds and monotonicity

**Target Platform**: Linux/macOS CLI (Python script); no installer required; Python 3.11+ virtualenv

**Project Type**: CLI tool (single entry-point `python -m solar_bess_risk` or `python main.py`)

**Performance Goals**: 44 default scenarios (11 × 4) complete in < 3 min on dual-core 8 GB laptop; vectorised NumPy dispatch loops preferred over Python-level `for` per hour

**Constraints**: HTML report fully offline (`include_plotlyjs="inline"`); deterministic output (seeded RNG); no magic numbers; no module > 400 lines; all public functions type-annotated with unit suffixes

**Scale/Scope**: 8,760 hourly values × up to 44 scenarios = ~385 k simulation steps; single-process, no concurrency required for default config

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify compliance with all seven Core Principles and Domain Constraints from
`.specify/memory/constitution.md` (v1.1.0):

- [x] **I. Brazilian Sector Compliance** — Curtailment defined per ANEEL convention
  (involuntary reduction of injected power at point of connection). ILR-driven clipping
  is labelled as technical curtailment. ONS 60 Hz grid reference used. CCEE PLD price
  CSV format supported. All outputs reference applicable norm.
- [x] **II. No Data Fabrication** — Every default parameter has a documented value and
  unit (see FR-001, Clarifications). Synthetic solar profile labelled as synthetic in all
  outputs, including manifest and report. All parameters configurable with bounds. pvlib
  clearsky model is documented as the generation method.
- [x] **III. Test-First** — TDD enforced: failing tests written before dispatch,
  economics, and profile code. Reference-case tests planned for LCOS, payback, and
  revenue formulas. Physical constraint tests (SoC bounds, power limits) for each
  dispatch function.
- [x] **IV. Reproducible Results** — JSON manifest written per run: tool version, ISO
  8601 timestamp, SHA-256 of serialised parameter set, RNG seed, profile source. Run-ID
  is ISO timestamp + 6-char hash. Deterministic pvlib clearsky + fixed seed → byte-
  identical results.
- [x] **V. Modular Python Architecture** — No module > 400 lines; public functions have
  PEP 484 type annotations with unit suffixes (`power_mw`, `energy_mwh`); NumPy
  docstrings on all public APIs; constants in `config.py`; no circular imports.
- [x] **VI. Engineering-Quality Visualizations** — All four Plotly charts: title, axis
  labels with units, legend; hover tooltips with value + unit; perceptually uniform
  colour scale (viridis/plasma) for heatmaps; "Premissas e Limitações" section in HTML.
- [x] **VII. SI Units & Brazilian Sector Conventions** — Power: MWac; energy: MWh;
  currency: BRL/MWh and USD/kWh labelled on every output; degradation: %/year;
  efficiency: %; duration: h. Unit labels in variable names, docstrings, axis labels,
  and table headers. USD→BRL conversion via explicit exchange rate parameter.
- [x] **Domain Constraints** — 8,760-element strictly ordered hourly arrays; 60 Hz
  Brazilian grid reference; no silent failures (structured exceptions); all outputs
  normalised to 1 MWac with explicit scaling note.

**Gate result**: ✅ PASS — no violations found. Phase 0 research may proceed.

### Post-Design Re-check (after Phase 1)

- [x] **I** — pvlib Ineichen clearsky labelled as synthetic; curtailment = ANEEL definition;
  all report sections reference the norm.
- [x] **II** — All defaults in `SimulationParams` documented with bounds; pvlib clearsky
  method and parameters recorded in manifest and report.
- [x] **III** — All `DispatchResult`/`ScenarioResult` invariants are direct test assertions;
  contract tests in `tests/contract/test_cli_schema.py`.
- [x] **IV** — `RunManifest` captures all fields for exact reproduction; run-ID ties output
  dir to manifest.
- [x] **V** — 8 modules × ≤ 400 lines; unit suffixes throughout data model.
- [x] **VI** — 4 Plotly charts with title/axes/legend/tooltips/viridis; "Premissas e
  Limitações" section in HTML; heatmap scenario labelled in chart title.
- [x] **VII** — All fields in `data-model.md` have explicit units; CLI contract shows units
  on every prompt; table columns have unit labels.

**Post-design gate result**: ✅ PASS — design is constitution-compliant.

## Project Structure

### Documentation (this feature)

```text
specs/002-modulation-risk-tool/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli-schema.md    # Phase 1 output — CLI parameter contract
└── tasks.md             # Phase 2 output (speckit-tasks)
```

### Source Code (repository root)

```text
solar_bess_risk/
├── __init__.py
├── __main__.py          # Entry point: python -m solar_bess_risk
├── config.py            # All defaults, bounds, physical constants (no magic numbers)
├── cli.py               # Interactive parameter prompting loop (< 400 lines)
├── profile.py           # Synthetic solar profile (pvlib clearsky) + CSV loader
├── data_sources.py      # BigQuery PLD price fetcher (mandatory; DataSourceError aborts run)
├── simulation.py        # Hour-by-hour BESS dispatch engine (vectorised NumPy)
├── economics.py         # LCOS, revenue, payback formulas
├── report_charts.py     # Plotly figure builders (4 chart functions)
└── report_export.py     # HTML assembly, summary tables, file writer
└── manifest.py          # Run-ID, JSON manifest writer, SHA-256 hashing

tests/
├── unit/
│   ├── test_profile.py       # Synthetic profile: shape, non-negative, seed determinism
│   ├── test_simulation.py    # SoC bounds, power limits, monotonicity, energy conservation
│   ├── test_economics.py     # LCOS, revenue, payback reference-case calculations
│   ├── test_data_sources.py  # BQ price fetcher: auth, row validation, DataSourceError propagation
│   └── test_manifest.py      # Manifest fields, SHA-256 reproducibility
├── integration/
│   └── test_full_run.py      # Default config end-to-end: 44 scenarios, HTML written
└── contract/
    └── test_cli_schema.py    # Parameter validation bounds contract

output/                  # Runtime-generated; gitignored
requirements.txt
pyproject.toml
README.md
```

**Structure Decision**: Single project (Option 1). CLI tool with one package
`solar_bess_risk/` and 10 modules, each ≤ 400 lines. No frontend or backend split needed.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Module | Projected Lines | Justification | Mitigation |
|--------|----------------|---------------|------------|
| `report.py` (original) | ~600 | 4 chart functions + HTML assembly + summary tables would exceed 400-line Constitution V limit | **Planned split**: `report_charts.py` (≤4 chart builders) + `report_export.py` (HTML assembly, top-up summary table, file writer); each projected ≤ 400 lines |
