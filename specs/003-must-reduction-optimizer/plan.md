# Implementation Plan: Otimizador de Redução de MUST

**Branch**: `003-must-reduction-optimizer` | **Date**: 2026-06-02 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-must-reduction-optimizer/spec.md`

## Summary

Adicionar um otimizador que, para cada cenário de duração de BESS já modelado,
determina a redução percentual de MUST que maximiza o benefício líquido anual
(`economia_TUST + variação_do_saldo_líquido`). Tecnicamente: introduzir um teto de
injeção `must_mw` no motor de despacho price-aware existente
(`_simulate_price_aware_dispatch`), de modo que todo excedente `max(0, injeção −
must_mw)` vire energia curtailável disponível para a BESS (mesma fila do ONS +
clipping, sem dupla contagem); reaproveitar o saldo líquido hora-a-hora de
`economics.py` para precificar a perda; varrer uma grade de `%_redução` por
cenário e reportar o ótimo + a curva de sensibilidade. MUST inicial = potência do
projeto (`mwac`); economia de TUST = `TUST[R$/kW·mês] × 12 × ΔMUST_MW × 1000`.

## Technical Context

**Language/Version**: Python 3.11

**Primary Dependencies**: numpy, pandas, plotly>=5.20 (charts da curva de
sensibilidade). Sem novas dependências externas.

**Storage**: Saída em diretório por run (manifesto JSON existente). Sem banco.

**Testing**: pytest 7.2.1, executado via `.venv/bin/python -m pytest tests/`
(o python do sistema não tem plotly).

**Target Platform**: Linux (CLI / biblioteca Python).

**Project Type**: Single project (biblioteca + CLI) — pacote `solar_bess_risk/`.

**Performance Goals**: A varredura roda `N_pontos × N_cenários` despachos de 8760h.
Com grade de ~21 pontos (0–40%, passo 2%) × 2 durações = ~42 despachos por run;
deve concluir em segundos. Sem meta de latência rígida.

**Constraints**: Reaproveitar o motor de despacho e a economia existentes sem
quebrar os 104 testes atuais. Nenhum valor fabricado (TUST configurável com
default documentado). Sem falhas silenciosas.

**Scale/Scope**: Horizonte anual de 8760h; 2 cenários de duração (2h, 4h);
grade de redução configurável (default 0–40%, passo 2%).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Verify compliance with all seven Core Principles and Domain Constraints from
`.specify/memory/constitution.md` (v1.1.0):

- [x] **I. Brazilian Sector Compliance** — O teto de MUST modela a restrição de
  injeção contratada (TUST/MUST, ANEEL/ONS). O excedente cortado é curtailment na
  definição ANEEL (redução involuntária da injeção no ponto de conexão). A
  premissa de "cap sem penalidade de ultrapassagem" é declarada explicitamente.
- [x] **II. No Data Fabrication** — TUSTg é parâmetro configurável (R$/kW·mês) com
  default documentado R$ 7,23 e bounds validados. A grade de varredura é
  parametrizável. Nenhum valor implícito.
- [x] **III. Test-First** — Testes unitários falhando serão escritos antes da
  implementação para: cap de injeção no despacho, fórmula de economia de TUST,
  reconciliação de energia (anti-dupla-contagem) e seleção do ótimo. Caso de
  referência manual para a economia de TUST e para um ótimo conhecido.
- [x] **IV. Reproducible Results** — A varredura é determinística (sem RNG novo).
  Parâmetros de MUST/TUST/grade entram no manifesto JSON e no hash SHA-256.
- [x] **V. Modular Python Architecture** — Novo módulo `must_optimizer.py`
  (< 400 linhas) com type hints (sufixo de unidade: `must_mw`, `tust_brl_per_kw_month`)
  e docstrings NumPy. O cap de injeção entra como parâmetro opcional do despacho,
  sem estado global. Constantes (default TUST, grade) em `config.py`.
- [x] **VI. Engineering-Quality Visualizations** — Curva benefício × redução de
  MUST com título, eixos rotulados (% e R$/ano), tooltip com valor+unidade, ponto
  ótimo destacado, colormap perceptualmente uniforme. Premissa de TUST exibida.
- [x] **VII. SI Units & Brazilian Sector Conventions** — Potência em MW, energia
  em MWh, moeda em BRL; TUST rotulado R$/kW·mês → anual via ×12×1000. Sufixos de
  unidade em nomes/anotações/colunas.
- [x] **Domain Constraints** — Séries horárias 8760 mantidas. Falhas explícitas
  (TUST fora de bounds, dados ausentes) levantam exceção estruturada. Resultados
  reportam a base de normalização. Sem sentinelas silenciosas.

**Resultado do gate**: PASS. Nenhuma violação — sem necessidade de Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/003-must-reduction-optimizer/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── must_optimizer_api.md   # Public function/CLI contracts
├── checklists/
│   └── requirements.md  # Spec quality checklist (já criado)
└── tasks.md             # Phase 2 output (/speckit-tasks — NÃO criado aqui)
```

### Source Code (repository root)

```text
solar_bess_risk/
├── config.py            # + DEFAULT_TUST_BRL_PER_KW_MONTH, MUST_SWEEP_*, bounds, params
├── simulation.py        # + must_mw cap opcional no despacho price-aware
├── must_optimizer.py    # NOVO — varredura, seleção do ótimo, MustOptimizationResult
├── economics.py         # reutilizado (saldo líquido hora-a-hora)
├── report_charts.py     # + gráfico da curva de sensibilidade
├── report_consultancy.py# + seção/coluna MUST ótimo (se aplicável ao relatório)
└── cli.py / __main__.py # + flags --tust e --must-sweep (opt-in)

tests/
├── unit/
│   ├── test_must_optimizer.py   # NOVO — economia TUST, seleção do ótimo, edge cases
│   └── test_must_cap_dispatch.py# NOVO — cap de injeção + reconciliação de energia
└── integration/
    └── test_full_run.py         # estende com run de otimização MUST (opt-in)
```

**Structure Decision**: Single project. A lógica de otimização vive em um novo
módulo coeso `must_optimizer.py`; o cap de injeção é uma extensão mínima e
retrocompatível do motor de despacho existente (parâmetro opcional `must_mw`,
default `None` = sem cap, preservando os 104 testes atuais).

## Complexity Tracking

> Não aplicável — Constitution Check passou sem violações.
