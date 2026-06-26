# Implementation Plan: Monthly PLD Solar Modulation

**Branch**: `001-monthly-pld-modulation` | **Date**: 2026-06-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-monthly-pld-modulation/spec.md`

## Summary

Build an isolated Python CLI subproject that computes month-by-month solar modulation for a generation curve without BESS across historical local PLD years. The tool reuses the existing validated solar CSV loader and local PLD loader from `solar_bess_risk`, then produces reproducible CSV outputs and a manifest without modifying existing modules.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: pandas, numpy, existing local `solar_bess_risk` package

**Storage**: Local filesystem only, run-specific output folders

**Testing**: pytest with unit and integration tests

**Target Platform**: Local CLI on Linux/WSL

**Project Type**: Isolated CLI subproject

**Performance Goals**: Process 5 years x 8,760 hourly values in under 10 seconds on a laptop

**Constraints**: No existing project files are modified; outputs must be deterministic except timestamped run directory; no module exceeds 400 non-test lines; all public APIs use type annotations and unit-labelled names

**Scale/Scope**: One solar curve, one submarket, default years 2021-2025

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- [x] **I. Brazilian Sector Compliance** — Uses CCEE PLD convention via the existing local PLD source labels; output columns identify BRL/MWh settlement price basis.
- [x] **II. No Data Fabrication** — No synthetic data; all assumptions are documented defaults; missing data raises errors.
- [x] **III. Test-First** — Unit tests define captured-price, factor, zero-generation, and export behavior before implementation.
- [x] **IV. Reproducible Results** — Manifest records parameters, input hashes, formulas, tool version, and source file names.
- [x] **V. Modular Python Architecture** — Separate modules for constants, adapters, calculation, manifest, report, and CLI; public APIs typed and documented.
- [x] **VI. Engineering-Quality Visualizations** — No chart output in v1; CSV tables use explicit units and can feed later charting.
- [x] **VII. SI Units & Brazilian Sector Conventions** — Public variable names and output columns use MWh, MWac, BRL/MWh, and BRL suffixes.
- [x] **Domain Constraints** — Hourly time-series are exactly 8,760 values; no silent failures; outputs include MWac normalization.

## Project Structure

### Documentation

```text
new_projects/pld-solar-monthly-modulation/specs/001-monthly-pld-modulation/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── cli-schema.md
└── tasks.md
```

### Source Code

```text
new_projects/pld-solar-monthly-modulation/
├── pyproject.toml
├── README.md
├── src/
│   └── solar_monthly_modulation/
│       ├── __init__.py
│       ├── __main__.py
│       ├── adapters.py
│       ├── cli.py
│       ├── constants.py
│       ├── errors.py
│       ├── manifest.py
│       ├── models.py
│       ├── modulation.py
│       └── report.py
└── tests/
    ├── integration/
    │   └── test_cli.py
    └── unit/
        └── test_modulation.py
```

**Structure Decision**: A nested subproject keeps all new artifacts isolated and avoids edits to existing Solar+BESS modules, packaging, specs, or agent instructions.

## Complexity Tracking

No constitution violations. The extra subproject directory is justified by the explicit requirement to avoid altering existing code while starting a separate project.
