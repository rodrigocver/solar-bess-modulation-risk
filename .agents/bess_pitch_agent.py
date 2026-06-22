import os
import re
import numpy as np
import numpy_financial as npf
from bs4 import BeautifulSoup

from solar_bess_risk.config import (
    DEFAULT_MODULATION_MODE,
    MODULATION_MODE_ENERGIA,
)
from solar_bess_risk.modulation import modulation_value_brl_per_mwh

# Piso e teto regulatórios do PLD (R$/MWh). Usados para clampar o PLD escalado
# ao estressar/relaxar a modulação no dashboard simplificado.
PLD_FLOOR_BRL_PER_MWH = 57.31
PLD_CEILING_BRL_PER_MWH = 1611.04

# Alvos de modulação s/ BESS (R$/MWh) dos cenários do dashboard simplificado.
MODULACAO_ALVO_ESTRESSADO_BRL_MWH = 75.0
MODULACAO_ALVO_LEVE_BRL_MWH = 50.0

def limpar_numero(texto):
    """Remove textos, espaços e símbolos (como % e R$) para converter em float."""
    if not texto or texto.strip() == "—":
        return 0.0
    texto_limpo = re.sub(r'[^\d.,-]', '', texto)
    texto_limpo = texto_limpo.replace(',', '.')
    try:
        return float(texto_limpo)
    except ValueError:
        return 0.0

def extrair_kpis_do_relatorio(caminho_html):
    """Faz o parsing do HTML do simulador e extrai os KPIs exatos para o pitch."""
    with open(caminho_html, 'r', encoding='utf-8') as f:
        soup = BeautifulSoup(f.read(), 'html.parser')

    dados = {
        'nome_projeto': 'Projeto Solar',
        'potencia_ac_mw': 0.0,
        'garantia_fisica_mw': 0.0,
        'energia_bess_mwh': 0.0,
        'capex_mm_mwh': 0.0,
        'opex_pct': 0.015,
        'vida_util_anos': 20,
        'wacc': 0.05,
        '2025_base': {},
        '2025_must': {},
        '2026_base': {},
        '2026_must': {}
    }

    # 1. Extração de Parâmetros Gerais (Potência AC, GF, Vida Útil, O&M, WACC via LCOS)
    tabelas_params = soup.find_all('table', class_='params-table')
    for tab in tabelas_params:
        linhas = tab.find_all('tr')
        for linha in linhas:
            th = linha.find('th')
            td = inline_td = linha.find('td')
            if th and td:
                chave = th.text.strip().lower()
                valor = td.text.strip()
                
                if 'curva solar' in chave:
                    nome_limpo = valor.split('/')[-1].replace('.csv', '').replace('solar_', '')
                    dados['nome_projeto'] = nome_limpo.upper()
                elif 'capacidade ac' in chave:
                    dados['potencia_ac_mw'] = limpar_numero(valor)
                elif 'garantia fisica' in chave:
                    dados['garantia_fisica_mw'] = limpar_numero(valor)
                elif 'vida util economica' in chave:
                    dados['vida_util_anos'] = int(limpar_numero(valor))
                elif 'o&m anual bess' in chave:
                    dados['opex_pct'] = limpar_numero(valor) / 100.0
                elif 'lcos' in chave:
                    match = re.search(r'([\d.]+)\s*%', valor)
                    if match:
                        dados['wacc'] = float(match.group(1)) / 100.0

    # 2. Extração dos 4 Cenários na Tabela de Resumo Comparativo
    tabelas_kpi = soup.find_all('table', class_='kpi-table')
    for tab in tabelas_kpi:
        tbody = tab.find('tbody')
        if tbody is None:
            continue
        linhas = tbody.find_all('tr')
        for linha in linhas:
            colunas = linha.find_all('td')
            if not colunas or len(colunas) < 18:
                continue
            
            cenario_nome = colunas[0].text.strip()
            
            if dados['energia_bess_mwh'] == 0.0:
                dados['energia_bess_mwh'] = limpar_numero(colunas[2].text)
                dados['capex_mm_mwh'] = limpar_numero(colunas[3].text)

            chave = None
            if '2025' in cenario_nome:
                chave = '2025_must' if 'must' in cenario_nome.lower() else '2025_base'
            elif '2026' in cenario_nome:
                chave = '2026_must' if 'must' in cenario_nome.lower() else '2026_base'

            if chave:
                mod_original = limpar_numero(colunas[4].text)
                mod_com_bess = limpar_numero(colunas[5].text)
                saldo_liquido = limpar_numero(colunas[9].text)
                economia_must = limpar_numero(colunas[10].text)
                caixa_adicionado = saldo_liquido + economia_must
                
                # KPI table columns: 13 = Curtailment ONS / Geração,
                # 14 = Clipping / Geração, 16 = Curtailment Recuperado, 17 = Δ CVaR.
                curt_ons = str(int(round(limpar_numero(colunas[13].text)))) + "%" if colunas[13].text.strip() != "—" else "0%"
                curt_clip = str(int(round(limpar_numero(colunas[14].text)))) + "%" if colunas[14].text.strip() != "—" else "0%"
                curt_rec = str(int(round(limpar_numero(colunas[16].text)))) + "%" if colunas[16].text.strip() != "—" else "0%"

                dados[chave] = {
                    'nome': cenario_nome,
                    'mod_original_inteira': int(round(mod_original)),
                    'mod_com_bess_inteira': int(round(mod_com_bess)),
                    'caixa_adicionado_mm': caixa_adicionado,
                    'curtailment_ons': curt_ons,
                    'curtailment_clip': curt_clip,
                    'curtailment_recuperado': curt_rec,
                    'delta_cvar_dia_mil': limpar_numero(colunas[17].text)
                }

    return dados

def calcular_premio_seguro(dados):
    """Aplica a matemática financeira de anuidade e calcula a representatividade da bateria."""
    energia = dados['energia_bess_mwh']
    capex_unitario = dados['capex_mm_mwh']
    wacc = dados['wacc']
    gf = dados['garantia_fisica_mw']
    
    if gf > 0:
        dados['representatividades_gf_pct'] = (energia / (gf * 24.0)) * 100.0
    else:
        dados['representatividades_gf_pct'] = 0.0

    capex_total_mm = energia * capex_unitario
    dados['capex_total_mm'] = capex_total_mm
    
    opex_anual_mm = capex_total_mm * dados['opex_pct']
    dados['opex_anual_mm'] = opex_anual_mm
    
    parcela_capex_mm = npf.pmt(rate=wacc, nper=dados['vida_util_anos'], pv=-capex_total_mm, fv=0)
    dados['parcela_capex_mm'] = parcela_capex_mm
    
    dados['premio_anual_seguro_mm'] = parcela_capex_mm + opex_anual_mm
    dados['wacc_utilizado_pct'] = wacc * 100
    
    return dados

