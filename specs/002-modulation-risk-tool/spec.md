# Feature Specification: Solar+BESS Modulation Risk Analysis Tool

**Feature Branch**: `002-modulation-risk-tool`

**Created**: 2026-05-15

**Status**: Draft

---

## Clarifications

### Session 2026-05-15

- Q: How should BESS CAPEX (USD/kWh) be converted to BRL for economic outputs? → A: Add a `USD/BRL exchange rate` parameter (default 5.0); engineer enters CAPEX in USD/kWh; tool converts internally for all BRL outputs.
- Q: Which JavaScript charting library should be embedded in the self-contained HTML report? → A: Plotly.js, generated via the Python `plotly` library with the full offline bundle embedded inline.
- Q: Should the generation/dispatch heatmap show generation, dispatch, or both? → A: Two sub-panels side by side within one chart — solar generation intensity (left) and BESS dispatch intensity (right) — sharing the same 365…24 grid layout and colour scale range.
- Q: Which of the 44 simulated scenarios should drive the generation/dispatch heatmap? → A: Engineer selects interactively (ILR, BESS %, duration) after simulation completes and before report generation; selection is validated against computed scenario list.
- Q: At what rate does the BESS charge during and outside curtailment events? → A: Hybrid strategy — primary source is curtailed energy: charge at min(curtailment_in_hour, rated_BESS_power, remaining_SoC_capacity). If daily curtailment leaves SoC below a parametrizable minimum threshold (default 80 % of capacity), the BESS may top-up from grid-injected generation during off-peak hours, limited so net grid injection never falls below a parametrizable floor (default 0 MW). Priority: curtailment first, grid second. Track and report separately: (a) energy absorbed from curtailment and (b) energy charged from grid generation.- Correction: BESS sizing ratios are expressed as a percentage of estimated annual solar energy without BESS (MWh/yr), NOT as a percentage of MWac. BESS energy capacity (MWh) = ratio × annual solar energy without BESS. BESS rated power (MW) = energy capacity / configured duration.
- Resolution C1: Grid top-up charging window selection uses a two-priority strategy per scenario. Priority 1 selects hours in the following day where curtailment occurs in this scenario's solar dispatch (excess solar already absorbs into BESS; net injection floor is not binding). Priority 2 selects remaining hours with the lowest BigQuery PLD prices, ranked ascending, until the BESS reaches the minimum SoC target. The list of selected top-up hours (HH:00 slots) is logged per scenario in the run JSON artifact.
- Resolution FR-004: BigQuery is the sole hourly price data source; CSV price input and the flat-rate fallback are removed. If BigQuery is unavailable the run aborts immediately with a descriptive error message identifying the connection issue.
---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Configure Parameters and Load Profiles (Priority: P1)

A renewable energy project development engineer starts the tool and is presented
with every configurable parameter alongside its default value. For each parameter
the engineer may press Enter to accept the default or type a new value. After
parameters, the engineer chooses whether to load an external CSV with the hourly
solar generation profile (8,760 rows, power in MW) or to use the built-in synthetic
profile for Southeast Brazil. The tool then fetches hourly energy prices from BigQuery
(CCEE PLD data for the configured submarket and year). The tool validates all inputs
before proceeding.

**Why this priority**: Every downstream calculation depends on correct parameters
and profile data. A failed or unvalidated input propagates silently into all results.

**Independent Test**: Launch the tool, accept all defaults, accept the synthetic
solar profile, and accept default BigQuery submarket (SE) and year (2025). The tool
must fetch prices, load without errors, report the parameter set chosen, and proceed
to simulation — delivering a complete HTML report.

**Acceptance Scenarios**:

1. **Given** the tool is started, **When** the engineer presses Enter at every
   parameter prompt, **Then** all parameters retain their default values and the
   analysis proceeds without errors.
2. **Given** the engineer provides a numeric value at any parameter prompt, **When**
   the prompt advances, **Then** the parameter is updated and all downstream
   calculations use the new value.
3. **Given** the engineer provides an out-of-range value (e.g., round-trip efficiency
   > 100 %, negative CAPEX, zero useful life), **When** the prompt is submitted,
   **Then** the tool displays a descriptive error referencing the physical or commercial
   bound violated and re-prompts without aborting.
4. **Given** the engineer provides a valid CSV path for the solar profile, **When**
   the file is loaded, **Then** the tool validates exactly 8,760 rows of non-negative
   numeric values and confirms the load with a summary (min, max, mean generation in MW).
