# Tasks: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Updated**: 2026-05-15 (v2 — Garantia Física model)

**Input**: spec.md (v2), plan.md (v2)

**Note on tests**: Tests are MANDATORY — Constitution Principle III (TDD Non-Negotiable)
requires failing tests to be written and confirmed before each implementation task begins.

---

## Format: `[ID] [P?] [Story?] Description — file path`

- **[P]**: Parallelisable (independent files or independent functions with no shared dependency)
- **[USn]**: User story label (maps to spec.md user stories)

---

## Phase 1: Setup

**Purpose**: Project skeleton, dependency files, constants module. Must complete before any other work.

- [ ] T001 Create project skeleton: `solar_bess_risk/` package (10 `.py` files), `tests/unit/`, `tests/integration/`, `tests/contract/` dirs, `output/` dir, `.gitignore` (ignores `output/`, `.venv/`, `__pycache__/`, `*.pyc`) — if not already present from v1
- [ ] T002 [P] Update `requirements.txt` (remove pvlib; keep numpy≥1.26, pandas≥2.1, plotly≥5.20, google-cloud-bigquery≥3.10, pytest≥8.0, pytest-cov≥4.1) and `pyproject.toml` (bump version to `2.0.0`, update entry point)
- [ ] T003 [P] Rewrite `solar_bess_risk/config.py` — remove ILR list, BESS size ratios, RNG seed, min SoC threshold, injection floor; add: `SCENARIOS: list[ScenarioDefinition]` (A/B/C as per spec FR-005), `PEAK_HOURS_BY_LABEL` dict, `DEFAULT_BQ_YEAR`, `DEFAULT_BQ_SUBMARKET`, `DEFAULT_CAPEX_USD_KWH = 200.0`, `DEFAULT_USD_BRL_RATE = 5.0`, `DEFAULT_USEFUL_LIFE_YR = 20`, `DEFAULT_DISCOUNT_RATE_PCT = 10.0`; `SimulationParams` dataclass with 8 fields as per plan.md data model; no magic numbers anywhere else

**Checkpoint**: `pip install -e .` and `python -m solar_bess_risk --help` exit cleanly.

---

## Phase 2: Foundational

**Purpose**: Cross-cutting infrastructure (manifest, entry point) that every user story depends on.

⚠️ **CRITICAL**: Write failing tests FIRST (T004). Confirm they fail before implementing T005.

- [ ] T004 Write failing tests in `tests/unit/test_manifest.py`: run-ID format matches `YYYYMMDD-HHMMSS-<7-char hex>`; SHA-256 of `json.dumps(params, sort_keys=True)` is deterministic; manifest JSON contains all required fields (`tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `profile_source`, `price_source`, `fc`, `garantia_fisica_mw`, `scenarios`); `bq_service_account_path` absent from serialised params; `scenarios` is a list of 3 dicts each with `label`, `peak_hours`, `duration_h`, `bess_power_mw`, `bess_energy_mwh`, `capex_brl`
- [ ] T005 Implement `solar_bess_risk/manifest.py` — `RunManifest` dataclass (fields: `tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `profile_source`, `price_source`, `fc`, `garantia_fisica_mw`, `scenarios: list[dict]`), `generate_run_id()`, `hash_params()` (SHA-256 of sorted JSON, excludes `bq_service_account_path`), `write_manifest(manifest, results, output_dir) -> Path` (creates `output/<run-id>/manifest.json`); all functions PEP 484 annotated
- [ ] T006 [P] Implement `solar_bess_risk/__main__.py` — `argparse` CLI flags (`--service-account <path>`); `main()` stub that chains all modules in order; `solar_bess_risk/__init__.py` with `__version__ = "2.0.0"`

**Checkpoint**: `pytest tests/unit/test_manifest.py` passes.

---

## Phase 3: User Story 1 — Configure Parameters and Load Profile (P1) 🎯 MVP

**Goal**: Engineer provides solar CSV path and MWac, accepts other parameter defaults, tool computes garantia física, fetches BigQuery prices, confirms inputs, proceeds.

**Independent Test**: Run with a valid solar CSV and MWac, press Enter at all other prompts → tool reports fc, garantia_fisica_mw, fetches BQ prices, proceeds to simulation.

### Tests for User Story 1 ⚠️ Write FIRST — confirm they FAIL before implementing T010–T012

