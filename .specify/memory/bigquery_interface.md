# BigQuery & PSR Data Interface

**Purpose**: Document all external price and generation data sources from the reference
project (`/home/cver/projects/copilot/modulacao/modulacao`) for use as real price inputs
in the Solar+BESS Modulation Risk Analysis Tool (feature 002-modulation-risk-tool).

**Documented**: 2026-05-15
**Reference files**:
- `Berto/data_reader.py` — PSR stochastic data loader (local CSV)
- `data_reader_comentado.py` — annotated version of the same module
- `bess_linkedin.py` — BigQuery client, queries, and constants

---

## 1. Google Cloud BigQuery — Connection

```python
BQ_BILLING_PROJECT = "cver-solar"        # GCP project for billing
BQ_PROJECT         = "benchmarkingmercado"  # GCP project with data
```

Authentication requires Google Cloud credentials (via `google.cloud.bigquery`).
In Colab: `from google.colab import auth; auth.authenticate_user()`.
Outside Colab: use Application Default Credentials (`gcloud auth application-default login`).

---

## 2. PLD Horário — CCEE Spot Price

### BigQuery table

```
benchmarkingmercado.ccee_infomercado.preco_da_liquidacao_das_diferencas_pld_por_submercado_hora
```

### Schema (columns used in reference project)

| Column | BQ type | Unit | Description |
|--------|---------|------|-------------|
| `date` | DATE | — | Date of the price record |
| `submercado` | STRING | — | Submarket name (raw values: "SE", "S", "NE", "N") |
| `hora` | INTEGER | h | Hour of day (0–23) |
| `value` | FLOAT64 | R$/MWh | PLD — Preço de Liquidação das Diferenças |

### Reference query

```sql
SELECT
    EXTRACT(YEAR FROM date) AS ano,
    date,
    submercado,
    hora,
    value AS pld
FROM `benchmarkingmercado.ccee_infomercado.preco_da_liquidacao_das_diferencas_pld_por_submercado_hora`
WHERE EXTRACT(YEAR FROM date) >= 2021
  AND value IS NOT NULL
```

### Returned DataFrame schema

| Column | dtype | Unit | Notes |
|--------|-------|------|-------|
| `ano` | int64 | — | Extracted year |
| `date` | datetime64 | — | Full date |
| `submercado` | object | — | Uppercased in post-processing: "SE", "NE", "S", "N" |
| `hora` | int64 | h | 0–23 |
| `pld` | float64 | R$/MWh | PLD value; NULL rows filtered by WHERE clause |

### Coverage & statistics (historical)
- **Period**: 2021 – present (continuously updated by CCEE)
- **Temporal resolution**: hourly (one row per submarket × hour × date)
- **Submercados**: SE/CO, S, NE, N (4 submarkets)
- **Observed range**: ~58–1,542 R$/MWh across PSR scenarios; CCEE floor is ~58.60 R$/MWh

### Usage for this project
The PLD table provides real historical hourly prices (2021–2026) for revenue calculations
when the analyst does not use the flat-rate default. The module should:
1. Query this table for the relevant year(s).
2. Filter to the submercado matching the project location (default: `submercado = 'SE'`).
3. Pivot to a 8,760-row Series indexed by `datetime` (year × date × hora).
4. Fall back to the configured flat rate if BQ is unavailable.

---

## 3. Restrição de Geração Fotovoltaica — ONS Curtailment

### BigQuery table

```
benchmarkingmercado.ons_dadosabertos_analysis.tb_constrained_off
```

### Schema (columns used in reference project)

| Column (BQ name) | dtype | Unit | Description |
|-----------------|-------|------|-------------|
| `datahora` | DATETIME | — | Semi-hourly or hourly timestamp (timezone: Brasília, UTC-3) |
| `fonte` | STRING | — | Source type: `'Solar'`, `'Fotovoltaica'`, `'Eólico'`, `'Eolica'` |
| `cod_razao_restricao` | STRING | — | Restriction reason code (see Reason Codes below) |
| `valor_geracao_limitada` | FLOAT64 | MW | Power limited (curtailed) at this timestamp |

### Reference query