5. **Given** the CSV solar profile contains a row with a non-numeric or negative value,
   **When** loading is attempted, **Then** the tool identifies the exact row number and
   value, rejects the file, and falls back to the synthetic profile with an explicit notice.
6. **Given** BigQuery credentials are invalid, the network is unavailable, or the CCEE
   table returns a row count other than 8,760, **When** the price fetch is attempted,
   **Then** the tool aborts immediately with a descriptive error message identifying the
   failure reason and does not proceed to simulation.

---

### User Story 2 — Simulate Solar+BESS Across All Scenarios (Priority: P1)

After configuration, the tool simulates the solar plant and BESS operation hour by
hour for an entire year for every combination of BESS size ratio and ILR. The engineer
observes progress feedback during the run. On completion the tool reports a structured
summary of scenario count, total curtailment range, and simulation runtime.

**Why this priority**: Simulation is the computational core. Errors here propagate to
all reported metrics and charts.

**Independent Test**: With default parameters and the synthetic profile, run simulation
for the 0 % and 100 % BESS size scenarios only. Verify that the 0 % scenario yields
0 MWh avoided curtailment, and that the 100 % scenario yields avoided curtailment
strictly greater than 0 MWh for any ILR > 1.0.

**Acceptance Scenarios**:

1. **Given** valid parameters and a solar profile, **When** simulation runs, **Then**
   results are produced for all 11 BESS size ratios (0, 5, 10, 15, 20, 25, 30, 40, 50,
   75, 100 % of estimated annual solar energy without BESS) × all configured ILR values
   (default: 1.2, 1.3, 1.4, 1.5).
2. **Given** BESS size ratio is 0 %, **When** the scenario is simulated, **Then**
   avoided curtailment is exactly 0 MWh/year and the effective capacity factor equals
   the clipped plant capacity factor (no BESS contribution).
3. **Given** increasing BESS size ratios with a fixed ILR, **When** results are
   compared across ratios, **Then** avoided curtailment is monotonically non-decreasing
   (larger BESS never reduces avoided curtailment).
4. **Given** a higher ILR with fixed BESS size, **When** results are compared, **Then**
   total curtailment before BESS is greater than or equal to that of a lower ILR (higher
   ILR produces more excess generation to curtail).
5. **Given** BESS dispatch in any hour, **When** results are examined, **Then** state of
   charge never exceeds BESS energy capacity (BESS size ratio × annual solar energy
   without BESS), never falls below zero, and power flow never exceeds rated BESS power
   (energy capacity / duration) — all bounds enforced hour by hour.
6. **Given** a duration constraint (e.g., 2 h), **When** dispatch is computed, **Then**
   energy stored in a single charge episode does not exceed BESS energy capacity
   (= BESS size ratio × annual solar energy without BESS).

---

### User Story 3 — Review Per-Scenario Economic Metrics (Priority: P2)

For each simulated scenario the engineer reviews eleven economic indicators: total
curtailed energy with and without BESS (MWh/year), percentage of curtailment avoided,
effective capacity factor, equivalent BESS cycles per year, incremental annual revenue,
simplified LCOS (BRL/MWh), simple payback period (years), annual energy absorbed from
curtailment (MWh/yr), annual energy charged from grid top-up (MWh/yr), and per-scenario
grid top-up charging window slots (HH:00 format). Revenue reflects the time value of
dispatch — energy dispatched during high-price PLD hours earns more.

**Why this priority**: Economic metrics drive the investment decision. They can be
verified independently of the visual report.

**Independent Test**: Using a single scenario (one BESS size, one ILR), confirm that:
(a) incremental revenue = Σ(hourly avoided curtailment × hourly price); (b) LCOS =
total discounted lifecycle cost / total discounted energy delivered; (c) simple payback =
BESS CAPEX (BRL) / annual incremental revenue.

**Acceptance Scenarios**:

1. **Given** a scenario with positive avoided curtailment and uniform hourly PLD prices
   (all 8,760 hours at price P BRL/MWh), **When** revenue is computed, **Then**
   incremental revenue = avoided energy (MWh) × P (BRL/MWh).
2. **Given** hourly PLD prices are loaded, **When** revenue is computed, **Then**
   incremental revenue = Σ over 8,760 hours of (avoided curtailment in hour h × PLD price
   in hour h), reflecting the time-of-dispatch value.
