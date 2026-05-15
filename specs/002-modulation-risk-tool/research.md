# Research: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Date**: 2026-05-15

All NEEDS CLARIFICATION items from Technical Context resolved below.

---

## R-01 — Synthetic Solar Profile Generation (pvlib Ineichen)

**Decision**: Use `pvlib` ≥ 0.10 with the **Ineichen clearsky model** at
`Location(lat=-22.0, lon=-45.0, altitude=800, tz='America/Sao_Paulo')`.

**Implementation approach**:
1. Build `pd.date_range('2025-01-01', periods=8760, freq='h', tz='America/Sao_Paulo')`.
2. Call `location.get_clearsky(times)` → DataFrame with `ghi`, `dni`, `dhi`.
3. Normalise `ghi` by its annual peak → unit-normalised hourly capacity factor array.
4. AC generation per hour (normalised to 1 MWac, given ILR): `ac_mw = min(cf × ILR, 1.0)`.
5. Curtailment per hour: `max(0, cf × ILR − 1.0)` MW.
6. Entirely deterministic — no RNG involved; same Location + year → byte-identical output.

**Annual solar energy without BESS** (used for BESS sizing):
`E_solar_no_bess_mwh = sum(min(ac_mw[h], 1.0) for h in range(8760))`

**Rationale**: Ineichen is pvlib's robust default for continental sites; uses Linke
turbidity factor (default 3 for SE Brazil altitude); no measured irradiance data needed;
fully offline and deterministic. Lat/lon chosen for Minas Gerais SE Brazil (≈ Baguaçu).

**Alternatives considered**:
- Haurwitz: too simple, no atmospheric parameters → rejected.
- Simplified Solis: requires ozone/water vapour inputs → unnecessary complexity.
- Simple sinusoidal model: not physically grounded, rejected per Principle II.

---

## R-02 — LCOS Formula (CAPEX-only, with degradation and discounting)

**Decision**: Use the following present-value ratio:

$$LCOS_{BRL/MWh} = \frac{CAPEX_{BRL}}{\displaystyle\sum_{y=1}^{N} \frac{E_{y1} \cdot (1 - d)^{y-1}}{(1 + r)^{y}}}$$

Where:
- `CAPEX_BRL` = `bess_capacity_kwh × capex_usd_per_kwh × usd_brl_rate`
- `bess_capacity_kwh` = `bess_energy_mwh × 1000`
- `E_y1` = annual energy discharged from BESS in year 1 (MWh) — from simulation
- `d` = annual degradation rate (fraction, e.g., 0.02)
- `r` = discount rate (fraction, e.g., 0.10)
- `N` = useful life (years, e.g., 15)

**Edge cases**:
- If `sum(denominator) == 0` (zero discharge over life): LCOS = `float('inf')`, reported as
  `"não calculável"`.
- If `d == 0`: `(1 − d)^(y−1) = 1` for all years — no division by zero.
- Degradation is applied only to energy throughput, not to power capacity.

**Rationale**: Standard industry LCOS definition (IRENA, Lazard). O&M excluded per spec
Assumptions. Discounting applied to energy (denominator) only — CAPEX is a single upfront
payment (numerator undiscounted).

**Alternatives considered**:
- Annualised CAPEX via Capital Recovery Factor (CRF): equivalent but less transparent for
  reporting — rejected for clarity.
- Including O&M: explicitly out of scope per spec Assumptions.

---

## R-03 — BESS Dispatch Algorithm (SoC State-Dependent — Python Loop)

**Decision**: Use a **Python `for` loop** over 8,760 hours. SoC state dependency
(`SoC_t` depends on `SoC_{t−1}`) prevents full NumPy vectorisation.

**Per-hour dispatch order** (within each hour `h`):

```
1. Curtailment charging (primary):
   curtail_h = max(0, solar_dc_mw[h] - plant_ac_cap_mw)
   charge_curtail = min(curtail_h, bess_rated_power_mw, energy_cap_mwh - soc)
   soc += charge_curtail
   energy_from_curtail[h] = charge_curtail

2. Discharge (if no curtailment and SoC > 0):
   if curtail_h == 0 and soc > 0:
       discharge = min(bess_rated_power_mw, soc)
       soc -= discharge
       grid_injection[h] += discharge * rte

3. Grid top-up (checked at end of each day, h % 24 == 23):
   if soc < min_soc_threshold * energy_cap_mwh:
       # Two-priority window selection for the next day:
       # Priority 1: next-day hours with curtailment (sorted by hour index)
       next_day_curtail_hours = [h+1+i for i in range(24) if curtail[h+1+i] > 0]
       # Priority 2: remaining next-day hours ranked by PLD price ascending
       next_day_other_hours = sorted(
           [h+1+i for i in range(24) if h+1+i not in next_day_curtail_hours],
           key=lambda idx: prices[idx]
       )
       top_up_candidates = next_day_curtail_hours + next_day_other_hours
       # Select hours from candidates until target SoC is reachable
       top_up_needed = min_soc_threshold * energy_cap_mwh - soc
       selected_top_up_hours = []  # accumulated into DispatchResult.top_up_hours
       # Applied in subsequent top-up hours (respecting injection floor)
```