- [ ] T007 Write failing contract tests in `tests/contract/test_cli_schema.py` — CT-01 (Enter at non-required prompts→defaults); CT-02 (out-of-bounds→ERRO+reprompt); CT-03 (non-numeric→ERRO+reprompt); CT-04 (8761-row solar CSV rejected with row count); CT-05 (negative solar CSV value cites row+value); CT-06 (non-numeric solar CSV value cites row+value); CT-07 (missing CSV path→run aborts); CT-08 (BQ auth error→run aborts with descriptive error); CT-09 (BQ returns wrong row count→aborts citing actual vs expected); CT-10 (MWac ≤ 0→rejected with ERRO+reprompt); CT-11 (fc and garantia_fisica_mw shown in confirmation summary); CT-12 (service account path absent from summary+manifest)
- [ ] T008 [P] Write failing unit tests in `tests/unit/test_profile.py` — CSV loader: shape `(8760,)`, all values ≥ 0, correct `annual_energy_mwh` sum, correct `fc = annual_energy_mwh / (mwac * 8760)`, correct `garantia_fisica_mw = mwac * fc`; CSV rejects non-numeric row (cites row number+value), negative row (cites row+value), wrong row count (cites actual vs 8760); `csv_filename` set to basename of path
- [ ] T009 [P] Write failing unit tests in `tests/unit/test_data_sources.py` — `fetch_price_bigquery` returns `PriceProfile` with `source == 'bigquery_pld_SE_2025'`, `len(prices) == 8760`, all values ≥ 0; `DataSourceError` raised (and propagates without fallback) on BQ auth failure, network error, row count mismatch; mocked BQ client returns deterministic test prices

### Implementation for User Story 1

- [ ] T010 [US1] Rewrite `solar_bess_risk/profile.py` — remove synthetic profile generator; keep/update `SolarProfile` dataclass; `load_solar_csv(path: str, mwac: float) -> SolarProfile` with full validation and garantia física computation; display summary (min, max, mean, fc, garantia_fisica_mw) on load; all functions PEP 484 annotated
- [ ] T011 [US1] Update `solar_bess_risk/data_sources.py` if needed — ensure `DataSourceError` propagates without fallback; no changes to BQ query logic unless needed for new schema
- [ ] T012 [US1] Rewrite `solar_bess_risk/cli.py` — remove ILR, BESS size ratios, RNG seed, min SoC, injection floor prompts; add required CSV path prompt (no default, must exist and be valid); add required MWac prompt (no default, must be > 0); keep BQ submarket, year, CAPEX, exchange rate, useful life, discount rate prompts with defaults; confirmation summary MUST show fc and garantia_fisica_mw; remove heatmap scenario selection prompt (no longer needed); all error messages match contract test format

**Checkpoint**: CT-01 through CT-12 all pass. CSV loads in < 1 s. BQ `DataSourceError` aborts run.

---

## Phase 4: User Story 2 — Simulate Three Fixed Scenarios (P1)

**Goal**: Tool simulates scenarios A, B, C hour-by-hour, enforces all SoC/power bounds, reports progress.

**Independent Test**: Run simulation for all 3 scenarios. Verify `annual_exposure_with_bess ≤ annual_exposure_without_bess` for every scenario.

### Tests for User Story 2 ⚠️ Write FIRST — confirm they FAIL before implementing T014

- [ ] T013 Write failing unit tests in `tests/unit/test_simulation.py`:
  - SoC never < 0 or > `bess_energy_mwh` across all 8760 hours (all 3 scenarios)
  - `charge_mwh[h] > 0` and `discharge_mwh[h] > 0` never simultaneously in same hour
  - `charge_mwh[h] > 0` only when `generation[h] > garantia_fisica_mw` AND `h%24 NOT in peak_hours`
  - `discharge_mwh[h] > 0` only when `h%24 IN peak_hours`
  - `deficit_mwh[h] = max(0, garantia_fisica_mw - generation[h])` for peak hours, 0 otherwise
  - `residual_deficit_mwh[h] = deficit_mwh[h] - discharge_mwh[h]` for all h
  - `residual_deficit_mwh[h] >= 0` for all h
  - `grid_injection_mwh[h] = generation[h] - charge_mwh[h] + discharge_mwh[h]` for all h
  - Scenario C has more peak hours than A → typically lower SoC after peak hours (ordering test)