3. **Given** BESS CAPEX, useful life, degradation rate, and discount rate, **When** LCOS
   is computed, **Then** it applies degradation year by year (energy throughput decreases
   each year) and discounts all costs and energy to present value using the configured rate.
4. **Given** annual incremental revenue is zero, **When** payback is computed, **Then**
   payback is reported as "não atingível" (not achievable) — no division by zero occurs.
5. **Given** the engineer configured multiple storage durations (e.g., 1 h, 2 h, 4 h),
   **When** results are displayed, **Then** a separate result set is produced for each
   duration, labelled with the duration value.
6. **Given** any scenario, **When** metrics are computed, **Then** effective capacity
   factor = (total energy injected into grid per year) / (MWac × 8,760 h), expressed
   as a percentage.
7. **Given** any scenario, **When** equivalent cycles per year are computed, **Then**
   equivalent cycles = total annual energy discharged from BESS / BESS energy capacity.

---

### User Story 4 — Receive Self-Contained HTML Report with Four Charts (Priority: P2)

After simulation and economics complete, the tool writes a single self-contained HTML
file to an output directory. The engineer opens it in any modern browser — offline,
without network access — and finds four interactive charts and a scrollable summary
table. The report is shareable with non-technical stakeholders and requires no special
software to view.

**Why this priority**: The report is the primary deliverable shared with decision-makers.
It must work standalone without requiring the tool to be installed.

**Independent Test**: Generate the report with default parameters, open the HTML file
in a browser while offline, verify all four charts render with data and interactive
tooltips, the summary table is present and complete, and no browser console errors appear.

**Acceptance Scenarios**:

1. **Given** all computations complete without error, **When** the tool is ready to
   generate the report, **Then** it prompts the engineer to select the (ILR, BESS %,
   duration) scenario for the generation/dispatch heatmap by listing available options;
   the engineer may press Enter to accept the first listed option as default.
2. **Given** the engineer enters an (ILR, BESS %, duration) combination that does not
   exist in the computed results, **When** the prompt is submitted, **Then** the tool
   displays the valid options and re-prompts without aborting.
3. **Given** a valid heatmap scenario is selected, **When** the report is generated,
   **Then** a single `.html` file is written to `output/<run-id>/report.html` and a
   JSON manifest is written alongside it at `output/<run-id>/manifest.json`.
4. **Given** the HTML report, **When** opened offline, **Then** all charts and tables
   render without broken elements or network requests.
5. **Given** the modulation saturation curve chart, **When** viewed, **Then** it plots
   avoided curtailment (MWh/year) on the Y axis versus BESS size (% of annual solar
   energy without BESS) on the X axis, one line per ILR, with hover tooltips showing
   exact (BESS %, ILR, MWh, % avoided) values.
6. **Given** the generation and dispatch heatmap, **When** viewed, **Then** it shows
   two side-by-side sub-panels — solar generation intensity (left) and BESS dispatch
   intensity (right) — each rendered as a 365 × 24 grid (day-of-year vs. hour-of-day)
   sharing the same perceptually uniform colour scale, with a shared colour bar labelled
   in MWh; the chart title identifies the selected (ILR, BESS %, duration) scenario.
7. **Given** the payback sensitivity chart, **When** viewed, **Then** it shows payback
   (years) as a contour or heat-map over a 2-D grid of energy price (BRL/MWh) × BESS CAPEX
   (USD/kWh), sweeping each axis ±50 % around the configured default; axes and colour bar
   are labelled with units.
8. **Given** the BESS hourly operation distribution chart, **When** viewed, **Then** it
   shows the count of hours in each operational state — charging, discharging, idle — as a
   bar or stacked bar chart, broken down by hour of day (0–23), labelled in MWh and hours.
9. **Given** the summary table, **When** reviewed, **Then** it contains one row per unique
   (ILR, BESS size %, duration h) combination with columns: ILR, BESS % of annual solar
   energy without BESS, Duration (h), Curtailment sem BESS (MWh/yr), Curtailment com BESS
   (MWh/yr), % Modulação evitada, CF efetivo (%), Ciclos equivalentes/ano, Energia
   absorvida de curtailment (MWh/yr), Energia carregada da rede (MWh/yr), Receita
   incremental (BRL/yr), LCOS (BRL/MWh), Payback simples (anos).

