# CuraBot fora do computador pessoal

**Escolha atual: gratuito e sem cartão.** Siga [RENDER-GRATUITO.md](RENDER-GRATUITO.md). As alternativas abaixo são referências anteriores; Oracle exige cartão e o worker Render é pago. O render.yaml padrão agora configura o serviço web Free; o worker pago ficou em render-paid.yaml.

Preparação de implantação; a existência destes arquivos não significa que o serviço já esteja hospedado.

O Telegram é a interface pública. Não é necessário comprar domínio, abrir portas no roteador nem publicar um site: o processo consulta o Telegram por HTTPS. É preciso um servidor com processo contínuo, acesso de saída à internet e armazenamento persistente. Use uma única instância com este token; pare a cópia do PC antes de iniciar a da nuvem, para evitar disputa pelo recebimento das mensagens.

## Opção gratuita: Oracle Cloud Always Free

Preferência do projeto: hospedagem sem mensalidade. Uma máquina virtual Always Free pode executar o pacote Docker continuamente, sem depender do computador pessoal. Essa opção ainda depende de cadastro e disponibilidade de capacidade na conta/região; não foi implantada.

A Oracle exige um cartão aceito para verificar identidade e pode fazer uma reserva temporária de validação. A conta não deve ser convertida para Pay As You Go. Use apenas recursos identificados como Always Free no painel e dentro dos limites totais da conta; créditos promocionais de 30 dias não são a solução permanente.

Depois de criar a conta, escolha uma VM Linux elegível para Always Free na região principal, com armazenamento também dentro da franquia. Confira a elegibilidade e os limites exibidos antes de criar: disponibilidade e franquias podem mudar. A seção Docker abaixo fornece a configuração do bot. Não é necessário um domínio ou servidor web público.

Always Free não oferece garantia de disponibilidade: pode faltar capacidade para criar a VM, e instâncias consideradas ociosas podem ser retomadas pelo provedor. Não gere tráfego ou consumo artificial para contornar essa regra. Guarde backups dos resultados necessários.

Cadastro: https://signup.cloud.oracle.com/
Regras de cadastro e cartão: https://www.oracle.com/cloud/free/faq/
Recursos e ociosidade: https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm

Se não for possível validar o cadastro com cartão, será necessário escolher outra infraestrutura e possivelmente adaptar a execução para webhooks, com limites menores. A versão atual de polling com SQLite persistente não deve ser publicada em um web service gratuito que suspende e descarta disco, prometendo funcionamento contínuo.

## Opção Render (paga; fora do orçamento atual)

O arquivo render.yaml configura um background worker e disco persistente de 10 GB. É uma opção paga; confira o preço mostrado no painel antes da criação. O plano inicial tem 512 MB, sem garantia de capacidade para todos os arquivos grandes, sobretudo Excel/PDF. Ajuste conforme uso e testes na hospedagem.

1. Coloque os arquivos desta pasta na raiz do repositório de implantação, excluindo .env, .state, .offset e caches. O repositório original só é atualizado quando esses arquivos forem publicados nele.
2. Na conta Render, crie um Blueprint a partir desse repositório. O painel deve detectar render.yaml.
3. Configure TELEGRAM_BOT_TOKEN no campo secreto solicitado pelo painel. GEMINI_API_KEY é opcional. Não grave tokens no GitHub ou no YAML.
4. Antes de ativar o processo remoto, pare o processo local. Não use duas instâncias com o mesmo token.
5. Confira os logs de conexão e teste pelo Telegram: envie um CSV sem legenda (apenas seleção), depois /diagnostico e /arrumar. Faça também um teste com outro usuário, em conversa privada.
6. Desligue o PC e repita o teste pelo celular. Reinicie o serviço remoto e confira se a seleção e /baixar continuam disponíveis. Só então considere a migração validada.

Documentação: https://render.com/docs/background-workers e https://render.com/docs/disks. O tier gratuito de web services que suspende por inatividade não atende a este processo contínuo de polling.

## Servidor Linux com Docker Compose

Copie o pacote sem dados privados para o servidor e configure .env nele com TELEGRAM_BOT_TOKEN. Deixe ALLOWED_USER_IDS vazio para permitir qualquer usuário. Depois de parar a instância local:

```sh
docker compose up -d --build
docker compose logs --tail=50 curabot
```

O volume curabot_data mantém a fila, seleções e resultados entre reinícios e atualizações. Não use docker compose down -v, pois isso apagaria esse volume. Faça backup do volume com o serviço parado. Habilite a inicialização do Docker no servidor; a política unless-stopped reinicia o bot após falhas e reinícios, exceto se ele tiver sido parado manualmente.

## Acesso e capacidade

Qualquer pessoa pode iniciar conversa privada com o bot quando ALLOWED_USER_IDS estiver vazio. Arquivos e relatórios são separados por conversa; membros de um mesmo grupo compartilham a conversa, portanto use chats privados para arquivos individuais. Conversa livre não inicia processamento.

A fila atual processa um arquivo por vez, com até três pedidos pendentes por conversa e vinte no total. Hospedar na nuvem não torna a capacidade ilimitada. Resultados são retidos para /baixar e ocupam disco; monitore uso e estabeleça retenção antes de divulgação em grande escala. Não há limpeza automática de históricos nesta versão. Limites atuais: 20 MiB por upload Telegram e 1 GiB por link, dependentes da capacidade do servidor.

CURABOT_STATE_DIR define a pasta persistente; sem a variável, permanece .state ao lado do programa. A cópia local do histórico não é transferida automaticamente para a nuvem. Usuários podem reenviar os arquivos na instalação nova.

Validação local: testes do motor, comandos e persistência; Docker e a implantação real precisam ser validados na hospedagem escolhida. Nenhuma assinatura de hospedagem foi contratada por este pacote.