### Implementation for User Story 2

- [ ] T014 [US2] Rewrite `solar_bess_risk/simulation.py` — remove ILR sweep, BESS size ratio sweep, curtailment logic, grid top-up logic; implement `simulate_scenario(solar: SolarProfile, prices: PriceProfile, scenario: ScenarioDefinition, params: SimulationParams) -> DispatchResult` with vectorised NumPy dispatch per FR-006; `simulate_all_scenarios(solar, prices, params, progress_cb) -> list[ScenarioResult]` runs A/B/C; post-simulation SoC bound assertion (raises `SimulationConstraintError` on violation); all functions PEP 484 annotated

**Checkpoint**: `pytest tests/unit/test_simulation.py` passes. 3 scenarios complete in < 30 s.

---

## Phase 5: User Story 3 — Review Per-Scenario Economic Metrics (P2)

**Goal**: For each scenario, compute all 10 output metrics from FR-007 including exposures, savings, payback, coverage.

**Independent Test**: Scenario A, uniform PLD 500 BRL/MWh for all hours: verify `annual_exposure_without_bess = garantia_fisica_mw × 2 × 365 × 500` (2 peak hours/day × 365 days) and `coverage_pct = 1 − (exposure_with / exposure_without)`.

### Tests for User Story 3 ⚠️ Write FIRST — confirm they FAIL before implementing T016

- [ ] T015 Write failing unit tests in `tests/unit/test_economics.py`:
  - Uniform-price exposure formula: `exposure_without = garantia_fisica_mw × len(peak_hours_in_year) × P`
  - `exposure_with = Σ(residual_deficit_h × P)` for peak hours
  - `annual_savings = exposure_without − exposure_with`
  - `payback_years = capex_brl / annual_savings` (reference case with known CAPEX and savings)
  - `payback_years is None` when `annual_savings ≤ 0`
  - `coverage_pct = (1 − exposure_with/exposure_without) × 100` (range [0, 100])
  - `capex_brl = bess_energy_mwh × capex_usd_per_kwh × 1000 × usd_brl_rate`
  - If BESS fully covers all peak-hour deficits: `exposure_with = 0`, `coverage_pct = 100`
  - Top-10 peak hours table identifies correct 10 hours by highest PLD within any scenario's peak_hours set

### Implementation for User Story 3

- [ ] T016 [US3] Rewrite `solar_bess_risk/economics.py` — remove LCOS, incremental revenue, curtailment metrics, top-up slot tracking; implement `compute_scenario_economics(solar: SolarProfile, prices: PriceProfile, scenario: ScenarioDefinition, dispatch: DispatchResult, params: SimulationParams) -> ScenarioResult`; `compute_all_scenarios(solar, prices, scenarios, dispatches, params) -> list[ScenarioResult]`; `build_top10_peak_hours(results: list[ScenarioResult], prices: PriceProfile) -> pd.DataFrame` (10 rows by highest PLD in union of peak hours sets); `payback_display(result: ScenarioResult) -> str` ("não atingível" if None); all functions PEP 484 annotated

**Checkpoint**: `pytest tests/unit/test_economics.py` passes. Economic formulas match hand-calculated reference cases.

---

## Phase 6: User Story 4 — Self-Contained HTML Report (P2)

**Goal**: Tool writes a single offline HTML file with 3 Plotly charts and 2 tables (scenario summary + top-10 hours).

**Independent Test**: Generate report with a valid CSV and default params. Open `output/<run-id>/report.html` offline — all charts render, both tables present, no console errors, no CDN references.

### Tests for User Story 4 ⚠️ Write FIRST — confirm they FAIL before implementing T018–T021

- [ ] T017 Write failing integration tests in `tests/integration/test_full_run.py`:
  - End-to-end run (mocked BQ, valid CSV, all defaults) completes without exception
  - `output/<run-id>/report.html` exists and contains `<!DOCTYPE html>`
  - HTML file contains no `cdn.plot.ly` or external URL references
  - `output/<run-id>/manifest.json` contains all required fields including `fc`, `garantia_fisica_mw`, `scenarios` list
  - `len(results) == 3` (exactly 3 scenarios)
  - HTML summary table contains exactly 3 data rows (one per scenario)
  - **SC-001**: wall-clock time for `simulate_all_scenarios()` (3 scenarios, mocked prices) < 30 s
  - **SC-003**: two consecutive runs with same mocked prices and CSV produce identical numerical results for all 3 scenarios (to within 1e-10)

