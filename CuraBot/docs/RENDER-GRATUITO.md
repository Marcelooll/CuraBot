# Render Free + Neon Free

Modo web preparado; ainda depende de publicação, configuração das contas e teste real. Use **Web Service Free**, não Background Worker ou o Postgres gratuito temporário do Render. O Neon guarda apenas seleções, fila, relatórios e identificadores de arquivos do Telegram. Caso um provedor exija cartão, não prossiga com pagamento.

## Configurar

1. Conecte o repositório atualizado no Render. O JSON n8n antigo sozinho não funciona aqui.
2. Crie um projeto Free em https://console.neon.tech. Em Connect, desative **Connection pooling** e copie a conexão direta PostgreSQL com SSL. Ela contém uma senha: coloque-a apenas nos segredos do Render.
3. Em New Web Service, escolha Python 3 e configure:

| Campo | Valor |
| --- | --- |
| Build Command | `pip install -r requirements-cloud.txt` |
| Start Command | `gunicorn --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:$PORT 'webapp:create_app()'` |
| Instance Type | Free |
| Health Check Path | `/healthz` |
| TELEGRAM_BOT_TOKEN | Token do bot no campo secreto |
| DATABASE_URL | Conexão direta do Neon com SSL |
| WEBHOOK_SECRET | Segredo aleatório com 32 a 256 letras, números, underscore ou hífen |
| PYTHON_VERSION | `3.12.11` |
| ALLOWED_USER_IDS | Vazio, para permitir qualquer usuário |

Blueprint: render.yaml e render-free.yaml selecionam Free e geram o segredo automaticamente. render-paid.yaml é uma alternativa paga antiga, fora do orçamento atual. Gemini é opcional, não está incluído na hospedagem gratuita e não é necessário para CSV/Excel ou perguntas básicas.

## Ativar e testar

1. Publique e confira `/healthz` na URL HTTPS do Render. `status: ok` confirma o servidor web, não o funcionamento completo.
2. Numa sessão local de administração, configure as mesmas variáveis TELEGRAM_BOT_TOKEN e WEBHOOK_SECRET, além de PUBLIC_URL com a URL HTTPS do Render sem caminho. Nunca publique esses segredos no GitHub.
3. Pare a instância local quando não houver pedido em andamento. Execute `python activate_webhook.py`. O script configura o webhook sem apagar mensagens pendentes. Subir o servidor web não muda o webhook automaticamente.
4. Teste `/start`, envio de arquivo sem comando, `/diagnostico`, `/arrumar` e `/baixar`. Teste outro usuário em conversa privada.
5. Reinicie o Render, teste a seleção e `/baixar` novamente; depois desligue o PC e teste pelo celular. Só declare a migração concluída após essa validação real.

O Docker/compose é para servidores contínuos, não para este modo gratuito. Para voltar ao PC, pare o serviço remoto e use o procedimento local `--migrate` para remover o webhook.

## Persistência e limites

- O webhook grava a mensagem no PostgreSQL antes de responder HTTP 200. Falha de banco retorna 503 para nova tentativa do Telegram.
- Arquivo sem comando salva somente metadados. Só comandos criam trabalhos de processamento.
- IDs únicos evitam enfileirar o mesmo pedido duas vezes. Uma interrupção entre envio e confirmação pode repetir respostas/arquivos: não há garantia de exatamente uma entrega.
- Um lock de sessão PostgreSQL coordena a execução. Use conexão direta, uma instância e um worker; não use transaction pooling. O lock precisa de validação no banco remoto.
- Após cada trabalho, os arquivos temporários são apagados. `/baixar` usa os identificadores retornados pelo Telegram. Entrega incompleta exige repetir o comando original. Telegram não é backup permanente; salve os resultados importantes.
- Seleções e resultados expiram após 7 dias, com limpeza nos ciclos de processamento. Pedidos pendentes não são apagados por essa retenção.
- Limite de entrada nesta configuração: **20 MiB** por arquivo ou link. CPU/memória podem limitar arquivos menores também. O benchmark grande local não valida o plano gratuito.
- Um processamento por vez; até três pedidos pendentes por conversa e vinte no total. Respostas de conversa/status podem aguardar o processamento atual.
- Após inatividade, o Render pode suspender e descartar disco temporário; a primeira mensagem pode demorar cerca de um minuto. Pedidos interrompidos ficam no banco para retomada quando o serviço acordar. Não há garantia de disponibilidade ou prazo.
- As duas contas têm franquias. Monitore uso e não habilite plano pago para este projeto. Metadados no banco também consomem espaço.
- Chats privados isolam usuários; membros de um grupo compartilham seu contexto.

## O que foi testado

Testes locais usam SQLAlchemy com SQLite temporário para verificar webhook, persistência lógica, mensagens repetidas, retomada e reenvio sem arquivos locais. Não substituem testes do PostgreSQL/lock, Gunicorn/Linux, reinício do Render ou Telegram real; esses dependem das contas e da publicação.

Fontes: https://render.com/docs/free, https://neon.com/variable-load, https://core.telegram.org/bots/api#setwebhook.