**Grid top-up** uses a two-priority window selection at end of each day (h % 24 == 23).
When end-of-day SoC < min_soc_threshold:
- **Priority 1**: next-day hours with curtailment in this scenario (excess solar; injection
  floor not binding; BESS can simultaneously receive curtailed energy).
- **Priority 2**: remaining next-day hours with lowest PLD price, ranked ascending, until
  target SoC is reachable.
Selected hour indices are accumulated in `DispatchResult.top_up_hours`. Injection floor
enforced at each top-up hour: reduce charge if it would drop net injection below floor.

**Performance**: 8,760 iterations × 44 scenarios = 385 k iterations. Python loop
completes in < 5 seconds per scenario on modern hardware. Total: < 4 minutes worst case
(within SC-001 3-min target for 44 scenarios — vectorise inner per-hour arithmetic via
NumPy scalar operations).

**Rationale**: SoC is inherently sequential. `numba.jit` would allow ~100× speedup but
adds a compilation dependency; not needed at this scale.

**Alternatives considered**:
- Full NumPy vectorisation via `np.cumsum`: only valid for unconstrained scenarios → rejected.
- `numba.jit`: adds dependency and JIT compilation delay; rejected for simplicity at this scale.

---

## R-04 — Plotly Self-Contained HTML Export

**Decision**: Use `plotly.io.write_html(fig, file_path, include_plotlyjs=True,
full_html=True, auto_open=False)`.

**Key parameters**:
- `include_plotlyjs=True` — embeds the full Plotly.js bundle inline (~3.5 MB).
- `full_html=True` — produces a complete `<!DOCTYPE html>` document.
- Charts combined via `plotly.subplots.make_subplots()` where layout allows, or as
  individual `<div>` sections assembled in a custom HTML template for the report with
  the "Premissas e Limitações" text section.

**Heatmap chart**: `go.Heatmap(z=data_365x24, x=list(range(24)), y=list(range(1, 366)),
colorscale='Viridis')` — 365 rows (day of year) × 24 columns (hour of day).

**File size**: ~3.5–4 MB per report (Plotly.js + chart data). Feasible for email/share.

**Rationale**: `include_plotlyjs=True` is the only mode that guarantees zero network
requests. CDN mode rejected (requires connectivity). Viridis chosen per Constitution
Principle VI (perceptually uniform, no rainbow/jet).

**Alternatives considered**:
- `include_plotlyjs='cdn'`: requires internet — rejected.
- Matplotlib static images: no interactive hover tooltips — rejected.
- ECharts/Chart.js: no native Python integration, no heatmap without plugins — rejected.

---

## R-05 — Run-ID and SHA-256 Manifest

**Decision**:

```python
import hashlib, json
from datetime import datetime

param_bytes = json.dumps(params, sort_keys=True, default=str).encode('utf-8')
sha256_hex  = hashlib.sha256(param_bytes).hexdigest()
run_id      = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{sha256_hex[:7]}"
# e.g., "20260515-143005-a1b2c3d"
```

**Manifest fields** (written to `output/<run-id>/manifest.json`):
```json
{
  "tool_version": "1.0.0",
  "run_id": "20260515-143005-a1b2c3d",
  "timestamp_iso8601": "2026-05-15T14:30:05-03:00",
  "params_sha256": "a1b2c3d...<full 64-char hex>",
  "rng_seed": 42,
  "profile_source": "synthetic",
  "price_source": "flat_220_brl_per_mwh"
}
```

**Rationale**: `sort_keys=True` ensures deterministic JSON serialisation regardless of
dict insertion order. ISO 8601 timestamp with timezone for unambiguous run ordering.
7-char hash prefix in run-ID provides human-readable uniqueness without full UUID length.

**Alternatives considered**:
- UUID4: non-deterministic, not input-derived — rejected.
- Timestamp only: collision risk for rapid successive runs — rejected.

---

## R-06 — CLI Parameter Prompting Pattern

**Decision**: Use Python's built-in `input()` in a re-prompt loop per parameter.
No third-party CLI library (click, inquirer) required — keeps dependencies minimal.

