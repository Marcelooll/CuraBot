"""Render Free webhook entrypoint. Start with gunicorn 'webapp:create_app()'."""
import hmac
import logging
import os
from pathlib import Path
import re
import shutil
import threading
import time

from flask import Flask, request, jsonify
import engine
import runtime
from cloud_store import CloudStore


def configure_limits():
    engine.MAX_FILE = 20 * 1024 ** 2
    runtime.HELP = runtime.HELP.replace('link direto até 1 GiB. O computador precisa ficar ligado.',
        'link direto até 20 MiB nesta hospedagem gratuita. Funciono na nuvem, sem depender do seu PC. '
        'Após inatividade, a primeira resposta pode demorar. Seleções e relatórios ficam disponíveis por até 7 dias. '
        'A fila tem capacidade limitada; arquivos complexos podem exceder os recursos disponíveis.')


def process_cycle(bot, store):
    # Advisory lock is held while dispatching and running one job; rolling deployments
    # cannot both consume the queue. Direct PostgreSQL connections are required.
    with store.leader() as acquired:
        if not acquired:
            return False
        store.recover()
        for update in store.pending():
            try:
                runtime.dispatch(bot, store, update)
            except ValueError as exc:
                message = update.get('message', {})
                if message.get('chat'):
                    bot.text(message['chat']['id'], str(exc))
            store.acknowledge(update['update_id'])
        job = store.next()
        if job:
            try:
                runtime.execute_job(bot, store, job)
            finally:
                # Only remove this job's temporary directory, never paths stored remotely.
                folder = (store.folder / str(job['id'])).resolve()
                if folder.parent == store.folder.resolve() and folder.is_dir():
                    shutil.rmtree(folder)
        store.prune()
        return bool(job)


def cloud_worker(bot, store, stop, wake):
    initialized = False
    while not stop.is_set():
        try:
            if not initialized:
                bot.username = bot.call('getMe')['username']
                initialized = True
            if process_cycle(bot, store):
                continue
        except Exception as exc:
            # Never log exceptions containing database URLs or Telegram tokens.
            logging.error('Cloud cycle failed (%s); will retry', type(exc).__name__)
        wake.wait(15)
        wake.clear()


def create_app(store=None, bot=None, secret=None, start_worker=True):
    secret = secret or os.environ.get('WEBHOOK_SECRET', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise ValueError('Configure WEBHOOK_SECRET com 32 a 256 caracteres aleatórios: letras, números, _ ou -.')
    if store is None:
        url = os.environ.get('DATABASE_URL', '')
        if not url.startswith(('postgresql://', 'postgres://', 'postgresql+psycopg://')):
            raise ValueError('Configure DATABASE_URL com a conexão PostgreSQL direta, com SSL.')
        if '-pooler.' in url:
            raise ValueError('Use a conexão direta do Neon: desative Connection pooling ao copiar DATABASE_URL.')
        store = CloudStore(url, os.environ.get('CURABOT_STATE_DIR', '/tmp/curabot'))
    if bot is None:
        token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        if not token:
            raise ValueError('Configure TELEGRAM_BOT_TOKEN nos segredos do serviço.')
        bot = runtime.Telegram(token)
    configure_limits()
    app = Flask(__name__)
    app.config['MAX_CONTENT_LENGTH'] = 1024 ** 2
    wake, stop = threading.Event(), threading.Event()

    @app.get('/')
    @app.get('/healthz')
    def health():
        return jsonify(status='ok', mode='telegram-webhook')

    @app.post('/telegram')
    def telegram():
        supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
        if not hmac.compare_digest(supplied.encode(), secret.encode()):
            return jsonify(error='unauthorized'), 403
        update = request.get_json(silent=True)
        if not isinstance(update, dict) or type(update.get('update_id')) is not int:
            return jsonify(error='invalid update'), 400
        message = update.get('message')
        if message is not None and (not isinstance(message, dict) or not isinstance(message.get('chat'), dict) or type(message['chat'].get('id')) is not int):
            return jsonify(error='invalid message'), 400
        try:
            store.receive(update)  # Commit before acknowledging to Telegram.
        except Exception:
            return jsonify(error='temporary database failure'), 503
        wake.set()
        return jsonify(ok=True)

    if start_worker:
        threading.Thread(target=cloud_worker, args=(bot, store, stop, wake), daemon=True).start()
    return app
