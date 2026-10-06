# CuraBot 2

Para rodar com o PC desligado no plano gratuito, siga [RENDER-GRATUITO.md](RENDER-GRATUITO.md): webhook Render Free + PostgreSQL Neon Free, entradas até 20 MiB e retenção de metadados de 7 dias. A hospedagem precisa ser configurada, ativada e validada em contas externas. Outras opções estão em [NUVEM.md](NUVEM.md).

Testes completos, incluindo modo web: instale `requirements-cloud.txt` e execute `python -m unittest discover -p 'test*.py'`. A suíte cloud usa SQLite temporário e não substitui integração PostgreSQL/Telegram/Render.

Bot independente do n8n para organizar tabelas e explicar a qualidade dos dados. Cada pedido entrega CSVs organizados e um relatório em português. Dados ausentes e ambíguos são preservados para revisão.

## Tratamento e diagnóstico

- Normaliza cabeçalhos, separa colunas com nomes repetidos, retira espaços das bordas e linhas inteiramente vazias.
- Preserva códigos com zeros iniciais, negativos e campos extras em linhas de largura irregular.
- Conta campos vazios, repetições integrais após normalização, formatos numéricos e datas ISO inválidas. O perfil sinaliza mistura de texto/números.
- Calcula estatísticas de números com formato inequívoco. Números com vírgula são preservados sem inferir o separador. Somas de códigos ou categorias podem não ter significado.
- Informa o que mudou e quando nada mudou. Não inventa dados, não exclui extremos e não corrige regras de negócio por suposição.
- Remove repetições integrais somente com `/deduplicar`. Linhas iguais podem representar pessoas/eventos diferentes.
- CSV/Parquet são lidos incrementalmente; a detecção de duplicatas usa disco. Saídas são divididas em partes de até 40 MiB.
- A fila é persistente. Reinícios retomam pedidos incompletos; uma interrupção no envio pode repetir entregas.

## Comandos

Envie arquivo ou link direto para selecioná-lo. Nada é baixado ou processado até um comando explícito, enviado depois ou na legenda. Cada comando usa a entrada original selecionada; para encadear operações, reenvie o resultado. A seleção persiste nos reinícios.

| Comando | Resultado |
| --- | --- |
| `/start`, `/help`, `/comandos` | Instruções |
| `/arrumar` | Cabeçalhos, espaços nas bordas, linhas vazias e proteção contra fórmulas |
| `/diagnostico` | Diagnóstico sem limpeza e sem CSV |
| `/vazios` | Contagem de ausências e relatório, sem CSV |
| `/duplicatas` | Contagem de repetições integrais, sem CSV |
| `/cabecalhos` | Padroniza somente cabeçalhos |
| `/espacos` | Retira somente espaços nas bordas das células |
| `/linhas_vazias` | Remove somente linhas totalmente vazias |
| `/separador ponto_virgula` | CSV separado por `;`; também aceita `virgula`, `tab`, `barra` |
| `/pontuacao valor br_para_us` | Na coluna valor, converte `1.234,56` em `1234.56` |
| `/pontuacao valor us_para_br` | Na coluna valor, converte `1,234.56` em `1234,56` |
| `/arquivo` | Mostra entrada selecionada |
| `/status` | Andamento do último pedido |
| `/relatorio` | Último diagnóstico disponível |
| `/baixar` | Reenvia o último resultado disponível |
| `/review` na legenda | Somente diagnóstico, sem Gemini |
| `/csreview` na legenda | CSVs e diagnóstico |
| `/deduplicar` | Remove somente repetições integrais, sem retirar espaços |

`/arrumar` não preenche ausências, remove duplicatas ou adivinha pontuação. `/review` equivale a `/diagnostico`; `/csreview` a `/arrumar`; `/decimais` a `/pontuacao`.

Em `/pontuacao`, use o identificador da coluna exibido no diagnóstico. BR significa ponto de milhar e vírgula decimal; US significa vírgula de milhar e ponto decimal. A conversão remove agrupamentos de milhar e troca o decimal. Agrupamentos inválidos, zeros iniciais, moedas, percentuais e textos são preservados e contados como fora da regra. Pontuação de frases e outras colunas não muda. É necessário escolher a coluna e a convenção explicitamente.

Operações específicas preservam os demais valores e cabeçalhos. Saídas são CSV UTF-8, com aspas e escapes necessários. Excel/Parquet são convertidos para representação tabular, sem preservar formatação visual. Campos excedentes de linhas irregulares são mantidos em colunas extras com aviso no relatório. Pedidos antigos sem comando explícito são recusados.