**Pattern**:
```python
def prompt_float(name: str, default: float, min_val: float, max_val: float, unit: str) -> float:
    while True:
        raw = input(f"  {name} [{unit}] (default {default}): ").strip()
        if raw == "":
            return default
        try:
            val = float(raw)
        except ValueError:
            print(f"  ERROR: '{raw}' is not a number. Enter a value in [{min_val}, {max_val}].")
            continue
        if not (min_val <= val <= max_val):
            print(f"  ERROR: {val} {unit} is out of range [{min_val}, {max_val}] {unit}.")
            continue
        return val
```

**Rationale**: Zero additional dependencies; satisfies FR-001 and FR-013 (re-prompt with
descriptive error). Sufficient for the tool's single-session interactive use case.

**Alternatives considered**:
- `click` with prompts: would work but adds a dependency for minimal gain — rejected.
- `inquirer`/`questionary`: richer UX but overkill for a technical CLI — rejected.

---

## R-07 — BigQuery PLD Price Integration

**Decision**: Add `data_sources.py` module wrapping `google-cloud-bigquery` to fetch
real CCEE hourly PLD prices. Two auth modes: **Application Default Credentials (ADC)**
(default, zero config for GCP environments) and **service account JSON path** (explicit,
for CI/CD or non-GCP machines). BigQuery is the **only** price data source; there is no
CSV fallback and no `--no-bigquery` flag. If BigQuery is unavailable for any reason,
`DataSourceError` is raised and the run aborts with a descriptive error message.

**Source table** (from `.specify/memory/bigquery_interface.md`):
```
benchmarkingmercado.ccee_infomercado
  .preco_da_liquidacao_das_diferencas_pld_por_submercado_hora
```

**Query pattern** (parameterised; no string interpolation — use BigQuery `@params`):
```sql
SELECT date, hora, value AS pld_brl_per_mwh
FROM `benchmarkingmercado.ccee_infomercado.preco_da_liquidacao_das_diferencas_pld_por_submercado_hora`
WHERE EXTRACT(YEAR FROM date) = @year
  AND submercado = @submarket
  AND value IS NOT NULL
ORDER BY date, hora
```

**Post-query processing**:
1. Validate result has exactly 8,760 rows (one per hour of year, non-leap).
2. Assert all `pld_brl_per_mwh` values ≥ 0 (ANEEL floor ~ 58.60 BRL/MWh).
3. Return `np.ndarray[float64, (8760,)]` ordered by `(date, hora)`.
4. On any `google.api_core.exceptions.GoogleAPIError`, `google.auth.exceptions.TransportError`,
   or row count mismatch: raise `DataSourceError` with descriptive message; **run aborts**.
   No fallback to flat rate.

**Auth resolution order**:
1. If `--service-account /path/to/key.json` CLI flag: use `service_account.Credentials`.
2. Otherwise: use ADC (`google.auth.default()`).

**Billing project**: `cver-solar` (default); configurable via CLI param `--bq-billing-project`.
**Data project**: `benchmarkingmercado` (fixed per interface doc; not user-configurable).
**Default submarket**: `SE` (Sudeste/Centro-Oeste — covers most solar projects in SE Brazil).
**Default year**: 2025 (most recent complete year in the CCEE table at time of writing).

**Security note**: Service account JSON path is never logged, hashed into the manifest,
or embedded in the HTML report. Only the auth method label (`"adc"` or `"service_account"`)
is recorded in the manifest.

**Rationale**: ADC is the lowest-friction auth method for GCP workstations and CI (no
secrets to manage). Service account JSON covers non-GCP machines and local development.

**Alternatives considered**:
- OAuth2 device flow: interactive browser auth — rejected (breaks headless/CI use).
- Embedding service account key in config file: security risk — rejected.

---

## Resolution Summary

| Item | Status | Decision |
|------|--------|----------|
| Synthetic profile library | ✅ Resolved | pvlib Ineichen, lat=-22, lon=-45 |
| LCOS formula | ✅ Resolved | PV-ratio, CAPEX/(Σ discounted energy) |
| Dispatch algorithm | ✅ Resolved | Python loop; curtailment-first; top-up next-day off-peak |
| HTML chart library | ✅ Resolved | Plotly.js inline via `include_plotlyjs=True` |
| Run-ID + manifest | ✅ Resolved | `YYYYMMDD-HHMMSS-<sha256[:7]>` |
| CLI prompting | ✅ Resolved | `input()` loop, no extra dependency |
| BigQuery PLD integration | ✅ Resolved | `data_sources.py`; ADC/service-account; mandatory (no fallback) |

No NEEDS CLARIFICATION items remain. Phase 1 design may proceed.
