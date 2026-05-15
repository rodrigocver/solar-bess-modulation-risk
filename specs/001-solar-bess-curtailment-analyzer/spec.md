# Feature Specification: Solar+BESS Curtailment/Modulation Risk Analyzer

**Feature Branch**: `001-solar-bess-curtailment-analyzer`

**Created**: 2026-05-15

**Status**: Draft

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Configure Analysis Parameters (Priority: P1)

A solar/energy analyst starts a new analysis by reviewing the default parameters and
adjusting them to match the specific project under evaluation. The tool presents each
default value with a prompt, allowing the analyst to accept it or enter a custom value.
Parameters cover the energy price, BESS CAPEX, round-trip efficiency, degradation rates,
storage durations, ILR scenarios, useful life, and discount rate. The analyst optionally
provides an external CSV with an hourly solar generation profile or accepts the synthetic
profile for the Brazilian Southeast region.

**Why this priority**: Without configurable parameters the tool cannot model any real
project; all downstream calculations and outputs depend on this step.

**Independent Test**: Run the tool with all defaults accepted (no custom input); the tool
must complete the full analysis without errors and produce a valid HTML report using the
built-in synthetic profile.

**Acceptance Scenarios**:

1. **Given** the tool is started, **When** the analyst presses Enter for every parameter,
   **Then** all parameters retain their default values and the analysis proceeds using the
   synthetic Brazilian Southeast solar profile.
2. **Given** the analyst provides a numeric value at any prompt, **When** the prompt
   advances, **Then** the parameter is updated to the provided value and all subsequent
   calculations use the new value.
3. **Given** the analyst provides an invalid value (non-numeric, negative CAPEX, efficiency
   outside 0–100%), **When** the prompt is submitted, **Then** the tool displays a clear
   error and re-prompts without proceeding.
4. **Given** the analyst provides a valid CSV file path at the solar profile prompt,
   **When** the file is loaded, **Then** the tool validates it contains exactly 8,760 rows
   of non-negative numeric power values and proceeds with that profile.
5. **Given** the CSV file path is invalid or the file fails validation, **When** the load
   is attempted, **Then** the tool notifies the analyst and falls back to the synthetic
   profile with an explicit notice.

---

### User Story 2 — Run Multi-Scenario Simulation (Priority: P1)

After parameter configuration, the analyst triggers the simulation. The tool evaluates
each combination of BESS size (as percentage of solar MWac) and ILR scenario, computing
the annual energy balance for every hour of the year. For each scenario the tool reports
avoided curtailment energy, effective capacity factor, equivalent BESS cycles per year,
and whether energy stored fits within the configured durations.

**Why this priority**: The simulation is the core computational engine; all economic and
visual outputs depend on correct simulation results.

**Independent Test**: With default parameters and the synthetic profile, run the
simulation and verify that the 0 % BESS scenario produces exactly the same dispatched
energy as the clipped solar output, and the 100 % BESS scenario produces avoided
curtailment greater than or equal to the 50 % scenario.

**Acceptance Scenarios**:

1. **Given** valid parameters and a solar profile, **When** the simulation runs,
   **Then** results are produced for every combination of the 11 BESS size ratios
   (0 %, 5 %, 10 %, 15 %, 20 %, 25 %, 30 %, 40 %, 50 %, 75 %, 100 % of MWac) and
   every configured ILR (1.2, 1.3, 1.4, 1.5).
2. **Given** BESS size is 0 %, **When** simulation completes, **Then** avoided curtailment
   is 0 MWh/year and effective capacity factor equals the base (clipped) plant capacity
   factor.
3. **Given** increasing BESS size ratios for a fixed ILR, **When** results are compared,
   **Then** avoided curtailment is monotonically non-decreasing.
4. **Given** a higher ILR with fixed BESS size, **When** results are compared, **Then**
   total curtailment before BESS intervention is greater than or equal to that of a lower
   ILR, and BESS contribution to avoided curtailment is at least as large.
5. **Given** a storage duration constraint is applied, **When** BESS dispatch is computed,
   **Then** energy stored in any single charge cycle does not exceed duration × BESS power
   capacity.

---

### User Story 3 — Review Economic Metrics per Scenario (Priority: P2)

For each simulated scenario the analyst views the economic performance: incremental
revenue from avoided curtailment, simplified Levelised Cost of Storage (LCOS), and
simple payback period. Degradation over the useful life reduces effective storage capacity
year by year, and the discount rate adjusts future revenues to present value.

**Why this priority**: Economic metrics justify investment decisions; they can be reviewed
independently of visualizations after simulation completes.

