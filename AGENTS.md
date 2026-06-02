<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
at `specs/003-must-reduction-optimizer/plan.md`.
<!-- SPECKIT END -->
## Projetos de Referência

### BigQuery Price Data
- **Caminho local:** /home/cver/projects/copilot/modulacao/modulacao/Berto
- **Descrição:** Módulo que conecta ao BigQuery e retorna dados de preço de energia e da PSR_2025
- **Arquivos principais:** analise_bateria_modulacao.ipynb, script_compartilhar_comentado.ipynb, data_reader.py
- **Como usar:** Importar diretamente via sys.path ou adaptar a interface existente
- **NÃO reescrever** a lógica de conexão — integrar via importação