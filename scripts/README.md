# scripts/

Scripts auxiliares, separados por **quando são executados**.

## `pipeline/` — rodam automaticamente no `uv run solar_bess_risk`

Importados/chamados pelo pipeline principal (`solar_bess_risk/__main__.py`). **Não** mova
sem atualizar o `sys.path` correspondente em `__main__.py`.

| Script | Papel | Base de preço |
|---|---|---|
| `calc_modulacao_contrato_ppa.py` | Modulação do contrato PPA flat (P90 do ano 20, 2030–2049), sem e com BESS. Gera `modulacao_contrato_ppa_*_flat_anual.html` + `.csv` na pasta do run. | **API Aurora EOS ao vivo** (submercado default SE, confirmado por prompt; fallback CSV offline só p/ SE/central). |

## `standalone/` — análises avulsas, rodadas à mão (NÃO no `uv run`)

Ferramentas one-off. Cada uma tem `main()` e roda direto (`python scripts/standalone/<x>.py`).
Não são tocadas pelo pipeline. Várias ainda leem **CSVs de preço congelados** (snapshots) e/ou
fontes que **não estão na Aurora** (ex.: PSR 2025, preços históricos 2025/2026) — por isso
permanecem desacopladas da API ao vivo de propósito.

| Script | O que faz | Base de preço | Saída |
|---|---|---|---|
| `aurora_download.py` | CLI p/ baixar dados da API Aurora (cenários, system/technology). | API Aurora ao vivo | CSV ad-hoc |
| `calc_modulacao_contrato.py` | Modulação de contrato flat (sem BESS), ponderada pela geração, 30 anos. | CSV congelado `brazil_q2_26_central` (região `bra`) | `output/modulacao_contrato/*_{anual,mensal}_*.csv` |
| `calc_modulacao_contrato_bess.py` | Grade BESS (15/20/25%) × curtailment (0/10/20%), contrato flat. | CSV congelado `brazil_q2_26_central` | `output/modulacao_contrato/*_bess_*.{csv,html}` |
| `calc_modulacao_alvo_bess.py` | Alvos de modulação (35/50/75 R$/MWh) × curtailment × BESS; escala o PLD. | raw Aurora `bra-central-system-1h.csv` | `output/modulacao_alvo/*.{csv,html}` (+ curvas) |
| `generate_psr_modulation_html.py` | Gera curvas de preço futuras + resumo de modulação por cenário (Aurora central/low/dry/constrained **e PSR 2025** por submercado). É a origem dos `curvas_preco_*` congelados. | raw Aurora (4 cenários) + PSR 2025 | `output/curvas_preco_*.csv`, `output/modulacao_*.{csv,html}` |
| `generate_curtailment_2025_2026_html.py` | HTML de curtailment mensal 2025/2026. | — | `output/curvas/curtailment_mensal_2025_2026.html` |
| `generate_curtailment_profile_html.py` | HTML do perfil de curtailment. | — | `output/...` |
| `generate_pld_day15_charts.py` | Gráficos de PLD (dia 15). | PLD histórico | `output/...` |
| `export_aurora_curtailment_curves.py` | Exporta curvas de curtailment do databook Aurora (cluster_23). | databook Aurora (xlsx) | `dados/aurora_seriemas_*.csv` |
| `plot_aurora_pld_hourly.py` | Gráfico do PLD horário (8760h) por submercado via API. | API Aurora ao vivo | `output/pld_aurora_*.html` |

> Scripts em `standalone/` usam caminhos relativos à raiz do projeto — rode-os a partir da
> raiz do repositório (`python scripts/standalone/<x>.py`).
