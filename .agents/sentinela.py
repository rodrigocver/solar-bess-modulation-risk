import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Importa o nosso agente financeiro que está na mesma pasta (.agents)
import bess_pitch_agent

class WatcherHandler(FileSystemEventHandler):
    def on_created(self, event):
        # 1. Ignora se for uma pasta sendo criada
        if event.is_directory:
            return
            
        # 2. Verifica se o arquivo criado é exatamente o relatório que queremos
        if os.path.basename(event.src_path) == 'relatorio_anos_2025_2026_completo.html':
            print(f"\n[+] Novo relatório detectado: {event.src_path}")
            
            # 3. Espera 2 segundos para garantir que o simulador terminou de salvar o arquivo
            time.sleep(2)
            
            # 4. Descobre a pasta exata onde o relatório está (ex: a pasta do otimizador)
            pasta_origem = os.path.dirname(event.src_path)
            caminho_saida = os.path.join(pasta_origem, 'relatorio_anos_2025_2026.html')
            
            # 5. Aciona o Agente Pitch Deck
            try:
                print("    Iniciando a extração de KPIs e cálculos financeiros...")
                dados = bess_pitch_agent.extrair_kpis_do_relatorio(event.src_path)
                dados_finais = bess_pitch_agent.calcular_premio_seguro(dados)
                
                print("    Gerando a apresentação HTML...")
                bess_pitch_agent.gerar_html_apresentacao(dados_finais, caminho_saida)
                
                print(f"[OK] Pitch executivo gerado com sucesso em:\n     {caminho_saida}")
            except Exception as e:
                print(f"[ERRO] Falha ao gerar o pitch deck para este relatório. Detalhes: {e}")

def iniciar_sentinela(caminho_monitorado):
    observer = Observer()
    event_handler = WatcherHandler()
    
    # recursive=True garante que ele olhe todas as subpastas criadas pela simulação
    observer.schedule(event_handler, caminho_monitorado, recursive=True)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        print("\nSentinela desativado.")
    observer.join()

if __name__ == "__main__":
    # Caminho base dos outputs no WSL
    pasta_output = "/home/cver/projects/solar-bess-modulation-risk/output/"
    
    print("===================================================")
    print("👁️  Sentinela do Agente BESS Ativado")
    print(f"📂 Monitorando novos relatórios em: {pasta_output}")
    print("Pressione Ctrl+C para encerrar.")
    print("===================================================")
    
    iniciar_sentinela(pasta_output)