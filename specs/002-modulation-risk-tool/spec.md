# Feature Specification: Solar+BESS Modulation Risk Analysis Tool

**Feature Branch**: `002-modulation-risk-tool`

**Created**: 2026-05-15

**Status**: Draft (v2 — Garantia Física Dispatch Model)

---

## Clarifications

### Session 2026-05-15

- Q: How should BESS CAPEX (USD/kWh) be converted to BRL for economic outputs? → A: Add a `USD/BRL exchange rate` parameter (default 5.0); engineer enters CAPEX in USD/kWh; tool converts internally for all BRL outputs.
- Q: Which JavaScript charting library should be embedded in the self-contained HTML report? → A: Plotly.js, generated via the Python `plotly` library with the full offline bundle embedded inline.
- Q: At what rate does the BESS charge? → A: Daytime only, from excess generation above garantia física. No grid top-up. No synthetic fallback — CSV required.
- Resolution FR-004: BigQuery is the sole hourly price data source. If BigQuery is unavailable the run aborts immediately with a descriptive error message identifying the connection issue.
- Resolution v2: ILR parameter removed entirely. Curtailment logic removed entirely. Grid top-up charging removed. Dispatch model replaced by garantia física physical guarantee framework with 2 fixed scenarios (A/B).

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Configure Parameters and Load Profile (Priority: P1)

A renewable energy project development engineer starts the tool and is presented
with every configurable parameter alongside its default value. The engineer provides
the solar generation CSV file path and the plant AC capacity (MWac). The tool
derives the physical guarantee (garantia física) from the CSV profile automatically.
It then fetches hourly energy prices from BigQuery (CCEE PLD data for the configured
submarket and year). The tool validates all inputs before proceeding.

**Why this priority**: Every downstream calculation depends on correct parameters
and profile data. A failed or unvalidated input propagates silently into all results.

**Independent Test**: Launch the tool, provide a valid solar CSV path and MWac, accept
all other defaults. The tool must fetch prices, compute garantia física, and proceed
to simulation — delivering a complete HTML report.

**Acceptance Scenarios**:

1. **Given** the tool is started, **When** the engineer presses Enter at every
   parameter prompt (except CSV path and MWac which are required), **Then** all
   parameters retain their default values and the analysis proceeds without errors.
2. **Given** the engineer provides a numeric value at any parameter prompt, **When**
   the prompt advances, **Then** the parameter is updated and all downstream
   calculations use the new value.
3. **Given** the engineer provides an out-of-range value (e.g., negative CAPEX, zero
   useful life), **When** the prompt is submitted, **Then** the tool displays a
   descriptive error referencing the physical or commercial bound violated and
   re-prompts without aborting.
4. **Given** the engineer provides a valid CSV path for the solar profile, **When**
   the file is loaded, **Then** the tool validates exactly 8,760 rows of non-negative
   numeric values and confirms the load with a summary (min, max, mean generation in MW,
   computed fc, garantia_fisica_mw).
5. **Given** the CSV solar profile contains a row with a non-numeric value,
   **When** loading is attempted, **Then** the tool identifies the exact row number and
   value, rejects the file, and exits with a descriptive error. Negative numeric values
   are treated as zero because the Baguaçu hourly profile contains night-time noise.
6. **Given** the CSV solar profile has a row count other than 8,760, **When** loading
   is attempted, **Then** the tool rejects the file citing actual and expected row counts.
7. **Given** BigQuery credentials are invalid, the network is unavailable, or the CCEE
   table returns a row count other than 8,760, **When** the price fetch is attempted,
   **Then** the tool aborts immediately with a descriptive error message identifying the
   failure reason and does not proceed to simulation.

---

### User Story 2 — Simulate Two Fixed Scenarios (Priority: P1)

After configuration, the tool simulates three fixed BESS scenarios (A, B, C) hour by
hour for an entire year. The engineer observes progress feedback during the run.
On completion the tool reports simulation runtime.

**Why this priority**: Simulation is the computational core. Errors here propagate to
all reported metrics and charts.

