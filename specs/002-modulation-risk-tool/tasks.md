# Tasks: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Updated**: 2026-05-18 (v3 — post-analysis remediation)

**Input**: spec.md (v2), plan.md (v2), data-model.md (v2), contracts/cli-schema.md, research.md

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
- [ ] T002 [P] Update `requirements.txt` (remove pvlib; keep numpy≥1.26, pandas≥2.1, plotly≥5.20, google-cloud-bigquery≥3.10, pytest≥8.0, pytest-cov≥4.1) and `pyproject.toml` (bump version to `2.0.0`, update entry point to `solar_bess_risk.__main__:main`)
- [ ] T003 [P] Rewrite `solar_bess_risk/config.py` — remove ILR list, BESS size ratios, RNG seed, min SoC threshold, injection floor, and discount rate; add: `SCENARIO_TEMPLATES: list[ScenarioTemplate]` (static `label`/`peak_hours`/`duration_h` constants for A/B using whole-hour windows 18-20 and 17-21; **note**: profile-dependent fields `bess_power_mw`, `charge_power_mw`, `bess_energy_mwh`, `capex_brl` are NOT set here — full `ScenarioDefinition` objects are assembled in `__main__.py` after CSV loading), `PEAK_HOURS_BY_LABEL: dict[str, frozenset[int]]`, `DEFAULT_BQ_YEAR: int = 2025`, `DEFAULT_BQ_SUBMARKET: str = "SE"`, `DEFAULT_CAPEX_USD_KWH: float = 200.0`, `DEFAULT_USD_BRL_RATE: float = 5.0`, `DEFAULT_USEFUL_LIFE_YR: int = 20`, BESS defaults for 85% efficiency, 1.5% O&M over CAPEX, and 2% annual degradation; `SimulationParams` dataclass with fields per data-model.md (including `bq_service_account_path: str | None = None`); `PARAM_BOUNDS` dict for all validated parameters; no magic numbers anywhere else in the codebase

**Checkpoint**: `pip install -e .` and `python -m solar_bess_risk --help` exit cleanly.

---

## Phase 2: Foundational

**Purpose**: Cross-cutting infrastructure (manifest, entry-point stub) that every user story depends on.

⚠️ **CRITICAL**: Write failing tests FIRST (T004). Confirm they fail before implementing T005.

- [ ] T004 Write failing tests in `tests/unit/test_manifest.py` — run-ID format matches `YYYYMMDD-HHMMSS-<7-char hex>`; SHA-256 of `json.dumps(params_dict, sort_keys=True)` is deterministic; manifest JSON contains all required fields: `tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `profile_source`, `price_source`, `fc`, `garantia_fisica_mw`, `scenarios`; `bq_service_account_path` is **absent from the serialised params dict and absent from manifest.json entirely** (not present as `null`); `scenarios` is a list of 2 dicts each with `label`, `peak_hours`, `duration_h`, `bess_power_mw`, `charge_power_mw`, `bess_energy_mwh`, `capex_brl`; two calls with identical inputs produce identical SHA-256
- [ ] T005 Implement `solar_bess_risk/manifest.py` — `RunManifest` dataclass (fields: `tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `profile_source`, `price_source`, `fc`, `garantia_fisica_mw`, `scenarios: list[dict]`), `generate_run_id() -> str`, `hash_params(params: SimulationParams) -> str` (SHA-256 of sorted JSON of all fields except `bq_service_account_path`, which is excluded and not serialised at all), `write_manifest(manifest: RunManifest, output_dir: Path) -> Path` (creates `output/<run-id>/manifest.json`); all functions PEP 484 annotated; all public functions carry a NumPy-style docstring (purpose, parameters with units, return value, raised exceptions)
- [ ] T006 [P] Implement `solar_bess_risk/__main__.py` stub — `argparse` with `--service-account <path>` flag; `main()` prints `"[solar_bess_risk v2.0.0] Not yet implemented — see T023"` and returns; **this is a placeholder only; the full module chaining is done in T023**; `solar_bess_risk/__init__.py` sets `__version__ = "2.0.0"`; `main()` carries a NumPy-style docstring

**Checkpoint**: `pytest tests/unit/test_manifest.py` passes.

---

## Phase 3: User Story 1 — Configure Parameters and Load Profile (P1) 🎯 MVP

**Goal**: Engineer provides solar CSV path and MWac, accepts other parameter defaults, tool computes garantia física, fetches BigQuery prices, confirms inputs, proceeds.

