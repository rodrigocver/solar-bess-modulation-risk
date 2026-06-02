# Quickstart: Otimizador de Redução de MUST

## Pré-requisitos

- Ambiente `.venv` com dependências instaladas (plotly etc.).
- Rodar testes sempre com `.venv/bin/python -m pytest tests/`.

## Uso via API Python

```python
from solar_bess_risk.config import SimulationParams
from solar_bess_risk.must_optimizer import optimize_must_reduction

params = SimulationParams(
    csv_path="solar/solar_baguacu_m2_600mw_id2.csv",
    mwac=600.0,                     # MUST inicial = potência do projeto
    tust_brl_per_kw_month=7.23,     # default documentado; informe o do projeto
)

result = optimize_must_reduction(solar, prices, scenario, params)

print(f"Cenário {result.scenario_label} ({result.duration_h}h)")
print(f"Redução ótima: {result.optimal_reduction_pct:.0%}")
print(f"MUST ótimo:    {result.optimal_must_mw:.1f} MW")
print(f"Benefício:     R$ {result.optimal_net_benefit_brl_per_yr:,.0f}/ano")

# Curva de sensibilidade
for p in result.sweep:
    print(f"{p.reduction_pct:>5.0%}  R$ {p.net_benefit_brl_per_yr:,.0f}/ano")
```

## Uso via CLI

A coleta de `csv`/`mwac` é interativa (prompts). As flags do otimizador são
opcionais e habilitam o fluxo opt-in:

```bash
.venv/bin/python -m solar_bess_risk \
    --must-sweep \
    --tust 7.23 \
    --must-sweep-max 0.40 \
    --must-sweep-step 0.02
```

Sem `--must-sweep`, o comportamento atual é preservado. `--tust`,
`--must-sweep-max` e `--must-sweep-step` sobrescrevem os defaults documentados.

## Como validar (mapeado aos Success Criteria)

1. **SC-001/002** — Para cada cenário sai exatamente um ótimo, e ele é o máximo da
   curva: `max(p.net_benefit for p in result.sweep) == result.optimal_net_benefit`.
2. **SC-003** — Com `tust=0`, `optimal_reduction_pct == 0`.
3. **SC-004** — A valoração usa PLD horário (reconciliação hora-a-hora no teste,
   nenhum PLD médio).
4. **SC-005** — Reconciliação de energia: `Σ gen_bess` fecha com injeção + perdas +
   curtailment dentro de tolerância (sem dupla contagem ONS/clipping/MUST).
5. **SC-006** — Sem TUST informado, `result.tust_is_default == True` e o relatório
   exibe R$ 7,23/kW·mês.

## Comando de teste

```bash
.venv/bin/python -m pytest tests/unit/test_must_optimizer.py \
                           tests/unit/test_must_cap_dispatch.py -v
```