def _modulation_value_brl_per_mwh(
    injection_mwh,
    pld_brl_per_mwh,
    gf_energy_mwh,
    mode=DEFAULT_MODULATION_MODE,
):
    """Calcula a modulação usando a implementação central do projeto."""
    return modulation_value_brl_per_mwh(
        injection_mwh,
        pld_brl_per_mwh,
        gf_energy_mwh,
        mode,
    )


def _target_modulation_for_mode(target_cost_brl_mwh, mode=DEFAULT_MODULATION_MODE):
    """Translate legacy cost targets into the selected modulation convention."""
    if mode == MODULATION_MODE_ENERGIA:
        return -float(target_cost_brl_mwh)
    return float(target_cost_brl_mwh)


def _modulation_mode_label(mode=DEFAULT_MODULATION_MODE):
    if mode == MODULATION_MODE_ENERGIA:
        return "Spread de captura"
    return "Custo de modulação"

def _duration_from_scenario_name(name):
    match = re.search(r'(\d+)\s*h', name or '', flags=re.IGNORECASE)
    return int(match.group(1)) if match else None

def _select_result_data(results_by_key, year, duration_h):
    selected = _select_labeled_result_data(results_by_key, year, duration_h)
    return selected[1] if selected else None


def _select_labeled_result_data(results_by_key, year, duration_h):
    if not results_by_key:
        return None

    candidates = []
    for label, data in results_by_key.items():
        if len(data) < 7:
            continue
        if data[6] != year:
            continue
        if duration_h is not None and data[5] != duration_h:
            continue
        candidates.append((label, data))

    if candidates:
        return candidates[-1]
    return None

def _daily_price_scale_mask(discharge_mwh, hours_per_day=24):
    """Marca todas as horas dos dias em que houve descarga da BESS."""
    discharge = np.asarray(discharge_mwh, dtype=np.float64) > 1e-10
    mask = np.zeros_like(discharge, dtype=bool)

    for start in range(0, len(discharge), hours_per_day):
        end = min(start + hours_per_day, len(discharge))
        if np.any(discharge[start:end]):
            mask[start:end] = True

    return mask

def _equilibrium_for_result_data(data, premium_brl, mode=DEFAULT_MODULATION_MODE):
    dispatch, pld, gf, gen = data[0], data[1], data[2], data[3]
    tust_savings_brl = data[11] if len(data) > 11 and data[11] is not None else 0.0

    pld_arr = np.asarray(pld, dtype=np.float64)
    gen_arr = np.asarray(gen, dtype=np.float64)
    injection_sem = gen_arr - np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64)
    injection_com = np.asarray(dispatch.grid_injection_mwh, dtype=np.float64)
    price_scale_mask = _daily_price_scale_mask(dispatch.discharge_mwh)

    delta_injection = injection_com - injection_sem
    cash_without_scaled_days = float(np.sum(delta_injection[~price_scale_mask] * pld_arr[~price_scale_mask]))
    cash_scaled_days_at_factor_1 = float(np.sum(delta_injection[price_scale_mask] * pld_arr[price_scale_mask]))

    if abs(cash_scaled_days_at_factor_1) <= 1e-10:
        return None

    factor = (
        premium_brl
        - tust_savings_brl
        - cash_without_scaled_days
    ) / cash_scaled_days_at_factor_1

    if factor < 0 or not np.isfinite(factor):
        return None

    pld_equilibrium = pld_arr.copy()
    pld_equilibrium[price_scale_mask] *= factor

    gf_energy = float(gf) * len(pld_equilibrium)
    mod_without_bess_equilibrium = _modulation_value_brl_per_mwh(
        injection_sem,
        pld_equilibrium,
        gf_energy,
        mode,
    )
    mod_with_bess_equilibrium = _modulation_value_brl_per_mwh(
        injection_com,
        pld_equilibrium,
        gf_energy,
        mode,
    )
    cash_equilibrium_brl = float(np.sum(delta_injection * pld_equilibrium)) + tust_savings_brl

    if (
        mod_without_bess_equilibrium is None
        or mod_with_bess_equilibrium is None
        or not np.isfinite(mod_without_bess_equilibrium)
        or not np.isfinite(mod_with_bess_equilibrium)
    ):
        return None

    return {
        'fator_pld_descarga_equilibrio': float(factor),
        'mod_equilibrio_brl_mwh': float(mod_without_bess_equilibrium),
        'mod_equilibrio_inteira': int(round(mod_without_bess_equilibrium)),
        'mod_equilibrio_com_bess_brl_mwh': float(mod_with_bess_equilibrium),
        'delta_mod_equilibrio_brl_mwh': float(
            mod_without_bess_equilibrium - mod_with_bess_equilibrium
        ),
        'caixa_equilibrio_mm': cash_equilibrium_brl / 1e6,
    }

def _scenario_metrics_from_result_data(label, data, mode=DEFAULT_MODULATION_MODE):
    dispatch, pld, gf, gen = data[0], data[1], data[2], data[3]
    risk_metrics = data[10] if len(data) > 10 and isinstance(data[10], dict) else None
    tust_savings_brl = data[11] if len(data) > 11 and data[11] is not None else 0.0

    pld_arr = np.asarray(pld, dtype=np.float64)
    gen_arr = np.asarray(gen, dtype=np.float64)
    injection_sem = gen_arr - np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64)
    injection_com = np.asarray(dispatch.grid_injection_mwh, dtype=np.float64)

    gf_energy = float(gf) * len(pld_arr)
    mod_original = _modulation_value_brl_per_mwh(injection_sem, pld_arr, gf_energy, mode)
    mod_com_bess = _modulation_value_brl_per_mwh(injection_com, pld_arr, gf_energy, mode)
    net_sem = float(np.sum((injection_sem - float(gf)) * pld_arr))
    net_com = float(np.sum((injection_com - float(gf)) * pld_arr))
    caixa_adicionado = (net_com - net_sem + tust_savings_brl) / 1e6

    curt_total = float(np.sum(dispatch.curtailment_mwh))
    curt_lost = float(np.sum(dispatch.curtailment_lost_mwh))
    curt_recovered = max(0.0, curt_total - curt_lost)
    gen_total = float(np.sum(gen_arr))
    curt_pct = (curt_total / gen_total * 100.0) if gen_total > 0 else 0.0
    curt_recovered_pct = (curt_recovered / curt_total * 100.0) if curt_total > 0 else 0.0
    # Split total curtailment into external-grid (ONS) and inverter-clipping
    # components. O clipping é a grandeza física max(0, gen_bess − gen_lim)
    # (dispatch.clipping_available_mwh), independente do corte ONS — NÃO um
    # resíduo. Ambos os percentuais usam a geração limitada sem BESS (gen_lim).
    ons_total = float(np.sum(np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64)))
    clip_total = float(np.sum(np.asarray(dispatch.clipping_available_mwh, dtype=np.float64)))
    curt_ons_pct = (ons_total / gen_total * 100.0) if gen_total > 0 else 0.0
    curt_clip_pct = (clip_total / gen_total * 100.0) if gen_total > 0 else 0.0

    cvar_delta_mil = 0.0
    if risk_metrics:
        cvar_sem = risk_metrics.get("cvar_95_sem_bess_brl")
        cvar_com = risk_metrics.get("cvar_95_com_bess_brl")
        if cvar_sem is not None and cvar_com is not None:
            cvar_delta_mil = (cvar_com - cvar_sem) / 1e3

    return {
        'nome': label,
        'titulo': label,
        'descricao': 'Sem redução de MUST',
        'mod_original_inteira': int(round(mod_original)) if mod_original is not None else 0,
        'mod_com_bess_inteira': int(round(mod_com_bess)) if mod_com_bess is not None else 0,
        'caixa_adicionado_mm': caixa_adicionado,
        'economia_must_mm': tust_savings_brl / 1e6,
        'curtailment_geracao': str(int(round(curt_pct))) + "%",
        'curtailment_ons': str(int(round(curt_ons_pct))) + "%",
        'curtailment_clip': str(int(round(curt_clip_pct))) + "%",
        'curtailment_recuperado': str(int(round(curt_recovered_pct))) + "%",
        'delta_cvar_dia_mil': cvar_delta_mil,
    }

