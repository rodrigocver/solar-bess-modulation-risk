# Feature Specification: Monthly PLD Solar Modulation

**Feature Branch**: `001-monthly-pld-modulation`

**Created**: 2026-06-01

**Status**: Draft

**Input**: User description: "novo projeto calcula a modulação mês a mês para o historico do pld desde 2021 para uma curva de geração sem bess. todos os dados já estão na pasta, e muitos cálculos já são realizados, como aproveitar tudo isso sem alterar o que já existe?"

## User Scenarios & Testing

### User Story 1 - Calculate Monthly Modulation (Priority: P1)

An energy analyst runs a calculation for one solar generation curve without BESS and receives monthly captured price, flat PLD, modulation factor, generation, and weighted revenue for each historical PLD year.

**Why this priority**: This is the core business value: quantify whether the solar generation profile captures a premium or discount relative to the monthly flat PLD.

**Independent Test**: Can be tested with a small known hourly sample where manual weighted-average prices produce expected monthly and annual metrics.

**Acceptance Scenarios**:

1. **Given** a valid 8,760-hour solar generation curve and local PLD files for 2021 through 2025, **When** the analyst runs the tool, **Then** it produces one monthly row per year-month with modulation metrics in BRL/MWh and MWh.
2. **Given** a month with positive PLD and positive generation, **When** the system computes the modulation factor, **Then** the result equals captured price divided by monthly flat PLD.

---

### User Story 2 - Audit Reproducible Inputs (Priority: P2)

An analyst can inspect the output folder and verify which CSV, years, submarket, and calculation assumptions produced the results.

**Why this priority**: The existing project constitution requires reproducible and auditable results for commercial analysis.

**Independent Test**: Can be tested by running the tool twice with identical inputs and verifying the manifest preserves input metadata and hashes.

**Acceptance Scenarios**:

1. **Given** a successful run, **When** the analyst opens the manifest, **Then** it includes tool version, timestamp, input configuration, input file hashes, PLD source labels, and formula names.
2. **Given** missing or invalid data, **When** the run fails, **Then** the error message identifies the failing input instead of silently producing partial results.

---

### User Story 3 - Export Decision Tables (Priority: P3)

An analyst receives clean CSV tables suitable for spreadsheet review and downstream reports.

**Why this priority**: The monthly and annual outputs need to be reused outside Python without depending on an HTML report.

**Independent Test**: Can be tested by checking the exported CSV schemas and row counts for a selected set of years.

**Acceptance Scenarios**:

1. **Given** five requested years and one submarket, **When** output is generated, **Then** the monthly CSV has 60 rows and the annual CSV has 5 rows.
2. **Given** the output CSVs, **When** opened in a spreadsheet, **Then** column names include explicit units.

### Edge Cases

- Leap-year PLD data must be normalized to 8,760 hours using the existing local PLD loader conventions.
- Months with zero generation must raise a structured error instead of returning an undefined captured price.
- Missing PLD files or unavailable submarkets must stop the run with a clear message.
- The tool must not use BESS generation, dispatch, CAPEX, O&M, or savings calculations.

## Requirements

### Functional Requirements

- **FR-001**: System MUST load the solar generation curve without BESS using the existing project loader and validation behavior.
- **FR-002**: System MUST load hourly local PLD for each requested year and submarket from the existing validated local PLD source.
- **FR-003**: System MUST calculate monthly generated energy in MWh, flat PLD in BRL/MWh, captured price in BRL/MWh, weighted revenue in BRL, and modulation factor.
- **FR-004**: System MUST calculate annual summary metrics from the same hourly basis.
- **FR-005**: System MUST export monthly and annual CSV files with unit-labelled column names.
- **FR-006**: System MUST write a JSON manifest with run metadata, input hashes, requested years, submarket, MWac, source file names, and formulas.
- **FR-007**: System MUST raise structured errors for invalid solar data, missing PLD data, zero generation periods, or non-positive flat PLD.
- **FR-008**: System MUST remain isolated from existing Solar+BESS source files and must not modify existing project modules or configuration.

### Key Entities

- **SolarGenerationProfile**: Validated 8,760-hour generation profile without BESS, associated MWac, CSV file name, capacity factor, and garantia fisica inherited from the source loader.
- **HourlyPriceProfile**: Validated 8,760-hour hourly PLD price series with source label, submarket, and year.
- **MonthlyModulationResult**: One year-month result with generation, flat PLD, captured price, weighted revenue, and modulation factor.
- **RunManifest**: Audit record of tool version, timestamp, parameters, input hashes, formulas, and output file names.

## Success Criteria

### Measurable Outcomes

- **SC-001**: A 2021-2025 run completes with 60 monthly rows and 5 annual rows for one curve/submarket.
- **SC-002**: Monthly captured price and modulation factor match manually calculated reference cases to at least 1e-9 relative tolerance.
- **SC-003**: Every exported numeric energy, price, currency, or factor column contains explicit units in the column name.
- **SC-004**: Failed runs identify the invalid input and produce no partial success message.

## Assumptions

- The requested historical interval defaults to 2021 through 2025 because local `pld_horario_2021.csv` through `pld_horario_2025.csv` are present.
- The default submarket is SE, matching the current Solar+BESS project default.
- The solar curve represents a normalized or absolute AC generation profile without BESS; results are reported in its native MW/MWh scale and also include per-MWac annual normalization.
- CSV outputs are sufficient for v1; HTML or Excel reports can be added later without changing the calculation contract.