Perguntas locais: “o que mudou?”, “quais campos estão vazios?”, “há duplicatas?”, “quantos registros?”, “qual a média de age?” e “aceita bases maiores?”. Use o nome exato da coluna. São intenções conhecidas, não uma conversa geral ilimitada. Mensagens livres não executam alterações nos arquivos.

## Limites

- Telegram: até 20 MiB por entrada. Para maiores, use link público direto.
- CSV/Parquet/XLSX por link ou arquivo local: teto de 1 GiB. É um limite configurado, não garantia de tempo/capacidade para qualquer arquivo. Volume, colunas, conteúdo e máquina afetam o resultado.
- Até 2.000 colunas; campos CSV individuais até 2 MiB. Uma linha que exceda uma parte de saída é recusada.
- XLS legado, PDF e texto: até 20 MiB. XLSX descompactado: até 2 GiB. XLS pode consumir memória proporcional ao arquivo; prefira CSV/Parquet para volume grande.
- Saídas de até 40 MiB por parte, enviadas sequencialmente. Há reconciliação das contagens de entrada e saída.
- Um arquivo processado por vez; até três pedidos pendentes por conversa e vinte no total. `/status` funciona durante o processamento. Uma chamada opcional ao Gemini pode atrasar respostas enquanto aguarda a API.
- Computador ligado e conectado. Não inclui hospedagem nem inicialização automática com o Windows.
- ZIP e bases compostas por arquivos relacionados não são um único pedido suportado. Cadastros como CNPJ exigem conhecer cabeçalhos, esquema e regras da fonte.

## PDF e Gemini

PDF com tabelas reconhecíveis tem extração local. A primeira linha de cada tabela vira cabeçalho. Cabeçalhos diferentes são recusados para evitar misturas. O relatório informa páginas sem tabelas; texto fora das tabelas não é convertido. Confira sempre a extração com o original.

PDF sem tabelas reconhecidas, TXT e HTML usam Gemini para extrair registros. Isso exige chave e revisão, sem garantia de cobertura integral. PDFs escaneados precisam de OCR externo (não implementado). Texto acima de 100.000 caracteres é recusado, sem corte silencioso.

Com Gemini configurado, perguntas gerais usam a pergunta e parte do relatório, não a base inteira. Resultados da IA nunca são executados como código ou ordens de alteração.

## Windows

No PowerShell desta pasta:

```powershell
.\iniciar.ps1 -Configurar -Diagnostico
.\iniciar.ps1
```

Tokens são inseridos com entrada oculta; Enter mantém os atuais. `.env` guarda as credenciais e é ignorado pelo Git. Não compartilhe esse arquivo. O diagnóstico testa o Telegram e apenas a presença da configuração Gemini, sem geração paga.

Se houver webhook, desative o fluxo no n8n e use `.\iniciar.ps1 -Migrar`. A migração mantém mensagens pendentes. Execute uma instância: a porta local 47631 impede outra nesta máquina, sem receber tráfego externo.

## Arquivo local

Python 3.11+ com `requirements.txt` instalado:

```sh
python curabot.py --input caminho/base.parquet --output resultado
python curabot.py --input caminho/base.csv --output resultado --deduplicate
```

A segunda opção remove repetições integrais; não substitui regras de identidade do negócio.

## Armazenamento e privacidade

`.state/` guarda fila, metadados de mensagens e resultados para consultas e `/baixar`. Entradas são removidas após sucesso; falhas podem deixar arquivos parciais. Não há expiração automática. O índice temporário de duplicatas é removido ao final. Reserve disco para entrada, saídas e índice durante o trabalho.

`ALLOWED_USER_IDS` no `.env` restringe usuários por IDs separados por vírgula. Sem lista, qualquer usuário do bot pode consumir recursos. Relatórios pertencem à conversa; grupos compartilham contexto. Prefira conversa privada para dados confidenciais.

Planilhas são processadas localmente. Extração e conversa que usarem Gemini enviam o conteúdo necessário ao Google. Logs de erro não imprimem chaves nem conteúdo dos arquivos.

## Testes

```sh
python -m unittest -v test_service.py test_curabot.py
```

Os testes cobrem preservação, transformação, divisão de arquivos, formatos, fila, reinício, isolamento entre conversas e consultas ao relatório. `VALIDACAO.md` registra o teste de escala real.

Origem: https://github.com/Marcelooll/CuraBot

Referências: https://core.telegram.org/bots/api e https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