def _scale_pld_to_target_modulation(
    pld,
    injection_sem,
    gf_energy,
    target_brl_per_mwh,
    mode=DEFAULT_MODULATION_MODE,
    pld_floor=PLD_FLOOR_BRL_PER_MWH,
    pld_ceil=PLD_CEILING_BRL_PER_MWH,
):
    """Escala o PLD por um fator uniforme (com clamp piso/teto) até a modulação
    s/ BESS atingir ``target_brl_per_mwh``.

    O despacho fica congelado: apenas a série de PLD é escalada e cada hora é
    limitada ao intervalo regulatório [piso, teto]. Como o clamp quebra a
    linearidade, o fator é resolvido por bisseção (a modulação é monótona no
    fator). Retorna a série de PLD já escalada e clampada.
    """
    pld_arr = np.asarray(pld, dtype=np.float64)

    def mod_for_factor(k):
        scaled = np.clip(pld_arr * k, pld_floor, pld_ceil)
        return _modulation_value_brl_per_mwh(injection_sem, scaled, gf_energy, mode)

    base_mod = mod_for_factor(1.0)
    if base_mod is None:
        return pld_arr.copy()

    # Garante um bracketing com monotonicidade detectada empiricamente.
    k_lo, k_hi = 0.0, 1.0
    mod_lo = mod_for_factor(k_lo)
    mod_hi = mod_for_factor(k_hi)
    if mod_lo is None or mod_hi is None:
        return pld_arr.copy()

    increasing = mod_hi >= mod_lo

    def _target_bracketed(lo_value, hi_value):
        low, high = sorted((lo_value, hi_value))
        return low <= target_brl_per_mwh <= high

    iters = 0
    while not _target_bracketed(mod_lo, mod_hi) and k_hi < 1e6 and iters < 200:
        k_hi *= 2.0
        mod_hi = mod_for_factor(k_hi)
        if mod_hi is None:
            return pld_arr.copy()
        iters += 1

    if not _target_bracketed(mod_lo, mod_hi):
        # Alvo fora do intervalo alcançável: retorna o extremo mais próximo.
        k_best = k_lo if abs(mod_lo - target_brl_per_mwh) <= abs(mod_hi - target_brl_per_mwh) else k_hi
        return np.clip(pld_arr * k_best, pld_floor, pld_ceil)

    for _ in range(80):
        k_mid = 0.5 * (k_lo + k_hi)
        mod_mid = mod_for_factor(k_mid)
        if mod_mid is None:
            break
        if (mod_mid < target_brl_per_mwh) == increasing:
            k_lo = k_mid
        else:
            k_hi = k_mid

    k = 0.5 * (k_lo + k_hi)
    return np.clip(pld_arr * k, pld_floor, pld_ceil)


def _clean_must_label(label):
    return (
        label.replace("2025 - 4h ", "")
        .replace("redução de MUST", "Redução de MUST")
        .replace("MUST definido", "MUST definido")
    )


def _build_modulation_cases(
    base,
    premium_brl,
    *,
    existing_description,
    mode=DEFAULT_MODULATION_MODE,
):
    """Build the three simplified modulation cases for an already simulated dispatch."""
    dispatch, pld, gf, gen = base[0], base[1], base[2], base[3]
    injection_sem = (
        np.asarray(gen, dtype=np.float64)
        - np.asarray(dispatch.ons_curtailment_mwh, dtype=np.float64)
    )
    gf_energy = float(gf) * len(np.asarray(pld, dtype=np.float64))

    def _make(label, descricao, scaled_pld):
        data = list(base)
        data[1] = scaled_pld
        data = tuple(data)
        metrics = _scenario_metrics_from_result_data(label, data, mode)
        metrics["titulo"] = label
        metrics["descricao"] = descricao
        if premium_brl > 0:
            equilibrium = _equilibrium_for_result_data(data, premium_brl, mode)
            if equilibrium:
                metrics.update(equilibrium)
        return metrics

    stressed_target = _target_modulation_for_mode(
        MODULACAO_ALVO_ESTRESSADO_BRL_MWH,
        mode,
    )
    light_target = _target_modulation_for_mode(
        MODULACAO_ALVO_LEVE_BRL_MWH,
        mode,
    )
    metric_label = _modulation_mode_label(mode)

    cenarios = [
        _make(
            "2025 — Modulação Existente",
            existing_description,
            np.asarray(pld, dtype=np.float64),
        ),
        _make(
            "2025 — Estressado",
            f"{metric_label} s/ BESS escalado p/ R$ {stressed_target:.0f}/MWh",
            _scale_pld_to_target_modulation(
                pld, injection_sem, gf_energy, stressed_target, mode
            ),
        ),
        _make(
            "2025 — Moderado",
            f"{metric_label} s/ BESS escalado p/ R$ {light_target:.0f}/MWh",
            _scale_pld_to_target_modulation(
                pld, injection_sem, gf_energy, light_target, mode
            ),
        ),
    ]
    return cenarios


def _build_simplified_scenarios(
    results_by_key,
    premium_brl,
    mode=DEFAULT_MODULATION_MODE,
):
    """Constrói os 3 cenários 2025 sem redução de MUST."""
    base = _select_result_data(results_by_key, 2025, 4)
    if base is None:
        base = _select_result_data(results_by_key, 2025, None)
    if base is None:
        return []

    return _build_modulation_cases(
        base,
        premium_brl,
        existing_description="PLD realizado 2025 · ONS no alvo configurado",
        mode=mode,
    )