**Independent Test**: Run with a valid solar CSV and MWac, press Enter at all other prompts → tool reports fc, garantia_fisica_mw, fetches BQ prices, proceeds to simulation.

### Tests for User Story 1 ⚠️ Write FIRST — confirm they FAIL before implementing T010–T012

- [ ] T007 Write failing contract tests in `tests/contract/test_cli_schema.py` — CT-01 (Enter at non-required prompts → defaults); CT-02 (out-of-bounds value → `ERRO:` message cites parameter name, value, range; re-prompts without aborting); CT-03 (non-numeric value → `ERRO:` + reprompt); CT-04 (8761-row solar CSV → rejected, message cites actual and expected row count); CT-05 (negative value in CSV → `ERRO:` cites row index and value); CT-06 (non-numeric value in CSV → `ERRO:` cites row index and value); CT-07 (missing CSV path → run aborts with descriptive error); CT-08 (BQ auth failure → `DataSourceError` propagates, run aborts with descriptive error, no partial output written); CT-09 (BQ returns ≠ 8760 rows → aborts, message cites actual vs expected count); CT-10 (MWac ≤ 0 → rejected with `ERRO:` + reprompt); CT-11 (confirmation summary shows `fc` and `garantia_fisica_mw`); CT-12 (`bq_service_account_path` absent from confirmation summary and absent from manifest.json entirely — not even as null)
- [ ] T008 [P] Write failing unit tests in `tests/unit/test_profile.py` — CSV loader: shape `(8760,)`, all values ≥ 0 after clipping negatives to zero, correct `annual_energy_mwh = sum(generation_mw)`, correct `fc = annual_energy_mwh / (mwac * 8760)`, correct `garantia_fisica_mw = mwac * fc`; rejects non-numeric row (cites row index + value), wrong row count (cites actual vs 8760); `csv_filename` equals `os.path.basename(path)`; zero-energy profile (all zeros) raises `StructuredError`
- [ ] T009 [P] Write failing unit tests in `tests/unit/test_data_sources.py` — `fetch_price_bigquery` returns `PriceProfile` with `source == 'bigquery_pld_SE_2025'`, `len(prices_brl_per_mwh) == 8760`, all values ≥ 0; `DataSourceError` raised (and propagates without fallback) on BQ auth failure, network error, row count ≠ 8760; mocked BQ client returns deterministic test price arrays

### Implementation for User Story 1

- [ ] T010 [US1] Rewrite `solar_bess_risk/profile.py` — remove synthetic pvlib profile generator entirely; implement `SolarProfile` dataclass per data-model.md; `load_solar_csv(path: str, mwac: float) -> SolarProfile` with full validation (shape, numeric, negatives clipped to zero) and garantia física computation (`fc = annual_energy_mwh / (mwac * 8760)`, `garantia_fisica_mw = mwac * fc`); zero-energy profile raises `StructuredError("Solar CSV has zero annual energy; cannot derive garantia física")`; prints load summary (min, max, mean generation in MW, fc, garantia_fisica_mw); all functions PEP 484 annotated; all public functions carry a NumPy-style docstring
- [ ] T011 [US1] Update `solar_bess_risk/data_sources.py` if needed — verify `DataSourceError` class exists and propagates without fallback; verify `fetch_price_bigquery(params: SimulationParams) -> PriceProfile` returns correct `PriceProfile` dataclass with `source` field formatted as `"bigquery_pld_{submarket}_{year}"`; no changes to BQ query logic unless required by updated schema
- [ ] T012 [US1] Rewrite `solar_bess_risk/cli.py` — remove ILR, BESS size ratios, RNG seed, min SoC, injection floor, and discount rate prompts; prompt flow: (1) required CSV path (no default; validates file exists and is loadable), (2) required MWac (no default; must be > 0), (3) BQ submarket [SE/S/NE/N] with default SE, (4) BQ year with default 2025, (5) CAPEX USD/kWh with default 200, (6) USD/BRL rate with default 5.0, (7) useful life years with default 20, (8) BESS efficiency default 85%, (9) O&M default 1.5% CAPEX/yr, (10) degradation default 2%/yr; each prompt displays parameter unit and valid range inline; confirmation summary shows all accepted values plus `fc` and `garantia_fisica_mw`; error messages follow contract format `"ERRO: Parameter '{name}': value {v} {unit} outside [{lo}, {hi}] {unit}; re-enter"`; `--help` lists all parameters with defaults and bounds; all public functions carry a NumPy-style docstring

