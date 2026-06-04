import os
import re
import numpy_financial as npf
from bs4 import BeautifulSoup

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
        linhas = tab.find('tbody').find_all('tr')
        for linha in linhas:
            colunas = linha.find_all('td')
            if not colunas or len(colunas) < 17:
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
                
                curt_ger = str(int(round(limpar_numero(colunas[13].text)))) + "%" if colunas[13].text.strip() != "—" else "0%"
                curt_rec = str(int(round(limpar_numero(colunas[15].text)))) + "%" if colunas[15].text.strip() != "—" else "0%"

                dados[chave] = {
                    'nome': cenario_nome,
                    'mod_original_inteira': int(round(mod_original)),
                    'mod_com_bess_inteira': int(round(mod_com_bess)),
                    'caixa_adicionado_mm': caixa_adicionado,
                    'curtailment_geracao': curt_ger,
                    'curtailment_recuperado': curt_rec,
                    'delta_cvar_dia_mil': limpar_numero(colunas[16].text)
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

def gerar_html_apresentacao(dados, caminho_saida):
    
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
        
        .container {{ max-width: 1550px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.05); padding: 2rem; overflow: hidden; }}
        
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
                    <th>Modulação s/ BESS</th>
                    <th>Modulação c/ BESS</th>
                    <th>Curtailment / Geração</th>
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
                    <td>{get_text('2025_base', 'curtailment_geracao')}</td>
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
                    <td>{get_text('2026_base', 'curtailment_geracao')}</td>
                    <td>{get_text('2026_base', 'curtailment_recuperado')}</td>
                    <td class="val-caixa">+ R$ {get_val('2026_base', 'caixa_adicionado_mm'):.0f} MM</td>
                    <td class="val-cvar">R$ {get_val('2026_base', 'delta_cvar_dia_mil'):.0f} mil / dia</td>
                </tr>
            </tbody>
        </table>
    </div>

    <div class="section-title"><span>3</span> Desempenho e Retorno do Seguro (Com Otimização de Redução de MUST)</div>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th style="width: 20%; text-align: left;">Cenário Otimizado</th>
                    <th>Prêmio Pago</th>
                    <th>Modulação s/ BESS</th>
                    <th>Modulação c/ BESS</th>
                    <th>Curtailment / Geração</th>
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
                    <td>{get_text('2025_must', 'curtailment_geracao')}</td>
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
                    <td>{get_text('2026_must', 'curtailment_geracao')}</td>
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

</div>

</body>
</html>"""

    with open(caminho_saida, 'w', encoding='utf-8') as f:
        f.write(html_content)