def _build_simplified_must_scenarios(
    must_reduction_by_key,
    premium_brl,
    mode=DEFAULT_MODULATION_MODE,
):
    """Constrói os 3 cenários 2025 para o dispatch com MUST reduzido/definido."""
    must_match = _select_labeled_result_data(must_reduction_by_key, 2025, 4)
    if must_match is None:
        return [], "", ""

    label, data = must_match
    clean_label = _clean_must_label(label)
    is_fixed_must = "definido" in label.lower()
    section_label = "MUST Definido" if is_fixed_must else "MUST Otimizado"
    scenarios = _build_modulation_cases(
        data,
        premium_brl,
        existing_description=f"{clean_label} · PLD realizado 2025",
        mode=mode,
    )
    return scenarios, section_label, clean_label


def adicionar_cenarios_curtailment_cruzado(
    dados,
    results_by_key,
    mode=DEFAULT_MODULATION_MODE,
):
    """Adiciona cenários sem MUST com PLD de um ano e curtailment do outro."""
    premium_brl = dados.get('premio_anual_seguro_mm', 0.0) * 1e6
    cenarios = []

    for label, data in (results_by_key or {}).items():
        scenario_data = _scenario_metrics_from_result_data(label, data, mode)
        if premium_brl > 0:
            equilibrium = _equilibrium_for_result_data(data, premium_brl, mode)
            if equilibrium:
                scenario_data.update(equilibrium)
        cenarios.append(scenario_data)

    dados['curtailment_cruzado'] = cenarios
    return dados

def adicionar_modulacao_equilibrio(
    dados,
    results_by_key,
    must_reduction_by_key=None,
    mode=DEFAULT_MODULATION_MODE,
):
    """Adiciona a modulação que faz o caixa anual igualar o prêmio.

    A simulação fica congelada. O PLD de todas as horas dos dias em que a BESS
    descarrega recebe um fator linear, e o fator é resolvido analiticamente para igualar:
    caixa adicionado recalculado = prêmio anual total.
    """
    premium_brl = dados.get('premio_anual_seguro_mm', 0.0) * 1e6
    if premium_brl <= 0:
        return dados

    scenario_sources = {
        '2025_base': (2025, results_by_key),
        '2026_base': (2026, results_by_key),
        '2025_must': (2025, must_reduction_by_key or {}),
        '2026_must': (2026, must_reduction_by_key or {}),
    }

    for scenario_key, (year, source) in scenario_sources.items():
        scenario_data = dados.get(scenario_key)
        if not scenario_data:
            continue

        duration_h = _duration_from_scenario_name(scenario_data.get('nome', ''))
        result_data = _select_result_data(source, year, duration_h)
        if result_data is None:
            continue

        equilibrium = _equilibrium_for_result_data(result_data, premium_brl, mode)
        if equilibrium:
            scenario_data.update(equilibrium)

    return dados

