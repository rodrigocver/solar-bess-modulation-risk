# CLI Schema Contract: Solar+BESS Modulation Risk Analysis Tool

**Branch**: `002-modulation-risk-tool` | **Date**: 2026-05-15

This contract defines the complete interactive CLI session that the tool presents to
the engineer. It is the external interface of the tool and governs:
- Parameter prompt order and display format
- Default values, units, and validation bounds for every parameter
- Profile load prompts (solar CSV)
- Post-simulation heatmap scenario selection prompt
- Error message format for validation failures

Implementations MUST conform to this contract. Test file: `tests/contract/test_cli_schema.py`.

---

## 1. Session Flow

```
[WELCOME BANNER]
Solar+BESS Modulation Risk Analysis Tool v1.0.0
Normalizado para 1 MWac | Resultados em BRL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[SECTION 1: Plant & Simulation Parameters]
  <prompts P-01 through P-09 in order>

[SECTION 2: BESS Economic Parameters]
  <prompts P-10 through P-14 in order>

[SECTION 3: Dispatch Strategy Parameters]
  <prompts P-15 through P-16 in order>

[SECTION 4: Solar Profile]
  <prompts P-17 through P-18>

[SECTION 5: Price Profile]
  <prompts P-19 through P-24>

[SECTION 6: BigQuery Authentication]
  <prompts P-20 through P-22>

[CONFIRMATION SUMMARY]
  Display all accepted parameter values with units before proceeding.
  Prompt: "Proceed with simulation? [Y/n]: "

[SIMULATION PROGRESS]
  "Simulating {n} scenarios... [1/44] ILR=1.2, BESS=0%... "

[POST-SIMULATION: HEATMAP SCENARIO SELECTION]
  <prompt P-21>

[REPORT GENERATION]
  "Generating report... output/<run-id>/report.html"

[DONE BANNER]
```

---

## 2. Parameter Prompts

All prompts follow this display pattern:

```
  {label} [{unit}] (padrão {default}): _
```

On invalid input, display error then repeat the same prompt:

```
  ERRO: {descriptive message identifying parameter, value, and acceptable range}
  {label} [{unit}] (padrão {default}): _
```

### Section 1 — Plant & Simulation Parameters

| ID | Label (PT-BR) | Unit | Default | Bounds | Param field |
|----|--------------|------|---------|--------|-------------|
| P-01 | `ILR (razão de inversão)` | list of floats | `1.2,1.3,1.4,1.5` | each ∈ [1.0, 2.0] | `ilr_values` |
| P-02 | `Razões de dimensionamento BESS` | % of E_solar | `0,5,10,15,20,25,30,40,50,75,100` | each ∈ [0, 500]; must include 0 | `bess_size_ratios_pct` |
| P-03 | `Duração do armazenamento` | h | `2` | each ∈ [0.5, 8.0] | `storage_durations_h` |
| P-04 | `Eficiência round-trip` | % | `85.0` | (0, 100] | `rte_pct` |
| P-05 | `Taxa de degradação anual` | %/ano | `2.0` | [0, 10] | `degradation_pct_yr` |

### Section 2 — BESS Economic Parameters

| ID | Label (PT-BR) | Unit | Default | Bounds | Param field |
|----|--------------|------|---------|--------|-------------|
| P-06 | `CAPEX do BESS` | USD/kWh | `250.0` | (0, 2000] | `capex_usd_per_kwh` |
| P-07 | `Taxa de câmbio USD/BRL` | BRL/USD | `5.0` | (0, 20] | `usd_brl_rate` |
| P-08 | `Vida útil` | anos | `15` | [1, 30] | `useful_life_yr` |
| P-09 | `Taxa de desconto` | %/ano | `10.0` | [0, 50] | `discount_rate_pct` |

### Section 3 — Dispatch Strategy Parameters

| ID | Label (PT-BR) | Unit | Default | Bounds | Param field |
|----|--------------|------|---------|--------|-------------|
| P-11 | `Limiar mínimo de SoC (para carga da rede)` | % da capacidade | `80.0` | [0, 100] | `min_soc_threshold_pct` |
| P-12 | `Piso mínimo de injeção na rede` | MW | `0.0` | [0, 1.0] | `min_injection_floor_mw` |

### Section 4 — Solar Profile

| ID | Prompt | Type |
|----|--------|------|
| P-13 | `Carregar perfil solar de CSV? (s/N): ` | boolean |
| P-14 | `Caminho do CSV do perfil solar: ` | file path (shown only if P-13 = s) |

Behaviour:
- If P-13 = N (default): load synthetic pvlib profile; print summary.
- If P-13 = s: validate path exists, file has 8,760 non-negative numeric rows; on failure,
  print error with row/value detail and fall back to synthetic with explicit notice.
- After load, always print: `"Perfil solar carregado: {source} | min={min:.3f} MW, max={max:.3f} MW, média={mean:.3f} MW"`

### Section 5 — Price Profile (BigQuery PLD — mandatory)

| ID | Prompt | Type |
|----|--------|------|
| P-15 | `Submercado CCEE [SE/S/NE/N] (padrão SE): ` | string, one of {SE,S,NE,N} |
| P-16 | `Ano para busca do PLD (padrão 2025): ` | int |

