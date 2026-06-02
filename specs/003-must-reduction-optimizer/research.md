# Phase 0 Research: Otimizador de Redução de MUST

Todas as decisões de produto já foram travadas com o usuário (ver Assumptions na
spec). Este documento resolve as decisões **técnicas** de implementação.

## Decisão 1 — Onde aplicar o teto de MUST no motor de despacho

**Decision**: Aplicar o teto como uma fonte adicional de energia curtailável,
calculada antes do despacho, dentro de `_simulate_price_aware_dispatch`. Para cada
hora: `must_excess = max(0, gen_bess − must_mw)`. Essa energia entra na mesma fila
de curtailment que a BESS já consome (ONS + clipping).

**Rationale**: O motor já trata curtailment (ONS + clipping) como energia de custo
zero que a BESS pode absorver; o excedente de MUST tem a mesma natureza física
(energia que não pode ser injetada e que a BESS pode armazenar). Reaproveitar a
fila evita reescrever a lógica de despacho e mantém a economia de saldo líquido
válida sem alteração.

**Alternatives considered**:
- *Capar `grid_injection` pós-despacho*: rejeitado — criaria circularidade (a BESS
  precisa saber o excedente antes de planejar a carga) e quebraria a reconciliação
  de energia.
- *Penalidade de ultrapassagem em vez de cap*: rejeitado — usuário escolheu cap
  físico sem penalidade (FR-003).

## Decisão 2 — Evitar dupla contagem com ONS e clipping

**Decision**: A energia curtailável total por hora passa a ser
`ons_curt + max(clip, must_excess)` quando há cap de MUST, onde
`clip = max(0, gen_bess − gen_lim)` e `must_excess = max(0, gen_bess − must_mw)`.
Usa-se `max(clip, must_excess)` (não a soma) porque ambos descrevem o mesmo topo do
perfil de `gen_bess`: o que exceder o menor entre `gen_lim` e `must_mw` é o teto
efetivo. O excedente de MUST é, portanto, o corte adicional além do clipping quando
`must_mw < gen_lim`.

**Rationale**: `clip` e `must_excess` medem a mesma parcela superior de `gen_bess`
contra dois tetos distintos (capacidade do inversor vs. MUST). Somá-los contaria a
faixa sobreposta duas vezes. O teto efetivo de injeção é `min(gen_lim_capacity,
must_mw)`; a energia curtailável é `gen_bess` acima desse teto efetivo. Mantém-se
`ons_curt` aditivo pois é uma restrição externa independente sobre a injeção já
limitada.

**Alternatives considered**:
- *Somar clip + must_excess*: rejeitado — viola SC-005 (reconciliação de energia).
- *Aplicar must sobre `gen_lim` em vez de `gen_bess`*: rejeitado — a BESS opera com
  `gen_bess` (inversores liberados); o teto de MUST limita a injeção real, que parte
  de `gen_bess`.

**Reconciliação (SC-005)**: para todo cenário e MUST,
`Σ gen_bess = Σ grid_injection + Σ curtailment_lost + Σ (carga_absorvida_e_descarregada
ajustada por RTE) + perdas_RTE`, validável dentro de tolerância numérica nos testes.

## Decisão 3 — Baseline para a variação de saldo líquido

**Decision**: A variação de saldo líquido de cada ponto da varredura é medida
contra o **mesmo cenário sem cap de MUST** (`must_mw = mwac`, isto é, redução 0%),
não contra o caso sem BESS. `Δsaldo(%red) = net_balance_com(must) −
net_balance_com(must_baseline)`.

**Rationale**: O otimizador decide sobre o MUST mantendo o BESS fixo; o efeito da
BESS já está embutido em ambos os termos e se cancela. Isola o efeito puro da
redução de MUST. `net_balance_com` já é computado por `compute_scenario_economics`
com PLD horário (FR-004), sem achatamento.

**Alternatives considered**:
- *Baseline sem BESS*: rejeitado — misturaria o valor da BESS com o da redução de
  MUST, contaminando a decisão.

## Decisão 4 — Cálculo da economia de TUST

**Decision**: `economia_TUST_anual_brl = tust_brl_per_kw_month × 12 × ΔMUST_mw ×
1000`, com `ΔMUST_mw = mwac × pct_reducao` e `must_mw = mwac × (1 − pct_reducao)`.
MUST inicial = `mwac` (FR-013).

**Rationale**: Conversão de R$/kW·mês para R$/ano: ×12 (meses) × 1000 (kW por MW).
A economia incide sobre a capacidade abdicada `ΔMUST`, não sobre o MUST remanescente
(erro corrigido no raciocínio original).

**Alternatives considered**:
- *TUST × MUST remanescente*: rejeitado — é o custo que permanece, não a economia.

## Decisão 5 — Estratégia de busca do ótimo

**Decision**: Grid sweep determinístico sobre `pct_reducao ∈ {0, passo, 2·passo, …,
max}` (default 0–40%, passo 2%), avaliando `beneficio(%) = economia_TUST(%) +
Δsaldo(%)` em cada ponto; ótimo = argmax. Reporta também a curva completa.

**Rationale**: Robusto, auditável e barato (~21 pontos × 2 cenários). A curva
expõe o platô (US2) e é mais transparente para a diretoria que um otimizador
contínuo. Determinístico → reprodutível (Princípio IV). Busca livre, sem piso
(FR-009): o `Δsaldo` fortemente negativo ao cortar o pico despachado pela BESS
rejeita reduções destrutivas naturalmente.

**Alternatives considered**:
- *Otimizador contínuo (scipy.optimize)*: rejeitado — adiciona dependência, é menos
  auditável e a função pode ter platôs/degraus que confundem métodos de gradiente.

## Decisão 6 — Parâmetros e bounds (Princípio II)

**Decision**: Adicionar a `config.py`:
- `DEFAULT_TUST_BRL_PER_KW_MONTH: float = 7.23`
- `MUST_SWEEP_MAX_PCT: float = 0.40`, `MUST_SWEEP_STEP_PCT: float = 0.02`
- bounds: `tust_brl_per_kw_month: (0.0, 1000.0)`, `must_reduction_pct: (0.0, 1.0)`
Adicionar a `SimulationParams`: `tust_brl_per_kw_month`, `must_sweep_max_pct`,
`must_sweep_step_pct` (todos com default documentado).

**Rationale**: Nenhum valor fabricado; tudo configurável e validado em bounds. O
default de TUST aparece explicitamente no relatório quando usado (SC-006).

## Resumo das premissas de produto (já travadas, ver spec)

| Tema | Decisão |
|---|---|
| MUST inicial | = potência do projeto (`mwac`) |
| TUST | por projeto, default R$ 7,23/kW·mês |
| Restrição | cap físico no MUST, sem penalidade |
| Valoração da perda | saldo líquido, PLD horário |
| Granularidade | MUST único anual |
| Busca | livre, sem piso |