**Independent Test**: With a single scenario (one BESS size, one ILR), verify that LCOS
equals total discounted BESS cost divided by total discounted energy delivered over the
useful life, and that simple payback equals BESS CAPEX divided by annual incremental
revenue.

**Acceptance Scenarios**:

1. **Given** a scenario with positive avoided curtailment, **When** economics are computed,
   **Then** incremental revenue equals avoided energy (MWh) × energy price, converted from
   BRL to a consistent currency.
2. **Given** CAPEX, useful life, degradation, and discount rate, **When** LCOS is computed,
   **Then** it accounts for decreasing annual energy delivery due to degradation and
   discounts costs and energy to present value.
3. **Given** incremental revenue is zero (no avoided curtailment), **When** payback is
   computed, **Then** payback is reported as "not achievable" rather than division by zero.
4. **Given** multiple degradation rates are configured, **When** economics are computed,
   **Then** a result row is produced for each degradation rate.
5. **Given** multiple storage durations are configured, **When** economics are computed,
   **Then** a result row is produced for each duration value.

---

### User Story 4 — Explore Visualizations and HTML Report (Priority: P2)

The analyst receives a self-contained HTML report containing four interactive charts and
a summary table. The report is openable in any modern web browser without network
connectivity. Charts are interactive (zoom, hover tooltips). The analyst can share the
report file with stakeholders.

**Why this priority**: The report is the primary deliverable for stakeholder communication;
it summarises and contextualises all simulation and economic results.

**Independent Test**: Open the generated HTML file in a browser; verify all four charts
render with data, the summary table has one row per scenario combination, and no external
network requests are required.

**Acceptance Scenarios**:

1. **Given** simulation and economics complete, **When** the report is generated,
   **Then** a single `.html` file is written to the output directory.
2. **Given** the HTML report, **When** opened offline in a browser, **Then** all charts
   and tables render correctly with no broken or missing elements.
3. **Given** the modulation saturation curve chart, **When** viewed, **Then** it shows
   avoided curtailment (MWh/year) on the Y axis versus BESS size (% of MWac) on the X
   axis, with one line per ILR scenario.
4. **Given** the generation heatmap chart, **When** viewed, **Then** it shows hourly
   solar generation and BESS dispatch intensity for each day of the year (8,760 cells).
5. **Given** the payback sensitivity chart, **When** viewed, **Then** it shows payback
   (years) as a heat-map or contour over a range of energy prices and BESS CAPEX values
   centred on the configured defaults.
6. **Given** the BESS hourly operation distribution chart, **When** viewed, **Then** it
   shows a histogram or box plot of the BESS power output (charge/discharge) across all
   8,760 hours.
7. **Given** the summary table, **When** reviewed, **Then** it contains columns for ILR,
   BESS size (%), duration (h), degradation (%/yr), avoided curtailment (MWh/yr), CF
   effective (%), equivalent cycles/yr, incremental revenue, LCOS, and payback.

---

### Edge Cases

- Solar profile with all-zero generation hours (fully cloudy year) must not cause
  division-by-zero; results should report zero curtailment and infinite payback.
- BESS size of 0 % must always produce a valid (zero-curtailment-avoided) result row.
- Very large BESS (100 % of MWac) with very long duration (4 h) and low ILR (1.2) may
  result in a BESS that absorbs all curtailment from the first hour; simulation must not
  run indefinitely.
- CSV files with header rows or non-numeric values must be rejected with a descriptive
  error identifying the problematic row.
- If energy price input is 0, revenue is 0; payback must be reported as "not achievable".

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST present each configurable parameter with its default value and
  prompt the analyst to accept or replace it before starting any computation.
- **FR-002**: The tool MUST support loading an hourly solar generation profile from an
  external CSV file (8,760 rows, one numeric value per row, power in MW).
- **FR-003**: When no CSV is provided or the file fails validation, the tool MUST generate
  a synthetic hourly solar profile representative of the Brazilian Southeast region
  (latitude ≈ −22°, high irradiance summer months, seasonal variation).
