# Tasks: Otimizador de Redução de MUST

**Input**: Design documents from `/specs/003-must-reduction-optimizer/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUÍDOS — TDD é obrigatório pela constituição (Princípio III). Testes
falhando são escritos antes da implementação para toda lógica de risco, despacho e
fórmulas econômicas.

**Organization**: Tarefas agrupadas por user story para entrega incremental e
testável de forma independente.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Pode rodar em paralelo (arquivos diferentes, sem dependências)
- **[Story]**: User story (US1, US2, US3)
- Caminhos de arquivo exatos nas descrições
- Comando de teste: `.venv/bin/python -m pytest tests/` (o python do sistema não tem plotly)

## Path Conventions

Single project — pacote `solar_bess_risk/` e testes em `tests/` na raiz do repo.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuração e constantes compartilhadas

- [ ] T001 Adicionar constantes em [solar_bess_risk/config.py](../../solar_bess_risk/config.py): `DEFAULT_TUST_BRL_PER_KW_MONTH = 7.23`, `MUST_SWEEP_MAX_PCT = 0.40`, `MUST_SWEEP_STEP_PCT = 0.02`, com comentários de unidade inline (R$/kW·mês, fração). Sem magic numbers.
- [ ] T002 Adicionar bounds em `PARAM_BOUNDS` de [solar_bess_risk/config.py](../../solar_bess_risk/config.py): `tust_brl_per_kw_month: (0.0, 1000.0)`, `must_reduction_pct: (0.0, 1.0)`, `must_sweep_step_pct: (1e-6, 1.0)`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Infraestrutura central que TODAS as user stories dependem

**⚠️ CRITICAL**: Nenhuma user story pode começar até esta fase concluir

- [ ] T003 Estender `SimulationParams` em [solar_bess_risk/config.py](../../solar_bess_risk/config.py) com campos `tust_brl_per_kw_month: float = DEFAULT_TUST_BRL_PER_KW_MONTH`, `must_sweep_max_pct: float = MUST_SWEEP_MAX_PCT`, `must_sweep_step_pct: float = MUST_SWEEP_STEP_PCT`, com docstrings (nome, tipo, unidade) e validação de bounds no ponto de construção.
- [ ] T004 [P] Escrever teste FALHANDO de validação de params em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): `tust` fora de bounds → `ValueError` estruturado; defaults aplicados quando ausentes.

**Checkpoint**: Configuração pronta — user stories podem começar

---

## Phase 3: User Story 1 - Encontrar a redução de MUST ótima por cenário (Priority: P1) 🎯 MVP

**Goal**: Para cada cenário de BESS, retornar a redução de MUST (%) que maximiza
`economia_TUST + Δsaldo_líquido`, com o MUST ótimo em MW.

**Independent Test**: Fornecer perfil, PLD, params e cenário; verificar que o
otimizador retorna a redução que maximiza o benefício líquido, consistente com
varredura manual; reconciliação de energia fecha (sem dupla contagem).

### Tests for User Story 1 (escrever PRIMEIRO, devem FALHAR) ⚠️

- [ ] T005 [P] [US1] Teste de cap de injeção no despacho em [tests/unit/test_must_cap_dispatch.py](../../tests/unit/test_must_cap_dispatch.py): com `must_mw=None`, resultado idêntico ao atual (retrocompatível); com `must_mw` finito, `grid_injection <= must_mw + tol` em toda hora.
- [ ] T006 [P] [US1] Teste de reconciliação de energia (anti-dupla-contagem, SC-005) em [tests/unit/test_must_cap_dispatch.py](../../tests/unit/test_must_cap_dispatch.py): curtailable = `ons + max(clip, must_excess)`; `Σ gen_bess` fecha com injeção + curtailment_lost + carga/descarga (ajustada por RTE) dentro de tolerância.
- [ ] T007 [P] [US1] Teste da fórmula de economia de TUST (caso de referência manual) em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): `tust_annual_savings_brl(tust=7.23, delta_must_mw=60)` == `7.23 × 12 × 60 × 1000`.
- [ ] T008 [P] [US1] Teste de seleção do ótimo (SC-001/SC-002) em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): exatamente um ótimo por cenário; `optimal_net_benefit == max(p.net_benefit for p in sweep)`; ponto `reduction_pct==0` presente com `net_benefit==0`.
- [ ] T009 [P] [US1] Teste de edge case TUST baixo (SC-003) em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): com `tust=0`, `optimal_reduction_pct == 0`.

### Implementation for User Story 1

- [ ] T010 [US1] Adicionar parâmetro opcional `must_mw: float | None = None` a `_simulate_price_aware_dispatch` e `simulate_scenario` em [solar_bess_risk/simulation.py](../../solar_bess_risk/simulation.py); quando finito, `must_excess = max(0, gen_bess − must_mw)` e `curtailment_arr_input = ons_curt + np.maximum(clip_arr, must_excess)`. Default `None` preserva comportamento atual. Type hints + docstring atualizados. (Faz T005, T006 passarem.)
- [ ] T011 [P] [US1] Criar [solar_bess_risk/must_optimizer.py](../../solar_bess_risk/must_optimizer.py) com dataclasses `MustEvaluationPoint` e `MustOptimizationResult` (campos e unidades per data-model.md), type hints e docstrings NumPy.
- [ ] T012 [US1] Implementar `tust_annual_savings_brl(*, tust_brl_per_kw_month, delta_must_mw) -> float` em [solar_bess_risk/must_optimizer.py](../../solar_bess_risk/must_optimizer.py). (Faz T007 passar.)
- [ ] T013 [US1] Implementar `optimize_must_reduction(...) -> MustOptimizationResult` em [solar_bess_risk/must_optimizer.py](../../solar_bess_risk/must_optimizer.py): gerar a grade `0..max passo step`; para cada `pct`, `must_mw = mwac × (1 − pct)`, rodar `simulate_scenario(..., must_mw=must_mw)`, obter `net_balance_com` via `compute_scenario_economics`, montar `MustEvaluationPoint` com `Δsaldo` vs baseline (pct=0) e `net_benefit`; argmax → ótimo. (Faz T008, T009 passarem.) (depende de T010, T011, T012)
- [ ] T014 [US1] Adicionar guardas de falha explícita em [solar_bess_risk/must_optimizer.py](../../solar_bess_risk/must_optimizer.py): PLD/perfil ausentes ou grade inválida → `ValueError` estruturado (FR-012, Domain Constraints). (Faz T004 passar.)

**Checkpoint**: US1 funcional e testável — o núcleo da feature entrega a decisão.

---

## Phase 4: User Story 2 - Visualizar a curva de sensibilidade (Priority: P2)

**Goal**: Expor e plotar a curva benefício × redução de MUST por cenário, com o
ponto ótimo destacado.

**Independent Test**: O resultado contém os pares (redução %, benefício líquido) e
o ponto de máximo coincide com o ótimo da US1; cenário com BESS maior admite
redução ótima maior.

### Tests for User Story 2 (escrever PRIMEIRO, devem FALHAR) ⚠️

- [ ] T015 [P] [US2] Teste da curva de sensibilidade em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): `result.sweep` cobre a faixa varrida com passo correto; ponto de máximo == ótimo reportado.
- [ ] T016 [P] [US2] Teste de monotonicidade de sinergia (SC, US2) em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): dado dois cenários com BESS maior/menor sob o mesmo perfil/PLD, o de BESS maior tem `optimal_reduction_pct >=` o de BESS menor.

### Implementation for User Story 2

- [ ] T017 [US2] Adicionar função de gráfico `must_sensitivity_chart(result)` em [solar_bess_risk/report_charts.py](../../solar_bess_risk/report_charts.py): plotly com título, eixos rotulados (Redução de MUST [%], Benefício líquido [R$/ano]), tooltip valor+unidade, ponto ótimo destacado, colormap perceptualmente uniforme (Princípio VI). (Faz T015 passar.)

**Checkpoint**: US1 + US2 funcionais; a decisão é visualizável e robusta.

---

## Phase 5: User Story 3 - Informar o TUST específico do projeto (Priority: P3)

**Goal**: Aceitar TUSTg do projeto (R$/kW·mês); na ausência, usar default
documentado e registrá-lo explicitamente.

**Independent Test**: Com TUST informado, a economia usa esse valor; sem informar,
aplica e reporta R$ 7,23/kW·mês.

### Tests for User Story 3 (escrever PRIMEIRO, devem FALHAR) ⚠️

- [ ] T018 [P] [US3] Teste de flag de default (SC-006) em [tests/unit/test_must_optimizer.py](../../tests/unit/test_must_optimizer.py): sem TUST → `result.tust_is_default == True` e `result.tust_brl_per_kw_month == 7.23`; com TUST → flag False e valor propagado à economia.

### Implementation for User Story 3

- [ ] T019 [US3] Popular `tust_is_default` e `tust_brl_per_kw_month` em `MustOptimizationResult` dentro de `optimize_must_reduction` em [solar_bess_risk/must_optimizer.py](../../solar_bess_risk/must_optimizer.py), comparando o valor recebido ao default. (Faz T018 passar.)
- [ ] T020 [US3] Adicionar flags de CLI `--tust`, `--must-sweep`, `--must-sweep-max`, `--must-sweep-step` em [solar_bess_risk/cli.py](../../solar_bess_risk/cli.py) e fluxo opt-in em [solar_bess_risk/__main__.py](../../solar_bess_risk/__main__.py); sem `--must-sweep`, comportamento atual inalterado.
- [ ] T021 [US3] Exibir no relatório a tabela do MUST ótimo por cenário e a premissa de TUST (incl. uso do default) em [solar_bess_risk/report_consultancy.py](../../solar_bess_risk/report_consultancy.py), com "Model Assumptions & Limitations" referenciando a premissa de cap sem penalidade (Princípio VI).

**Checkpoint**: Todas as user stories independentemente funcionais.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integração, manifesto e validação final

- [ ] T022 [P] Incluir `tust_brl_per_kw_month`, `must_sweep_max_pct`, `must_sweep_step_pct` no manifesto JSON e no hash SHA-256 em [solar_bess_risk/manifest.py](../../solar_bess_risk/manifest.py) (Princípio IV — reprodutibilidade).
- [ ] T023 [P] Teste de integração opt-in do run com `--must-sweep` em [tests/integration/test_full_run.py](../../tests/integration/test_full_run.py): run completo produz `MustOptimizationResult` por cenário sem quebrar o fluxo existente.
- [ ] T024 Rodar a suíte completa via `.venv/bin/python -m pytest tests/` e confirmar 104 testes existentes + novos todos passando (retrocompatibilidade).
- [ ] T025 Validar [quickstart.md](./quickstart.md): executar os exemplos de API/CLI e conferir os 6 Success Criteria (SC-001..SC-006).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: sem dependências — começa imediatamente.
- **Foundational (Phase 2)**: depende do Setup — BLOQUEIA todas as user stories.
- **User Stories (Phase 3+)**: dependem da Phase 2.
  - US1 (P1) é o MVP e fornece o motor (`optimize_must_reduction`) que US2 e US3 consomem.
  - US2 e US3 dependem de US1 (consomem `MustOptimizationResult`).
- **Polish (Phase 6)**: depende das user stories desejadas concluídas.

### User Story Dependencies

- **US1 (P1)**: após Phase 2. Independente — entrega o resultado de otimização.
- **US2 (P2)**: após US1 (plota o `sweep` de `MustOptimizationResult`).
- **US3 (P3)**: após US1 (anota TUST no resultado + CLI/relatório).

### Within Each User Story

- Testes escritos e FALHANDO antes da implementação (Princípio III).
- Dataclasses (models) antes das funções que as usam.
- `must_mw` no despacho (T010) antes do otimizador (T013).
- Núcleo antes da integração (CLI/relatório).

### Parallel Opportunities

- T004 ∥ (após T003).
- Testes US1 T005, T006, T007, T008, T009 — todos [P], arquivos/casos independentes.
- T011 [P] (módulo novo) em paralelo ao ajuste do despacho T010.
- Testes US2 T015, T016 [P]; teste US3 T018 [P].
- Polish T022, T023 [P].

---

## Parallel Example: User Story 1

```text
# Após Phase 2, escrever os testes falhando em paralelo:
T005  test_must_cap_dispatch.py  (cap de injeção)
T006  test_must_cap_dispatch.py  (reconciliação de energia)
T007  test_must_optimizer.py     (economia TUST — referência manual)
T008  test_must_optimizer.py     (seleção do ótimo)
T009  test_must_optimizer.py     (edge case TUST baixo)

# Depois implementar; T010 e T011 podem correr em paralelo (arquivos distintos),
# T012→T013→T014 em sequência (mesmo módulo / dependências).
```

## Implementation Strategy

- **MVP = US1 (Phase 1+2+3)**: entrega a redução de MUST ótima por cenário com
  reconciliação de energia validada. Já é demonstrável à diretoria.
- **Incremento 2 = US2**: curva de sensibilidade (robustez visual).
- **Incremento 3 = US3**: TUST por projeto + CLI + relatório integrado.
- Cada incremento mantém os 104 testes existentes verdes (retrocompatibilidade via
  `must_mw=None` default).
