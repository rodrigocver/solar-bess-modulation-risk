# Contracts: Otimizador de Redução de MUST

Tipo de projeto: biblioteca Python + CLI. Os contratos são as assinaturas das
funções públicas e as flags de CLI.

## API Python (`solar_bess_risk/must_optimizer.py`)

```python
def optimize_must_reduction(
    solar: SolarProfile,
    prices: PriceProfile,
    scenario: ScenarioDefinition,
    params: SimulationParams,
    *,
    curtailment_series: np.ndarray | None = None,
    solar_year_idx: int = 1,
) -> MustOptimizationResult:
    """Encontra a redução de MUST que maximiza o benefício líquido anual.

    Varre ``params.must_sweep_*`` aplicando, em cada ponto, um teto de injeção
    ``must_mw = mwac × (1 − pct)`` no despacho price-aware e medindo
    ``net_benefit = economia_TUST + Δsaldo_líquido`` contra a baseline (pct=0).

    Parameters
    ----------
    solar : SolarProfile
        Perfil solar (fornece ``garantia_fisica_mw`` e séries gen_lim/gen_bess).
    prices : PriceProfile
        PLD horário (BRL/MWh) — base da valoração da perda.
    scenario : ScenarioDefinition
        Cenário de duração da BESS.
    params : SimulationParams
        Parâmetros; usa ``mwac`` (MUST inicial), ``tust_brl_per_kw_month`` e a grade.
    curtailment_series : np.ndarray | None
        Curtailment ONS opcional (8760,), MWh.
    solar_year_idx : int
        Índice do ano solar.

    Returns
    -------
    MustOptimizationResult
        Redução ótima, MUST ótimo, benefício no ótimo e curva de sensibilidade.

    Raises
    ------
    ValueError
        Se ``tust_brl_per_kw_month`` ou a grade estiverem fora dos bounds, ou se
        dados obrigatórios (PLD/perfil) estiverem ausentes.
    """


def tust_annual_savings_brl(
    *, tust_brl_per_kw_month: float, delta_must_mw: float
) -> float:
    """Economia anual de TUST = tust × 12 × delta_must_mw × 1000 (BRL/ano)."""
```

### Contrato de comportamento

| Entrada | Saída esperada |
|---|---|
| TUST muito baixo (perda sempre > economia) | `optimal_reduction_pct == 0.0` |
| TUST alto, excedente em horas de PLD baixo | `optimal_reduction_pct > 0`; `optimal_must_mw ≈ pico de injeção pós-BESS` |
| `must_mw >= pico de injeção` (pct pequeno) | `curtailment_lost` extra = 0; `net_benefit` = só economia TUST |
| Sem TUST informado | resultado com `tust_is_default == True`, `tust == 7.23` |
| `tust` fora de bounds | `ValueError` estruturado |
| qualquer ponto do sweep | `net_benefit <= optimal_net_benefit` |

## Contrato de despacho (`simulate_scenario` estendido)

```python
def simulate_scenario(
    solar, prices, scenario, params,
    curtailment_series=None, solar_year_idx=1,
    must_mw: float | None = None,   # NOVO
) -> DispatchResult: ...
```

| Entrada | Saída esperada |
|---|---|
| `must_mw is None` | resultado idêntico ao atual (retrocompatível) |
| `must_mw` finito | injeção capada; excedente vira curtailment absorvível pela BESS |
| reconciliação | `Σ gen_bess` = injeção + perdas + curtailment_lost (± RTE), tol. numérica |

## Contrato de CLI (opt-in)

```text
--tust <R$/kW·mês>        # default 7.23 (DEFAULT_TUST_BRL_PER_KW_MONTH)
--must-sweep              # ativa a otimização de MUST no run
--must-sweep-max <frac>   # default 0.40
--must-sweep-step <frac>  # default 0.02
```

- Sem `--must-sweep`: comportamento atual inalterado.
- Com `--must-sweep`: o relatório inclui a tabela do MUST ótimo por cenário e a
  curva de sensibilidade; a premissa de TUST (incl. uso do default) é exibida.