**Checkpoint**: CT-01 through CT-12 all pass. CSV loads in < 1 s. BQ `DataSourceError` aborts run.

---

## Phase 4: User Story 2 — Simulate Three Fixed Scenarios (P1)

**Goal**: Tool simulates scenarios A, B, C hour-by-hour, enforces all SoC/power bounds, reports progress and runtime.

**Independent Test**: Run simulation for both scenarios. Verify `annual_exposure_with_bess ≤ annual_exposure_without_bess` for every scenario.

### Tests for User Story 2 ⚠️ Write FIRST — confirm they FAIL before implementing T014

- [ ] T013 Write failing unit tests in `tests/unit/test_simulation.py`:
  - SoC never < 0 or > `bess_energy_mwh` across all 8760 hours (both scenarios)
  - `charge_mwh[h] > 0` and `discharge_mwh[h] > 0` never simultaneously in same hour
  - `charge_mwh[h] > 0` only when `generation[h] > garantia_fisica_mw` AND `h%24 NOT in peak_hours`
  - **A2 edge case**: `charge_mwh[h] == 0` when `generation[h] > garantia_fisica_mw` AND `h%24 IN peak_hours` (excess during a peak hour does NOT trigger charging; `deficit_mwh[h]` collapses to 0)
  - `discharge_mwh[h] > 0` only when `h%24 IN peak_hours`
  - `deficit_mwh[h] = max(0, garantia_fisica_mw - generation[h])` for peak hours, 0 otherwise
  - `residual_deficit_mwh[h] = deficit_mwh[h] - discharge_mwh[h]` for all h
  - `residual_deficit_mwh[h] >= 0` for all h
  - `grid_injection_mwh[h] = generation[h] - charge_mwh[h] + discharge_mwh[h]` for all h
  - `simulate_all_scenarios` returns `list[tuple[ScenarioDefinition, DispatchResult]]` of length 3

### Implementation for User Story 2

- [ ] T014 [US2] Rewrite `solar_bess_risk/simulation.py` — remove ILR sweep, BESS size ratio sweep, curtailment logic, and grid top-up logic; implement `simulate_scenario(solar: SolarProfile, prices: PriceProfile, scenario: ScenarioDefinition, params: SimulationParams) -> DispatchResult` with vectorised NumPy dispatch per FR-006, applying BESS efficiency to charged energy (charging capped by `charge_power_mw`; discharging capped by `bess_power_mw`; excess during a peak hour does NOT trigger charging — deficit collapses to 0 so BESS is idle); `simulate_all_scenarios(solar: SolarProfile, prices: PriceProfile, scenarios: list[ScenarioDefinition], params: SimulationParams, progress_cb: Callable[[str], None] | None = None) -> list[tuple[ScenarioDefinition, DispatchResult]]` runs A/B and returns paired (scenario, dispatch) tuples — **does NOT compute economics**; economic fields are added downstream by `economics.compute_all_scenarios()` in T016; post-simulation SoC bound assertion (raises `SimulationConstraintError` on violation); all functions PEP 484 annotated; all public functions carry a NumPy-style docstring

**Checkpoint**: `pytest tests/unit/test_simulation.py` passes. 2 scenarios complete in < 30 s (simulation only, with uniform prices).

---

## Phase 5: User Story 3 — Review Per-Scenario Economic Metrics (P2)

**Goal**: For each scenario, compute all 10 output metrics from FR-007 including exposures, savings, payback, coverage.

**Independent Test**: Scenario A, uniform PLD 500 BRL/MWh for all hours: verify `annual_exposure_without_bess = garantia_fisica_mw × 2 × 365 × 500` (2 peak hours/day × 365 days) and `coverage_pct = 1 − (exposure_with / exposure_without)`.

### Tests for User Story 3 ⚠️ Write FIRST — confirm they FAIL before implementing T016

