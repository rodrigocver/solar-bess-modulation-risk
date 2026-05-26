# Data Model: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Updated**: 2026-05-18 (v2 — Garantia Física Dispatch)

> This document is the authoritative entity reference for the v2 model.
> For implementation pseudocode and economic formulas see [plan.md](plan.md).
> For requirements see [spec.md](spec.md).

---

## Entities

### 1. `SimulationParams`

The complete, validated configuration for a single analysis run. Immutable after
validation. Serialised to JSON for the run manifest SHA-256 hash (excluding
`bq_service_account_path`).

| Field | Type | Unit | Default | Bounds | Description |
|-------|------|------|---------|--------|-------------|
| `csv_path` | `str` | — | required | non-empty, existing file | Path to solar generation CSV (8,760 rows) |
| `mwac` | `float` | MWac | required | > 0 | Plant AC capacity; scales garantia física and BESS |
| `bq_year` | `int` | year | 2025 | [2000, 2100] | Year to fetch from CCEE PLD BigQuery table |
| `bq_submarket` | `str` | — | `"SE"` | one of {SE, S, NE, N} | CCEE submarket for PLD price fetch |
| `capex_usd_per_kwh` | `float` | USD/kWh | 200.0 | > 0 | BESS capital cost in market unit |
| `usd_brl_rate` | `float` | BRL/USD | 5.0 | > 0 | Exchange rate for CAPEX conversion |
| `useful_life_years` | `int` | years | 20 | [1, 100] | Economic useful life (undiscounted payback horizon) |
| `bess_roundtrip_efficiency` | `float` | fraction | 0.85 | (0, 1] | AC-to-AC BESS efficiency applied to charged energy |
| `bess_o_and_m_pct_capex` | `float` | fraction/yr | 0.015 | [0, 1] | Fixed annual O&M as a share of BESS CAPEX |
| `bess_degradation_pct_yr` | `float` | fraction/yr | 0.02 | [0, 1] | Annual savings degradation applied to gross savings |
| `bq_service_account_path` | `str \| None` | — | None | valid path if set | Path to service account JSON key; None when using ADC |

**Invariants**:
- `bq_service_account_path` is **never** serialised into the manifest SHA-256 hash.
- `mwac > 0` is enforced at input time; determines all downstream BESS sizing.
- No ILR, grid top-up, SoC floor, discount rate, or RNG seed fields exist in v2.

---

### 2. `SolarProfile`

8,760 hourly AC generation values loaded from the engineer-supplied CSV. Immutable after
load. The physical guarantee (garantia física) is derived here — it is NOT a user input.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `generation_mw` | `np.ndarray[float64, (8760,)]` | MW | Hourly AC power; all values ≥ 0 |
| `annual_energy_mwh` | `float` | MWh | `sum(generation_mw)` — computed on load |
| `fc` | `float` | — | `annual_energy_mwh / (mwac × 8760)` — capacity factor |
| `garantia_fisica_mw` | `float` | MW | `mwac × fc` — physical guarantee; drives all scenario sizing |
| `csv_filename` | `str` | — | Basename of the source CSV path; logged in all outputs |

**Invariants**:
- `len(generation_mw) == 8760` (exactly one calendar year)
- All values ∈ [0, ∞) — negative values abort with a descriptive error citing row and value
- `fc > 0` (guaranteed if `annual_energy_mwh > 0`; zero-energy profile raises `StructuredError`)
- `garantia_fisica_mw ≤ mwac` by construction (fc ≤ 1)

---

### 3. `PriceProfile`

8,760 hourly energy prices from BigQuery. Immutable after fetch.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `prices_brl_per_mwh` | `np.ndarray[float64, (8760,)]` | BRL/MWh | Hourly CCEE PLD prices |
| `source` | `str` | — | `"bigquery_pld_{submarket}_{year}"` (e.g., `"bigquery_pld_SE_2025"`) |
| `bq_submarket` | `str` | — | CCEE submarket (e.g., `"SE"`) |
| `bq_year` | `int` | — | Year fetched from CCEE PLD table |

**Invariants**:
- `len(prices_brl_per_mwh) == 8760`
- All values ≥ 0.0 BRL/MWh
- BigQuery is the sole source — no CSV fallback; unavailability aborts the run

---

### 4. `ScenarioDefinition`

