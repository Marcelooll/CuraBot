import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine
import runtime
from cloud_store import CloudStore
from webapp import create_app, process_cycle
from test_service import Bot


class CloudBot(Bot):
    def send_file(self, chat, path):
        super().send_file(chat, path)
        return 'telegram-file-' + Path(path).name
    def call(self, method, **kwargs):
        self.messages.append((method, kwargs))


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.url = 'sqlite:///' + str(self.root / 'cloud.sqlite')
        self.store = CloudStore(self.url, self.root / 'scratch')
        self.bot = CloudBot()
        self.secret = 'a' * 40
        self.old_help, self.old_limit = runtime.HELP, engine.MAX_FILE
        self.env = patch.dict(os.environ, {'ALLOWED_USER_IDS': '', 'GEMINI_API_KEY': ''})
        self.env.start()
        self.client = create_app(self.store, self.bot, self.secret, start_worker=False).test_client()
    def tearDown(self):
        self.env.stop()
        runtime.HELP, engine.MAX_FILE = self.old_help, self.old_limit
        self.store.engine.dispose()
        self.tmp.cleanup()
    def post(self, update):
        return self.client.post('/telegram', json=update, headers={'X-Telegram-Bot-Api-Secret-Token': self.secret})
    def test_secret_required_and_payload_checked(self):
        self.assertEqual(self.client.post('/telegram', json={'update_id': 1}).status_code, 403)
        self.assertEqual(self.post({'update_id': 'one'}).status_code, 400)
        self.assertEqual(self.post({'update_id': 1, 'message': {}}).status_code, 400)
        self.assertEqual(self.store.pending(), [])
    def test_db_failure_is_not_acknowledged(self):
        with patch.object(self.store, 'receive', side_effect=RuntimeError('test')):
            self.assertEqual(self.post({'update_id': 1}).status_code, 503)
    def test_receipt_is_durable_and_duplicates_ignored(self):
        update = {'update_id': 1, 'message': {'chat': {'id': 42}, 'document': {'file_id': 'source', 'file_name': 'x.csv'}}}
        self.assertEqual(self.post(update).status_code, 200)
        self.assertEqual(self.post(update).status_code, 200)
        reopened = CloudStore(self.url, self.root / 'scratch')
        self.assertEqual(len(reopened.pending()), 1)
        reopened.engine.dispose()
        process_cycle(self.bot, self.store)
        self.assertEqual(self.store.selected(42)['document']['file_id'], 'source')
        self.assertIsNone(self.store.latest(42))
        self.post(update)
        self.assertEqual(self.store.pending(), [])
    def test_result_redelivery_after_scratch_deleted(self):
        self.post({'update_id': 1, 'message': {'chat': {'id': 42}, 'document': {'file_id': 'source', 'file_name': 'x.csv'}}})
        self.post({'update_id': 2, 'message': {'chat': {'id': 42}, 'text': '/arrumar'}})
        process_cycle(self.bot, self.store)
        self.assertEqual(self.store.latest(42)['status'], 'done')
        self.assertFalse((self.store.folder / '2').exists())
        self.assertEqual(len(self.store.deliveries(2)), 2)
        self.assertIsNone(self.store.latest(43, report_only=True))
        self.post({'update_id': 3, 'message': {'chat': {'id': 42}, 'text': '/baixar'}})
        process_cycle(self.bot, self.store)
        self.assertEqual(self.store.latest(42)['status'], 'done')
        self.assertEqual(len([m for m in self.bot.messages if m[0] == 'sendDocument']), 2)
    def test_interrupted_job_restarts_from_original(self):
        self.store.enqueue(7, {'chat': {'id': 42}, '_operation': 'diagnostico', 'document': {'file_id': 'source', 'file_name': 'x.csv'}})
        self.store.next()
        process_cycle(self.bot, self.store)
        self.assertEqual(self.store.latest(42)['status'], 'done')
        self.assertEqual(json.loads(self.store.latest(42)['report'])['registros_exportados'], 0)
    def test_pruning_preserves_queued_jobs(self):
        with patch('cloud_store.time.time', return_value=1):
            self.store.enqueue(1, {'chat': {'id': 42}})
            self.store.enqueue(2, {'chat': {'id': 43}})
            self.store.update(2, status='done')
            self.store.record_delivery(2, 'x.csv', 'id')
        self.store.prune()
        self.assertEqual(self.store.latest(42)['status'], 'queued')
        self.assertIsNone(self.store.latest(43))
        self.assertEqual(self.store.deliveries(2), {})
    def test_health_exposes_no_secrets(self):
        result = self.client.get('/healthz')
        self.assertEqual(result.status_code, 200)
        self.assertNotIn(self.secret, result.get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