- [ ] T015 Write failing unit tests in `tests/unit/test_economics.py`:
  - Uniform-price exposure formula: `exposure_without = garantia_fisica_mw × count_of_peak_hours_in_year × P`
  - `exposure_with = Σ(residual_deficit_mwh[h] × P)` for peak hours
  - `annual_gross_savings = Σ((grid_injection_with_bess − GF) × PLD) − Σ((grid_injection_without_bess − GF) × PLD)`, including deficit reduction and surplus above GF
  - `annual_savings = annual_gross_savings − annual_o_and_m`
  - `payback_years = capex_brl / annual_savings` (reference case with known CAPEX and savings)
  - **I2**: `payback_years` is stored as `float | None` in `ScenarioResult` — `None` when `annual_savings ≤ 0`; `payback_display(result)` returns the string `"não atingível"` when `payback_years is None`; the `payback_years` field is never the string itself
  - `coverage_pct = (1 − exposure_with / exposure_without) × 100` (range [0, 100])
  - `capex_brl = bess_energy_mwh × capex_usd_per_kwh × 1000 × usd_brl_rate`
  - If BESS fully covers all peak-hour deficits: `exposure_with = 0`, `coverage_pct = 100`
  - `compute_all_scenarios` accepts `list[tuple[ScenarioDefinition, DispatchResult]]` and returns `list[ScenarioResult]`
  - Top-10 peak hours table identifies correct 10 hours by highest PLD within the union of all scenarios' peak_hours {17, 18, 19, 20}

### Implementation for User Story 3

- [ ] T016 [US3] Rewrite `solar_bess_risk/economics.py` — remove LCOS, incremental revenue, curtailment metrics, top-up slot tracking, and discount rate; implement gross savings, fixed O&M, year-1 net savings, degraded lifetime net savings, and simple degraded payback in `compute_scenario_economics(solar: SolarProfile, prices: PriceProfile, scenario: ScenarioDefinition, dispatch: DispatchResult, params: SimulationParams) -> ScenarioResult`; `compute_all_scenarios(solar: SolarProfile, prices: PriceProfile, dispatch_pairs: list[tuple[ScenarioDefinition, DispatchResult]], params: SimulationParams) -> list[ScenarioResult]`; `build_top10_peak_hours(results: list[ScenarioResult], prices: PriceProfile) -> pd.DataFrame` (10 rows by highest PLD in union of all peak_hours sets; columns: `hour_index`, `date`, `hour_of_day`, `pld_brl_per_mwh`, plus for each scenario `dispatch_mwh` and `residual_deficit_mwh`); `payback_display(result: ScenarioResult) -> str` (returns `"não atingível"` if `payback_years is None`); all functions PEP 484 annotated; all public functions carry a NumPy-style docstring
- [ ] T016a [US3] Add `projection.py` with year-by-year RTE cashflow projection for payback and LCOS. For each useful-life year, re-run dispatch with that calendar year's supplier RTE, compute net-balance benefit, fixed O&M, cumulative payback, lifetime discharged MWh, and LCOS. Reports must use this projection when present.

**Checkpoint**: `pytest tests/unit/test_economics.py` passes. Economic formulas match hand-calculated reference cases.

---

## Phase 6: User Story 4 — Self-Contained HTML Report (P2)

**Goal**: Tool writes a single offline HTML file with 3 Plotly charts and 2 tables (scenario summary + top-10 hours).

**Independent Test**: Generate report with a valid CSV and default params. Open `output/<run-id>/report.html` offline — all charts render, both tables present, no console errors, no CDN references.

### Tests for User Story 4 ⚠️ Write FIRST — confirm they FAIL before implementing T018–T021

- [ ] T017 Write failing integration tests in `tests/integration/test_full_run.py`:
  - End-to-end run (mocked BQ with 8760 uniform prices, valid CSV, all defaults) completes without exception
  - `output/<run-id>/report.html` exists and contains `<!DOCTYPE html>`
  - HTML file contains no `cdn.plot.ly` or other external URL references
  - `output/<run-id>/manifest.json` parses as valid JSON and contains all required fields: `tool_version`, `run_id`, `timestamp_iso8601`, `params_sha256`, `profile_source`, `price_source`, `fc`, `garantia_fisica_mw`, `scenarios` (list of 2 dicts)
  - `manifest.json` does NOT contain a `bq_service_account_path` key at any level (not even as null)
  - `len(results) == 2` (exactly 2 `ScenarioResult` objects)
  - HTML summary table contains exactly 3 data rows (one per scenario)
  - **SC-001** (simulation scope): wall-clock time for `simulate_all_scenarios()` with mocked uniform prices < 30 s; note — this covers simulation performance only; BigQuery fetch latency is excluded from this test
  - **SC-002 (manual gate)**: `pytest.mark.skip(reason="SC-002: manual browser verification required — open report.html with network disabled and confirm all charts render within 10 s with no console errors; record outcome as ✅/❌ in the PR description")` stub test
  - **SC-003**: two consecutive runs with identical mocked prices and CSV produce byte-identical numerical results for both scenarios (difference < 1e-10)