**Independent Test**: With a valid CSV and MWac, run simulation for all three scenarios.
Verify that `annual_exposure_with_bess ≤ annual_exposure_without_bess` for every scenario.

**Acceptance Scenarios**:

1. **Given** valid parameters and a solar profile, **When** simulation runs, **Then**
   results are produced for exactly 2 scenarios: A (2 h) and B (4 h).
2. **Given** any scenario, **When** the scenario is simulated, **Then** SoC never
   exceeds `bess_energy_mwh` and never falls below 0, hour by hour.
3. **Given** any hour h in {17, 18, 19, 20}, **When** results are examined, **Then**
   `residual_deficit_h = max(0, deficit_h − dispatch_h)` is correctly computed.
4. **Given** BESS dispatch in a peak hour, **When** results are examined, **Then**
   `dispatch_h = min(deficit_h, bess_power_mw, available_energy_mwh)` and never
   exceeds available energy.
5. **Given** a charging hour where the h-rule passes (`rte × min_PLD_peak > PLD_h`),
   **When** results are examined, **Then**
   `charge_h = min(excess_h, remaining_capacity_mwh)` and
   `grid_injection_h = generation_h - charge_h`, with `grid_injection_h ≥ 0`.
   If the h-rule fails, `charge_h = 0` and `grid_injection_h = generation_h`.

---

### User Story 3 — Review Per-Scenario Economic Metrics (Priority: P2)

For each scenario the engineer reviews 10 economic indicators: fc, garantia_fisica_mw,
bess_energy_mwh, bess_power_mw, capex_brl, annual_exposure_without_bess (BRL/yr),
annual_exposure_with_bess (BRL/yr), annual_savings (BRL/yr), payback_years, and
coverage_pct (%). Exposure reflects the time value of the financial risk — peak-hour
residual deficit priced at actual PLD.

**Why this priority**: Economic metrics drive the investment decision. They can be
verified independently of the visual report.

**Independent Test**: Single scenario (A, 2 h), uniform PLD price of 500 BRL/MWh for
all 8,760 hours: verify
`annual_exposure_without_bess = garantia_fisica_mw × 730 × 500` (2 peak hrs/day × 365 days = 730 hrs/yr)
and `coverage_pct = 1 − (exposure_with / exposure_without)`.

**Acceptance Scenarios**:

1. **Given** any valid CSV, **When** fc is computed, **Then** `fc = annual_energy_mwh /
   (mwac × 8760)` and `garantia_fisica_mw = mwac × fc`, both > 0.
2. **Given** hourly PLD prices from BigQuery, **When** exposure is computed, **Then**
   `annual_exposure_without_bess = Σ(deficit_h × PLD_h)` summed over all guarantee-window
   hours h across 8,760 h, using only whole-hour guarantee windows.
3. **Given** annual_savings is zero (BESS provides no relief), **When** payback is
   computed, **Then** payback is reported as "não atingível" — no division by zero occurs.
4. **Given** any scenario, **When** coverage_pct is computed, **Then**
   `coverage_pct = 1 − (exposure_with / exposure_without)` where exposure_without > 0;
   result is in [0, 1] and expressed as a percentage.

---

### User Story 4 — Receive Self-Contained HTML Report with Charts and Tables (Priority: P2)

After simulation and economics complete, the tool writes a single self-contained HTML
file. The engineer opens it in any modern browser — offline, without network access —
and finds interactive charts and tables. The report is shareable with non-technical
stakeholders and requires no special software to view.

**Why this priority**: The report is the primary deliverable shared with decision-makers.

**Independent Test**: Generate the report with a valid CSV and default parameters, open
the HTML file in a browser while offline, verify all charts render with data and
interactive tooltips, all tables are present, and no browser console errors appear.

**Acceptance Scenarios**:

1. **Given** all computations complete without error, **When** the report is generated,
   **Then** a single `.html` file is written to `output/<run-id>/report.html` and a
   JSON manifest is written alongside it at `output/<run-id>/manifest.json`.
2. **Given** the HTML report, **When** opened offline, **Then** all charts and tables
   render without broken elements or network requests.