---

### Edge Cases

- Solar profile with all-zero generation (fully cloudy year): curtailment is 0 for all
  scenarios; payback is "não atingível"; the report must still be generated without errors.
- BESS size 0 %: must produce a valid result row with 0 avoided curtailment and
  "não atingível" payback for every ILR.
- ILR = 1.0 (no oversizing): curtailment is 0 for all hours; all BESS scenarios produce
  0 avoided curtailment; the saturation curve is a flat line at 0.
- Energy price of 0 BRL/MWh: incremental revenue is 0; payback is "não atingível";
  LCOS is computed but has no economic breakeven.
- Very large BESS (100 % of annual solar energy without BESS, 4 h duration) with ILR 1.5:
  BESS may absorb all curtailment in every hour; simulation must terminate normally and
  not loop indefinitely.
- BESS degradation rate of 0 %: LCOS formula must not divide by zero; energy throughput
  is constant over useful life.
- BigQuery authentication failure or network error: the run aborts immediately with a
  descriptive error message; no partial output is written.
- BigQuery returns a row count other than 8,760 for the requested year and submarket:
  the run aborts with a message stating the actual and expected row counts.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST present each configurable parameter with its default value and
  prompt the engineer to accept or provide a replacement before any computation starts.
  Parameters include: round-trip efficiency (%), annual degradation rate (%/yr), storage
  duration(s) (h), BESS CAPEX (USD/kWh), USD/BRL exchange rate (default 5.0), useful life
  (years), discount rate (%/yr), ILR values (list), BESS size ratios (list), minimum SoC
  threshold for grid top-up charging (% of energy capacity, default 80 %), and minimum net
  grid injection floor (MW, default 0 — no floor). The tool multiplies CAPEX (USD/kWh) by
  the exchange rate to obtain BRL/kWh for all cost and economic calculations.
- **FR-002**: The tool MUST accept an external solar generation CSV file (8,760 rows,
  one numeric non-negative value per row, power in MW). When absent or invalid, it MUST
  fall back to the built-in synthetic profile with a console notice.
- **FR-003**: The built-in synthetic solar profile MUST be generated deterministically
  using a fixed, configurable integer seed, representative of Southeast Brazil (latitude
  ≈ −22°, 60 Hz grid), and labelled as synthetic in all outputs.
- **FR-004**: Hourly energy prices MUST be fetched from BigQuery using the CCEE PLD table
  for the configured submarket and year. BigQuery is the only price data source; no CSV
  price input or flat-rate fallback is provided. If the BigQuery connection fails, the
  requested table returns an unexpected row count, or authentication is rejected, the
  run MUST abort immediately with a descriptive error message identifying the failure
  reason. The engineer MUST resolve the connectivity issue before re-running.
- **FR-005**: The simulation MUST evaluate all 11 BESS size ratios (0, 5, 10, 15, 20, 25,
  30, 40, 50, 75, 100 % of estimated annual solar energy without BESS) and all configured
  ILR values. The annual solar energy without BESS MUST be computed from the loaded solar
  profile (sum of min(generation_h, MWac) over 8,760 hours) before scenario simulation
  begins, and used consistently to derive all BESS energy capacities.
- **FR-006**: BESS dispatch MUST enforce hour-by-hour the following rules in priority order:
  1. **Curtailment charging (primary)**: when solar generation exceeds MWac, charge at
     `min(curtailment_in_hour, rated_BESS_power, remaining_SoC_capacity)`; this energy is
     tracked as *curtailment absorbed*.
  2. **Grid top-up charging (secondary)**: if end-of-day SoC is below the minimum SoC
     threshold (default 80 % of energy capacity), the tool selects top-up charging windows
     for the following day using a two-priority strategy:
     - **Priority 1 — curtailment hours**: hours in the following day where curtailment
       occurs in this scenario's solar dispatch; charging in these hours does not reduce
       net grid injection below the floor because solar excess already exceeds the plant
       AC capacity.
     - **Priority 2 — cheapest PLD hours**: remaining hours in the following day with the
       lowest BigQuery PLD price, ranked ascending, selected until the BESS reaches the
       minimum SoC target.
     Top-up charging per selected hour: `min(rated_BESS_power, remaining_SoC_capacity)`
     per hour, provided net grid injection does not fall below the configured minimum
     injection floor (default 0 MW). Energy charged this way is tracked separately as
     *grid-charged energy*. The list of selected top-up hour slots (HH:00 format) MUST
     be saved per scenario in the run JSON artifact.
  3. **Discharge**: when SoC > 0 and no curtailment is occurring, discharge at
     `min(rated_BESS_power, current_SoC)` per hour; round-trip efficiency is applied on
     discharge.
  4. **Hard bounds**: SoC ∈ [0, energy capacity]; power flow ≤ rated BESS power;
     BESS energy capacity (MWh) = BESS size ratio × annual solar energy without BESS
     (MWh/yr); BESS rated power (MW) = energy capacity / configured duration.