def gerar_html_apresentacao(dados, caminho_saida, mode=DEFAULT_MODULATION_MODE):
    
    # Cabeçalho Técnico (Inteiros)
    nome_proj = dados.get('nome_projeto', 'PROJETO SOLAR')
    pot_ac = dados.get('potencia_ac_mw', 0.0)
    gf_mw = dados.get('garantia_fisica_mw', 0.0)
    rep_gf = dados.get('representatividades_gf_pct', 0.0)

    # Financeiro Global
    energia = dados.get('energia_bess_mwh', 0)
    capex_total = dados.get('capex_total_mm', 0)
    parcela_anual = dados.get('parcela_capex_mm', 0)
    opex_anual = dados.get('opex_anual_mm', 0)
    premio = dados.get('premio_anual_seguro_mm', 0)
    vida_util = dados.get('vida_util_anos', 20)
    wacc_pct = dados.get('wacc_utilizado_pct', 0.0)
    
    def get_val(cenario_key, field):
        return dados.get(cenario_key, {}).get(field, 0.0)

    def get_text(cenario_key, field):
        return dados.get(cenario_key, {}).get(field, "-")

    def get_int(cenario_key, field):
        return dados.get(cenario_key, {}).get(field, 0)

    def get_mod_equilibrio(cenario_key):
        value = dados.get(cenario_key, {}).get('mod_equilibrio_brl_mwh')
        if value is None:
            return "n/a"
        return f"R$ {value:.0f}/MWh"

    def get_fator_equilibrio(cenario_key):
        value = dados.get(cenario_key, {}).get('fator_pld_descarga_equilibrio')
        if value is None:
            return "PLD dias c/ descarga n/a"
        return f"PLD dias c/ descarga × {value:.2f}"

    metric_table_label = "Spread" if mode == MODULATION_MODE_ENERGIA else "Modulação"

    def format_scenario_row(cenario, badge_class):
        nome = cenario.get('nome', '-')
        titulo = cenario.get('titulo', nome)
        descricao = cenario.get('descricao', '')
        return f"""<tr>
                    <td class="col-scenario">
                        <span class="badge-ano {badge_class}">{titulo}</span><br>
                        <span class="desc-cenario">{descricao}</span>
                    </td>
                    <td class="val-premium">R$ {premio:.0f} MM / ano</td>
                    <td class="val-mod-orig">R$ {int(round(cenario.get('mod_original_inteira', 0)))}/MWh</td>
                    <td class="val-mod-bess">R$ {int(round(cenario.get('mod_com_bess_inteira', 0)))}/MWh</td>
                    <td class="val-mod-eq">{_format_mod_equilibrio_value(cenario)}<div class="val-factor">{_format_fator_equilibrio_value(cenario)}</div></td>
                    <td>{cenario.get('curtailment_ons', '0%')}</td>
                    <td>{cenario.get('curtailment_clip', '0%')}</td>
                    <td>{cenario.get('curtailment_recuperado', '0%')}</td>
                    <td class="val-caixa">+ R$ {cenario.get('caixa_adicionado_mm', 0.0):.0f} MM</td>
                    <td class="val-cvar">R$ {cenario.get('delta_cvar_dia_mil', 0.0):.0f} mil / dia</td>
                </tr>"""

    def _format_mod_equilibrio_value(cenario):
        value = cenario.get('mod_equilibrio_brl_mwh')
        if value is None:
            return "n/a"
        return f"R$ {value:.0f}/MWh"

    def _format_fator_equilibrio_value(cenario):
        value = cenario.get('fator_pld_descarga_equilibrio')
        if value is None:
            return "PLD dias c/ descarga n/a"
        return f"PLD dias c/ descarga × {value:.2f}"

    cruzados = dados.get('curtailment_cruzado', [])
    cruzados_rows = []
    for idx, cenario in enumerate(cruzados):
        badge_class = 'badge-2025' if idx == 0 else 'badge-2026'
        cruzados_rows.append(format_scenario_row(cenario, badge_class))
    cruzados_section = ""
    if cruzados_rows:
        cruzados_section = f"""
    <div class="section-title"><span>4</span> Sensibilidade Cruzada de Curtailment (Sem Redução de MUST)</div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 20%; text-align: left;">Cenário Cruzado</th>
                    <th>Prêmio Pago</th>
                    <th>{metric_table_label} s/ BESS</th>
                    <th>{metric_table_label} c/ BESS</th>
                    <th>{metric_table_label} de Equilíbrio s/ BESS</th>
                    <th>Curtailment ONS / Geração</th>
                    <th>Clipping / Geração</th>
                    <th>Curtailment Recuperado</th>
                    <th>Caixa Adicionado Total</th>
                    <th>Redução CVaR 95%</th>
                </tr>
            </thead>
            <tbody>
                {''.join(cruzados_rows)}
            </tbody>
        </table>
        <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted); font-weight: 600;">
            Cenários cruzados mantêm o PLD e o despacho sem redução de MUST do ano indicado, trocando apenas a série de curtailment técnico usada na simulação.
        </p>
    </div>
"""

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Executivo: BESS {nome_proj}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');
        
        :root {{
            --navy: #0f172a;
            --blue: #1d4ed8;
            --green: #059669;
            --emerald: #10b981;
            --bg-light: #f8fafc;
            --border: #e2e8f0;
            --text-dark: #1e293b;
            --text-muted: #64748b;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', sans-serif; }}
        body {{ background-color: #e2e8f0; color: var(--text-dark); padding: 2rem; }}
        
        .container {{ max-width: 1700px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); padding: 2rem; overflow: hidden; }}
        
        .header {{ border-bottom: 2px solid var(--border); padding-bottom: 1.5rem; margin-bottom: 2rem; display: flex; justify-content: space-between; align-items: flex-end; }}
        .header h1 {{ font-size: 1.8rem; font-weight: 800; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px; }}
        .header h1 span {{ color: var(--blue); }}
        .header p {{ color: var(--text-muted); font-size: 1.1rem; font-weight: 600; }}
        
        .project-summary {{ display: flex; gap: 2rem; background: var(--navy); color: white; padding: 1.2rem 2rem; border-radius: 8px; margin-bottom: 2rem; }}
        .summary-item {{ display: flex; flex-direction: column; }}
        .summary-item .s-label {{ font-size: 0.75rem; color: #94a3b8; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }}
        .summary-item .s-value {{ font-size: 1.2rem; font-weight: 700; }}

        .section-title {{ font-size: 1.25rem; font-weight: 700; color: var(--navy); margin-bottom: 1rem; display: flex; align-items: center; }}
        .section-title span {{ background: var(--blue); color: white; width: 28px; height: 28px; display: inline-flex; justify-content: center; align-items: center; border-radius: 50%; font-size: 0.9rem; margin-right: 10px; }}
        
        .calc-box {{ background: var(--bg-light); border: 1px solid var(--border); border-radius: 10px; padding: 1.5rem; margin-bottom: 2.5rem; }}
        .calc-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 1rem; align-items: center; }}
        .calc-item {{ text-align: center; }}
        .calc-item .label {{ font-size: 0.85rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 0.5rem; }}
        .calc-item .value {{ font-size: 1.4rem; font-weight: 800; color: var(--navy); }}
        .calc-operator {{ text-align: center; font-size: 1.5rem; font-weight: 800; color: var(--text-muted); }}
        .calc-total {{ background: linear-gradient(135deg, var(--green), var(--emerald)); color: white; padding: 1rem; border-radius: 8px; box-shadow: 0 4px 10px rgba(5,150,105,0.2); }}
        .calc-total .label {{ color: rgba(255,255,255,0.9); }}
        .calc-total .value {{ color: white; font-size: 1.6rem; }}

        .table-container {{ margin-bottom: 2.5rem; }}
        table {{ width: 100%; border-collapse: collapse; text-align: center; }}
        th {{ background: #1e293b; color: white; padding: 1rem; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid #1e293b; }}
        td {{ padding: 1.2rem 0.8rem; border: 1px solid var(--border); font-size: 1.05rem; font-weight: 600; color: var(--text-dark); vertical-align: middle; }}
        
        tr:nth-child(even) td {{ background-color: var(--bg-light); }}
        
        .col-scenario {{ text-align: left; background: var(--bg-light); }}
        .badge-ano {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 0.85rem; font-weight: 700; margin-bottom: 4px; }}
        .badge-2025 {{ background: #e0f2fe; color: #0369a1; }}
        .badge-2026 {{ background: #fee2e2; color: #b91c1c; }}
        .desc-cenario {{ font-size: 0.9rem; color: var(--text-muted); font-weight: 400; }}

        .val-premium {{ color: var(--text-muted); font-size: 0.95rem; }}
        .val-mod-orig {{ color: #b91c1c; }}
        .val-mod-bess {{ color: var(--blue); }}
        .val-mod-eq {{ color: var(--green); }}
        .val-factor {{ color: var(--text-muted); font-size: 0.78rem; font-weight: 600; margin-top: 4px; }}
        .val-caixa {{ color: var(--green); font-size: 1.2rem; font-weight: 800; }}
        .val-cvar {{ color: var(--blue); font-size: 0.95rem; }}
        
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div>
            <h1>Ativo de Proteção de Caixa — BESS <span>{nome_proj}</span></h1>
            <p>Apresentação Executiva: Mitigação de Riscos de Mercado e Modulação</p>
        </div>
    </div>

    <div class="project-summary">
        <div class="summary-item">
            <div class="s-label">Projeto Executivo</div>
            <div class="s-value" style="color: var(--emerald);">{nome_proj}</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Potência Inicial AC</div>
            <div class="s-value">{pot_ac:.0f} MWac</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Garantia Física (GF)</div>
            <div class="s-value">{gf_mw:.0f} MWmédio</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Dimensionamento BESS</div>
            <div class="s-value">{energia:.0f} MWh</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Taxa de Cobertura Diária da GF</div>
            <div class="s-value" style="color: var(--emerald);">{rep_gf:.0f}%</div>
        </div>
    </div>

    <div class="section-title"><span>1</span> Cálculo do Prêmio Anual de Seguro</div>
    <div class="calc-box">
        <div class="calc-grid">
            <div class="calc-item">
                <div class="label">Capex Total</div>
                <div class="value">R$ {capex_total:.0f} MM</div>
            </div>
            <div class="calc-item" style="border-left: 1px solid var(--border); border-right: 1px solid var(--border);">
                <div class="label">Premissas de Custo</div>
                <div class="value" style="font-size: 1rem; margin-top: 5px;">Taxa: {wacc_pct:.2f}% a.a.<br>Vida: {vida_util} anos</div>
            </div>
            <div class="calc-item">
                <div class="label">Parcela Anual (Capex)</div>
                <div class="value">R$ {parcela_anual:.0f} MM</div>
            </div>
            <div class="calc-operator">+</div>
            <div class="calc-item">
                <div class="label">O&M Anual</div>
                <div class="value">R$ {opex_anual:.0f} MM</div>
            </div>
            <div class="calc-item calc-total">
                <div class="label">Prêmio Anual Total</div>
                <div class="value">R$ {premio:.0f} MM</div>
            </div>
        </div>
    </div>

    <div class="section-title"><span>2</span> Desempenho e Retorno do Seguro (Sem Otimização de MUST)</div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 20%; text-align: left;">Cenário Base</th>
                    <th>Prêmio Pago</th>
                    <th>{metric_table_label} s/ BESS</th>
                    <th>{metric_table_label} c/ BESS</th>
                    <th>{metric_table_label} de Equilíbrio s/ BESS</th>
                    <th>Curtailment ONS / Geração</th>
                    <th>Clipping / Geração</th>
                    <th>Curtailment Recuperado</th>
                    <th>Caixa Adicionado Total</th>
                    <th>Redução CVaR 95%</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td class="col-scenario">
                        <span class="badge-ano badge-2025">2025 (Ano Normal)</span><br>
                        <span class="desc-cenario">PLD estável. Foco em eficiência física.</span>
                    </td>
                    <td class="val-premium">R$ {premio:.0f} MM / ano</td>
                    <td class="val-mod-orig">R$ {get_int('2025_base', 'mod_original_inteira')}/MWh</td>
                    <td class="val-mod-bess">R$ {get_int('2025_base', 'mod_com_bess_inteira')}/MWh</td>
                    <td class="val-mod-eq">{get_mod_equilibrio('2025_base')}<div class="val-factor">{get_fator_equilibrio('2025_base')}</div></td>
                    <td>{get_text('2025_base', 'curtailment_ons')}</td>
                    <td>{get_text('2025_base', 'curtailment_clip')}</td>
                    <td>{get_text('2025_base', 'curtailment_recuperado')}</td>
                    <td class="val-caixa">+ R$ {get_val('2025_base', 'caixa_adicionado_mm'):.0f} MM</td>
                    <td class="val-cvar">R$ {get_val('2025_base', 'delta_cvar_dia_mil'):.0f} mil / dia</td>
                </tr>
                <tr>
                    <td class="col-scenario">
                        <span class="badge-ano badge-2026">2026 (Ano Estressado)</span><br>
                        <span class="desc-cenario">PLD no Teto. Defesa contra volatilidade extrema.</span>
                    </td>
                    <td class="val-premium">R$ {premio:.0f} MM / ano</td>
                    <td class="val-mod-orig">R$ {get_int('2026_base', 'mod_original_inteira')}/MWh</td>
                    <td class="val-mod-bess">R$ {get_int('2026_base', 'mod_com_bess_inteira')}/MWh</td>
                    <td class="val-mod-eq">{get_mod_equilibrio('2026_base')}<div class="val-factor">{get_fator_equilibrio('2026_base')}</div></td>
                    <td>{get_text('2026_base', 'curtailment_ons')}</td>
                    <td>{get_text('2026_base', 'curtailment_clip')}</td>
                    <td>{get_text('2026_base', 'curtailment_recuperado')}</td>
                    <td class="val-caixa">+ R$ {get_val('2026_base', 'caixa_adicionado_mm'):.0f} MM</td>
                    <td class="val-cvar">R$ {get_val('2026_base', 'delta_cvar_dia_mil'):.0f} mil / dia</td>
                </tr>
            </tbody>
        </table>
        <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted); font-weight: 600;">
            {metric_table_label} de Equilíbrio s/ BESS: valor original recalculado aplicando um fator linear ao PLD de todas as horas dos dias em que a BESS descarrega, mantendo o despacho original, até o Caixa Adicionado Total igualar o Prêmio Anual Total.
        </p>
    </div>

    <div class="section-title"><span>3</span> Desempenho e Retorno do Seguro (Com Otimização de Redução de MUST)</div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 20%; text-align: left;">Cenário Otimizado</th>
                    <th>Prêmio Pago</th>
                    <th>{metric_table_label} s/ BESS</th>
                    <th>{metric_table_label} c/ BESS</th>
                    <th>{metric_table_label} de Equilíbrio s/ BESS</th>
                    <th>Curtailment ONS / Geração</th>
                    <th>Clipping / Geração</th>
                    <th>Curtailment Recuperado</th>
                    <th>Caixa Adicionado Total*</th>
                    <th>Redução CVaR 95%</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td class="col-scenario">
                        <span class="badge-ano badge-2025">2025 (Ano Normal)</span><br>
                        <span class="desc-cenario">{get_text('2025_must', 'nome').replace('2025 - 4h ', '').capitalize()}</span>
                    </td>
                    <td class="val-premium">R$ {premio:.0f} MM / ano</td>
                    <td class="val-mod-orig">R$ {get_int('2025_must', 'mod_original_inteira')}/MWh</td>
                    <td class="val-mod-bess">R$ {get_int('2025_must', 'mod_com_bess_inteira')}/MWh</td>
                    <td class="val-mod-eq">{get_mod_equilibrio('2025_must')}<div class="val-factor">{get_fator_equilibrio('2025_must')}</div></td>
                    <td>{get_text('2025_must', 'curtailment_ons')}</td>
                    <td>{get_text('2025_must', 'curtailment_clip')}</td>
                    <td>{get_text('2025_must', 'curtailment_recuperado')}</td>
                    <td class="val-caixa">+ R$ {get_val('2025_must', 'caixa_adicionado_mm'):.0f} MM</td>
                    <td class="val-cvar">R$ {get_val('2025_must', 'delta_cvar_dia_mil'):.0f} mil / dia</td>
                </tr>
                <tr>
                    <td class="col-scenario">
                        <span class="badge-ano badge-2026">2026 (Ano Estressado)</span><br>
                        <span class="desc-cenario">{get_text('2026_must', 'nome').replace('2026 - 4h ', '').capitalize()}</span>
                    </td>
                    <td class="val-premium">R$ {premio:.0f} MM / ano</td>
                    <td class="val-mod-orig">R$ {get_int('2026_must', 'mod_original_inteira')}/MWh</td>
                    <td class="val-mod-bess">R$ {get_int('2026_must', 'mod_com_bess_inteira')}/MWh</td>
                    <td class="val-mod-eq">{get_mod_equilibrio('2026_must')}<div class="val-factor">{get_fator_equilibrio('2026_must')}</div></td>
                    <td>{get_text('2026_must', 'curtailment_ons')}</td>
                    <td>{get_text('2026_must', 'curtailment_clip')}</td>
                    <td>{get_text('2026_must', 'curtailment_recuperado')}</td>
                    <td class="val-caixa">+ R$ {get_val('2026_must', 'caixa_adicionado_mm'):.0f} MM</td>
                    <td class="val-cvar">R$ {get_val('2026_must', 'delta_cvar_dia_mil'):.0f} mil / dia</td>
                </tr>
            </tbody>
        </table>
        <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted); font-weight: 600;">
            *O Caixa Adicionado Total nos cenários otimizados consolida o ganho operacional (Δ Saldo Líquido) somado à Economia Anual de TUST gerada pela redução do MUST contratado.
        </p>
    </div>

{cruzados_section}

</div>

</body>
</html>"""

    with open(caminho_saida, 'w', encoding='utf-8') as f:
        f.write(html_content)


def gerar_html_simplificado(
    dados,
    caminho_saida,
    results_by_key,
    must_reduction_by_key=None,
    mode=DEFAULT_MODULATION_MODE,
):
    """Gera um dashboard simplificado com prêmio e cenários de modulação 2025.

    Quadro 1: cálculo do prêmio anual de seguro (idêntico ao pitch completo).
    Quadro 2: três cenários sem MUST. Quadro 3 opcional: três cenários com o
    MUST reduzido/definido, quando essa fonte é recebida.
    """
    nome_proj = dados.get('nome_projeto', 'PROJETO SOLAR')
    pot_ac = dados.get('potencia_ac_mw', 0.0)
    gf_mw = dados.get('garantia_fisica_mw', 0.0)
    rep_gf = dados.get('representatividades_gf_pct', 0.0)

    energia = dados.get('energia_bess_mwh', 0)
    capex_total = dados.get('capex_total_mm', 0)
    parcela_anual = dados.get('parcela_capex_mm', 0)
    opex_anual = dados.get('opex_anual_mm', 0)
    premio = dados.get('premio_anual_seguro_mm', 0)
    vida_util = dados.get('vida_util_anos', 20)
    wacc_pct = dados.get('wacc_utilizado_pct', 0.0)

    premium_brl = premio * 1e6
    cenarios = _build_simplified_scenarios(results_by_key, premium_brl, mode)
    must_cenarios, must_section_label, must_description = (
        _build_simplified_must_scenarios(
            must_reduction_by_key,
            premium_brl,
            mode,
        )
    )
    metric_label = _modulation_mode_label(mode)
    metric_table_label = "Spread" if mode == MODULATION_MODE_ENERGIA else "Modulação"
    stressed_target = _target_modulation_for_mode(MODULACAO_ALVO_ESTRESSADO_BRL_MWH, mode)
    light_target = _target_modulation_for_mode(MODULACAO_ALVO_LEVE_BRL_MWH, mode)

    def _mod_eq_value(cenario):
        value = cenario.get('mod_equilibrio_brl_mwh')
        if value is None:
            return "n/a"
        return f"R$ {value:.0f}/MWh"

    def _fator_eq_value(cenario):
        value = cenario.get('fator_pld_descarga_equilibrio')
        if value is None:
            return "PLD dias c/ descarga n/a"
        return f"PLD dias c/ descarga × {value:.2f}"

    def _build_rows(cenarios, empty_message):
        badges = ['badge-2025', 'badge-2026', 'badge-2025']
        rows = []
        for idx, cenario in enumerate(cenarios):
            badge_class = badges[idx % len(badges)]
            rows.append(f"""<tr>
                    <td class="col-scenario">
                        <span class="badge-ano {badge_class}">{cenario.get('titulo', '-')}</span><br>
                        <span class="desc-cenario">{cenario.get('descricao', '')}</span>
                    </td>
                    <td class="val-premium">R$ {premio:.0f} MM / ano</td>
                    <td class="val-mod-orig">R$ {int(round(cenario.get('mod_original_inteira', 0)))}/MWh</td>
                    <td class="val-mod-bess">R$ {int(round(cenario.get('mod_com_bess_inteira', 0)))}/MWh</td>
                    <td class="val-mod-eq">{_mod_eq_value(cenario)}<div class="val-factor">{_fator_eq_value(cenario)}</div></td>
                    <td>{cenario.get('curtailment_ons', '0%')}</td>
                    <td>{cenario.get('curtailment_clip', '0%')}</td>
                    <td>{cenario.get('curtailment_recuperado', '0%')}</td>
                    <td class="val-caixa">+ R$ {cenario.get('caixa_adicionado_mm', 0.0):.0f} MM</td>
                    <td class="val-cvar">R$ {cenario.get('delta_cvar_dia_mil', 0.0):.0f} mil / dia</td>
                </tr>""")
        return ''.join(rows) if rows else (
            '<tr><td colspan="10" style="text-align:center;color:var(--text-muted);">'
            f'{empty_message}</td></tr>'
        )

    rows_html = _build_rows(cenarios, 'Sem dados de cenário 2025 disponíveis.')
    must_rows_html = _build_rows(
        must_cenarios,
        'Sem dados de cenário 2025 com MUST definido disponíveis.',
    )
    must_section_html = ""
    if must_cenarios:
        must_section_html = f"""
    <div class="section-title"><span>3</span> Desempenho e Retorno do Seguro — Cenários de Modulação com {must_section_label}: {must_description}</div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 20%; text-align: left;">Cenário 2025</th>
                    <th>Prêmio Pago</th>
                    <th>{metric_table_label} s/ BESS</th>
                    <th>{metric_table_label} c/ BESS</th>
                    <th>{metric_table_label} de Equilíbrio s/ BESS</th>
                    <th>Curtailment ONS / Geração</th>
                    <th>Clipping / Geração</th>
                    <th>Curtailment Recuperado</th>
                    <th>Caixa Adicionado Total</th>
                    <th>Redução CVaR 95%</th>
                </tr>
            </thead>
            <tbody>
                {must_rows_html}
            </tbody>
        </table>
        <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted); font-weight: 600;">
            Cenários com {must_description} mantêm o despacho com cap de MUST e,
            nos casos estressado e moderado, escalam apenas o PLD dentro do piso/teto.
            O Caixa Adicionado Total inclui o ganho operacional mais a economia anual de TUST.
        </p>
    </div>
"""

    html_content = f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Simplificado: BESS {nome_proj}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap');

        :root {{
            --navy: #0f172a;
            --blue: #1d4ed8;
            --green: #059669;
            --emerald: #10b981;
            --bg-light: #f8fafc;
            --border: #e2e8f0;
            --text-dark: #1e293b;
            --text-muted: #64748b;
        }}

        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Inter', sans-serif; }}
        body {{ background-color: #e2e8f0; color: var(--text-dark); padding: 2rem; }}

        .container {{ max-width: 1700px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); padding: 2rem; overflow: hidden; }}

        .header {{ border-bottom: 2px solid var(--border); padding-bottom: 1.5rem; margin-bottom: 2rem; display: flex; justify-content: space-between; align-items: flex-end; }}
        .header h1 {{ font-size: 1.8rem; font-weight: 800; color: var(--navy); text-transform: uppercase; letter-spacing: 0.5px; }}
        .header h1 span {{ color: var(--blue); }}
        .header p {{ color: var(--text-muted); font-size: 1.1rem; font-weight: 600; }}

        .project-summary {{ display: flex; gap: 2rem; background: var(--navy); color: white; padding: 1.2rem 2rem; border-radius: 8px; margin-bottom: 2rem; }}
        .summary-item {{ display: flex; flex-direction: column; }}
        .summary-item .s-label {{ font-size: 0.75rem; color: #94a3b8; font-weight: 700; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 2px; }}
        .summary-item .s-value {{ font-size: 1.2rem; font-weight: 700; }}

        .section-title {{ font-size: 1.25rem; font-weight: 700; color: var(--navy); margin-bottom: 1rem; display: flex; align-items: center; }}
        .section-title span {{ background: var(--blue); color: white; width: 28px; height: 28px; display: inline-flex; justify-content: center; align-items: center; border-radius: 50%; font-size: 0.9rem; margin-right: 10px; }}

        .calc-box {{ background: var(--bg-light); border: 1px solid var(--border); border-radius: 10px; padding: 1.5rem; margin-bottom: 2.5rem; }}
        .calc-grid {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 1rem; align-items: center; }}
        .calc-item {{ text-align: center; }}
        .calc-item .label {{ font-size: 0.85rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase; margin-bottom: 0.5rem; }}
        .calc-item .value {{ font-size: 1.4rem; font-weight: 800; color: var(--navy); }}
        .calc-operator {{ text-align: center; font-size: 1.5rem; font-weight: 800; color: var(--text-muted); }}
        .calc-total {{ background: linear-gradient(135deg, var(--green), var(--emerald)); color: white; padding: 1rem; border-radius: 8px; box-shadow: 0 4px 10px rgba(5,150,105,0.2); }}
        .calc-total .label {{ color: rgba(255,255,255,0.9); }}
        .calc-total .value {{ color: white; font-size: 1.6rem; }}

        .table-container {{ margin-bottom: 2.5rem; }}
        table {{ width: 100%; border-collapse: collapse; text-align: center; }}
        th {{ background: #1e293b; color: white; padding: 1rem; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.5px; border: 1px solid #1e293b; }}
        td {{ padding: 1.2rem 0.8rem; border: 1px solid var(--border); font-size: 1.05rem; font-weight: 600; color: var(--text-dark); vertical-align: middle; }}

        tr:nth-child(even) td {{ background-color: var(--bg-light); }}

        .col-scenario {{ text-align: left; background: var(--bg-light); }}
        .badge-ano {{ display: inline-block; padding: 4px 10px; border-radius: 6px; font-size: 0.85rem; font-weight: 700; margin-bottom: 4px; }}
        .badge-2025 {{ background: #e0f2fe; color: #0369a1; }}
        .badge-2026 {{ background: #fee2e2; color: #b91c1c; }}
        .desc-cenario {{ font-size: 0.9rem; color: var(--text-muted); font-weight: 400; }}

        .val-premium {{ color: var(--text-muted); font-size: 0.95rem; }}
        .val-mod-orig {{ color: #b91c1c; }}
        .val-mod-bess {{ color: var(--blue); }}
        .val-mod-eq {{ color: var(--green); }}
        .val-factor {{ color: var(--text-muted); font-size: 0.78rem; font-weight: 600; margin-top: 4px; }}
        .val-caixa {{ color: var(--green); font-size: 1.2rem; font-weight: 800; }}
        .val-cvar {{ color: var(--blue); font-size: 0.95rem; }}
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <div>
            <h1>Ativo de Proteção de Caixa — BESS <span>{nome_proj}</span></h1>
            <p>Apresentação Executiva Simplificada: Prêmio e Cenários de Modulação 2025</p>
        </div>
    </div>

    <div class="project-summary">
        <div class="summary-item">
            <div class="s-label">Projeto Executivo</div>
            <div class="s-value" style="color: var(--emerald);">{nome_proj}</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Potência Inicial AC</div>
            <div class="s-value">{pot_ac:.0f} MWac</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Garantia Física (GF)</div>
            <div class="s-value">{gf_mw:.0f} MWmédio</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Dimensionamento BESS</div>
            <div class="s-value">{energia:.0f} MWh</div>
        </div>
        <div class="summary-item" style="border-left: 1px solid #334155; padding-left: 1.5rem;">
            <div class="s-label">Taxa de Cobertura Diária da GF</div>
            <div class="s-value" style="color: var(--emerald);">{rep_gf:.0f}%</div>
        </div>
    </div>

    <div class="section-title"><span>1</span> Cálculo do Prêmio Anual de Seguro</div>
    <div class="calc-box">
        <div class="calc-grid">
            <div class="calc-item">
                <div class="label">Capex Total</div>
                <div class="value">R$ {capex_total:.0f} MM</div>
            </div>
            <div class="calc-item" style="border-left: 1px solid var(--border); border-right: 1px solid var(--border);">
                <div class="label">Premissas de Custo</div>
                <div class="value" style="font-size: 1rem; margin-top: 5px;">Taxa: {wacc_pct:.2f}% a.a.<br>Vida: {vida_util} anos</div>
            </div>
            <div class="calc-item">
                <div class="label">Parcela Anual (Capex)</div>
                <div class="value">R$ {parcela_anual:.0f} MM</div>
            </div>
            <div class="calc-operator">+</div>
            <div class="calc-item">
                <div class="label">O&M Anual</div>
                <div class="value">R$ {opex_anual:.0f} MM</div>
            </div>
            <div class="calc-item calc-total">
                <div class="label">Prêmio Anual Total</div>
                <div class="value">R$ {premio:.0f} MM</div>
            </div>
        </div>
    </div>

    <div class="section-title"><span>2</span> Desempenho e Retorno do Seguro — Cenários de Modulação 2025</div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 20%; text-align: left;">Cenário 2025</th>
                    <th>Prêmio Pago</th>
                    <th>{metric_table_label} s/ BESS</th>
                    <th>{metric_table_label} c/ BESS</th>
                    <th>{metric_table_label} de Equilíbrio s/ BESS</th>
                    <th>Curtailment ONS / Geração</th>
                    <th>Clipping / Geração</th>
                    <th>Curtailment Recuperado</th>
                    <th>Caixa Adicionado Total</th>
                    <th>Redução CVaR 95%</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <p style="margin-top: 1rem; font-size: 0.9rem; color: var(--text-muted); font-weight: 600;">
            Cenários estressado e moderado mantêm o despacho de 2025 e escalam o PLD por um fator uniforme,
            limitado ao piso (R$ {PLD_FLOOR_BRL_PER_MWH:.2f}/MWh) e ao teto (R$ {PLD_CEILING_BRL_PER_MWH:.2f}/MWh),
            até o {metric_label.lower()} s/ BESS atingir R$ {stressed_target:.0f}/MWh e R$ {light_target:.0f}/MWh, respectivamente.
        </p>
    </div>

{must_section_html}
</div>

</body>
</html>"""

    with open(caminho_saida, 'w', encoding='utf-8') as f:
        f.write(html_content)
