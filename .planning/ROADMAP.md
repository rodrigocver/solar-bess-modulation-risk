# ROADMAP.md

## Milestone 1 — Solar+BESS Modulation Risk Tool v2

> **Model**: Garantia Física Dispatch (replaces curtailment-based v1 model)
> **Entry point**: `python -m solar_bess_risk`
> **Dependency chain**: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7

---

### Phase 1 — Setup
**Goal**: Establish the project skeleton, dependency files, and constants module so all downstream phases have a clean, importable base.
**Status**: complete
**Deliverables**:
- `solar_bess_risk/` package (10 `.py` source files)
- `tests/unit/`, `tests/integration/`, `tests/contract/` directory structure
- `output/` directory with `.gitignore` exclusions
- `requirements.txt` (numpy, pandas, plotly, google-cloud-bigquery, pytest, pytest-cov; no pvlib)
- `pyproject.toml` at version `2.0.0` with `solar_bess_risk.__main__:main` entry point
- `solar_bess_risk/config.py` — `SCENARIO_TEMPLATES` (A/B/C), `PEAK_HOURS_BY_LABEL`, `SimulationParams` dataclass, `PARAM_BOUNDS`, all defaults (no magic numbers elsewhere)

---

### Phase 2 — Foundational Infrastructure
**Goal**: Deliver the run manifest and entry-point stub so every phase can produce traceable, reproducible output.
**Status**: complete
**Deliverables**:
- `tests/unit/test_manifest.py` — failing tests for run-ID format, SHA-256 determinism, required manifest fields, and absence of `bq_service_account_path`
- `solar_bess_risk/manifest.py` — `RunManifest` dataclass, `generate_run_id()`, `hash_params()` (SHA-256; excludes service account path), `write_manifest()`
- `solar_bess_risk/__main__.py` placeholder — `--service-account` flag; prints "Not yet implemented" message

---

### Phase 3 — User Story 1: Configure Parameters and Load Profile (P1)
**Goal**: Engineer supplies solar CSV and MWac, accepts parameter defaults, tool computes garantia física, fetches BigQuery prices, and validates all inputs before proceeding to simulation.
**Status**: complete
**Deliverables**:
- `tests/contract/test_cli_schema.py` — contract tests CT-01 through CT-12 (defaults, bounds, CSV validation, BQ failure, service-account exclusion)
- `tests/unit/test_profile.py` — CSV loader shape, non-negative clipping, fc formula, garantia_fisica_mw, error paths
- `tests/unit/test_data_sources.py` — BQ price fetcher: auth, row count, `DataSourceError` propagation; mocked client
- `solar_bess_risk/profile.py` — `SolarProfile` dataclass, `load_solar_csv()` with full validation and garantia física computation
- `solar_bess_risk/data_sources.py` — `DataSourceError`, `fetch_price_bigquery()` returning `PriceProfile`
- `solar_bess_risk/cli.py` — 10-parameter prompt flow with inline units/ranges, `ERRO:` re-prompt contract, confirmation summary

---

### Phase 4 — User Story 2: Simulate Three Fixed Scenarios (P1)
**Goal**: Run scenarios A (2 h), B (3 h), C (4 h) hour-by-hour with SoC/power bounds enforced and progress feedback.
**Status**: complete
**Deliverables**:
- `tests/unit/test_simulation.py` — SoC bounds, charge/discharge exclusivity, peak-hour-only dispatch, A2 edge case (no charging during peak excess), residual deficit formula
- `solar_bess_risk/simulation.py` — `simulate_scenario()` (vectorised NumPy, BESS efficiency applied to charging, FR-006 dispatch rules), `simulate_all_scenarios()` returning `list[tuple[ScenarioDefinition, DispatchResult]]`; post-simulation SoC assertion

---

### Phase 5 — User Story 3: Per-Scenario Economic Metrics (P2)
**Goal**: Compute all 10 output metrics per scenario — exposures, savings, payback, coverage — referenced against hand-calculated formulas.
**Status**: complete
**Deliverables**:
- `tests/unit/test_economics.py` — uniform-price exposure formula, payback = None when savings ≤ 0, `payback_display()` returns "não atingível", coverage formula, CAPEX BRL conversion, top-10 peak hours table
- `solar_bess_risk/economics.py` — `compute_scenario_economics()`, `compute_all_scenarios()`, `build_top10_peak_hours()`, `payback_display()`

---

### Phase 6 — User Story 4: Self-Contained HTML Report (P2)
**Goal**: Write a single offline HTML file with three Plotly charts and two tables; no CDN references; passes integration test end-to-end.
**Status**: complete
**Deliverables**:
- `tests/integration/test_full_run.py` — end-to-end run with mocked BQ, HTML written, no CDN URLs, manifest valid, determinism (SC-003), performance gate (SC-001 < 30 s), SC-002 manual browser stub
- `solar_bess_risk/report_charts.py` — `build_exposure_bar_chart()`, `build_capex_savings_bar_chart()`, `build_payback_curve()` (with "não atingível" annotation for non-viable scenarios)
- `solar_bess_risk/report_export.py` — `build_summary_table_html()`, `build_top10_table_html()`, `write_report()` with `include_plotlyjs="inline"` and "Premissas e Limitações do Modelo" section citing Portaria MME nº 101/2016, Portaria MME nº 60/2020, CCEE Módulo 03 Garantia Física, ANEEL RN nº 1.034/2022

---

### Phase 7 — Polish & End-to-End Wiring
**Goal**: Add edge-case guards for all spec §Edge Cases and wire the full session chain in `__main__.py`.
**Status**: complete
**Deliverables**:
- Additional tests in `tests/unit/test_simulation.py` and `tests/unit/test_economics.py` for edge cases: zero-generation peak hours, BESS fully discharges mid-block, high-fc (≈100% coverage), zero/negative savings payback = None, A2 peak-excess idle guard
- `solar_bess_risk/simulation.py` and `solar_bess_risk/economics.py` — edge-case guards added
- `solar_bess_risk/__main__.py` — full session chain: `cli → profile → data_sources → [assemble ScenarioDefinitions] → simulation → economics → report_charts → report_export → manifest`; `DataSourceError` caught at top level with code 1 exit and no partial output written; progress banners and elapsed-time done banner