### Implementation for User Story 4

- [ ] T018 [US4] Implement chart (a) in `solar_bess_risk/report_charts.py` — `build_exposure_bar_chart(results: list[ScenarioResult]) -> go.Figure`: grouped bar chart, one group per scenario (A/B/C), two bars per group (`exposure_without`, `exposure_with`), BRL/yr Y-axis, hover shows exact BRL value, title "Exposição Financeira: Sem vs Com BESS"
- [ ] T019 [P] [US4] Implement chart (b) in `solar_bess_risk/report_charts.py` — `build_capex_savings_bar_chart(results: list[ScenarioResult], useful_life_years: int) -> go.Figure`: grouped bar chart per scenario, bars = CAPEX (BRL) and cumulative undiscounted savings (= annual_savings × useful_life_years), BRL Y-axis, title "CAPEX vs Economia Acumulada no Horizonte de Vida Útil"
- [ ] T020 [P] [US4] Implement chart (c) in `solar_bess_risk/report_charts.py` — `build_payback_curve(results: list[ScenarioResult]) -> go.Figure`: line chart, X = year (1..useful_life_years), Y = cumulative savings (BRL) for each scenario (A, B, C as separate lines); horizontal dashed reference line at each scenario's CAPEX value (same colour, dashed); title "Curva de Payback: Economia Acumulada vs Anos"
- [ ] T021 [US4] Implement `solar_bess_risk/report_export.py` — `build_summary_table_html(results: list[ScenarioResult]) -> str` (3 rows × 10 columns, Portuguese headers with units, "não atingível" display); `build_top10_table_html(top10_df: pd.DataFrame, results: list[ScenarioResult]) -> str` (10 rows, columns: Data, Hora, PLD BRL/MWh, and for each scenario: dispatch MWh + deficit residual MWh); `write_report(figures, summary_html, top10_html, results, params, output_dir) -> Path` (Jinja-free string assembly; `include_plotlyjs=True, full_html=True`; "Premissas e Limitações" section)

**Checkpoint**: `pytest tests/integration/test_full_run.py` passes. HTML opens offline with all charts and tables.

---

## Phase 7: Polish & End-to-End Wiring

- [ ] T022 [P] Add edge-case guards in `solar_bess_risk/simulation.py` and `solar_bess_risk/economics.py` — BESS fully discharges before end of peak block (remaining hours have full deficit as residual); all peak hours have zero generation (BESS never charged, full deficit everywhere); annual_savings ≤ 0 (payback = None, report generates without error)
- [ ] T023 Wire full end-to-end session in `solar_bess_risk/__main__.py` — chain: `cli.run_session() → profile.load_solar_csv() → data_sources.fetch_price_bigquery() → simulation.simulate_all_scenarios() → economics.compute_all_scenarios() → economics.build_top10_peak_hours() → report_charts.build_*() → report_export.write_report() → manifest.write_manifest()`; print progress at each stage; allow `DataSourceError` to propagate and print error then exit with non-zero status; print done banner with output path

---

## Dependencies

```
Phase 1 → Phase 2 → Phase 3 (US1) → Phase 4 (US2) → Phase 5 (US3)
                                                    ↘ Phase 6 (US4) ← Phase 5
                                                    Phase 6 → Phase 7
```

**Parallel execution within phases**:
- Phase 1: T002 ∥ T003
- Phase 3 tests: T008 ∥ T009 (different files)
- Phase 3 impl: T010 ∥ T011 (different modules)
- Phase 6 chart impl: T019 ∥ T020 (independent chart functions)
- Phase 7: T022 ∥ T023 (independent)

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 23 |
| Phase 1 (Setup) | 3 tasks |
| Phase 2 (Foundational) | 3 tasks |
| Phase 3 / US1 (P1) | 6 tasks |
| Phase 4 / US2 (P1) | 2 tasks |
| Phase 5 / US3 (P2) | 2 tasks |
| Phase 6 / US4 (P2) | 5 tasks |
| Phase 7 (Polish) | 2 tasks |
| Parallelisable [P] | 9 tasks |
| Scenarios | 3 fixed (A/B/C) — down from 44 |