3. **Given** the summary table, **When** reviewed, **Then** it contains one row per
   scenario (A, B, C) with all 10 metrics labelled in Portuguese with units.
4. **Given** the exposure bar chart, **When** viewed, **Then** it shows
   `annual_exposure_without_bess` and `annual_exposure_with_bess` side by side for
   each scenario, with hover tooltips showing exact values in BRL/yr.
5. **Given** the CAPEX vs cumulative savings bar chart, **When** viewed, **Then** it
   shows CAPEX (BRL) and cumulative savings at useful-life horizon side by side for
   each scenario.
6. **Given** the payback curve, **When** viewed, **Then** it plots cumulative savings
   (BRL) vs year (1 to useful_life) for scenarios A, B, C as separate lines, with a
   horizontal reference line at CAPEX value; x-axis is years, y-axis is BRL.
7. **Given** the top-10 peak hours table, **When** reviewed, **Then** it lists the
   10 hours (across all 8,760 h) with the highest PLD that fall within any scenario's
   peak_hours, showing for each: date, hour, PLD (BRL/MWh), and for each scenario
   the BESS dispatch (MWh) and residual deficit (MWh).

---

### Edge Cases

- Solar CSV where all peak hours have zero generation: BESS cannot discharge (never
  charged during those hours); residual deficit equals full deficit in all peak hours.
- BESS fully discharges mid-peak (insufficient energy for all 4 peak hours in scenario
  C): `residual_deficit_h > 0` for remaining hours; simulation must not loop or error.
- Solar CSV with only daytime generation in summer (high fc): garantia física may
  approach or equal MWac; all peak hours fully served; exposure_with ≈ 0.
- annual_savings ≤ 0 (BESS costs more than it saves): payback reported as "não atingível".
- BigQuery authentication failure or network error: the run aborts immediately with a
  descriptive error message; no partial output is written.
- BigQuery returns a row count other than 8,760 for the requested year and submarket:
  the run aborts with a message stating the actual and expected row counts.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST present each configurable parameter with its default value
  and prompt the engineer to accept or provide a replacement before any computation
  starts. Required inputs (no default): solar CSV file path, MWac. Parameters with
  defaults: BigQuery PLD year (2025), BigQuery submarket (SE), BESS CAPEX USD/kWh
  (200), USD/BRL exchange rate (5.0), useful life years (20).
  ILR is NOT a parameter. The tool multiplies CAPEX (USD/kWh) by the exchange rate
  to obtain BRL/kWh for all cost and economic calculations.

  **Parameter validation bounds**:

  | Parameter | Default | Min | Max | Unit |
  |-----------|---------|-----|-----|------|
  | MWac | — (required) | > 0 | — | MWac |
  | BigQuery PLD year | 2025 | 2000 | 2100 | year |
  | BigQuery submarket | SE | — | — | one of {SE, S, NE, N} |
  | BESS CAPEX | 200 | > 0 | — | USD/kWh |
  | USD/BRL exchange rate | 5.0 | > 0 | — | BRL/USD |
  | Useful life | 20 | ≥ 1 | 100 | years |
  | Round-trip efficiency (rte) | 0.85 | > 0 | ≤ 1 | dimensionless |

- **FR-002**: The tool MUST require a solar generation CSV file (8,760 rows, one numeric
  value per row or an `avg_generation` column, power in MW). Negative numeric values MUST
  be clipped to zero before any downstream calculation. No synthetic fallback. If the file
  is absent or invalid, the run MUST abort with a descriptive error message.

- **FR-003**: The physical guarantee (garantia física) MUST be calculated from the CSV
  profile as follows:
  - `annual_energy_mwh = Σ(generation_h)` for h in 1..8760
  - `fc = annual_energy_mwh / (mwac × 8760)`
  - `garantia_fisica_mw = mwac × fc`
  Both `fc` and `garantia_fisica_mw` MUST be displayed in the CLI confirmation summary
  and included in the HTML report and JSON manifest.
