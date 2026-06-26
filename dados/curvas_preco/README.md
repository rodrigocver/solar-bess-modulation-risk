# dados/curvas_preco/

Snapshots **versionados** de curvas de preço horário (8760h × ano) usados como
**input/fallback offline** pelos scripts de modulação. Ficam aqui (e não em
`output/`, que é gitignored) porque são consumidos como entrada — um clone limpo
precisa deles.

| Arquivo | Cenário | Consumido por |
|---|---|---|
| `curvas_preco_brazil_q2_26_central_2030_2059.csv` | Aurora "Central" Brazil Q2 26, região nacional `bra` (média ~343 R$/MWh) | fallback offline de `scripts/pipeline/calc_modulacao_contrato_ppa.py` (quando a API Aurora está indisponível, só SE/central); input de `scripts/standalone/calc_modulacao_contrato.py` e `calc_modulacao_contrato_bess.py` |

Formato: coluna `hour_of_year` + uma `price_YYYY_brl_mwh` por ano.

**Como regenerar:** `python scripts/standalone/generate_psr_modulation_html.py`
(lê o raw Aurora `dados/Brazil Q2 26 (Central)-bra-central-...system-1h.csv`,
escreve em `output/`); copie a curva atualizada para cá se quiser trocar o snapshot.
Os demais cenários (low/dry/constrained) e as curvas PSR são saídas regeneráveis e
permanecem em `output/`.
