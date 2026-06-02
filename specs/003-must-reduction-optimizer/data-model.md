# Phase 1 Data Model: Otimizador de Redução de MUST

## Entidades

### MustEvaluationPoint

Um ponto da varredura de redução de MUST para um cenário.

| Campo | Tipo | Unidade | Descrição | Validação |
|---|---|---|---|---|
| `reduction_pct` | float | fração (0–1) | Redução de MUST avaliada | 0 ≤ x ≤ `must_sweep_max_pct` |
| `must_mw` | float | MW | MUST resultante = `mwac × (1 − reduction_pct)` | > 0 |
| `delta_must_mw` | float | MW | Capacidade abdicada = `mwac × reduction_pct` | ≥ 0 |
| `tust_savings_brl_per_yr` | float | BRL/ano | `tust × 12 × delta_must_mw × 1000` | ≥ 0 |
| `net_balance_com_brl` | float | BRL/ano | Saldo líquido com BESS sob este MUST | — |
| `net_balance_delta_vs_baseline_brl` | float | BRL/ano | `net_balance_com − net_balance_com(reducao 0%)` | ≤ 0 esperado |
| `net_benefit_brl_per_yr` | float | BRL/ano | `tust_savings + net_balance_delta_vs_baseline` | — |
| `curtailment_lost_mwh` | float | MWh/ano | Energia perdida sob este MUST (auditoria SC-005) | ≥ 0 |

### MustOptimizationResult

Resultado da otimização para um cenário de duração de BESS.

| Campo | Tipo | Unidade | Descrição |
|---|---|---|---|
| `scenario_label` | str | — | Rótulo do cenário ("A", "B", …) |
| `duration_h` | int | h | Duração da BESS |
| `mwac` | float | MW | Potência do projeto = MUST inicial |
| `tust_brl_per_kw_month` | float | R$/kW·mês | TUST usado |
| `tust_is_default` | bool | — | True se o default (7,23) foi aplicado (SC-006) |
| `optimal_reduction_pct` | float | fração (0–1) | Redução ótima |
| `optimal_must_mw` | float | MW | MUST no ótimo |
| `optimal_net_benefit_brl_per_yr` | float | BRL/ano | Benefício líquido no ótimo |
| `sweep` | list[MustEvaluationPoint] | — | Curva de sensibilidade completa |

**Regras de validação / invariantes**:
- `optimal_net_benefit ≥ net_benefit` de qualquer ponto do `sweep` (SC-002).
- Ponto de `reduction_pct == 0` sempre presente, com `net_benefit == 0`
  (baseline: economia 0, Δsaldo 0).
- Se nenhum ponto tem `net_benefit > 0`, `optimal_reduction_pct == 0` (SC-003).
- `tust` fora de bounds → `ValueError` estruturado (Domain Constraints).

## Extensões em entidades existentes

### `SimulationParams` (config.py) — campos adicionados

| Campo | Tipo | Default | Unidade | Bounds |
|---|---|---|---|---|
| `tust_brl_per_kw_month` | float | `DEFAULT_TUST_BRL_PER_KW_MONTH` (7.23) | R$/kW·mês | (0.0, 1000.0) |
| `must_sweep_max_pct` | float | `MUST_SWEEP_MAX_PCT` (0.40) | fração | (0.0, 1.0) |
| `must_sweep_step_pct` | float | `MUST_SWEEP_STEP_PCT` (0.02) | fração | (0.0, 1.0) |

### `_simulate_price_aware_dispatch` / `simulate_scenario` (simulation.py)

Novo parâmetro opcional `must_mw: float | None = None`.
- `None` → comportamento atual inalterado (preserva 104 testes).
- valor → energia curtailável por hora vira `ons_curt + max(clip, max(0, gen_bess − must_mw))`.

## Fluxo de dados

```text
mwac, tust, grade ──┐
                    ▼
   para cada pct em sweep:
     must_mw = mwac × (1 − pct)
     dispatch = simulate_scenario(..., must_mw=must_mw)
     net_com  = compute_scenario_economics(...).net_balance_com_bess_brl
     ponto = MustEvaluationPoint(
                tust_savings = tust×12×(mwac×pct)×1000,
                Δsaldo       = net_com − net_com_baseline,
                net_benefit  = tust_savings + Δsaldo)
                    ▼
   ótimo = argmax(net_benefit) ──► MustOptimizationResult (+ curva)
```