One of three fixed scenarios defined in `config.py`. Derived from `garantia_fisica_mw`
after the profile is loaded. Immutable.

| Field | Type | Unit | Derivation / Value |
|-------|------|------|--------------------|
| `label` | `str` | — | `"A"`, `"B"`, or `"C"` |
| `peak_hours` | `frozenset[int]` | hour-of-day | A: {18,19} / B: {17,18,19} / C: {17,18,19,20}; whole-hour windows only |
| `duration_h` | `int` | h | A: 2 / B: 3 / C: 4 |
| `bess_power_mw` | `float` | MW | `= garantia_fisica_mw` |
| `bess_energy_mwh` | `float` | MWh | `= garantia_fisica_mw × duration_h` |
| `capex_brl` | `float` | BRL | `= bess_energy_mwh × capex_usd_per_kwh × 1000 × usd_brl_rate` |

**Invariants**:
- Exactly 3 scenarios; labels A, B, C are fixed.
- `bess_power_mw == bess_energy_mwh / duration_h` (C-rate = 1).
- `capex_brl > 0` (guaranteed when CAPEX and exchange rate are positive).

---

### 5. `DispatchResult`

Hour-by-hour simulation output for one scenario. Read-only after simulation.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `soc_mwh` | `np.ndarray[float64, (8760,)]` | MWh | State of charge at end of each hour |
| `charge_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Energy charged from solar excess (non-peak hours only) |
| `discharge_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Energy discharged during peak hours |
| `grid_injection_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Net power delivered to grid each hour |
| `deficit_mwh` | `np.ndarray[float64, (8760,)]` | MWh | `max(0, garantia_fisica_mw − generation_h)` in peak hours; 0 elsewhere |
| `residual_deficit_mwh` | `np.ndarray[float64, (8760,)]` | MWh | `deficit_mwh − discharge_mwh`; portion of deficit not covered by BESS |

**Invariants** (validated post-simulation; violation raises `SimulationConstraintError`):
- `soc_mwh[h] ∈ [0, bess_energy_mwh]` for every h
- `charge_mwh[h] > 0` only when `h%24 NOT in peak_hours` AND `generation_h > garantia_fisica_mw`
- `discharge_mwh[h] > 0` only when `h%24 IN peak_hours`
- `charge_mwh[h] × discharge_mwh[h] == 0` (never simultaneous)
- `residual_deficit_mwh[h] ≥ 0` for all h

---

### 6. `ScenarioResult`

Scalar annual metrics for one scenario (A, B, or C). Derived from `DispatchResult`,
`PriceProfile`, `ScenarioDefinition`, and `SimulationParams`.

| Field | Type | Unit | Formula |
|-------|------|------|---------|
| `scenario` | `ScenarioDefinition` | — | The source scenario definition |
| `dispatch` | `DispatchResult` | — | Full hourly dispatch time-series |
| `fc` | `float` | — | Capacity factor (same for all scenarios) |
| `garantia_fisica_mw` | `float` | MW | Physical guarantee (same for all scenarios) |
| `bess_energy_mwh` | `float` | MWh | `garantia_fisica_mw × duration_h` |
| `bess_power_mw` | `float` | MW | `= garantia_fisica_mw` |
| `capex_brl` | `float` | BRL | `bess_energy_mwh × capex_usd_per_kwh × 1000 × usd_brl_rate` |
| `annual_exposure_without_bess_brl` | `float` | BRL/yr | `Σ(deficit_h × PLD_h)` over the guarantee window |
| `annual_exposure_with_bess_brl` | `float` | BRL/yr | `Σ(residual_deficit_mwh[h] × PLD_h)` over peak hours |
| `annual_savings_brl` | `float` | BRL/yr | `exposure_without − exposure_with` |
| `payback_years` | `float \| None` | years | `capex_brl / annual_savings_brl`; `None` if `annual_savings_brl ≤ 0` |
| `coverage_pct` | `float` | % | `(1 − exposure_with / exposure_without) × 100`; range [0, 100] |

**String representations** (for table and report display):
- `payback_years is None` → display `"não atingível"`
- `coverage_pct` formatted to 1 decimal place with `%` suffix

---

### 7. `RunManifest`

Written as JSON to `output/<run-id>/manifest.json` at end of every run.

| Field | Type | Description |
|-------|------|-------------|
| `tool_version` | `str` | Semantic version string (e.g., `"2.0.0"`) |
| `run_id` | `str` | `YYYYMMDD-HHMMSS-<7-char hex>` |
| `timestamp_iso8601` | `str` | ISO 8601 with timezone (e.g., `"2026-05-18T14:30:05-03:00"`) |
| `params_sha256` | `str` | 64-char SHA-256 hex of `json.dumps(params, sort_keys=True)` |
| `profile_source` | `str` | CSV filename (basename); never `"synthetic"` in v2 |
| `price_source` | `str` | `"bigquery_pld_{submarket}_{year}"` |
| `fc` | `float` | Capacity factor derived from CSV |
| `garantia_fisica_mw` | `float` | Physical guarantee in MW |
| `scenarios` | `list[dict]` | 3 entries, each with: `label`, `peak_hours`, `duration_h`, `bess_power_mw`, `bess_energy_mwh`, `capex_brl` |

**Invariants**:
- `bq_service_account_path` is NEVER included in `params_sha256` computation.
- Two runs with identical manifests produce byte-identical numerical results (no stochastic processes in v2).

---

## Dispatch State Transitions

BESS SoC evolves hour by hour (h = 0 … 8759):

```
SoC[0] = 0.0  (start of year, fully discharged)