- **FR-007**: For each scenario the tool MUST compute and report: (a) total curtailment
  without BESS (MWh/yr), (b) total curtailment with BESS (MWh/yr), (c) % curtailment
  avoided, (d) effective capacity factor (%), (e) equivalent BESS cycles per year,
  (f) incremental annual revenue (BRL/yr), (g) simplified LCOS (BRL/MWh), (h) simple
  payback (years or “não atingível”), (i) annual energy absorbed from curtailment (MWh/yr),
  (j) annual energy charged from grid generation via top-up (MWh/yr), (k) list of grid
  top-up charging window slots selected for this scenario (HH:00 format). Metrics (i) and
  (j) MUST appear as separate columns in the summary table and be labelled distinctly.
  Metric (k) MUST be logged in the run JSON artifact per scenario.
- **FR-008**: LCOS MUST be computed as the sum of discounted annual BESS costs divided
  by the sum of discounted annual energy delivered, where annual energy delivery decreases
  each year by the configured degradation rate applied cumulatively.
- **FR-009**: Incremental revenue MUST equal the sum over 8,760 hours of (avoided curtailment
  in MWh in that hour × BigQuery PLD price in BRL/MWh for that hour).
- **FR-010**: The tool MUST generate four charts: (a) modulation saturation curve,
  (b) generation and dispatch heatmap — two side-by-side sub-panels (solar generation
  left, BESS dispatch right) sharing a 365…24 grid and perceptually uniform colour scale,
  for an engineer-selected (ILR, BESS %, duration) scenario prompted after simulation
  and validated against the computed scenario list,
  (c) payback sensitivity heat-map, (d) BESS hourly operation distribution — as described
  in User Story 4.
- **FR-011**: The HTML report MUST be self-contained (all JavaScript, CSS, and chart data
  embedded inline), fully functional offline, and include a "Premissas e Limitações do
  Modelo" section listing all configured parameters and documented assumptions. All four
  charts MUST be generated using the Python `plotly` library and rendered as a fully
  offline Plotly.js bundle embedded in the HTML (i.e., `include_plotlyjs='inline'` or
  equivalent — no CDN references).
- **FR-012**: The tool MUST write a JSON manifest to `output/<run-id>/manifest.json`
  containing: tool version, ISO 8601 timestamp, SHA-256 hash of the serialised parameter
  set, RNG seed used, profile source (synthetic or CSV filename), price source
  (`"bigquery_pld_{submarket}_{year}"`), and for each scenario a list of the grid top-up
  charging window slots selected (keyed by scenario ID as `"{ilr}_{bess_pct}_{dur_h}"`,
  values as lists of HH:00 strings).
- **FR-013**: All numeric parameter inputs MUST be validated against documented bounds;
  invalid inputs MUST produce a descriptive error identifying the parameter name, the
  value provided, and the acceptable range, then re-prompt without aborting.
- **FR-014**: Payback sensitivity analysis MUST sweep energy price and BESS CAPEX each
  over [50 %, 150 %] of their respective baselines — energy price baseline = annual mean
  of the fetched BigQuery PLD prices (BRL/MWh); CAPEX baseline = configured `capex_usd_per_kwh`
  — using at least a 10 × 10 grid of points.
- **FR-015**: The summary table in the HTML report MUST include one row per (ILR, BESS %,
  Duration) combination with all metrics from FR-007 (a–j), including the two separately
  tracked energy-charge columns (curtailment absorbed and grid top-up charged).
- **FR-016**: The HTML report MUST include a grid top-up window summary table showing,
  for each simulated scenario, the top-5 most frequent grid top-up hour slots across the
  simulated year and their average BigQuery PLD price (BRL/MWh). The table MUST be
  labelled in Portuguese and placed as a dedicated section immediately following the
  scenario summary table.

