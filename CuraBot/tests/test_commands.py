import csv
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine
import runtime
from test_service import Bot


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = runtime.Store(self.root / 'state')
        self.bot = Bot()
        self.env = patch.dict(os.environ, {'ALLOWED_USER_IDS': '', 'GEMINI_API_KEY': ''})
        self.env.start()
    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()
    def send(self, number, text='', **fields):
        runtime.dispatch(self.bot, self.store, {'update_id': number, 'message': {'chat': {'id': 42}, 'text': text, **fields}})
    def run_data(self, operation, options=None):
        source = self.root / 'source.csv'
        source.write_text(' ID ;Valor;Nota\n001;1.234,56; A, B \n001;1.234,56; A, B \n002;001,20;Texto.\n;;\n', encoding='utf-8')
        return engine.run(source, self.root / operation, operation=operation, options=options)
    def rows(self, file, delimiter=';'):
        with file.open(encoding='utf-8-sig', newline='') as stream:
            return list(csv.reader(stream, delimiter=delimiter))
    def test_no_command_never_downloads_or_enqueues(self):
        with patch.object(self.bot, 'download_to') as download, patch('runtime.fetch_public') as fetch:
            self.send(1, document={'file_id': 'abc', 'file_name': 'x.csv'})
            self.send(2, 'arrume tudo')
            self.send(3, 'pode fazer /arrumar agora')
            self.send(4, 'https://example.com/file.csv')
            self.send(5, '/desconhecido')
            self.send(6, '/arrumar@OutroBot')
            self.assertIsNone(self.store.next())
            download.assert_not_called()
            fetch.assert_not_called()
    def test_cloud_state_directory_survives_reopening(self):
        folder = self.root / 'persistent-volume'
        with patch.dict(os.environ, {'CURABOT_STATE_DIR': str(folder)}):
            store = runtime.Store()
            store.select(42, {'document': {'file_id': 'cloud', 'file_name': 'a.csv'}})
            store.advance(123)
            reopened = runtime.Store()
            self.assertEqual(reopened.path.parent, folder)
            self.assertEqual(reopened.offset(), 123)
            self.assertEqual(reopened.selected(42)['document']['file_id'], 'cloud')
            self.assertIsNone(reopened.selected(43))
    def test_explicit_state_directory_overrides_cloud_environment(self):
        with patch.dict(os.environ, {'CURABOT_STATE_DIR': str(self.root / 'cloud')}):
            store = runtime.Store(self.root / 'explicit')
            self.assertEqual(store.path.parent, self.root / 'explicit')
    def test_selected_file_persists_and_is_reusable(self):
        self.send(1, document={'file_id': 'abc', 'file_name': 'x.csv'})
        self.store = runtime.Store(self.root / 'state')
        self.send(2, '/diagnostico')
        runtime.execute_job(self.bot, self.store, self.store.next())
        report = json.loads(self.store.latest(42)['report'])
        self.assertEqual(report['registros_exportados'], 0)
        self.assertEqual(report['registros_avaliados'], 1)
        self.assertEqual(report['partes'], [])
        self.send(3, '/arrumar')
        runtime.execute_job(self.bot, self.store, self.store.next())
        self.assertEqual(self.store.latest(42)['status'], 'done')
        self.assertIsNone(self.store.selected(99))
    def test_invalid_parameters_do_not_enqueue(self):
        for text in ['/pontuacao', '/separador adivinhe', '/arrumar tudo']:
            with self.assertRaises(ValueError):
                self.send(1, text)
        self.assertIsNone(self.store.next())
    def test_legacy_automatic_job_cannot_execute(self):
        self.store.enqueue(1, {'chat': {'id': 42}, 'document': {'file_id': 'abc'}})
        with patch.object(self.bot, 'download_to') as download:
            runtime.execute_job(self.bot, self.store, self.store.next())
            download.assert_not_called()
        self.assertEqual(self.store.latest(42)['status'], 'failed')
    def test_specific_operations_do_not_clean_other_fields(self):
        report, files = self.run_data('cabecalhos')
        rows = self.rows(files[0])
        self.assertEqual(rows[0], ['id', 'valor', 'nota'])
        self.assertEqual(rows[1], ['001', '1.234,56', ' A, B '])
        self.assertEqual(len(rows), 5)
        report, files = self.run_data('espacos')
        rows = self.rows(files[0])
        self.assertEqual(rows[0][0], ' ID ')
        self.assertEqual(rows[1][2], 'A, B')
        self.assertEqual(len(rows), 5)
        report, files = self.run_data('linhas_vazias')
        self.assertEqual(self.rows(files[0])[1][2], ' A, B ')
        self.assertEqual(report['registros_exportados'], 3)
    def test_separator_preserves_punctuation_and_quotes(self):
        report, files = self.run_data('separador', {'delimiter': ','})
        rows = self.rows(files[0], ',')
        self.assertEqual(rows[1], ['001', '1.234,56', ' A, B '])
        self.assertEqual(rows[0][0], ' ID ')
        self.assertEqual(report['valores_alterados'], 0)
    def test_numeric_punctuation_only_selected_column(self):
        report, files = self.run_data('pontuacao', {'column': 'valor', 'direction': 'br_para_us'})
        rows = self.rows(files[0])
        self.assertEqual(rows[1], ['001', '1234.56', ' A, B '])
        self.assertEqual(rows[3][1], '001,20')
        self.assertEqual(report['alteracoes']['pontuacao'], 2)
        self.assertEqual(report['conversoes_ignoradas'], 1)
        self.assertEqual(len(rows), 5)
    def test_reverse_numeric_conversion_and_wrong_column(self):
        source = self.root / 'us.csv'
        source.write_text('Price;Text\n1,234.56;a,b\n-12.50;a.b\n', encoding='utf-8')
        report, files = engine.run(source, self.root / 'us', operation='pontuacao', options={'column': 'price', 'direction': 'us_para_br'})
        self.assertEqual(self.rows(files[0])[1:], [['1234,56', 'a,b'], ['-12,50', 'a.b']])
        with self.assertRaises(ValueError):
            engine.run(source, self.root / 'bad', operation='pontuacao', options={'column': 'missing', 'direction': 'us_para_br'})
    def test_exact_dedup_does_not_strip_spaces(self):
        source = self.root / 'dups.csv'
        source.write_text('Nome\n Ana \nAna\nAna\n', encoding='utf-8')
        report, files = engine.run(source, self.root / 'dups', operation='deduplicar')
        self.assertEqual(report['registros_exportados'], 2)
        self.assertEqual(report['alteracoes']['espacos'], 0)


if __name__ == '__main__':
    unittest.main()
