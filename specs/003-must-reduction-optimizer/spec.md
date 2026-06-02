# Feature Specification: Otimizador de Redução de MUST

**Feature Branch**: `003-must-reduction-optimizer`

**Created**: 2026-06-02

**Status**: Draft

**Input**: User description: "Otimizador de redução de MUST: encontra a redução de MUST contratado ótima por cenário de BESS, equilibrando economia de TUST contra energia perdida por curtailment, valorada via net-balance hora-a-hora"

## Contexto de Negócio

O MUST (Montante de Uso do Sistema de Transmissão) é a capacidade de injeção
contratada junto à transmissora, paga recorrentemente via TUST (Tarifa de Uso do
Sistema de Transmissão). Um projeto solar+BESS pode contratar um MUST inferior à
sua potência de pico: ao fazê-lo, economiza TUST proporcional à capacidade
abdicada, mas cria um teto de injeção. Toda energia que excede esse teto e que a
BESS não consegue absorver torna-se curtailment (perda).

Como o pico de geração solar ocorre ao meio-dia — janela de PLD historicamente
baixo — e a BESS já desloca parte dessa energia para os horários de PLD alto,
existe uma sinergia: a redução de MUST corta exatamente o topo do perfil de
injeção que a BESS busca absorver. O nível ótimo de MUST depende, portanto, do
tamanho da BESS de cada cenário.

Esta feature adiciona um otimizador que, para cada cenário de duração de BESS já
modelado, determina a redução percentual de MUST que maximiza o benefício
líquido anual: economia de TUST menos a variação no saldo líquido de energia.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Encontrar a redução de MUST ótima por cenário (Priority: P1)

Como analista de viabilidade, executo a análise e recebo, para cada cenário de
duração de BESS, a redução percentual de MUST que maximiza o benefício líquido
anual (economia de TUST menos perda de energia), de forma que eu possa
recomendar à diretoria quanto de capacidade de transmissão contratar.

**Why this priority**: É o núcleo da feature. Sem este resultado, nada do resto
tem valor. Entrega a decisão econômica central que motivou o pedido.

**Independent Test**: Pode ser testado isoladamente fornecendo um perfil de
injeção, uma curva de PLD, parâmetros de BESS e um valor de TUST, e verificando
que o otimizador retorna a redução percentual que maximiza o benefício líquido,
consistente com uma varredura manual.

**Acceptance Scenarios**:

1. **Given** um cenário com BESS dimensionada e TUST definido, **When** o
   otimizador é executado, **Then** ele retorna a redução de MUST (%) que
   maximiza `economia_TUST + variação_do_saldo_líquido` e o MUST resultante em MW.
2. **Given** um TUST muito baixo relativo ao valor da energia, **When** o
   otimizador é executado, **Then** a redução ótima recomendada é 0% (não vale a
   pena abdicar de capacidade).
3. **Given** um TUST alto e um excedente de injeção concentrado em horas de PLD
   baixo, **When** o otimizador é executado, **Then** a redução ótima é positiva
   e o MUST recomendado fica próximo do pico de injeção pós-BESS.

---

### User Story 2 - Visualizar a curva de sensibilidade da decisão (Priority: P2)

Como analista, visualizo a curva de benefício líquido em função da redução de
MUST (%) para cada cenário, de modo a entender quão sensível é a decisão e onde
está o platô em torno do ótimo.

**Why this priority**: O valor ótimo isolado pode enganar; a curva mostra
robustez e ajuda a comunicar a recomendação. Depende da US1 já existir.

**Independent Test**: Verificar que, para um cenário, o relatório contém os pares
(redução %, benefício líquido anual) cobrindo a faixa varrida e que o ponto de
máximo coincide com o ótimo reportado na US1.

**Acceptance Scenarios**:

1. **Given** a análise concluída, **When** abro o relatório, **Then** vejo a
   curva benefício × redução de MUST por cenário com o ponto ótimo destacado.