### Key Entities

- **Solar Plant**: AC power capacity (MWac) normalised to 1 MWac; ILR determines clipping
  threshold (MWac × ILR = DC capacity; excess above MWac is curtailed).
- **Solar Profile**: 8,760 hourly generation values in MW. Source: synthetic (seeded) or
  external CSV. Always labelled with source in outputs.
- **Price Profile**: 8,760 hourly prices in BRL/MWh. Source: BigQuery PLD (CCEE table,
  submarket and year as configured). Unavailability aborts the run.
- **BESS Unit**: Energy capacity (MWh) = BESS size ratio × annual solar energy without
  BESS (MWh/yr); rated power (MW) = energy capacity / configured duration; round-trip
  efficiency (%); annual degradation rate (%/yr). Power capacity is derived from energy
  capacity and duration — it is NOT an independent input.
- **Scenario**: Unique combination of (ILR, BESS size %, storage duration). Simulation
  produces an 8,760-element dispatch time-series and scalar annual metrics. Dispatch
  tracks two energy flows per hour: curtailment absorbed and grid top-up charged.
- **Economic Result**: LCOS, incremental revenue, and payback derived from simulation
  results, CAPEX, useful life, discount rate, and price profile.
- **Run Manifest**: JSON record of all inputs sufficient to reproduce the run exactly.
- **HTML Report**: Self-contained file with four interactive charts, summary table, and
  model assumptions section.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All scenarios for the default configuration (11 BESS sizes × 4 ILRs = 44
  scenarios) complete within 3 minutes on a standard laptop (dual-core, 8 GB RAM).
- **SC-002**: The generated HTML report opens and all four charts render within 10 seconds
  in a modern browser with no network connection and no browser console errors.
- **SC-003**: Running the tool twice with identical parameters and the same synthetic
  profile seed produces byte-identical numerical results for all 44 scenarios.
- **SC-004**: For any scenario with a positive BESS size and ILR > 1.0, avoided
  curtailment reported in the summary table matches the value plotted on the saturation
  curve to within floating-point rounding (< 0.01 MWh).
- **SC-005**: An engineer with no prior knowledge of the tool can configure all parameters,
  load or accept profiles, and receive a complete HTML report in a single session without
  consulting external documentation.
- **SC-006**: The modulation saturation curve is monotonically non-decreasing across all
  11 BESS size points for every ILR — verifiable programmatically from the chart data.

---

## Assumptions

- All models are normalised to 1 MWac solar plant AC capacity. Engineers must scale
  output values (MWh/yr, BRL/yr) by their actual plant capacity in MWac.
- The synthetic solar profile is generated deterministically using a fixed seed (default:
  42). It represents a typical Southeast Brazil site (latitude ≈ −22°, longitude ≈ −45°)
  and does NOT replace measured irradiance data for final investment decisions.
- Revenue calculations use real hourly BigQuery PLD prices (CCEE, configured submarket
  and year). Results reflect the actual time-of-day price variation for the selected year.
- BESS capital cost is modelled as a single upfront payment in USD/kWh. The tool converts
  CAPEX to BRL/kWh using the configured USD/BRL exchange rate (default 5.0). All final
  economic outputs are in BRL. The engineer is responsible for verifying the exchange rate
  reflects market conditions at the time of analysis.
- O&M costs for the BESS are not modelled explicitly. The LCOS formula captures only
  capital cost amortised over useful life with degradation and discounting.
- BESS operates in a hybrid dispatch strategy: curtailment-first charging
  (`min(curtailment, rated_power, remaining_SoC_capacity)`) with grid top-up charging
  permitted when end-of-day SoC would otherwise fall below the configured minimum SoC
  threshold (default 80 % of energy capacity), subject to the minimum net injection floor
  (default 0 MW). Discharge occurs greedily when SoC > 0 and no curtailment is active.
  No price-optimised dispatch is modelled in this version.
- The Brazilian grid nominal frequency is 60 Hz. Frequency deviation risk is not
  modelled quantitatively in this version; the tool focuses on energy curtailment risk.
- A single representative year of simulation is repeated over the full useful life for
  economic calculations (no multi-year weather variability or PLD variability modelling).
- The tool runs as a command-line Python script and requires Python 3.11+ with standard
  scientific computing libraries. No web server or GUI framework is required.
