# Validação do CuraBot 2

## Titanic — entrega real pelo Telegram

O usuário enviou o CSV original ao bot e recebeu CSV e relatório. Os arquivos recebidos foram comparados localmente com a entrada: 891 registros, 15 colunas e valores idênticos. Ausências: age 177, deck 688, embarked 2 e embark_town 2. As 107 repetições integrais foram verificadas independentemente e preservadas. Elas não comprovam duplicidade de passageiros.

## Escala — base governamental real (benchmark anterior aos comandos específicos)

Fonte: NYC Taxi & Limousine Commission, Yellow Taxi, janeiro de 2025.
Página oficial: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page
Arquivo: https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2025-01.parquet

- Entrada: 59,158,238 bytes, 20 colunas.
- Registros processados/exportados: 3,475,226.
- Duração do processamento: 846.109 segundos.
- Pico de memória RSS observado no processo Python (amostragem a cada 0,2 segundo): 147.6 MiB. Não representa a memória de todo o sistema ou cache do sistema operacional.
- Saída: 368,514,643 bytes em 9 CSVs, cada um até 40 MiB.
- Comparação independente: 3,475,226 registros comparados na ordem original, célula por célula, sem divergências na representação CSV. Nulos/NaN são campos vazios e datas usam ISO.
- Conferência integral da saída: 89.59 segundos adicionais.

O download foi feito por conexão pública validada e o processamento usou o mesmo motor do bot. Os nove arquivos grandes não foram enviados ao Telegram durante esse teste. A entrega real de arquivo pequeno e relatório foi confirmada pelo usuário; a divisão e recuperação de envio foram verificadas em testes automatizados.

Este resultado valida esse arquivo nesta máquina. Não garante que qualquer arquivo até 1 GiB terá o mesmo desempenho. O índice temporário de duplicatas e os CSVs exigem espaço em disco adicional. O motor ainda é de processamento local, com um trabalho de arquivo por vez.

## Testes de regressão

51 testes passaram na versão atual, incluindo sete testes de webhook/persistência SQLAlchemy com SQLite, sem validar PostgreSQL remoto ou implantação Render. Também foi verificada a persistência em diretório configurável para nuvem: comandos explícitos, nenhuma execução/download sem comando, seleção persistente, operações isoladas, pontuação numérica e separadores, preservação de códigos e negativos, campos com quebras de linha, cabeçalhos repetidos, larguras irregulares, encodings, proteção de fórmulas, CSV/Excel/Parquet, divisão/reconciliação, limites, URLs internas e redirecionamento, fila persistente, retomada, falha de envio, reenvio, isolamento entre conversas e perguntas locais. O benchmark grande acima não foi repetido após a adição dos comandos específicos.

O teste de extração de tabelas PDF usa simulação do extrator. Não é uma validação de fidelidade para PDFs arbitrários. Gemini não foi configurado nem validado com chamadas reais. OCR não está implementado. A conversa local reconhece intenções documentadas, não perguntas gerais ilimitadas.