- **FR-004**: Hourly energy prices MUST be fetched from BigQuery using the CCEE PLD
  table for the configured submarket and year. BigQuery is the only price data source;
  no CSV price input or flat-rate fallback is provided. If the BigQuery connection fails,
  the requested table returns an unexpected row count, or authentication is rejected,
  the run MUST abort immediately with a descriptive error message identifying the failure
  reason. The engineer MUST resolve the connectivity issue before re-running.
- **FR-005**: The tool MUST simulate exactly three fixed scenarios:
  - Scenario A: guarantee window 18:00-20:00, peak_hour_weights = {18: 1.0, 19: 1.0}, duration = 2 h
  - Scenario B: guarantee window 17:00-21:00, peak_hour_weights = {17: 1.0, 18: 1.0, 19: 1.0, 20: 1.0}, duration = 4 h
  For each scenario:
  - `bess_power_mw` comes from the executed block-sized scenario
  - `charge_power_mw = bess_power_mw` unless explicitly overridden
  - `bess_energy_mwh` comes from the executed block-sized scenario
  - `capex_brl = scenario.capex_brl`
- **FR-006**: BESS dispatch MUST enforce hour-by-hour physical limits. In mode 3,
  dispatch MUST use a daily day-ahead optimizer:
  - rank feasible discharge hours by descending PLD, allowing discharge above GF;
  - rank prior charge sources by marginal cost, with curtailment at zero cost and
    solar charge valued at the current-hour PLD opportunity cost;
  - accept each marginal pair only when `rte × PLD_discharge > PLD_charge`;
  - never charge and discharge in the same hour;
  - enforce `charge_power_mw`, `bess_power_mw`, `bess_energy_mwh`, SoC bounds and the
    05:00 carryover drain deadline.

  Legacy coverage mode MUST enforce the following rules:

  **Pre-computation per scenario**: Before simulation, compute
  `min_PLD_peak = min(PLD_h for all h where hour_of_day IN scenario.peak_hours)`.
  This is the floor value of the discharge price used in the h-rule below.

  **Charging (non-peak hours where generation_h > garantia_fisica_mw)**:
  - `excess_h = max(0, generation_h − garantia_fisica_mw)`
  - **h-rule check**: charge only if `rte × min_PLD_peak > PLD_h`; otherwise sell
    excess directly to market (battery idle — `charge_h = 0`).
  - If h-rule passes: `charge_h = min(excess_h, charge_power_mw, remaining_capacity_mwh / rte)`
    *(charging is capped by `charge_power_mw`, equal to PCS by default)*
  - `grid_injection_h = generation_h − charge_h`

  **Discharging (peak hours only — hour-of-day in scenario's peak_hours set)**:
  - `deficit_h = max(0, garantia_fisica_mw − generation_h)`
  - `dispatch_h = min(deficit_h, bess_power_mw, available_energy_mwh)`
  - `residual_deficit_h = deficit_h − dispatch_h`
  - `grid_injection_h = generation_h + dispatch_h`

  **Hard bounds**: SoC ∈ [0, bess_energy_mwh]; discharge power flow ≤ bess_power_mw;
  charge and discharge never occur in the same hour.

  **Edge case — excess during peak hour**: If `generation_h > garantia_fisica_mw`
  AND `hour_of_day IN peak_hours`, the BESS does NOT charge. The excess generation
  reduces the effective dispatch deficit directly: `deficit_h = max(0, garantia_fisica_mw − generation_h) = 0`
  in this sub-case, so the BESS is idle regardless of SoC.

  Non-peak, non-excess hours: BESS is idle; SoC unchanged.
- **FR-007**: For each scenario the tool MUST compute and report all 10 output metrics:
  - `fc` (dimensionless, 4 decimal places)
  - `garantia_fisica_mw` (MW)
  - `bess_energy_mwh` (MWh)
  - `bess_power_mw` (MW)
  - `capex_brl` (BRL)
  - `annual_exposure_without_bess` = `Σ(deficit_h × PLD_h)` for all h in the guarantee
    window, using whole-hour windows only (BRL/yr)
  - `annual_exposure_with_bess` = `Σ(residual_deficit_h × PLD_h)` for the same hours
    (BRL/yr)
  - `annual_gross_savings` = signed net-balance improvement with BESS versus without
    BESS before fixed O&M (BRL/yr), including deficit reduction and positive surplus
    above GF valued at PLD
  - `annual_o_and_m` = `capex_brl × bess_o_and_m_pct_capex` (BRL/yr)
  - `annual_savings` = `annual_gross_savings − annual_o_and_m` for year 1 (BRL/yr)
  - `payback_years` = first year in the projected cash-flow series where cumulative net
    savings recover `capex_brl`, or "não atingível" if this does not occur in useful life.
    Each projected year MUST re-run dispatch with that calendar year's RTE from the
    supplier curve; no averaged RTE may be used for payback.
  - `lcos_brl_mwh` = `(capex_brl + fixed O&M over useful life) / lifetime discharged MWh`,
    where lifetime discharged MWh is computed from the same year-by-year RTE projection
    used for payback.
  - `coverage_pct` = `1 − (exposure_with / exposure_without)` × 100 (%)
- **FR-008**: CAPEX for each scenario MUST be computed as:
  `capex_brl` is taken from the executed `ScenarioDefinition`; reports and manifests
  must not recompute it from `duration_h`.
  (converting USD/kWh → BRL/MWh via ×1000×rate, then ×MWh capacity).
- **FR-009**: The HTML report MUST contain:
  (a) Summary table: one row per scenario (A, B, C), all 10 metrics, Portuguese headers
      with units.
  (b) Exposure bar chart: `annual_exposure_without_bess` vs `annual_exposure_with_bess`
      per scenario, side-by-side grouped bars, BRL/yr, hover tooltips with exact values.
  (c) CAPEX vs cumulative savings bar chart: CAPEX and cumulative savings at useful-life
      horizon (= annual_savings × useful_life_years, undiscounted) side by side per
      scenario, BRL.
  (d) Payback curve: cumulative savings (BRL) vs year (1..useful_life_years) for A, B,
      C as three lines; horizontal reference line at each scenario's CAPEX; axes labelled.
  (e) Top-10 peak hours table: the 10 hours (by highest PLD) with hour-of-day in any
      scenario's peak_hours set, showing for each: date, hour, PLD (BRL/MWh), and for
      each scenario: BESS dispatch (MWh) and residual deficit (MWh).
- **FR-010**: The HTML report MUST be self-contained (all JavaScript, CSS, and chart data
  embedded inline), fully functional offline, and include a "Premissas e Limitações do
  Modelo" section listing all configured parameters and documented assumptions. The
  Premissas section MUST also include explicit references to the applicable regulatory
  norms for each relevant assumption:
  - **Portaria MME nº 101/2016** — methodology for calculating the physical guarantee
    of new generation projects connected to the SIN; establishes the capacity-factor
    approach (`garantia_fisica_mw = mwac × fc`) used in this tool.
  - **Portaria MME nº 60/2020** — specific procedures and methodologies for solar PV
    plants, including physical guarantee revision due to technical characteristic
    changes and calculation/revision based on verified generation.
  - **CCEE Regras de Comercialização — Módulo 03 Garantia Física** — operational
    treatment of physical guarantee in CCEE accounting (lastro, sazonalização,
    modulação). Does NOT define the original calculation methodology; it
    operationalizes the use of published physical guarantee values in CCEE processes.
  - **ANEEL Resolução Normativa nº 1.034/2022** — deadlines and conditions for
    sazonalização and modulação of physical guarantee.
  All charts MUST use Plotly.js with `include_plotlyjs='inline'` (string literal) — no
  CDN references. Do NOT pass the boolean `True` to this parameter.
- **FR-011**: The tool MUST write a JSON manifest to `output/<run-id>/manifest.json`
  containing: tool version, ISO 8601 timestamp, SHA-256 hash of the serialised parameter
  set, profile source (CSV filename), price source (`"bigquery_pld_{submarket}_{year}"`),
  fc, garantia_fisica_mw, and the 3 scenario definitions (peak_hours, duration,
  bess_power_mw, bess_energy_mwh, capex_brl).
- **FR-012**: All numeric parameter inputs MUST be validated against documented bounds;
  invalid inputs MUST produce a descriptive error identifying the parameter name, the
  value provided, and the acceptable range, then re-prompt without aborting.

### Key Entities

- **Solar Plant**: AC power capacity (MWac), required input from engineer.
- **Solar Profile**: 8,760 hourly generation values in MW. Source: required external CSV.
  Always labelled with filename in all outputs.
- **Physical Guarantee (Garantia Física)**: `fc = annual_energy / (mwac × 8760)`;
  `garantia_fisica_mw = mwac × fc`. Derived from CSV. Not a user input.
- **Price Profile**: 8,760 hourly prices in BRL/MWh. Source: BigQuery PLD (CCEE table,
  submarket and year as configured). Unavailability aborts the run.
- **BESS Unit**: Per scenario — block-sized `bess_power_mw`, `charge_power_mw`,
  `bess_energy_mwh`, and `capex_brl` are stored in the executed scenario.
- **Scenario**: One of two fixed definitions (A/B). Each defines peak_hours set and
  duration. Simulation produces an 8,760-element dispatch time-series and scalar metrics.
- **Economic Result**: Exposure without/with BESS, savings, payback, coverage — derived
  from simulation results, CAPEX, and price profile.
- **Run Manifest**: JSON record of all inputs and derived parameters sufficient to
  reproduce the run exactly.
- **HTML Report**: Self-contained file with three interactive Plotly charts, summary
  table, top-10 hours table, and model assumptions section.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three scenarios complete within 30 seconds on a standard laptop
  (dual-core, 8 GB RAM).
- **SC-002**: The generated HTML report opens and all charts render within 10 seconds
  in a modern browser with no network connection and no browser console errors.
- **SC-003**: Running the tool twice with identical parameters and the same CSV produces
  byte-identical numerical results for all three scenarios.
- **SC-004**: `annual_exposure_without_bess` for any scenario, computed via the formula
  in FR-007, matches the sum of `(deficit_h × PLD_h)` over the guarantee window to
  within floating-point rounding (< 0.01 BRL).
- **SC-005**: An engineer with no prior knowledge of the tool can configure all
  parameters, load a CSV, and receive a complete HTML report in a single session without
  consulting external documentation.

---

## Assumptions

- Engineers provide a real measured or simulated solar generation CSV (8,760 rows). No
  synthetic fallback is offered. The CSV filename is logged in all outputs.
- The garantia física is derived entirely from the CSV profile and MWac. It is NOT an
  input parameter and cannot be overridden.
- Revenue/exposure calculations use real hourly BigQuery PLD prices (CCEE, configured
  submarket and year). Results reflect the actual time-of-day price variation for the
  selected year.
- BESS capital cost is modelled as a single upfront payment in USD/kWh converted to BRL.
  Fixed annual O&M is modelled as 1.5% of CAPEX by default. Savings are degraded by 2%
  per year by default for simple payback and lifetime net savings.
- Dispatch is strictly physical: the BESS charges only from solar excess above garantia
  física and discharges only during peak hours to cover deficit below garantia física.
  No price-optimised dispatch, no grid charging, no discharge outside peak hours.
- **h-rule for charging**: excess solar above garantia física is stored only when
  `rte × min_PLD_peak > PLD_h`; otherwise the excess is sold directly to market at the
  current hour's PLD. `min_PLD_peak` is the minimum hourly PLD across all peak hours of
  the scenario for the simulated year. Default `rte` = 0.85.
- **Charge power is capped at PCS**: `charge_power_mw` defaults to `bess_power_mw`.
  Charging is limited by available excess/curtailment, remaining SoC capacity, and
  the charge PCS limit.
- ILR is NOT modelled. The tool works directly with the AC generation profile from the
  CSV without any DC/AC clipping transformation.
- A single representative year of simulation is used. No multi-year weather or PLD
  variability modelling.
- The tool runs as a command-line Python script and requires Python 3.11+ with standard
  scientific computing libraries. No web server or GUI framework is required.