For each hour h:
  hour_of_day = h % 24

  if generation[h] > garantia_fisica_mw AND hour_of_day NOT in peak_hours:
    # Charging from solar excess
    excess        = generation[h] - garantia_fisica_mw
    charge        = min(excess, bess_power_mw, bess_energy_mwh - SoC[h])
    SoC[h+1]      = SoC[h] + charge
    grid_inj[h]   = generation[h] - charge

  elif hour_of_day IN peak_hours:
    # Discharging to cover deficit below garantia física
    deficit       = max(0, garantia_fisica_mw - generation[h])
    dispatch      = min(deficit, bess_power_mw, SoC[h])
    residual      = deficit - dispatch
    SoC[h+1]      = SoC[h] - dispatch
    grid_inj[h]   = generation[h] + dispatch

  else:
    # Idle (non-peak, no excess)
    SoC[h+1]      = SoC[h]
    grid_inj[h]   = generation[h]

Invariant enforced at every step: 0 ≤ SoC[h] ≤ bess_energy_mwh
```

No RTE losses, no grid charging, no curtailment, no end-of-day SoC floor in v2.

---

## Validation Rules Summary

| Entity | Rule | Error Message Pattern |
|--------|------|-----------------------|
| `SolarProfile` CSV | exactly 8,760 rows | `"Solar CSV has {n} rows; expected 8,760"` |
| `SolarProfile` CSV | all values non-negative numeric | `"Solar CSV row {i}: invalid value '{v}'"` |
| `SolarProfile` CSV | file exists | `"Solar CSV not found: '{path}'"` |
| `PriceProfile` (BQ) | exactly 8,760 rows returned | `"BigQuery PLD: {n} rows returned for {submarket}/{year}; expected 8,760"` |
| `PriceProfile` (BQ) | connection or auth success | raises `DataSourceError`; **run aborts** with descriptive error |
| Any parameter | outside documented bounds | `"Parameter '{name}': value {v} {unit} outside [{lo}, {hi}] {unit}; re-enter"` |
| SoC bound (post-sim) | `soc_mwh[h] < 0` or `> bess_energy_mwh` | raises `SimulationConstraintError` |

---

## Constitution Check (Post-Design)

- [x] **I. Brazilian Sector Compliance** — Garantia física per ANEEL/CCEE convention; PLD price from CCEE BQ table; all outputs reference applicable norm.
- [x] **II. No Data Fabrication** — All defaults documented with value and unit; no synthetic profile; CSV filename logged in every output.
- [x] **III. Test-First** — All entities and invariants directly encode test assertions (SoC bounds, power limits, formula reference cases).
- [x] **IV. Reproducible Results** — `RunManifest` captures all inputs for exact reproduction; no stochastic processes in v2.
- [x] **V. Modular Python Architecture** — Each entity maps to one module; unit suffixes on all fields; no magic numbers.
- [x] **VI. Engineering-Quality Visualizations** — `ScenarioResult` fields map 1:1 to chart axes and table columns with units.
- [x] **VII. SI Units & Brazilian Sector Conventions** — All units explicit: MWac, MWh, BRL/MWh, USD/kWh, h; no mixing.
