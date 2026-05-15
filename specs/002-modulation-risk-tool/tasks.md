# Tasks: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Generated**: 2026-05-15

**Input**: spec.md, plan.md, research.md, data-model.md, contracts/cli-schema.md, quickstart.md

**Note on tests**: Tests are MANDATORY — Constitution Principle III (TDD Non-Negotiable)
requires failing tests to be written and confirmed before each implementation task begins.

## Format: `[ID] [P?] [Story?] Description — file path`

- **[P]**: Parallelisable (independent files or independent functions with no shared dependency)
- **[USn]**: User story label (maps to spec.md user stories)
- Setup and Foundational phases have no story label

---

## Phase 1: Setup

**Purpose**: Project skeleton, dependency files, constants module. Must complete before any other work.

- [X] T001 Create project skeleton: `solar_bess_risk/` package (10 empty `.py` files — including `report_charts.py` and `report_export.py` instead of `report.py`), `tests/unit/`, `tests/integration/`, `tests/contract/` dirs, `output/` dir, `.gitignore` (ignores `output/`, `.venv/`, `__pycache__/`, `*.pyc`)
- [X] T002 [P] Write `requirements.txt` (numpy≥1.26, pandas≥2.1, plotly≥5.20, pvlib≥0.10, google-cloud-bigquery≥3.10, pytest≥8.0, pytest-cov≥4.1) and `pyproject.toml` (package name, version `1.0.0`, Python ≥3.11, entry point `solar_bess_risk.__main__:main`)
- [X] T003 [P] Write `solar_bess_risk/config.py` — all physical constants, default parameter values, validation bounds, and `SimulationParams` dataclass with full PEP 484 type annotations and unit suffixes; no magic numbers anywhere else in the codebase

**Checkpoint**: Project installs with `pip install -e .` and `python -m solar_bess_risk --help` exits cleanly.

---

## Phase 2: Foundational

**Purpose**: Cross-cutting infrastructure (manifest, entry point) that every user story depends on.

⚠️ **CRITICAL**: Write failing tests FIRST (T004). Confirm they fail before implementing T005.

- [X] T004 Write failing tests in `tests/unit/test_manifest.py`: run-ID format matches `YYYYMMDD-HHMMSS-<7-char hex>`; SHA-256 of `json.dumps(params, sort_keys=True)` is deterministic; manifest JSON contains all required fields (`tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `rng_seed`, `profile_source`, `price_source`, `scenario_top_up_hours`); `scenario_top_up_hours` is a dict keyed by `"{ilr}_{bess_pct}_{dur_h}"` with list-of-HH:00-string values; `bq_service_account_path` absent from serialised params
- [X] T005 Implement `solar_bess_risk/manifest.py` — `RunManifest` dataclass (fields: `tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `rng_seed`, `profile_source`, `price_source`, `scenario_top_up_hours: dict[str, list[str]]`), `generate_run_id()`, `hash_params()` (SHA-256 of sorted JSON, excludes `bq_service_account_path`), `write_manifest(manifest: RunManifest, results: list[ScenarioResult], output_dir: Path) -> Path` (creates `output/<run-id>/manifest.json`, populates `scenario_top_up_hours` from `ScenarioResult.top_up_hour_slots`); all functions PEP 484 annotated with NumPy docstrings
- [X] T006 [P] Implement `solar_bess_risk/__main__.py` — `argparse` CLI flags (`--service-account <path>`); `main()` stub that chains all modules in order; `solar_bess_risk/__init__.py` with `__version__ = "1.0.0"`

**Checkpoint**: `pytest tests/unit/test_manifest.py` passes. `python -m solar_bess_risk` prints welcome banner.

---

## Phase 3: User Story 1 — Configure Parameters and Load Profiles (Priority: P1) 🎯 MVP

**Goal**: Engineer can run the tool, be prompted for all parameters, load solar profile (synthetic/CSV) and BigQuery PLD prices, and reach the simulation stage with validated inputs.

**Independent Test**: Run `python -m solar_bess_risk` with a mocked BigQuery client (returns deterministic test prices), press Enter at every prompt → tool reports parameter set chosen, fetches BigQuery PLD prices, loads synthetic solar profile, and proceeds to simulation stage.

