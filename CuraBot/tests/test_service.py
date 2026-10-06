import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine
import runtime


class Bot:
    def __init__(self, data=b'id;valor\n001;-12,50\n'):
        self.data, self.messages, self.files = data, [], []
    def text(self, chat, text):
        self.messages.append((chat, text))
    def download_to(self, file_id, destination):
        Path(destination).write_bytes(self.data)
    def send_file(self, chat, path):
        self.files.append((chat, Path(path).name, Path(path).read_bytes()))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
    def tearDown(self):
        self.temp.cleanup()
    def run_csv(self, text, **kwargs):
        path = self.root / 'input.csv'
        path.write_text(text, encoding='utf-8', newline='')
        return engine.run(path, self.root / 'result', **kwargs)
    def test_changes_missing_duplicates_and_signs(self):
        report, files = self.run_csv(' ID ;Nome;Nome;valor\n001; Ana ;X;-12.50\n002;B;;0\n002;B;;0\n ; ; ; \n')
        self.assertEqual(report['registros_exportados'], 3)
        self.assertEqual(report['duplicatas'], 1)
        self.assertEqual(report['alteracoes']['linhas_vazias'], 1)
        self.assertEqual(report['perfil']['nome_2']['ausentes'], 2)
        self.assertEqual(report['perfil']['valor']['negativos_preservados'], 1)
        self.assertEqual(report['perfil']['id']['zeros_iniciais_preservados'], 3)
        with files[0].open(encoding='utf-8-sig', newline='') as source:
            rows = list(csv.DictReader(source))
        self.assertEqual(rows[0]['id'], '001')
        self.assertEqual(rows[0]['valor'], '-12.50')
    def test_dedupe_is_opt_in(self):
        report, _ = self.run_csv('id,x\n1,a\n1,a\n2,b\n', deduplicate=True)
        self.assertEqual(report['registros_exportados'], 2)
        self.assertEqual(report['alteracoes']['duplicatas_removidas'], 1)
    def test_irregular_width_preserved(self):
        report, files = self.run_csv('a;b\nx;y;z\nw\n')
        self.assertEqual(report['colunas'], ['a', 'b', 'extra_1'])
        self.assertEqual(report['linhas_irregulares'], 2)
        self.assertIn('z', files[0].read_text())
    def test_quoted_newline(self):
        report, files = self.run_csv('id,note\n1,"hello\nworld"\n2,"a,b"\n')
        self.assertEqual(report['registros_exportados'], 2)
        with files[0].open(encoding='utf-8-sig', newline='') as source:
            self.assertEqual(list(csv.DictReader(source))[0]['note'], 'hello\nworld')
    def test_invalid_csv_is_rejected(self):
        with self.assertRaises(csv.Error):
            self.run_csv('id,note\n1,"unclosed\n')
    def test_formula_and_ambiguous_value_preserved(self):
        report, files = self.run_csv('x;y\n=1+1;1,234\n-12,50;2025-02-30\n')
        self.assertEqual(report['alteracoes']['formulas_protegidas'], 1)
        self.assertEqual(report['datas_invalidas'], 1)
        self.assertIn('-12,50', files[0].read_text())
    def test_output_split_without_loss(self):
        report, files = self.run_csv('id,note\n' + ''.join(f'{i},abcdefghijk\n' for i in range(200)), max_part_bytes=200)
        self.assertGreater(len(files), 1)
        rows = []
        for file in files:
            self.assertLessEqual(file.stat().st_size, 200)
            with file.open(encoding='utf-8-sig') as source:
                rows.extend(csv.DictReader(source))
        self.assertEqual([int(r['id']) for r in rows], list(range(200)))
    def test_parquet_typed_values(self):
        import pyarrow as pa
        import pyarrow.parquet as pq
        path = self.root / 'input.parquet'
        pq.write_table(pa.table({'ID': ['001', '002'], 'Value': [-1.25, None]}), path)
        report, files = engine.run(path, self.root / 'result')
        self.assertEqual(report['perfil']['value']['ausentes'], 1)
        self.assertEqual(report['registros_exportados'], 2)
    def test_excel_all_sheets(self):
        import openpyxl
        path = self.root / 'input.xlsx'
        book = openpyxl.Workbook()
        book.active.append(['ID', 'Valor'])
        book.active.append(['001', -2])
        sheet = book.create_sheet('Segunda')
        sheet.append(['ID', 'Valor'])
        sheet.append(['002', 0])
        book.save(path)
        report, files = engine.run(path, self.root / 'result')
        self.assertEqual(report['registros_exportados'], 2)
        self.assertIn('Segunda', files[0].read_text())
    def test_utf16(self):
        path = self.root / 'input.csv'
        path.write_text('id;nome\n001;João\n', encoding='utf-16')
        report, files = engine.run(path, self.root / 'result')
        self.assertEqual(report['registros_exportados'], 1)
        self.assertIn('João', files[0].read_text(encoding='utf-8-sig'))
    def test_persisted_queue_and_report(self):
        store = runtime.Store(self.root / 'state')
        msg = {'chat': {'id': 42}, 'caption': '/arrumar', 'document': {'file_id': 'abc', 'file_name': 'x.csv'}}
        bot = Bot()
        runtime.dispatch(bot, store, {'update_id': 1, 'message': msg})
        self.assertFalse(store.enqueue(1, msg))
        job = store.next()
        runtime.execute_job(bot, store, job)
        self.assertEqual(store.latest(42)['status'], 'done')
        self.assertEqual(len(bot.files), 2)
        runtime.dispatch(bot, store, {'update_id': 2, 'message': {'chat': {'id': 42}, 'text': 'O que mudou?'}})
        self.assertIn('Diagnóstico concluído', bot.messages[-1][1])
        runtime.dispatch(bot, store, {'update_id': 3, 'message': {'chat': {'id': 55}, 'text': '/relatorio'}})
        self.assertNotIn('Diagnóstico concluído', bot.messages[-1][1])
    def test_review_needs_no_gemini(self):
        bot = Bot()
        store = runtime.Store(self.root / 'state')
        store.enqueue(1, {'chat': {'id': 42}, '_operation': 'diagnostico', 'document': {'file_id': 'abc', 'file_name': 'x.csv'}})
        with patch.dict(os.environ, {}, clear=True):
            runtime.execute_job(bot, store, store.next())
        self.assertEqual([f[1] for f in bot.files], ['relatorio.txt'])
    def test_natural_question_limits(self):
        self.assertIn(f'{engine.MAX_FILE // 1024 ** 2} MiB', runtime.answer('Consegue trabalhar com bases maiores?'))
    def test_report_answers_use_exact_values(self):
        report, _ = self.run_csv('age,deck\n20,A\n,\n')
        # A completely blank record is removed and not counted as a passenger.
        report['perfil']['age']['ausentes'] = 177
        self.assertIn('177', runtime.answer('Quais campos estão vazios?', report))
        self.assertIn('Média dos valores numéricos: 20', runtime.answer('qual a média de age?', report))
    def test_restart_recovers_incomplete_job(self):
        store = runtime.Store(self.root / 'state')
        store.enqueue(7, {'chat': {'id': 42}})
        store.next()
        store = runtime.Store(self.root / 'state')
        store.recover()
        self.assertEqual(store.next()['id'], 7)
    def test_block_private_address(self):
        with patch('socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]), patch('socket.create_connection') as connect:
            with self.assertRaises(ValueError):
                runtime.fetch_public('http://public.test/file.csv', self.root / 'x')
            connect.assert_not_called()
    def test_download_limit(self):
        with self.assertRaises(ValueError):
            runtime.copy_bounded(io.BytesIO(b'a' * 20), self.root / 'x', 10)
    def test_queue_limit(self):
        store = runtime.Store(self.root / 'state')
        for i in range(3):
            store.enqueue(i, {'chat': {'id': 42}})
        with self.assertRaises(ValueError):
            store.enqueue(4, {'chat': {'id': 42}})

    def test_output_never_overwrites_input(self):
        path = self.root / 'curabot_organizado_001.csv'
        path.write_text('x\n1\n')
        with self.assertRaises(ValueError):
            engine.run(path, self.root)
        self.assertEqual(path.read_text(), 'x\n1\n')

    def test_redirect_to_internal_blocked(self):
        from unittest.mock import MagicMock
        response = MagicMock(status=302)
        response.getheader.return_value = 'http://127.0.0.1/private'
        connection = MagicMock()
        connection.getresponse.return_value = response
        public = [(2, 1, 6, '', ('93.184.216.34', 80))]
        private = [(2, 1, 6, '', ('127.0.0.1', 80))]
        with patch('socket.getaddrinfo', side_effect=[public, private]), patch('socket.create_connection'), patch('http.client.HTTPConnection', return_value=connection):
            with self.assertRaises(ValueError):
                runtime.fetch_public('http://example.test/start', self.root / 'x')

    def test_pdf_local_tables_without_key(self):
        from unittest.mock import MagicMock
        page = MagicMock()
        page.extract_tables.return_value = [[['ID', 'Nome'], ['001', 'Ana']]]
        page.extract_text.return_value = 'ID Nome 001 Ana'
        book = MagicMock()
        book.__enter__.return_value.pages = [page]
        path = self.root / 'input.pdf'
        path.write_bytes(b'%PDF-test')
        with patch('pdfplumber.open', return_value=book), patch.dict(os.environ, {}, clear=True):
            tabular, warnings = runtime.prepare_tabular(path, self.root)
            report, files = engine.run(tabular, self.root / 'result')
        self.assertEqual(report['registros_exportados'], 1)
        self.assertIn('001', files[0].read_text())
        self.assertTrue(warnings)

    def test_failed_send_retains_recoverable_report(self):
        bot = Bot()
        store = runtime.Store(self.root / 'state')
        store.enqueue(1, {'chat': {'id': 42}, '_operation': 'arrumar', 'document': {'file_id': 'abc', 'file_name': 'x.csv'}})
        with patch.object(bot, 'send_file', side_effect=ValueError('Falha de envio')):
            runtime.execute_job(bot, store, store.next())
        self.assertEqual(store.latest(42)['status'], 'failed')
        self.assertIsNotNone(store.latest(42, report_only=True))
        runtime.dispatch(bot, store, {'update_id': 2, 'message': {'chat': {'id': 42}, 'text': '/baixar'}})
        runtime.execute_job(bot, store, store.next())
        self.assertEqual(store.latest(42)['status'], 'done')
        self.assertEqual(len(bot.files), 2)


if __name__ == '__main__':
    unittest.main()