```sql
SELECT
    datahora                    AS din_instante,
    fonte,
    cod_razao_restricao,
    SUM(valor_geracao_limitada) AS val_geracaolimitada
FROM `benchmarkingmercado.ons_dadosabertos_analysis.tb_constrained_off`
WHERE DATE(datahora) >= '2021-01-01'
  AND fonte IN ('Eólico', 'Solar', 'Eolica', 'Fotovoltaica')
GROUP BY 1, 2, 3
ORDER BY 1, 2
```

### Reason codes (`cod_razao_restricao`)

| Code | Label | Meaning |
|------|-------|---------|
| `ENE` | Energético | System-level energy surplus (load too low relative to must-run generation). Most relevant for BESS modulation analysis. |
| `REL` | Razão Elétrica | Electrical network constraint (transmission congestion, voltage). |
| `CNF` | Confiabilidade | Reliability constraint. |
| `PAR` | Partição | Market partition constraint. |

**Analysis hypotheses used in reference project:**
- **H1**: ENE + REL (broader definition of avoidable curtailment)
- **H2**: ENE only (conservative — only energetic curtailment is BESS-relevant)

**Recommended for this project**: H2 (ENE only) — consistent with ANEEL definition of
involuntary curtailment caused by energy surplus, which a BESS co-located with a solar
plant can absorb.

### Temporal resolution
- **Raw**: semi-hourly (0.5h) or hourly depending on the period and data source.
- **Detection**: use `detectar_resolucao_temporal(df)` from the reference project.
- **Conversion factor**: when summing semi-hourly MW values to MWh, multiply by 0.5h.
  When summing hourly values, multiply by 1.0h.

### Coverage
- **Period**: 2021 – present
- **Temporal resolution**: semi-hourly (0.5h) in most recent data

---

## 4. PSR Stochastic Scenarios — Local CSV Files

### Source
Produced by the PSR (Planejamento de Sistemas de Reservatórios) hydraulic-thermal
dispatch model. Files are local and not fetched from BigQuery.

**Local base path**: `/home/cver/projects/copilot/modulacao/modulacao/psr_2025/`

### Directory structure

```text
psr_2025/
└── precos/
    ├── 2026/
    │   ├── psr_price_se_2026.csv   # Prices — Sudeste/Centro-Oeste
    │   ├── psr_price_ne_2026.csv   # Prices — Nordeste
    │   ├── psr_price_su_2026.csv   # Prices — Sul
    │   └── psr_price_no_2026.csv   # Prices — Norte
    ├── 2027/ ... 2040/             # Same structure for all years
```

> **Note**: Generation CSV files (geracao/) are NOT present in the local copy. Only
> price data (precos/) is available locally.

### CSV file schema

Each file `psr_price_{submarket}_{year}.csv`:

| Dimension | Value | Notes |
|-----------|-------|-------|
| Rows | 8,760 | One per hour of the year (non-leap year) |
| Columns | 400 (PSR 2025), 200 (older decks) | One per stochastic scenario |
| Column names | `"1"`, `"2"`, ..., `"400"` | String-typed sequential scenario IDs |
| dtype | float64 | |
| Unit | R$/MWh | Spot price for that submarket, hour, and scenario |
| Index | None (positional) | Row 0 = hour 0 of Jan 1, row 8759 = hour 23 of Dec 31 |

**After transposing** (`.values.T`): shape `(n_series, 8760)` — standard for all
internal operations in the reference project.

### Value ranges (empirical from local data)

| Year | Submarket | Mean (R$/MWh) | Min (R$/MWh) | Max (R$/MWh) |
|------|-----------|---------------|--------------|--------------|
| 2026 | SE | 193.88 | 58.60 | 1,542.23 |
| 2030 | SE | 155.67 | 58.60 | 1,482.42 |
| 2035 | SE | 146.61 | 58.60 | 1,000.00 |

**Price floor**: ~58.60 R$/MWh (ANEEL-set minimum PLD, confirmed across all years and
scenarios).

### Available years (local copy)
2026, 2027, 2028, 2029, 2030, 2031, 2032, 2033, 2034, 2035, 2036, 2037, 2038, 2039, 2040

### Available submarkets (local copy)
`se`, `ne`, `su`, `no`

---

## 5. DataReader class — Interface Summary

**File**: `Berto/data_reader.py` (and `data_reader_comentado.py` for annotated version)

### Constructor

```python
reader = DataReader(psr_data_path="/path/to/psr_2025", psr_year=2025)
# psr_year=2025 → 400 series; any other year → 200 series
```

### `get_psr_hourly()` — Prices + generation (NORMALIZED)

