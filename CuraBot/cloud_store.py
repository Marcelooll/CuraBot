"""Small durable control records in PostgreSQL; files stay in Telegram, not SQL."""
from contextlib import contextmanager
import json
from pathlib import Path
import time

from sqlalchemy import create_engine, MetaData, Table, Column, BigInteger, Text, Float, select, func, text


class CloudStore:
    def __init__(self, url, folder='/tmp/curabot'):
        if url.startswith(('postgres://', 'postgresql://')):
            url = 'postgresql+psycopg://' + url.split('://', 1)[1]
        self.engine = create_engine(url, pool_pre_ping=True, hide_parameters=True)
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        meta = MetaData()
        self.jobs = Table('curabot_jobs', meta,
            Column('id', BigInteger, primary_key=True), Column('chat', Text), Column('message', Text),
            Column('status', Text), Column('progress', Text), Column('folder', Text),
            Column('report', Text), Column('error', Text), Column('created', Float))
        self.selections = Table('curabot_selections', meta,
            Column('chat', Text, primary_key=True), Column('source', Text), Column('created', Float))
        self.inbox = Table('curabot_inbox', meta,
            Column('id', BigInteger, primary_key=True), Column('payload', Text), Column('created', Float))
        self.sent = Table('curabot_deliveries', meta,
            Column('job', BigInteger, primary_key=True), Column('name', Text, primary_key=True), Column('file_id', Text))
        meta.create_all(self.engine)

    def _insert(self, table):
        if self.engine.dialect.name == 'postgresql':
            from sqlalchemy.dialects.postgresql import insert
        else:  # SQLite is used only for automated adapter tests.
            from sqlalchemy.dialects.sqlite import insert
        return insert(table)

    def receive(self, update):
        with self.engine.begin() as db:
            statement = self._insert(self.inbox).values(id=update['update_id'], payload=json.dumps(update), created=time.time())
            db.execute(statement.on_conflict_do_nothing(index_elements=['id']))

    def pending(self):
        with self.engine.connect() as db:
            rows = db.execute(select(self.inbox).where(self.inbox.c.payload.is_not(None)).order_by(self.inbox.c.id).limit(25)).mappings().all()
            return [json.loads(row['payload']) for row in rows]

    def acknowledge(self, update_id):
        with self.engine.begin() as db:
            db.execute(self.inbox.update().where(self.inbox.c.id == update_id).values(payload=None))

    def select(self, chat, source):
        with self.engine.begin() as db:
            values = {'chat': str(chat), 'source': json.dumps(source), 'created': time.time()}
            db.execute(self._insert(self.selections).values(**values).on_conflict_do_update(index_elements=['chat'], set_=values))

    def selected(self, chat):
        with self.engine.connect() as db:
            value = db.execute(select(self.selections.c.source).where(self.selections.c.chat == str(chat))).scalar_one_or_none()
            return json.loads(value) if value else None

    def enqueue(self, update_id, msg):
        with self.engine.begin() as db:
            if db.execute(select(self.jobs.c.id).where(self.jobs.c.id == update_id)).first():
                return False
            active = self.jobs.c.status.in_(['queued', 'running'])
            total = db.execute(select(func.count()).select_from(self.jobs).where(active)).scalar_one()
            own = db.execute(select(func.count()).select_from(self.jobs).where(active, self.jobs.c.chat == str(msg['chat']['id']))).scalar_one()
            if total >= 20 or own >= 3:
                raise ValueError('A fila está cheia. Aguarde e repita o comando.')
            db.execute(self.jobs.insert().values(id=update_id, chat=str(msg['chat']['id']), message=json.dumps(msg),
                status='queued', progress='Aguardando processamento', folder=str(self.folder / str(update_id)), created=time.time()))
            return True

    def next(self):
        with self.engine.begin() as db:
            row = db.execute(select(self.jobs).where(self.jobs.c.status == 'queued').order_by(self.jobs.c.id).limit(1)).mappings().first()
            if row:
                db.execute(self.jobs.update().where(self.jobs.c.id == row['id']).values(status='running'))
            return dict(row) if row else None

    def recover(self):
        with self.engine.begin() as db:
            db.execute(self.jobs.update().where(self.jobs.c.status == 'running').values(status='queued', progress='Retomando após interrupção'))

    def update(self, job_id, **fields):
        if not set(fields) <= {'status', 'progress', 'report', 'error'}:
            raise ValueError('Invalid state fields')
        with self.engine.begin() as db:
            db.execute(self.jobs.update().where(self.jobs.c.id == job_id).values(**fields))

    def latest(self, chat, report_only=False):
        query = select(self.jobs).where(self.jobs.c.chat == str(chat))
        if report_only:
            query = query.where(self.jobs.c.report.is_not(None))
        with self.engine.connect() as db:
            row = db.execute(query.order_by(self.jobs.c.id.desc()).limit(1)).mappings().first()
            return dict(row) if row else None

    def record_delivery(self, job_id, name, file_id):
        if not file_id:
            raise ValueError('O Telegram não confirmou o identificador do arquivo enviado.')
        with self.engine.begin() as db:
            values = {'job': job_id, 'name': name, 'file_id': file_id}
            db.execute(self._insert(self.sent).values(**values).on_conflict_do_update(index_elements=['job', 'name'], set_={'file_id': file_id}))

    def deliveries(self, job_id):
        with self.engine.connect() as db:
            return dict(db.execute(select(self.sent.c.name, self.sent.c.file_id).where(self.sent.c.job == job_id)).all())

    @contextmanager
    def leader(self):
        """One processing cycle globally; use a direct PostgreSQL URL, not transaction pooling."""
        if self.engine.dialect.name != 'postgresql':
            yield True
            return
        with self.engine.connect().execution_options(isolation_level='AUTOCOMMIT') as db:
            acquired = db.execute(text('SELECT pg_try_advisory_lock(8648101153)')).scalar_one()
            try:
                yield acquired
            finally:
                if acquired:
                    db.execute(text('SELECT pg_advisory_unlock(8648101153)'))

    def prune(self, days=7):
        """Bound retained metadata; active jobs and unhandled updates are never pruned."""
        cutoff = time.time() - days * 86400
        with self.engine.begin() as db:
            old = select(self.jobs.c.id).where(self.jobs.c.created < cutoff, self.jobs.c.status.in_(['done', 'failed']))
            db.execute(self.sent.delete().where(self.sent.c.job.in_(old)))
            db.execute(self.jobs.delete().where(self.jobs.c.id.in_(old)))
            db.execute(self.inbox.delete().where(self.inbox.c.created < cutoff, self.inbox.c.payload.is_(None)))
            db.execute(self.selections.delete().where(self.selections.c.created < cutoff))