### Implementation for User Story 4

- [ ] T018 [US4] Implement chart (a) in `solar_bess_risk/report_charts.py` — `build_exposure_bar_chart(results: list[ScenarioResult]) -> go.Figure`: grouped bar chart, one group per scenario (A/B), two bars per group (`annual_exposure_without_bess_brl`, `annual_exposure_with_bess_brl`), Y-axis label "Exposição Financeira (BRL/ano)", hover tooltip shows exact BRL value with label, title "Exposição Financeira: Sem vs Com BESS", legend present; function carries a NumPy-style docstring
- [ ] T019 [P] [US4] Implement chart (b) in `solar_bess_risk/report_charts.py` — `build_capex_savings_bar_chart(results: list[ScenarioResult], useful_life_years: int) -> go.Figure`: grouped bar chart per scenario, bars = `capex_brl` and undiscounted cumulative savings (`annual_savings_brl × useful_life_years`), Y-axis label "BRL", title "CAPEX vs Economia Acumulada no Horizonte de Vida Útil", hover shows exact BRL values; function carries a NumPy-style docstring
- [ ] T020 [P] [US4] Implement chart (c) in `solar_bess_risk/report_charts.py` — `build_payback_curve(results: list[ScenarioResult]) -> go.Figure`: line chart, X = year (1..`useful_life_years` from `results[0].scenario`), Y = cumulative savings BRL for each scenario (A, B, C as separate lines); for scenarios where `annual_savings_brl ≤ 0` plot the flat/negative line and annotate `"não atingível"` in the legend rather than omitting it; horizontal dashed reference line at each scenario's `capex_brl` (same colour as its line, dashed); title "Curva de Payback: Economia Acumulada vs Anos"; X-axis label "Ano", Y-axis label "Economia Acumulada (BRL)"; function carries a NumPy-style docstring
- [ ] T021 [US4] Implement `solar_bess_risk/report_export.py` — `build_summary_table_html(results: list[ScenarioResult]) -> str` (3 rows × 10 columns, Portuguese headers with units, `payback_display()` for payback column, `coverage_pct` to 1 decimal place with `%`); `build_top10_table_html(top10_df: pd.DataFrame) -> str` (10 rows: Data, Hora, PLD BRL/MWh, and per scenario: Despacho BESS MWh + Déficit Residual MWh); `write_report(figures: list[go.Figure], summary_html: str, top10_html: str, results: list[ScenarioResult], params: SimulationParams, output_dir: Path) -> Path` (Jinja-free string assembly; **`include_plotlyjs='inline'`** — do NOT pass `True` or `'cdn'`; "Premissas e Limitações do Modelo" section); the Premissas section MUST cite these regulatory instruments by exact name and scope: **Portaria MME nº 101/2016** (methodology for calculating physical guarantee of new SIN generation projects; establishes the capacity-factor approach: `garantia_fisica_mw = mwac × fc`), **Portaria MME nº 60/2020** (specific procedures for solar PV plants including physical guarantee revision based on verified generation), **CCEE Regras de Comercialização — Módulo 03 Garantia Física** (operational treatment of physical guarantee in CCEE accounting — lastro, sazonalização, modulação; does NOT define the original calculation methodology), **ANEEL Resolução Normativa nº 1.034/2022** (deadlines and conditions for sazonalização and modulação of physical guarantee); each Premissas item MUST cross-reference which chart(s) it affects; all public functions carry a NumPy-style docstring

**Checkpoint**: `pytest tests/integration/test_full_run.py` passes. HTML opens offline with all charts and tables.

---

## Phase 7: Polish & End-to-End Wiring

⚠️ **CRITICAL**: Write failing tests FIRST (T022a). Confirm they FAIL before implementing T022.

- [ ] T022a Write failing unit tests for spec.md §Edge Cases in `tests/unit/test_simulation.py` and `tests/unit/test_economics.py`:
  - All peak hours have zero generation: `charge_mwh` all-zero (BESS never charged during non-peak hours either); `discharge_mwh` all-zero; `residual_deficit_mwh[h] == garantia_fisica_mw` for every peak hour h
  - BESS fully discharges mid-peak block (Scenario C, 4 peak hours): after SoC reaches 0 mid-block, `residual_deficit_mwh[h] > 0` for remaining peak hours in that block; simulation does not raise or loop infinitely
  - High-fc CSV (all hours generate at MWac): `garantia_fisica_mw ≈ mwac`; `annual_exposure_with_bess_brl ≈ 0`; `coverage_pct ≈ 100`; no division-by-zero occurs
  - `annual_savings_brl ≤ 0`: `payback_years is None`; `payback_display()` returns `"não atingível"`; `write_report()` completes without exception
  - **A2 edge case**: excess generation during a peak hour → `charge_mwh[h] == 0`, `deficit_mwh[h] == 0`; BESS idle in that hour