BigQuery is the only price data source. Prices are fetched during the price-load phase
after parameters are confirmed. If BigQuery fails for any reason (auth error, network
error, unexpected row count), the tool prints a descriptive error message and aborts;
there is no fallback.

After successful load, print:
`"Preços PLD carregados: BigQuery {submarket} {year} | min={min:.2f} BRL/MWh, max={max:.2f} BRL/MWh, média={mean:.2f} BRL/MWh"`

| ID | Label (PT-BR) | Unit | Default | Bounds | Param field |
|----|--------------|------|---------|--------|-------------|
| P-15 | `Submercado CCEE` | — | `SE` | one of {SE,S,NE,N} | `bq_submarket` |
| P-16 | `Ano para busca do PLD` | — | `2025` | [2021, 2040] | `bq_year` |

### Section 6 — BigQuery Authentication (shown only when BigQuery selected)

| ID | Prompt | Type |
|----|--------|------|
| P-20 | `Método de autenticação BigQuery [adc/service_account] (padrão adc): ` | string |
| P-21 | `Caminho do arquivo JSON da conta de serviço: ` | file path (shown only if P-20 = service_account) |
| P-22 | `Projeto de faturação GCP (padrão cver-solar): ` | string |

**Auth behaviour**:
- If P-20 = `adc` (default): use Application Default Credentials; no file path required.
- If P-20 = `service_account`: require P-21; validate that the path exists and is a
  readable JSON file before proceeding. If file not found: print error and re-prompt.
- Service account path is **never** logged, embedded in the HTML report, or included in
  the manifest SHA-256 hash. Only the auth method label is recorded.

### Post-Simulation — Heatmap Scenario Selection

| ID | Prompt |
|----|--------|
| P-17 | `Selecione o cenário para o heatmap de geração/despacho:` |

Display format:
```
Cenários disponíveis:
  [1] ILR=1.2 | BESS=25.0% | Duração=2.0h
  [2] ILR=1.3 | BESS=25.0% | Duração=2.0h
  ...
Digite o número do cenário (padrão 1): _
```

Validation: integer in [1, n_scenarios]; invalid input → re-prompt with list.

---

## 3. Validation Error Format

All validation errors follow this exact format:

```
ERRO: Parâmetro '{label}': valor {value} {unit} fora do intervalo [{min}, {max}] {unit}.
```

For CSV validation errors:

```
ERRO: CSV '{path}': linha {row}: valor inválido '{value}' — esperado número ≥ 0.
ERRO: CSV '{path}': {n} linhas encontradas; esperado exatamente 8.760.
```

---

## 4. Confirmation Summary Format

After all parameters are accepted, display:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Parâmetros aceitos:
  ILR values:              1.2, 1.3, 1.4, 1.5
  BESS size ratios (%):    0, 5, 10, 15, 20, 25, 30, 40, 50, 75, 100
  Storage durations (h):   2.0
  Round-trip efficiency:   85.0 %
  Annual degradation:      2.0 %/ano
  BESS CAPEX:              250.0 USD/kWh  →  1.250,0 BRL/kWh (câmbio 5.0)
  Useful life:             15 anos
  Discount rate:           10.0 %/ano
  Preço de energia:          BigQuery PLD {submarket} {year} | média={mean:.2f} BRL/MWh
  Min SoC threshold:       80.0 %
  Min injection floor:     0.0 MW
  Solar profile:           synthetic (pvlib Ineichen, lat=-22.0, lon=-45.0)
  Price profile:           BigQuery PLD {submarket} {year}
  Scenarios to simulate:   44  (11 BESS sizes × 4 ILRs × 1 duration)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Proceed with simulation? [Y/n]: _
```

---

## 5. Contract Test Assertions (`tests/contract/test_cli_schema.py`)

The following behaviours MUST be verified by the contract test suite:

| Test ID | Assertion |
|---------|-----------|
| CT-01 | Pressing Enter at every prompt produces the exact default values listed above |
| CT-02 | Providing an out-of-bounds value triggers a `ERRO:` line and re-prompts |
| CT-03 | A non-numeric value at any float prompt triggers `ERRO:` and re-prompts |
| CT-04 | A solar CSV with 8,761 rows is rejected with the exact row-count error message |
| CT-05 | A solar CSV with a negative value on row k is rejected with row k cited |
| CT-06 | A solar CSV with a non-numeric value on row k is rejected with row k and value cited |
| CT-08 | Heatmap scenario selection with an invalid integer re-prompts with the available list |
| CT-09 | Heatmap selection with a valid integer proceeds without error |
| CT-10 | Confirmation summary shows CAPEX in both USD/kWh and converted BRL/kWh |
| CT-11 | Selecting `service_account` (P-20) without a valid JSON path re-prompts |
| CT-12 | Selecting `adc` (P-20) does not prompt for a file path |
| CT-13 | When BQ raises an auth error or network error, the tool prints a descriptive error and aborts (no fallback, non-zero exit) |
| CT-14 | When BQ returns a row count other than 8,760, the tool aborts citing the actual count and the expected count |
| CT-15 | Service account path is absent from the confirmation summary and manifest |
