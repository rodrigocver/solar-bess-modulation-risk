# Data Model: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Date**: 2026-05-15

---

## Entities

### 1. `SimulationParams`

The complete, validated configuration for a single analysis run. Immutable after
validation. Serialised to JSON for the run manifest SHA-256 hash.

| Field | Type | Unit | Default | Bounds | Description |
|-------|------|------|---------|--------|-------------|
| `plant_capacity_mwac` | `float` | MWac | 1.0 | fixed | Normalisation basis; always 1.0 MWac |
| `ilr_values` | `list[float]` | — | [1.2,1.3,1.4,1.5] | each ∈ [1.0, 2.0] | ILR scenarios to simulate |
| `bess_size_ratios_pct` | `list[float]` | % of E_solar | [0,5,10,15,20,25,30,40,50,75,100] | each ∈ [0, 500] | BESS energy sizing as % of annual solar energy without BESS |
| `storage_durations_h` | `list[float]` | h | [2.0] | each ∈ [0.5, 8.0] | Storage duration(s); BESS rated power = energy_cap / duration |
| `rte_pct` | `float` | % | 85.0 | (0, 100] | Round-trip efficiency; applied on discharge |
| `degradation_pct_yr` | `float` | %/year | 2.0 | [0, 10] | Annual capacity degradation |
| `capex_usd_per_kwh` | `float` | USD/kWh | 250.0 | (0, 2000] | BESS CAPEX (market unit) |
| `usd_brl_rate` | `float` | BRL/USD | 5.0 | (0, 20] | Exchange rate for cost conversion |
| `useful_life_yr` | `int` | years | 15 | [1, 30] | Economic useful life |
| `discount_rate_pct` | `float` | %/year | 10.0 | [0, 50] | Discount rate for LCOS |
| `min_soc_threshold_pct` | `float` | % of capacity | 80.0 | [0, 100] | End-of-day SoC below which grid top-up is triggered |
| `min_injection_floor_mw` | `float` | MW | 0.0 | [0, 1.0] | Minimum net grid injection during top-up hours |
| `rng_seed` | `int` | — | 42 | [0, 2³²) | Seed for any stochastic processes |
| `synthetic_profile_lat` | `float` | ° | -22.0 | [-90, 90] | Latitude for pvlib clearsky |
| `synthetic_profile_lon` | `float` | ° | -45.0 | [-180, 180] | Longitude for pvlib clearsky |
| `synthetic_profile_alt_m` | `float` | m | 800.0 | [0, 5000] | Altitude for pvlib Ineichen |
| `bq_billing_project` | `str` | — | `"cver-solar"` | non-empty | GCP billing project for BigQuery queries |
| `bq_submarket` | `str` | — | `"SE"` | one of {SE,S,NE,N} | CCEE submarket for PLD price fetch |
| `bq_year` | `int` | — | 2025 | [2021, 2040] | Year to fetch from CCEE PLD table |
| `bq_auth_method` | `Literal['adc','service_account']` | — | `"adc"` | — | BigQuery authentication method |
| `bq_service_account_path` | `str \| None` | — | None | valid path if set | Path to service account JSON key file; None when using ADC |

**Invariants**:
- `bess_size_ratios_pct` must include 0 (for baseline scenario).
- `rte_pct` / 100 is the discharge efficiency multiplier.
- `plant_capacity_mwac` is always 1.0 MWac (normalisation basis — engineers scale results
  by their actual plant MWac).
- `bq_service_account_path` MUST be set (non-None, existing path) when `bq_auth_method == 'service_account'`.
- `bq_service_account_path` is NEVER serialised into the manifest SHA-256 hash — only
  `bq_auth_method` label is recorded (security: no key path in output files).

---

### 2. `SolarProfile`

8,760 hourly AC generation values for a 1 MWac plant, normalised. Immutable after load.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `generation_mw` | `np.ndarray[float64, (8760,)]` | MW | Hourly AC power injected, capped at 1.0 MWac |
| `source` | `Literal['synthetic', 'csv']` | — | Provenance label; appears in all outputs |
| `source_path` | `str \| None` | — | CSV path if source='csv'; None if synthetic |
| `annual_energy_mwh` | `float` | MWh | `sum(generation_mw)` — computed on load; used for BESS sizing |

**Invariants**:
- `len(generation_mw) == 8760`
- All values ∈ [0.0, 1.0] MWac (non-negative, capped at plant capacity)
- `annual_energy_mwh > 0` (validated; zero-generation profile raises `StructuredError`)

---

### 3. `PriceProfile`