- [ ] T022 [P] Add edge-case guards in `solar_bess_risk/simulation.py` and `solar_bess_risk/economics.py` — BESS fully discharges before end of peak block (remaining peak hours in the block use full deficit as residual; simulation continues); all peak hours have zero generation (BESS never charged; full deficit everywhere); `annual_savings_brl ≤ 0` (payback = None; report and manifest generate without exception); excess during peak hour (no charge triggered per FR-006 A2 edge case)
- [ ] T023 Wire full end-to-end session in `solar_bess_risk/__main__.py` — replace T006 stub with full chain: `cli.run_session() → profile.load_solar_csv() → data_sources.fetch_price_bigquery() → [assemble ScenarioDefinition list from config + solar] → simulation.simulate_all_scenarios() → economics.compute_all_scenarios() → economics.build_top10_peak_hours() → report_charts.build_exposure_bar_chart() → report_charts.build_capex_savings_bar_chart() → report_charts.build_payback_curve() → report_export.write_report() → manifest.write_manifest()`; print progress banner at each stage; allow `DataSourceError` to propagate — catch at top level, print descriptive error, exit with code 1, write no partial output; print done banner showing output path and elapsed time in seconds

---

## Dependencies

```
Phase 1 → Phase 2 → Phase 3 (US1, P1) → Phase 4 (US2, P1) → Phase 5 (US3, P2) → Phase 6 (US4, P2) → Phase 7
```

- Phase 6 depends on Phase 5 — `ScenarioResult` objects are required by all chart builders and summary table
- Phase 7 (T022, T023) depends on Phase 6 completing
- T014 (`simulate_all_scenarios`) returns `list[tuple[ScenarioDefinition, DispatchResult]]`; T016 (`compute_all_scenarios`) consumes this — simulation and economics modules are decoupled

**Parallel execution within phases**:

| Phase | Parallel opportunities |
|-------|----------------------|
| Phase 1 | T002 ∥ T003 |
| Phase 3 tests | T008 ∥ T009 |
| Phase 3 impl | T010 ∥ T011 |
| Phase 6 chart impl | T019 ∥ T020 |
| Phase 7 | T022a → T022 (serial — tests must fail before guards); T022 ∥ T023 |

---

## Summary

| Metric | Value |
|--------|-------|
| Total tasks | 25 |
| Phase 1 (Setup) | 3 tasks |
| Phase 2 (Foundational) | 3 tasks |
| Phase 3 / US1 (P1) | 6 tasks |
| Phase 4 / US2 (P1) | 2 tasks |
| Phase 5 / US3 (P2) | 2 tasks |
| Phase 6 / US4 (P2) | 5 tasks |
| Phase 7 (Polish) | 4 tasks (T022a, T022, T023 + T022a counted separately) |
| Parallelisable [P] | 9 tasks |
| Scenarios | 2 fixed (A/B) |

### Task-to-Requirement Coverage

| FR / SC | Tasks |
|---------|-------|
| FR-001 (parameters + defaults) | T003, T007, T012 |
| FR-002 (CSV required, no fallback) | T008, T010 |
| FR-003 (garantia física computation) | T008, T010 |
| FR-004 (BigQuery mandatory) | T009, T011 |
| FR-005 (2 fixed scenarios) | T003, T013, T014 |
| FR-006 (dispatch rules + A2 edge case) | T013, T014, T022a, T022 |
| FR-007 (10 metrics) | T015, T016 |
| FR-008 (CAPEX formula) | T015, T016 |
| FR-009 (HTML content — 3 charts + 2 tables) | T017, T018, T019, T020, T021 |
| FR-010 (self-contained + regulatory norms) | T021 |
| FR-011 (manifest) | T004, T005 |
| FR-012 (validation re-prompt) | T007, T012 |
| SC-001 (< 30 s, simulation scope) | T017 |
| SC-002 (offline render, manual gate) | T017 |
| SC-003 (determinism) | T017 |
| SC-004 (formula accuracy) | T015 |
| Edge cases (spec.md §Edge Cases) | T022a, T022 |