### Tests for User Story 1 ⚠️ Write FIRST — confirm they FAIL before implementing T010–T012

- [X] T007 Write failing contract tests in `tests/contract/test_cli_schema.py` — CT-01 (Enter→defaults), CT-02 (out-of-bounds→ERRO+reprompt), CT-03 (non-numeric→ERRO+reprompt), CT-04 (8761-row solar CSV rejected with row count), CT-05 (negative solar CSV value cites row), CT-06 (non-numeric solar CSV value cites row+value), CT-08 (invalid heatmap scenario→reprompt with list), CT-09 (valid heatmap int→proceeds), CT-10 (CAPEX shown in USD and BRL), CT-11 (service_account without valid path→reprompt), CT-12 (ADC→no file path prompt), CT-13 (BQ auth error→run aborts with descriptive error, no fallback), CT-14 (BQ returns wrong row count→run aborts citing actual vs expected count), CT-15 (service account path absent from summary+manifest)
- [X] T008 [P] Write failing unit tests in `tests/unit/test_profile.py` — synthetic profile has shape `(8760,)`, all values ∈ [0.0, 1.0], annual sum > 0, two calls with same params produce byte-identical arrays; CSV loader rejects non-numeric row, negative row, wrong row count with exact error messages; `SolarProfile.annual_energy_mwh == sum(generation_mw)`
- [X] T009 [P] Write failing unit tests in `tests/unit/test_data_sources.py` — `fetch_price_bigquery` returns `PriceProfile` with `source == 'bigquery_pld'`, `len(prices) == 8760`, all values ≥ 0; `DataSourceError` raised (and propagates without fallback) on BQ auth failure, network error, and row count mismatch; `bq_submarket` and `bq_year` populated in returned `PriceProfile`; mocked BQ client returns deterministic test prices

### Implementation for User Story 1

- [X] T010 [US1] Implement `solar_bess_risk/profile.py` — `SolarProfile` dataclass; `generate_synthetic_profile(params: SimulationParams) -> SolarProfile` using pvlib Ineichen at lat/lon/alt from params, normalised to 1.0 MWac, GHI→AC conversion; `load_solar_csv(path: str) -> SolarProfile` with row-count and non-negative validation; both functions fully annotated with NumPy docstrings and unit suffixes
- [X] T011 [US1] Implement `solar_bess_risk/data_sources.py` — `PriceProfile` dataclass; `fetch_price_bigquery(params: SimulationParams) -> PriceProfile` (parameterised BQ query using `@year` and `@submarket` BigQuery parameters, ADC or service-account auth, 8760-row validation, all prices ≥ 0 validated, raises `DataSourceError` on any failure without fallback); `DataSourceError` exception class; all functions annotated with NumPy docstrings
- [X] T012 [US1] Implement `solar_bess_risk/cli.py` — full interactive prompting loop per `contracts/cli-schema.md`: Sections 1–6 in order, `prompt_float()` / `prompt_int()` / `prompt_list()` helpers with bounds validation and ERRO re-prompt; solar profile section (P-13/P-14); BigQuery-mandatory price section (P-15–P-17: submarket and year only); BQ auth section (P-20–P-22); confirmation summary (CAPEX in USD+BRL, price source as `"BigQuery PLD {submarket} {year}"`); heatmap scenario selection prompt (post-simulation, numbered list, Enter=first); all error messages match exact format from contract; `DataSourceError` propagates to abort run with error message

**Checkpoint**: CT-01 through CT-15 all pass. Synthetic profile loads in < 1 s. BQ `DataSourceError` aborts run with clear error.

---

## Phase 4: User Story 2 — Simulate Solar+BESS Across All Scenarios (Priority: P1)

**Goal**: After US1 is complete, the tool simulates 44 scenarios (11 BESS sizes × 4 ILRs × 1 default duration) hour-by-hour with the hybrid dispatch strategy, enforces all SoC/power bounds, and reports progress and a completion summary.

**Independent Test**: Run simulation for BESS=0% and BESS=100% with ILR=1.3, synthetic profile. BESS=0% → `avoided_curtailment == 0`; BESS=100% → `avoided_curtailment > 0`.

### Tests for User Story 2 ⚠️ Write FIRST — confirm they FAIL before implementing T014