```python
prices, gen_dict = reader.get_psr_hourly(
    submarkets=["se", "ne"],
    g_list=[{"g_type": "eolica", "submarket": "ne",
             "target_submarket": "ne", "output_label": "wind"}],
    years=[2026, 2027],
    price_range=(0, 1000)  # Filter: keep series with mean annual price in this range
)
```

**Returns**:
- `prices`: `np.ndarray` shape `(n_filtered_series, n_submarkets, 8760)`, unit R$/MWh
- `gen_dict`: `dict[str, np.ndarray]` same shape; values NORMALIZED (divided by global
  mean, so mean ≈ 1.0). Use for relative deviation analysis.

### `get_psr_hourly_not_normalized()` — Prices + generation (ABSOLUTE)

Same signature; generation values returned in absolute MW (not divided by mean).
Use this when absolute generation quantities are needed (e.g., curtailment accounting).

### `_get_p_psr_hourly_single_year()` — Internal: prices for one year

```python
prices, bool_index = reader._get_p_psr_hourly_single_year(
    submarkets=["se"],
    year=2026,
    price_range=(50, 500)
)
# prices: shape (n_filtered, n_submarkets, 8760), R$/MWh
# bool_index: shape (n_series_total,) — True for series passing the price filter
```

---

## 6. Integration Strategy for This Project

### Recommended price source hierarchy

```
1. User provides external PLD CSV (8,760 rows, BRL/MWh)   → highest priority
2. BigQuery available (cver-solar project, benchmarkingmercado)
   → query preco_da_liquidacao_das_diferencas_pld_por_submercado_hora
   → filter to year(s) and submercado
3. PSR stochastic mean (local CSV, mean over 400 series)
   → representative forward price for project location
4. Flat rate (configured default: 220 BRL/MWh)             → fallback
```

### Price extraction for a single year (SE submarket, PSR)

```python
import pandas as pd, numpy as np

PSR_PATH = "/home/cver/projects/copilot/modulacao/modulacao/psr_2025"
YEAR = 2026
SUBMARKET = "se"

df = pd.read_csv(f"{PSR_PATH}/precos/{YEAR}/psr_price_{SUBMARKET}_{YEAR}.csv")
# shape: (8760, 400)

# Mean price profile across all 400 scenarios (one R$/MWh per hour):
price_mean_brl_mwh = df.values.mean(axis=1)  # shape (8760,)

# Median price profile (more robust to outlier scenarios):
price_median_brl_mwh = df.values.median(axis=1)  # shape (8760,)
```

### Mapping PSR array index to datetime

```python
import pandas as pd

def psr_hour_index_to_datetime(year: int) -> pd.DatetimeIndex:
    """Returns a DatetimeIndex for the 8,760 hours of the given non-leap year."""
    return pd.date_range(
        start=f"{year}-01-01 00:00",
        periods=8760,
        freq="h",
        tz=None  # Brasília local time (no DST in most of Brazil's electric grid reporting)
    )
```

### Important caveats

1. **Synthetic label**: PSR prices are stochastic projections, NOT realized prices.
   Results derived from PSR MUST be labelled as "based on PSR {year} stochastic
   scenarios" — NOT as "realized" or "measured" prices (Constitution Principle II).

2. **BigQuery PLD is realized**: the CCEE PLD table contains actual historical settlements.
   This is appropriate for backtesting and for the default year(s) 2025–2026.

3. **Currency**: all values are in **R$/MWh** (BRL). No automatic USD conversion.

4. **Unit**: prices are in **R$/MWh** (megawatt-hour). All revenue calculations in
   this project MUST use MWh as the energy unit (Constitution Principle VII).

5. **Submarket**: for a solar project in Southeast Brazil, use `submercado = "se"` (PSR)
   or `submercado = 'SE'` (BQ, after `.str.upper()`). The SE/CO submarket sets the PLD
   for most of the installed solar capacity in Brazil (Constitution Principle I — ONS).

6. **BQ access**: requires `cver-solar` GCP project credentials. The module MUST
   gracefully fall back to the flat rate if BQ is unavailable (FR-004, spec 002).

7. **Temporal resolution**: PSR CSVs are strictly hourly (8,760 rows). BQ PLD table
   is also hourly (one row per date × submarket × hour). The ONS curtailment table
   may be semi-hourly — always detect resolution before converting MW → MWh.