2. **Given** dois cenários de durações diferentes, **When** comparo as curvas,
   **Then** o cenário com BESS maior admite redução ótima maior (pico pós-BESS
   menor).

---

### User Story 3 - Informar o TUST específico do projeto (Priority: P3)

Como analista, informo o TUSTg específico do projeto (com a unidade R$/kW·mês),
e, na ausência de um valor informado, o sistema usa um padrão documentado, de
modo que a análise reflita o custo de transmissão real sem fabricar premissas.

**Why this priority**: Garante fidelidade econômica e conformidade com a
constituição (sem premissas fabricadas), mas a mecânica do otimizador funciona
mesmo com o valor padrão.

**Independent Test**: Verificar que, fornecido um TUST, a economia anual usa esse
valor; e que, sem fornecer, o sistema aplica e reporta explicitamente o padrão.

**Acceptance Scenarios**:

1. **Given** um TUST informado, **When** a análise roda, **Then** a economia de
   TUST anual é `TUST × 12 × ΔMUST_MW × 1000`.
2. **Given** nenhum TUST informado, **When** a análise roda, **Then** o sistema
   usa R$ 7,23/kW·mês e registra essa premissa no relatório.

---

### Edge Cases

- **Redução ótima = 0%**: quando a economia de TUST nunca supera a perda de
  energia, o sistema deve recomendar manter o MUST integral.
- **Redução cortando energia de PLD alto**: como a busca é livre (sem piso
  imposto), reduções que cortam o pico despachado pela BESS produzem variação de
  saldo líquido fortemente negativa; o critério de benefício líquido deve
  rejeitá-las naturalmente.
- **Cenário sem BESS**: o otimizador deve operar com a injeção pós-curtailment
  ONS apenas, sem deslocamento de energia.
- **Dupla contagem de curtailment**: o teto de MUST aplica-se sobre a injeção já
  líquida do curtailment ONS e do clipping; o excedente de MUST não pode ser
  contabilizado em duplicidade com essas fontes.
- **MUST maior ou igual ao pico de injeção**: redução 0% — nenhum excedente é
  cortado; benefício líquido = 0.
- **PLD ou perfil de injeção ausentes para o período**: a análise deve falhar de
  forma explícita, sem assumir valores.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: O sistema MUST aplicar, no motor de despacho, um teto de injeção
  igual ao MUST avaliado, transformando todo excedente (`max(0, injeção_desejada
  − MUST)`) em curtailment, sobre a injeção já líquida do curtailment ONS e do
  clipping de inversores.
- **FR-002**: O sistema MUST permitir que a BESS absorva parte do excedente de
  MUST, respeitando os limites de energia e potência já modelados da BESS, sem
  contabilizar a mesma energia em duplicidade com as demais fontes de curtailment.
- **FR-003**: O sistema MUST capar fisicamente a injeção no MUST (curtailment do
  excedente), sem aplicar penalidade de ultrapassagem.
- **FR-004**: O sistema MUST valorar a energia perdida via saldo líquido (net
  balance) hora-a-hora, usando o PLD de cada hora, sem achatar o PLD em uma média.
- **FR-005**: O sistema MUST calcular a economia de TUST anual como
  `TUST[R$/kW·mês] × 12 × ΔMUST_MW × 1000`, onde `ΔMUST_MW` é a capacidade de MUST
  abdicada (parcela reduzida, não o MUST remanescente).
- **FR-006**: O sistema MUST tratar o MUST como um único valor anual (sem
  distinção de posto tarifário ou sazonal).
- **FR-013**: O sistema MUST adotar como MUST inicial (linha de base) a potência
  instalada do projeto em MW, calculando `MUST_avaliado = potência_projeto ×
  (1 − %_redução)` e `ΔMUST_MW = potência_projeto × %_redução`.
- **FR-007**: O sistema MUST, para cada cenário de duração de BESS, varrer uma
  faixa de reduções percentuais de MUST e calcular, para cada ponto, o benefício
  líquido anual = `economia_TUST + variação_do_saldo_líquido` (a variação é
  relativa ao caso sem redução de MUST).