- **FR-004**: The simulation MUST evaluate all 11 BESS size ratios (0 %, 5 %, 10 %, 15 %,
  20 %, 25 %, 30 %, 40 %, 50 %, 75 %, 100 % of the solar plant's AC power capacity).
- **FR-005**: The simulation MUST evaluate all configured ILR values (default: 1.2, 1.3,
  1.4, 1.5); analysts may add or remove ILR values at the parameter prompt.
- **FR-006**: For each scenario the tool MUST compute: total avoided curtailment
  (MWh/year), effective capacity factor (%), equivalent BESS cycles per year, incremental
  annual revenue, simplified LCOS, and simple payback period.
- **FR-007**: LCOS MUST be computed as the ratio of total discounted BESS lifecycle cost
  to total discounted energy delivered over the useful life, applying the configured
  degradation rate and discount rate.
- **FR-008**: BESS dispatch in each simulated hour MUST respect: round-trip efficiency,
  maximum charge/discharge power (BESS rated power), maximum stored energy (BESS power ×
  duration), and state-of-charge bounds (0 % – 100 %).
- **FR-009**: The tool MUST generate a self-contained HTML report embedding all four
  required charts and the scenario summary table without requiring external network access.
- **FR-010**: The modulation saturation curve MUST plot avoided curtailment (MWh/year) vs.
  BESS size (% of MWac), with a separate line for each ILR.
- **FR-011**: The generation and dispatch heatmap MUST display solar generation and BESS
  dispatch intensity across all 8,760 hours of the year laid out in a day-of-year vs.
  hour-of-day grid.
- **FR-012**: The payback sensitivity chart MUST display payback as a function of energy
  price and BESS CAPEX, sweeping each over a range of ±50 % around the configured
  default values.
- **FR-013**: The BESS hourly operation distribution chart MUST show the frequency
  distribution of BESS power across all hours.
- **FR-014**: The summary table in the HTML report MUST include one row per unique
  combination of (ILR, BESS size %, storage duration, degradation rate).
- **FR-015**: All numeric parameters MUST be validated at input time; invalid values MUST
  produce an error message and re-prompt without crashing.

### Key Entities

- **Solar Plant**: Defined by AC power capacity (MWac) and ILR (DC/AC ratio). ILR
  determines the DC array size and therefore the clipping threshold.
- **Solar Profile**: 8,760 hourly generation values (MWh or normalised to MWac). Source:
  synthetic or external CSV.
- **BESS Unit**: Characterised by power capacity (% of MWac), energy capacity (power ×
  duration), round-trip efficiency, and annual degradation rate.
- **Scenario**: One combination of (ILR, BESS size %, storage duration, degradation rate).
- **Simulation Result**: Per-scenario annual energy totals (curtailed, avoided, dispatched)
  and hourly dispatch time-series.
- **Economic Result**: Per-scenario LCOS, incremental revenue, and payback derived from
  simulation results and economic parameters.
- **Report**: Self-contained HTML file containing all charts and the summary table.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The tool completes a full analysis of all default scenarios (44 ILR × BESS
  size combinations × 4 degradation rates × 3 durations = up to 528 rows) in under
  5 minutes on a standard laptop.
- **SC-002**: The generated HTML report opens and renders fully in a modern browser within
  10 seconds without network access.
- **SC-003**: Given identical inputs, running the tool twice produces byte-identical
  simulation results (determinism requirement from Constitution Principle IV).
- **SC-004**: An analyst with no prior knowledge of the tool can configure all parameters
  and receive a complete HTML report in a single session without consulting external
  documentation.
- **SC-005**: The modulation saturation curve shows a monotonically non-decreasing avoided
  curtailment as BESS size increases, for every ILR — verifiable from the chart data.
- **SC-006**: LCOS values are within ±5 % of a manually calculated reference case
  (verifiable using the documented formula and default parameters).

---

## Assumptions

- Solar plant AC capacity is treated as 1 MWac (normalised); all energy values scale
  linearly, so the analyst must scale output values by their actual plant capacity.
- The synthetic Brazilian Southeast profile is generated deterministically (fixed seed)
  so results are reproducible without an external data source.
- Economic calculations use a single representative year of the simulation repeated over
  the full useful life (no multi-year weather variability modelling).
- Currency conversion (BRL to USD) is not performed automatically; energy price is used
  as entered (default 220 BRL/MWh) and CAPEX is in USD/kWh; the analyst is responsible
  for currency consistency interpretation.
- BESS capital cost is modelled as a single upfront payment with no operational
  expenditure (O&M costs) beyond what is implicitly captured in the LCOS formula.
- The tool runs as a command-line Python script; no web server or GUI framework is
  required.
- Plotly is used for chart generation and outputs charts as self-contained HTML fragments
  embedded in the report via `include_plotlyjs='cdn'` fallback overridden to inline JS
  so the report works offline.
- All configurable lists (ILR values, degradation rates, BESS size ratios, durations)
  are entered as comma-separated values at the prompt.