8,760 hourly energy prices. Immutable after load.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `prices_brl_per_mwh` | `np.ndarray[float64, (8760,)]` | BRL/MWh | Hourly energy prices |
| `source` | `Literal['bigquery_pld']` | — | Price data provenance; always BigQuery PLD |
| `bq_submarket` | `str` | — | CCEE submarket (e.g., `"SE"`) |
| `bq_year` | `int` | — | Year fetched from CCEE PLD table |

**Invariants**:
- `len(prices_brl_per_mwh) == 8760`
- All values ≥ 0.0 BRL/MWh
- `bq_submarket` and `bq_year` are always non-None
- `bq_service_account_path` is never stored in this entity (security boundary)

---

### 4. `BESSConfig` (derived from `SimulationParams` + `SolarProfile` per scenario)

Computed sizing for a single (ILR, BESS size ratio, duration) scenario.
Derived — not directly configurable.

| Field | Type | Unit | Derivation |
|-------|------|------|------------|
| `energy_capacity_mwh` | `float` | MWh | `(bess_size_ratio_pct / 100) × annual_solar_energy_no_bess_mwh` |
| `rated_power_mw` | `float` | MW | `energy_capacity_mwh / duration_h` |
| `capex_brl` | `float` | BRL | `energy_capacity_mwh × 1000 × capex_usd_per_kwh × usd_brl_rate` |
| `duration_h` | `float` | h | from `storage_durations_h` |
| `ilr` | `float` | — | from `ilr_values` |
| `bess_size_ratio_pct` | `float` | % | from `bess_size_ratios_pct` |

**Note on `annual_solar_energy_no_bess_mwh`**: computed once from `SolarProfile` for each
ILR value as `sum(min(generation_mw[h] * ilr, 1.0) for h in range(8760))` — this is the
clipped energy that would be injected without any BESS.

---

### 5. `DispatchResult`

Hour-by-hour simulation output for one scenario. Read-only after simulation.

| Field | Type | Unit | Description |
|-------|------|------|-------------|
| `soc_mwh` | `np.ndarray[float64, (8760,)]` | MWh | State of charge at end of each hour |
| `charge_curtail_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Energy charged from curtailment per hour |
| `charge_grid_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Energy charged from grid generation (top-up) per hour |
| `discharge_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Energy discharged (before RTE loss) per hour |
| `curtailment_with_bess_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Residual curtailment per hour after BESS |
| `curtailment_without_bess_mwh` | `np.ndarray[float64, (8760,)]` | MWh | Curtailment per hour without BESS |
| `top_up_hours` | `list[int]` | — | Hour indices (0–8759) selected for grid top-up charging; empty if no top-up occurred |

**Invariants** (validated post-simulation):
- `soc_mwh` ∈ [0, `energy_capacity_mwh`] for every hour
- `charge_curtail_mwh + charge_grid_mwh ≤ rated_power_mw` per hour
- `discharge_mwh ≤ rated_power_mw` per hour
- `charge_*` and `discharge_*` are never non-zero in the same hour

---

### 6. `ScenarioResult`

Scalar annual metrics for one (ILR, BESS %, duration) scenario. Derived from
`DispatchResult` + `PriceProfile` + `BESSConfig` + `SimulationParams`.

| Field | Type | Unit | Formula |
|-------|------|------|---------|
| `scenario_id` | `tuple[float, float, float]` | (ILR, %, h) | (ilr, bess_size_ratio_pct, duration_h) |
| `curtailment_without_bess_mwh_yr` | `float` | MWh/yr | `sum(curtailment_without_bess_mwh)` |
| `curtailment_with_bess_mwh_yr` | `float` | MWh/yr | `sum(curtailment_with_bess_mwh)` |
| `curtailment_avoided_pct` | `float` | % | `(1 − c_with/c_without) × 100`; 0 if c_without=0 |
| `effective_cf_pct` | `float` | % | `sum(grid_injection_mwh) / (1.0 MWac × 8760 h) × 100` |
| `equivalent_cycles_yr` | `float` | cycles/yr | `sum(discharge_mwh) / energy_capacity_mwh`; 0 if cap=0 |
| `incremental_revenue_brl_yr` | `float` | BRL/yr | `sum(charge_curtail_mwh[h] × price[h] × rte)` |
| `energy_from_curtail_mwh_yr` | `float` | MWh/yr | `sum(charge_curtail_mwh)` |
| `energy_from_grid_mwh_yr` | `float` | MWh/yr | `sum(charge_grid_mwh)` |
| `lcos_brl_per_mwh` | `float \| None` | BRL/MWh | See R-02; `None` if denominator=0 |
| `payback_yr` | `float \| None` | years | `capex_brl / incremental_revenue_brl_yr`; `None` if revenue≤0 |
| `top_up_hour_slots` | `list[str]` | HH:00 | Grid top-up window slots derived from `top_up_hours` (e.g., `["00:00", "01:00"]`); empty list if no top-up occurred |

