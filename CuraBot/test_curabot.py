import io
import os
import unittest
from unittest.mock import patch
import curabot as c


class FakeBot:
    def __init__(self):
        self.messages, self.files = [], []
    def text(self, chat, text):
        self.messages.append(text)
    def document(self, chat, data):
        self.files.append(data)
    def download(self, file_id):
        return b'id;valor\n001;-12,50\n'


class Tests(unittest.TestCase):
    def test_csv_preserves_identifiers_and_negative(self):
        rows = c.process(b'id;valor\n001;-12,50\n', 'test.csv')
        self.assertEqual(rows, [{'id': '001', 'valor': '-12,50'}])
        self.assertIn('-12,50', c.csv_bytes(rows).decode('utf-8-sig'))

    def test_duplicate_headers_and_extra_fields(self):
        self.assertEqual(c.table_rows([['Nome', 'Nome'], ['a', 'b', 'c']]),
                         [{'nome': 'a', 'nome_2': 'b', 'column': 'c'}])

    def test_formula_protection(self):
        result = c.csv_bytes([{'a': '=1+1', 'b': '-12.50', 'c': '-CMD()'}]).decode('utf-8-sig')
        self.assertIn("'=1+1", result)
        self.assertIn("'-CMD()", result)
        self.assertNotIn("'-12.50", result)

    def test_excel_all_sheets(self):
        import openpyxl
        book = openpyxl.Workbook()
        book.active.append(['ID', 'Valor'])
        book.active.append(['001', -12.5])
        other = book.create_sheet('Outra')
        other.append(['ID', 'Valor'])
        other.append(['002', 20])
        data = io.BytesIO()
        book.save(data)
        rows = c.process(data.getvalue(), 'test.xlsx')
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]['valor'], -12.5)
        self.assertEqual(rows[1]['_sheet'], 'Outra')

    def test_private_urls_blocked_before_connect(self):
        addr = [(2, 1, 6, '', ('127.0.0.1', 80))]
        with patch('socket.getaddrinfo', return_value=addr), patch('socket.create_connection') as connect:
            with self.assertRaises(ValueError):
                c.fetch_public('http://example.test')
            connect.assert_not_called()

    def test_start_without_gemini(self):
        bot = FakeBot()
        with patch.dict(os.environ, {}, clear=True), patch('curabot.gemini') as ai:
            c.handle(bot, {'chat': {'id': 1}, 'text': '/start'})
            self.assertIn('Olá', bot.messages[0])
            ai.assert_not_called()

    def test_csv_telegram_flow_without_gemini(self):
        bot = FakeBot()
        with patch.dict(os.environ, {}, clear=True), patch('curabot.gemini') as ai:
            c.handle(bot, {'chat': {'id': 1}, 'document': {'file_id': 'x', 'file_name': 'a.csv'}})
            self.assertEqual(len(bot.files), 1)
            self.assertIn(b'001', bot.files[0])
            ai.assert_not_called()

    def test_review_mode_only(self):
        bot = FakeBot()
        with patch.dict(os.environ, {}, clear=True), patch('curabot.gemini', return_value='Análise de teste'):
            c.handle(bot, {'chat': {'id': 1}, 'caption': '/review', 'document': {'file_id': 'x', 'file_name': 'a.csv'}})
        self.assertFalse(bot.files)
        self.assertIn('Análise de teste', bot.messages)

    def test_invalid_ai_structure(self):
        with patch('curabot.gemini', return_value='{"rows": [1]}'):
            with self.assertRaises(ValueError):
                c.extract_text('test')

    def test_long_document_not_truncated(self):
        with patch('curabot.gemini') as ai:
            with self.assertRaises(ValueError):
                c.extract_text('a' * 100001)
            ai.assert_not_called()

    def test_restricted_user(self):
        bot = FakeBot()
        with patch.dict(os.environ, {'ALLOWED_USER_IDS': '123'}):
            c.handle(bot, {'chat': {'id': 1}, 'from': {'id': 456}, 'text': '/start'})
        self.assertIn('restrito', bot.messages[0])


if __name__ == '__main__':
    unittest.main()