- [X] T013 Write failing unit tests in `tests/unit/test_simulation.py` — SoC never < 0 or > `energy_cap_mwh` across 8760 hours; power flow per hour ≤ `rated_power_mw`; charge and discharge never non-zero in the same hour; BESS=0% produces `sum(charge_curtail_mwh) == 0`; avoided curtailment monotonically non-decreasing across BESS sizes for fixed ILR; `annual_solar_energy_no_bess_mwh` computed correctly from clipped profile; grid top-up only triggers when end-of-day SoC < threshold; top-up respects injection floor; top-up window Priority 1 selects next-day curtailment hours before Priority 2 price-ranked hours; `DispatchResult.top_up_hours` is a non-empty list of int hour-indices when top-up occurred, empty list otherwise

### Implementation for User Story 2

- [X] T014 [US2] Implement `solar_bess_risk/simulation.py` — `BESSConfig` dataclass (energy_capacity_mwh, rated_power_mw, capex_brl from SimulationParams + SolarProfile); `DispatchResult` dataclass (6 numpy arrays + `top_up_hours: list[int]`); `compute_annual_solar_energy_no_bess(profile: SolarProfile, ilr: float) -> float`; `simulate_scenario(bess_cfg: BESSConfig, solar: SolarProfile, prices: PriceProfile, params: SimulationParams) -> DispatchResult` (hour-by-hour Python loop, curtailment-first charge, greedy discharge, end-of-day top-up check using two-priority window: Priority 1 = next-day curtailment hours, Priority 2 = next-day cheapest PLD hours ranked ascending, until SoC target reached, respecting injection floor); `simulate_all_scenarios(params, solar, prices, progress_cb) -> list[DispatchResult]` with progress callback; post-simulation SoC bound assertion (raises `SimulationConstraintError` on violation); full PEP 484 annotations and NumPy docstrings

**Checkpoint**: `pytest tests/unit/test_simulation.py` passes. 44 default scenarios complete in < 3 min (SC-001).

---

## Phase 5: User Story 3 — Review Per-Scenario Economic Metrics (Priority: P2)

**Goal**: For each simulated scenario, compute and expose all 10 `ScenarioResult` fields including LCOS, incremental revenue (BigQuery PLD hourly prices), payback, effective CF, and separately tracked curtailment-absorbed vs grid-charged energy.

**Independent Test**: Single scenario (ILR=1.3, BESS=25%, duration=2h), uniform PLD price 220 BRL/MWh for all hours: verify `incremental_revenue_brl_yr = sum(charge_curtail_mwh × 220 × rte)` and `payback_yr = capex_brl / incremental_revenue_brl_yr` match hand-calculated reference values.

### Tests for User Story 3 ⚠️ Write FIRST — confirm they FAIL before implementing T016

- [X] T015 Write failing unit tests in `tests/unit/test_economics.py` — uniform-price revenue formula (reference case with known inputs: all hours at P BRL/MWh); hourly-price revenue formula (Σ charge × price × rte); LCOS reference case (manually computed CAPEX / Σ discounted energy); payback = None when revenue ≤ 0 (no division-by-zero); LCOS = None when total discounted energy = 0; degradation d=0 produces constant annual energy in LCOS denominator; effective CF formula (`sum(grid_injection) / 8760`); equivalent cycles formula (`sum(discharge) / energy_cap`); payback sensitivity sweep returns 10×10 grid covering [50%, 150%] of base price (mean of PLD array) and CAPEX defaults; `energy_from_curtail_mwh_yr` and `energy_from_grid_mwh_yr` sum correctly from DispatchResult arrays; `ScenarioResult.top_up_hour_slots` contains correct HH:00 strings derived from `DispatchResult.top_up_hours`

### Implementation for User Story 3