- **FR-008**: O sistema MUST reportar, por cenário, a redução percentual ótima, o
  MUST ótimo em MW e o benefício líquido anual no ótimo.
- **FR-009**: O sistema MUST permitir a busca livre da redução (sem piso imposto),
  confiando no critério de benefício líquido para rejeitar cortes destrutivos de
  energia de PLD alto.
- **FR-010**: O sistema MUST aceitar um TUSTg específico do projeto na unidade
  R$/kW·mês e, na ausência de valor informado, usar R$ 7,23/kW·mês, registrando
  explicitamente a premissa adotada no relatório.
- **FR-011**: O sistema MUST expor, por cenário, os pares (redução %, benefício
  líquido anual) que compõem a curva de sensibilidade, com o ponto ótimo
  identificável.
- **FR-012**: O sistema MUST falhar de forma explícita quando faltarem dados
  obrigatórios (perfil de injeção ou PLD do período), sem fabricar valores.

### Key Entities *(include if feature involves data)*

- **Parâmetro de TUST**: valor do TUSTg do projeto e sua unidade (R$/kW·mês);
  base para o cálculo da economia recorrente anual.
- **Avaliação de redução de MUST**: um ponto da varredura, contendo a redução
  percentual, o MUST resultante em MW, a economia de TUST anual, a variação de
  saldo líquido e o benefício líquido anual.
- **Resultado de otimização por cenário**: para cada duração de BESS, a redução
  ótima, o MUST ótimo em MW, o benefício líquido no ótimo e a curva de
  sensibilidade completa.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Para cada cenário de BESS analisado, o sistema reporta exatamente
  uma redução de MUST ótima com o respectivo MUST em MW e o benefício líquido
  anual em R$.
- **SC-002**: O benefício líquido reportado no ótimo é maior ou igual ao de
  qualquer outro ponto da curva de sensibilidade do mesmo cenário (o ótimo é, de
  fato, o máximo da varredura).
- **SC-003**: Em um cenário onde a economia de TUST nunca supera a perda de
  energia, a redução ótima recomendada é 0%.
- **SC-004**: A variação de saldo líquido usada na decisão é calculada a partir
  do PLD horário (nunca de um PLD médio achatado), verificável por reconciliação
  hora-a-hora.
- **SC-005**: A soma de energia injetada, curtailment ONS, clipping e excedente
  de MUST reconcilia com a geração total do cenário (sem dupla contagem),
  validável dentro de uma tolerância numérica.
- **SC-006**: Quando nenhum TUST é informado, o relatório exibe explicitamente o
  valor padrão de R$ 7,23/kW·mês utilizado.

## Assumptions

- O MUST inicial (linha de base, antes de qualquer redução) é sempre igual à
  potência instalada do projeto em MW. A redução percentual é aplicada sobre essa
  base: `MUST_avaliado = potência_projeto × (1 − %_redução)` e
  `ΔMUST_MW = potência_projeto × %_redução`.
- O TUSTg é específico por projeto e deve ser solicitado ao usuário; na ausência,
  adota-se R$ 7,23/kW·mês como padrão documentado.
- A injeção é fisicamente capada no MUST (curtailment do excedente), sem modelar
  penalidade de ultrapassagem.
- A energia perdida é valorada via saldo líquido com PLD horário, reaproveitando
  o motor de despacho e precificação já existente.
- O MUST é um valor único anual, sem distinção de posto tarifário ou sazonal.
- A busca da redução ótima é livre (sem piso); o critério de benefício líquido
  protege naturalmente a energia de PLD alto despachada pela BESS.
- Os cenários de duração de BESS, perfis de geração (com e sem BESS), curva de
  PLD e a mecânica de curtailment (ONS + clipping) já existentes são reutilizados.
- A análise opera no horizonte anual de 8760 horas já adotado pelo modelo.
