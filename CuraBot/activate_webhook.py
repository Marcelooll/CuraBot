"""Run once after deployment is healthy and local polling has been stopped."""
import os
import re
import urllib.parse
import runtime


def main():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    secret = os.environ.get('WEBHOOK_SECRET', '')
    url = os.environ.get('PUBLIC_URL', os.environ.get('RENDER_EXTERNAL_URL', '')).rstrip('/')
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('PUBLIC_URL deve ser a URL HTTPS pública do serviço, sem caminho.')
    if not token or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise ValueError('Configure token e WEBHOOK_SECRET antes da ativação.')
    bot = runtime.Telegram(token)
    bot.call('setWebhook', url=url + '/telegram', secret_token=secret,
             allowed_updates=['message'], max_connections=1, drop_pending_updates=False)
    bot.call('setMyCommands', commands=[{'command': c, 'description': d} for c, d in runtime.MENU])
    info = bot.call('getWebhookInfo')
    if info.get('url') != url + '/telegram':
        raise ValueError('Webhook não confirmado.')
    print('Webhook ativado. Teste /start, arquivo sem comando e /diagnostico pelo Telegram.')


if __name__ == '__main__':
    main()