- [X] T016 [US3] Implement `solar_bess_risk/economics.py` — `ScenarioResult` dataclass (all 10 fields + `scenario_id` + `top_up_hour_slots: list[str]` (HH:00 strings from DispatchResult.top_up_hours) + display string properties `lcos_display` and `payback_display`); `compute_incremental_revenue(dispatch: DispatchResult, prices: PriceProfile, rte_pct: float) -> float`; `compute_lcos(bess_cfg: BESSConfig, dispatch: DispatchResult, params: SimulationParams) -> float | None`; `compute_payback(capex_brl: float, revenue_brl_yr: float) -> float | None`; `compute_scenario_result(bess_cfg, dispatch, prices, params) -> ScenarioResult`; `compute_payback_sensitivity(base_result: ScenarioResult, prices: PriceProfile, params: SimulationParams) -> np.ndarray` (10×10 grid per FR-014, base price = mean of PLD array); all functions PEP 484 annotated with NumPy docstrings

**Checkpoint**: `pytest tests/unit/test_economics.py` passes. LCOS and payback match hand-calculated reference cases within floating-point tolerance.

---

## Phase 6: User Story 4 — Self-Contained HTML Report with Four Charts (Priority: P2)

**Goal**: After US2 and US3 complete, the tool writes a single self-contained offline HTML file with four Plotly interactive charts and a 13-column summary table. No network access required to view it.

**Independent Test**: Generate report with default params, open `output/<run-id>/report.html` offline in browser — all four charts render with data, hover tooltips show values and units, summary table has 44 rows, no browser console errors.

### Tests for User Story 4 ⚠️ Write FIRST — confirm they FAIL before implementing T018–T022

- [X] T017 Write failing integration tests in `tests/integration/test_full_run.py` — end-to-end run with mocked BigQuery client (returns deterministic 8760-row test prices) and all defaults completes without exception; `output/<run-id>/report.html` exists and contains `<!DOCTYPE html>`; `output/<run-id>/manifest.json` contains all required fields including `price_source` and `scenario_top_up_hours`; `len(results) == 44`; saturation curve data is monotonically non-decreasing for each ILR across BESS sizes; HTML file contains no `cdn.plot.ly` or external URL references (fully self-contained); summary table HTML contains 44 `<tr>` data rows; **SC-001**: assert total wall-clock time for `simulate_all_scenarios()` (44 scenarios, synthetic profile, mocked prices) is < 180 s; **SC-004**: for each scenario, avoided curtailment MWh derived from `ScenarioResult` matches the corresponding saturation curve data point to within `1e-2` MWh tolerance

### Implementation for User Story 4

- [X] T018 [US4] Implement chart (a) in `solar_bess_risk/report_charts.py` — `build_saturation_curve(results: list[ScenarioResult]) -> go.Figure`: Plotly line chart, Y = avoided curtailment (MWh/yr), X = BESS size (% of annual solar energy without BESS), one line per ILR, hover tooltip shows `(BESS%, ILR, MWh, % avoided)`, axis labels with units, title "Curva de Saturação da Modulação"
- [X] T019 [P] [US4] Implement chart (b) in `solar_bess_risk/report_charts.py` — `build_dispatch_heatmap(dispatch: DispatchResult, bess_cfg: BESSConfig) -> go.Figure`: two side-by-side `go.Heatmap` sub-panels (generation left, BESS dispatch right), 365×24 grid reshaped from 8760 arrays, Viridis colour scale, shared colour bar labelled in MWh, chart title identifies (ILR, BESS%, duration)
- [X] T020 [P] [US4] Implement chart (c) in `solar_bess_risk/report_charts.py` — `build_payback_sensitivity(sensitivity_grid: np.ndarray, params: SimulationParams, base_price_brl_per_mwh: float) -> go.Figure`: Plotly Heatmap or Contour over 10×10 grid of price × CAPEX (each ±50% of base price and default CAPEX), axes labelled BRL/MWh and USD/kWh, colour bar labelled "Payback (anos)", title "Análise de Sensibilidade do Payback"
- [X] T021 [P] [US4] Implement chart (d) in `solar_bess_risk/report_charts.py` — `build_operation_distribution(dispatch: DispatchResult) -> go.Figure`: Plotly stacked bar chart, X = hour-of-day (0–23), bars = MWh charged/discharged/idle per hour aggregated across 365 days, labelled in MWh and hours, title "Distribuição Horária de Operação do BESS"
- [X] T022 [US4] Implement HTML assembly and summary tables in `solar_bess_risk/report_export.py` — `build_summary_table_html(results: list[ScenarioResult]) -> str` (13 columns per FR-015/US4 scenario 9, Portuguese headers, `"não atingível"`/`"não calculável"` display strings, 1 row per scenario); `build_topup_summary_table_html(results: list[ScenarioResult], prices: PriceProfile) -> str` (per FR-016: top-5 most frequent top-up hour slots per scenario with average PLD price, Portuguese headers); `write_report(figures: list[go.Figure], table_html: str, topup_table_html: str, results: list[ScenarioResult], params: SimulationParams, output_dir: Path) -> Path` (Jinja-free string assembly of all 4 chart divs + scenario table + top-up summary table + "Premissas e Limitações" section; `plotly.io.write_html(include_plotlyjs=True, full_html=True)`)