**String representations** (for table display):
- `lcos_brl_per_mwh` is None → display `"não calculável"`
- `payback_yr` is None → display `"não atingível"`

---

### 7. `RunManifest`

Written as JSON to `output/<run-id>/manifest.json` at end of every run.

| Field | Type | Description |
|-------|------|-------------|
| `tool_version` | `str` | Semantic version string (e.g., `"1.0.0"`) |
| `run_id` | `str` | `YYYYMMDD-HHMMSS-<sha256[:7]>` |
| `timestamp_iso8601` | `str` | ISO 8601 with timezone (e.g., `"2026-05-15T14:30:05-03:00"`) |
| `params_sha256` | `str` | Full 64-char SHA-256 hex of `json.dumps(params, sort_keys=True)` |
| `rng_seed` | `int` | RNG seed used |
| `profile_source` | `str` | `"synthetic"` or CSV filename |
| `price_source` | `str` | `"bigquery_pld_{submarket}_{year}"` (e.g., `"bigquery_pld_SE_2025"`) |
| `scenario_top_up_hours` | `dict[str, list[str]]` | Per-scenario top-up slots; key = `"{ilr}_{bess_pct}_{dur_h}"`, value = list of HH:00 strings |

---

## State Transitions

### BESS SoC (per hour, per scenario)

```
SoC[h=0] = 0.0  (start of year)

Each hour h:
  curtail_h = max(0, solar_dc_mw[h] - 1.0)       # clipping above MWac
  if curtail_h > 0:
    Δcharge_curtail = min(curtail_h, rated_power_mw, energy_cap_mwh - SoC[h])
    SoC[h] += Δcharge_curtail
  elif SoC[h] > 0:                                 # no curtailment, discharge
    Δdischarge = min(rated_power_mw, SoC[h])
    SoC[h] -= Δdischarge
    grid_injection[h] += Δdischarge × rte

  if h % 24 == 23 and SoC[h] < min_soc_threshold × energy_cap_mwh:
    # Two-priority window selection for next day:
    # Priority 1: hours in next day with curtailment (sorted first)
    # Priority 2: remaining next-day hours with cheapest PLD price, ranked ascending
    # Select hours until target SoC is reachable; record selected indices in top_up_hours
    mark_top_up(priority1_curtail_hours + priority2_cheap_pld_hours, target_soc)

[At marked top-up hours]
  Δcharge_grid = min(rated_power_mw, energy_cap_mwh - SoC[h])
  SoC[h] += Δcharge_grid
  (net injection floor enforced: reduce Δcharge_grid if it would drop injection below floor)
```

**Invariant enforced at every step**: `0 ≤ SoC ≤ energy_cap_mwh`.

---

## Validation Rules Summary

| Entity | Rule | Error Message Pattern |
|--------|------|-----------------------|
| `SolarProfile` CSV | exactly 8,760 rows | `"Solar CSV has {n} rows; expected 8,760"` |
| `SolarProfile` CSV | all values non-negative numeric | `"Solar CSV row {i}: invalid value '{v}'"` |
| BigQuery PLD result | exactly 8,760 rows | `"BigQuery PLD: {n} rows returned for year {y}, submarket {s}; expected 8,760"` |
| BigQuery PLD result | all values ≥ 0 | `"BigQuery PLD: negative price {v} BRL/MWh at index {i}"` |
| BigQuery auth | service_account path exists | `"BigQuery auth: service account file not found: '{path}'"` |
| Any parameter | outside documented bounds | `"Parameter '{name}': value {v} {unit} outside [{lo}, {hi}] {unit}"` |
| Heatmap scenario | not in computed results | `"Scenario (ILR={i}, BESS={b}%, dur={d}h) not found. Available: {list}"` |
| SoC bound (post-sim) | SoC < 0 or > cap | raises `SimulationConstraintError` |
| BigQuery unavailable | any `GoogleAPIError` or `TransportError` | raises `DataSourceError`; **run aborts** with descriptive error message |

---

## Constitution Check (Post-Design)

- [x] **I** — Curtailment = ANEEL: involuntary clipping at MWac threshold. Labelled in all outputs.
- [x] **II** — All defaults and bounds documented above; no silent values.
- [x] **III** — All entities/invariants directly encode test assertions.
- [x] **IV** — `RunManifest` captures all inputs for exact reproduction.
- [x] **V** — Each entity maps to one module (≤ 400 lines); unit suffixes on all fields.
- [x] **VI** — `ScenarioResult` fields map 1:1 to chart axes and table columns with units.
- [x] **VII** — All units explicit: MWac, MWh, BRL/MWh, USD/kWh, %/year, h.