**Checkpoint**: `pytest tests/integration/test_full_run.py` passes. HTML file opens offline, all four charts interactive, no CDN references.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Wire the full end-to-end session, edge-case guards, and final project documentation.

- [X] T023 [P] Add edge-case guards in `solar_bess_risk/simulation.py` and `solar_bess_risk/economics.py` — all-zero solar profile (curtailment=0, payback=`"não atingível"`, report generates without error); ILR=1.0 (no curtailment, flat saturation curve at 0); BESS=0% (0 avoided curtailment, 0 revenue, `"não atingível"` payback); price=0 BRL/MWh (revenue=0, payback=`"não atingível"`); degradation_pct_yr=0 (no ZeroDivisionError in LCOS denominator)
- [X] T024 Wire full end-to-end session in `solar_bess_risk/__main__.py` — chain: `cli.run_session() → profile.load() → data_sources.fetch_price_bigquery() → simulation.simulate_all_scenarios() → economics.compute_all() → cli.prompt_heatmap_scenario() → report_charts.build_*() → report_export.write_report() → manifest.write_manifest()`; print progress at each stage; allow `DataSourceError` to propagate and print error message then exit with non-zero status; print done banner with output path
- [X] T025 [P] Verify SC-003 reproducibility: add integration test that two consecutive runs with identical params and a mocked BigQuery client (same deterministic prices both calls) produce numerical results matching to `< 1e-10` MWh across all 44 scenarios; add to `tests/integration/test_full_run.py`

---

## Dependencies

```
Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3)
                                                    ↘ Phase 6 (US4) ← Phase 5 (US3)
                                                    Phase 6 → Phase 7
```

**Story independence**:
- US1 (T007–T012): depends only on Phase 2 foundational
- US2 (T013–T014): depends on US1 (needs SolarProfile, SimulationParams)
- US3 (T015–T016): depends on US2 (needs DispatchResult)
- US4 (T017–T022): depends on US2 + US3 (needs ScenarioResult + DispatchResult)

**Parallel execution opportunities**:

Within Phase 1: T002 ∥ T003
Within Phase 3 test writing: T008 ∥ T009 (different test files)
Within Phase 3 implementation: T010 ∥ T011 (different modules, no dependency)
Within Phase 6 chart implementation: T019 ∥ T020 ∥ T021 (independent chart functions)
Within Phase 7: T023 ∥ T025

---

## Implementation Strategy

**MVP scope (deliver first)**: Phases 1–4 (US1 + US2 complete)
- Engineer can configure, load profiles, and run all 44 simulations
- All SoC/power invariants verified
- Covers both P1 user stories

**Increment 2**: Phase 5 (US3) — economics
**Increment 3**: Phase 6 (US4) — HTML report
**Increment 4**: Phase 7 — polish + edge cases + end-to-end wiring

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 25 |
| Phase 1 (Setup) | 3 tasks |
| Phase 2 (Foundational) | 3 tasks |
| Phase 3 / US1 (P1) | 6 tasks (3 tests + 3 impl) |
| Phase 4 / US2 (P1) | 2 tasks (1 test + 1 impl) |
| Phase 5 / US3 (P2) | 2 tasks (1 test + 1 impl) |
| Phase 6 / US4 (P2) | 6 tasks (1 test + 5 impl) |
| Phase 7 (Polish) | 3 tasks |
| Parallelisable [P] | 12 tasks |
| Independent test criteria | 4 (one per user story) |
| Suggested MVP scope | Phases 1–4 (US1 + US2) |
