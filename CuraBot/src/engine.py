"""Bounded-memory tabular processing. No AI and no guessed replacement values."""
import codecs
from collections import Counter
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import time
import unicodedata

MAX_FILE = 1024 ** 3
MAX_COLUMNS = 2000
csv.field_size_limit(2 * 1024 ** 2)
NUMBER = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')
COMMA_NUMBER = re.compile(r'^[+-]?\d+,\d+$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[ T].*)?$')


def slug(value):
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '_', text).strip('_') or 'column'


def headers_unique(values):
    used, result = set(), []
    for value in values:
        base = slug(value)
        name, i = base, 2
        while name in used:
            name, i = f'{base}_{i}', i + 1
        used.add(name)
        result.append(name)
    return result


def scalar(value):
    if value is None or isinstance(value, float) and math.isnan(value):
        return ''
    if isinstance(value, (dt.date, dt.datetime, dt.time)):
        return value.isoformat()
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return str(value)


def encoding_of(path):
    with open(path, 'rb') as source:
        prefix = source.read(4)
        if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            return 'utf-16'
        source.seek(0)
        decoder = codecs.getincrementaldecoder('utf-8-sig')()
        try:
            while block := source.read(1024 * 1024):
                decoder.decode(block)
            decoder.decode(b'', final=True)
            return 'utf-8-sig'
        except UnicodeDecodeError:
            return 'cp1252'


def csv_format(path):
    encoding = encoding_of(path)
    with open(path, encoding=encoding, newline='') as source:
        sample = source.read(65536)
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=',;\t|').delimiter
    except csv.Error:
        # Malformed row widths must not cause a semicolon file to be read as one column.
        first = sample.splitlines()[0] if sample else ''
        delimiter = max(',;\t|', key=first.count) if first else ','
    return encoding, delimiter


class Source:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.stat().st_size > MAX_FILE:
            raise ValueError('Arquivo acima do limite atual de 1 GiB.')
        self.kind = self.path.suffix.lower()
        self.warnings = []
        self.encoding, self.delimiter = '', ''
        if self.kind in ('.csv', '.tsv'):
            self.encoding, self.delimiter = csv_format(path)
            if self.kind == '.tsv':
                self.delimiter = '\t'
            with open(path, encoding=self.encoding, newline='') as source:
                self.original_headers = next(csv.reader(source, delimiter=self.delimiter, strict=True), [])
            self.headers = headers_unique(self.original_headers)
        elif self.kind == '.parquet':
            import pyarrow.parquet as pq
            self.original_headers = pq.ParquetFile(path).schema_arrow.names
            self.headers = headers_unique(self.original_headers)
        elif self.kind in ('.xlsx', '.xls'):
            self.sheet_headers = {}
            original_names = {}
            for title, header in self.excel_headers():
                names = headers_unique(header)
                self.sheet_headers[title] = names
                for name, value in zip(names, header):
                    original_names.setdefault(name, str(value or ''))
            self.headers = list(dict.fromkeys(k for names in self.sheet_headers.values() for k in names))
            self.sheet_key = '_sheet'
            while self.sheet_key in self.headers:
                self.sheet_key = '_' + self.sheet_key
            self.headers.append(self.sheet_key)
            self.original_headers = [original_names.get(k, k) for k in self.headers]
            self.warnings.append('Excel: fórmulas não são recalculadas; são lidos os valores armazenados no arquivo.')
        else:
            raise ValueError('Use CSV, TSV, XLSX, XLS ou Parquet para processamento tabular.')
        if not self.headers:
            raise ValueError('Arquivo sem cabeçalho. Nada foi processado.')
        if len(self.headers) > MAX_COLUMNS:
            raise ValueError('A tabela excede 2.000 colunas.')

    def excel_headers(self):
        if self.kind == '.xlsx':
            import openpyxl
            import zipfile
            with zipfile.ZipFile(self.path) as archive:
                if sum(x.file_size for x in archive.infolist()) > 2 * MAX_FILE:
                    raise ValueError('XLSX descompactado acima de 2 GiB.')
            book = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
            try:
                for sheet in book:
                    yield sheet.title, next(sheet.values, [])
            finally:
                book.close()
        else:
            import xlrd
            if self.path.stat().st_size > 20 * 1024 ** 2:
                raise ValueError('XLS legado limitado a 20 MiB. Converta para CSV ou Parquet para bases grandes.')
            book = xlrd.open_workbook(self.path, on_demand=True)
            try:
                for sheet in book.sheets():
                    yield sheet.name, sheet.row_values(0) if sheet.nrows else []
            finally:
                book.release_resources()

    def rows(self):
        if self.kind in ('.csv', '.tsv'):
            with open(self.path, encoding=self.encoding, newline='') as source:
                reader = csv.reader(source, delimiter=self.delimiter, strict=True)
                next(reader, None)
                for row in reader:
                    yield row
        elif self.kind == '.parquet':
            import pyarrow.parquet as pq
            with pq.ParquetFile(self.path) as source:
                for batch in source.iter_batches(batch_size=4096):
                    # Lists are bounded by a batch, never the whole dataset.
                    columns = [column.to_pylist() for column in batch.columns]
                    yield from zip(*columns)
        elif self.kind == '.xlsx':
            import openpyxl
            book = openpyxl.load_workbook(self.path, read_only=True, data_only=True)
            try:
                for sheet in book:
                    values = iter(sheet.values)
                    next(values, None)
                    names = self.sheet_headers[sheet.title]
                    for row in values:
                        if not any(scalar(v).strip() for v in row):
                            yield []
                            continue
                        record = dict(zip(names, row))
                        record[self.sheet_key] = sheet.title
                        yield [record.get(k) for k in self.headers]
            finally:
                book.close()
        else:
            import xlrd
            book = xlrd.open_workbook(self.path, on_demand=True)
            try:
                for sheet in book.sheets():
                    names = self.sheet_headers[sheet.name]
                    for i in range(1, sheet.nrows):
                        values = []
                        for cell in sheet.row(i):
                            if cell.ctype == xlrd.XL_CELL_DATE:
                                values.append(xlrd.xldate_as_datetime(cell.value, book.datemode).isoformat())
                            else:
                                values.append(cell.value)
                        if not any(scalar(v).strip() for v in values):
                            yield []
                            continue
                        record = dict(zip(names, values))
                        record[self.sheet_key] = sheet.name
                        yield [record.get(k) for k in self.headers]
            finally:
                book.release_resources()


def encoded_row(values, delimiter=','):
    text = io.StringIO(newline='')
    csv.writer(text, delimiter=delimiter).writerow(values)
    return text.getvalue().encode('utf-8')


class Parts:
    def __init__(self, folder, headers, max_bytes=40 * 1024 ** 2, delimiter=','):
        self.delimiter = delimiter
        self.folder, self.headers, self.max_bytes = Path(folder), headers, max_bytes
        self.files, self.file, self.size, self.part_rows = [], None, 0, 0
    def write(self, row):
        data = encoded_row(row, self.delimiter)
        head = codecs.BOM_UTF8 + encoded_row(self.headers, self.delimiter)
        if len(data) + len(head) > self.max_bytes:
            raise ValueError('Uma única linha excede o tamanho máximo de uma parte de saída.')
        if self.file is None or self.size + len(data) > self.max_bytes:
            self.close()
            path = self.folder / f'curabot_organizado_{len(self.files) + 1:03}.csv'
            self.files.append(path)
            self.file = path.open('wb')
            self.file.write(head)
            self.size = len(head)
        self.file.write(data)
        self.size += len(data)
    def close(self):
        if self.file:
            self.file.close()
            self.file = None


class Profile:
    def __init__(self):
        self.missing = self.numeric = self.text = self.negative = self.invalid_dates = self.comma_numbers = self.leading_zero = 0
        self.minimum = self.maximum = None
        self.total = Decimal(0)
        self.types = Counter()
    def add(self, value):
        if value == '':
            self.missing += 1
            return
        if re.match(r'^[+-]?0\d', value):
            self.leading_zero += 1
            self.types['identificador_possivel'] += 1
            return
        if NUMBER.fullmatch(value) and len(value) < 100:
            try:
                number = Decimal(value)
                if not number.is_finite() or abs(number.adjusted()) > 100:
                    raise InvalidOperation()
                self.numeric += 1
                self.negative += number < 0
                self.minimum = number if self.minimum is None else min(self.minimum, number)
                self.maximum = number if self.maximum is None else max(self.maximum, number)
                self.total += number
                self.types['numero'] += 1
                return
            except InvalidOperation:
                pass
        if COMMA_NUMBER.fullmatch(value):
            self.comma_numbers += 1
        if DATE.fullmatch(value):
            try:
                dt.datetime.fromisoformat(value)
                self.types['data_iso'] += 1
            except ValueError:
                self.invalid_dates += 1
                self.types['data_invalida'] += 1
        else:
            self.types['texto'] += 1
        self.text += 1
    def report(self):
        return {'ausentes': self.missing, 'tipos_observados': dict(self.types),
                'numeros_inequivocos': self.numeric, 'negativos_preservados': self.negative,
                'numeros_com_virgula_preservados': self.comma_numbers,
                'zeros_iniciais_preservados': self.leading_zero, 'datas_iso_invalidas': self.invalid_dates,
                'minimo_numerico': str(self.minimum) if self.minimum is not None else None,
                'maximo_numerico': str(self.maximum) if self.maximum is not None else None,
                'soma_numerica': str(self.total) if self.numeric else None,
                'media_numerica': str(self.total / self.numeric) if self.numeric else None}


def summary(report):
    changes = report['alteracoes']
    outcome = f"{report['registros_exportados']:,} exportados" if report.get('gerou_csv', True) else 'somente análise, sem gerar CSV'
    text = [f"Diagnóstico concluído: {report['registros_lidos']:,} registros lidos; {outcome}; {len(report['colunas'])} colunas.",
            f"Alterações: {changes['cabecalhos']} cabeçalhos, {changes['espacos']} células com espaços nas bordas, {changes['linhas_vazias']} linhas vazias removidas, {changes['formulas_protegidas']} textos protegidos contra fórmulas.",
            f"Repetições integrais nos valores avaliados: {report['duplicatas']}. Removidas: {changes['duplicatas_removidas']}."]
    if report.get('operacao') == 'pontuacao':
        text.append(f"Formato numérico: {changes.get('pontuacao', 0)} células convertidas; {report.get('conversoes_ignoradas', 0)} valores não vazios fora da regra foram preservados.")
    if report.get('operacao') == 'separador':
        text.append(f"Separador de saída: {report['delimitador_saida']!r}. Conteúdo das células preservado.")
    missing = [(k, v['ausentes']) for k, v in report['perfil'].items() if v['ausentes']]
    text.append('Campos vazios: ' + ('; '.join(f'{k}: {n}' for k, n in missing[:15]) if missing else 'nenhum'))
    if len(missing) > 15:
        text.append('Mais colunas com ausências estão no relatório completo.')
    if report['linhas_irregulares']:
        text.append(f"Linhas com largura irregular: {report['linhas_irregulares']}; campos excedentes foram preservados em colunas extras.")
    if report['datas_invalidas']:
        text.append(f"Datas ISO inválidas: {report['datas_invalidas']}; preservadas para revisão.")
    if not report.get('gerou_csv', True):
        text.append('Apenas diagnóstico solicitado; nenhuma limpeza foi executada.')
    elif report['valores_alterados'] == 0 and changes['cabecalhos'] == 0 and changes['linhas_vazias'] == 0 and changes['duplicatas_removidas'] == 0:
        text.append('Nenhuma alteração de conteúdo foi necessária pelas regras aplicadas. Isso não certifica a qualidade semântica da base.')
    text.append('Valores ausentes não foram inventados; formatos ambíguos e possíveis inconsistências exigem revisão.')
    text.append(f"Processamento integral, sem amostragem: {report['segundos']:.1f} s.")
    return '\n'.join(text)


def pretty_number(value):
    if value is None:
        return 'não disponível'
    with localcontext() as context:
        context.prec = 256
        number = Decimal(value)
        if abs(number) >= Decimal('1e15'):
            return str(number)
        return format(number, ',.4f').rstrip('0').rstrip('.').replace(',', '#').replace('.', ',').replace('#', '.')


def column_summary(name, profile):
    lines = [f'Coluna: {name}', f"Campos vazios: {profile['ausentes']}",
             f"Números com formato inequívoco: {profile['numeros_inequivocos']}"]
    if profile['numeros_inequivocos']:
        lines += [f"Menor valor: {pretty_number(profile['minimo_numerico'])}",
                  f"Maior valor: {pretty_number(profile['maximo_numerico'])}",
                  f"Média dos valores numéricos: {pretty_number(profile['media_numerica'])}",
                  f"Soma dos valores numéricos: {pretty_number(profile['soma_numerica'])}",
                  f"Valores negativos preservados: {profile['negativos_preservados']}"]
    if profile['zeros_iniciais_preservados']:
        lines.append(f"Valores com zeros iniciais preservados: {profile['zeros_iniciais_preservados']}")
    if profile['numeros_com_virgula_preservados']:
        lines.append(f"Valores com vírgula preservados sem conversão: {profile['numeros_com_virgula_preservados']}")
    if profile['datas_iso_invalidas']:
        lines.append(f"Datas ISO inválidas para revisão: {profile['datas_iso_invalidas']}")
    types = profile['tipos_observados']
    if types.get('numero') and types.get('texto'):
        lines.append('Revisar: a coluna mistura números e texto. Isso pode ser válido, dependendo do significado da coluna.')
    return '\n'.join(lines)


def write_report(report, folder):
    folder = Path(folder)
    (folder / 'relatorio.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    details = [summary(report), '', 'O QUE REVISAR']
    missing = [name for name, profile in report['perfil'].items() if profile['ausentes']]
    if missing:
        details.append('Dados ausentes: procure os valores na fonte original ou defina uma regra de preenchimento com o responsável pelos dados. Campos vazios foram mantidos.')
    if report['duplicatas']:
        details.append('Repetições: confirme a chave identificadora antes de excluir. Linhas iguais podem representar pessoas ou eventos diferentes. /deduplicar só remove repetições integrais quando solicitado.')
    details += ['Valores extremos e negativos não são necessariamente erros. Não foram removidos automaticamente.',
                '', 'PERFIL POR COLUNA — TODOS OS REGISTROS AVALIADOS']
    for name, profile in report['perfil'].items():
        details += ['', column_summary(name, profile)]
    details += ['', 'ALTERAÇÕES NOS CABEÇALHOS']
    changed = [m for m in report['mapeamento_cabecalhos'] if m['origem'] != m['destino']]
    details.extend([f"{m['origem']!r} -> {m['destino']}" for m in changed] or ['Nenhuma.'])
    details += ['', 'LIMITES DA ANÁLISE',
                'As estatísticas descrevem valores numéricos; somar códigos ou categorias numéricas pode não ter significado.',
                'Valores ausentes, zeros iniciais e números ambíguos não são convertidos nem preenchidos por suposição.',
                'Este diagnóstico não verifica todas as regras específicas de negócio. Não comprova que cada registro seja verdadeiro.',
                *report['avisos'], '', 'RASTREABILIDADE', f"SHA-256 da entrada tabular: {report['sha256_entrada']}",
                f"Tamanho da entrada tabular: {report['bytes_entrada']} bytes", f"Partes CSV: {len(report['partes'])}"]
    (folder / 'relatorio.txt').write_text('\n'.join(details), encoding='utf-8-sig')


def run(path, folder, deduplicate=False, progress=None, max_part_bytes=40 * 1024 ** 2, operation='arrumar', options=None):
    options = options or {}
    started = time.monotonic()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    if Path(path).resolve().parent == folder.resolve() and Path(path).name.startswith('curabot_organizado_'):
        raise ValueError('Escolha outra pasta de saída para não sobrescrever o arquivo original.')
    source = Source(path)
    analysis_only = operation in {'diagnostico', 'vazios', 'duplicatas'}
    if operation not in {'arrumar', 'cabecalhos', 'espacos', 'linhas_vazias', 'deduplicar', 'diagnostico', 'vazios', 'duplicatas', 'pontuacao', 'separador'}:
        raise ValueError('Operação desconhecida.')
    trim = operation in {'arrumar', 'espacos'}
    remove_empty = operation in {'arrumar', 'linhas_vazias'}
    rename = operation in {'arrumar', 'cabecalhos'}
    deduplicate = deduplicate or operation == 'deduplicar'
    delimiter = options.get('delimiter', source.delimiter or ',')
    if operation == 'arrumar':
        delimiter = ','
    if delimiter not in (',', ';', '\t', '|'):
        raise ValueError('Separador inválido.')
    numeric_column = None
    if operation == 'pontuacao':
        column = options.get('column')
        if column not in source.headers:
            raise ValueError('Coluna não encontrada. Use um destes nomes: ' + ', '.join(source.headers))
        numeric_column = source.headers.index(column)
        if options.get('direction') not in ('br_para_us', 'us_para_br'):
            raise ValueError('Use br_para_us ou us_para_br.')
    # First pass discovers extra fields without discarding data or changing output headers midway.
    width = len(source.headers)
    total = 0
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        while block := stream.read(1024 ** 2):
            digest.update(block)
    for row in source.rows():
        width = max(width, len(row))
        total += 1
        if width > MAX_COLUMNS:
            raise ValueError('A tabela excede 2.000 colunas.')
        if progress and total % 100000 == 0:
            progress('Conferindo estrutura', total)
    headers = list(source.headers)
    while len(headers) < width:
        name = f'extra_{len(headers) - len(source.headers) + 1}'
        while name in headers:
            name = '_' + name
        headers.append(name)
    profiles = [Profile() for _ in headers]
    output_headers = headers if rename else list(source.original_headers) + headers[len(source.headers):]
    report = {'arquivo': Path(path).name, 'sha256_entrada': digest.hexdigest(), 'bytes_entrada': Path(path).stat().st_size,
              'operacao': operation, 'opcoes': options, 'delimitador_saida': delimiter, 'conversoes_ignoradas': 0, 'gerou_csv': not analysis_only, 'linhas_vazias_encontradas': 0,
              'registros_lidos': total, 'registros_exportados': 0, 'duplicatas': 0, 'linhas_irregulares': 0,
              'colunas': headers, 'codificacao': source.encoding, 'delimitador': source.delimiter,
              'alteracoes': {'cabecalhos': sum(str(a) != b for a, b in zip(source.original_headers, source.headers)) if rename else 0,
                             'espacos': 0, 'linhas_vazias': 0, 'formulas_protegidas': 0, 'duplicatas_removidas': 0, 'pontuacao': 0},
              'avisos': source.warnings, 'mapeamento_cabecalhos': [{'origem': str(a), 'destino': b} for a, b in zip(source.original_headers, output_headers)]}
    connection = sqlite3.connect(folder / 'duplicates.sqlite')
    connection.execute('PRAGMA cache_size=-8192')
    connection.execute('PRAGMA journal_mode=OFF')
    connection.execute('DROP TABLE IF EXISTS seen')
    connection.execute('CREATE TABLE seen (row BLOB PRIMARY KEY) WITHOUT ROWID')
    parts = Parts(folder, output_headers, max_part_bytes, delimiter=delimiter if operation != 'arrumar' else ',')
    changes = report['alteracoes']
    try:
        for index, row in enumerate(source.rows(), 1):
            original = [scalar(v) for v in row]
            values = [v.strip() for v in original] if trim else original
            if not any(v.strip() for v in original):
                report['linhas_vazias_encontradas'] += 1
                if remove_empty:
                    changes['linhas_vazias'] += 1
                    continue
            if len(values) != len(source.headers):
                report['linhas_irregulares'] += 1
            changes['espacos'] += sum(a != b for a, b in zip(original, values))
            values += [''] * (width - len(values))
            if numeric_column is not None:
                value = values[numeric_column]
                decimal, thousands = (',', '.') if options['direction'] == 'br_para_us' else ('.', ',')
                pattern = r'[+-]?(?:0|[1-9]\d*|[1-9]\d{0,2}(?:' + re.escape(thousands) + r'\d{3})+)(?:' + re.escape(decimal) + r'\d+)?'
                if re.fullmatch(pattern, value):
                    converted = value.replace(thousands, '').replace(decimal, '.' if decimal == ',' else ',')
                    changes['pontuacao'] += converted != value
                    values[numeric_column] = converted
                elif value:
                    report['conversoes_ignoradas'] += 1
            key = json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            cursor = connection.execute('INSERT OR IGNORE INTO seen VALUES (?)', (key,))
            if cursor.rowcount == 0:
                report['duplicatas'] += 1
                if deduplicate:
                    changes['duplicatas_removidas'] += 1
                    continue
            safe = []
            for profile, value in zip(profiles, values):
                profile.add('' if not value.strip() else value)
                if not analysis_only and operation == 'arrumar' and value.startswith(('=', '@', '+', '-')) and not (NUMBER.fullmatch(value) or COMMA_NUMBER.fullmatch(value)):
                    value = "'" + value
                    changes['formulas_protegidas'] += 1
                safe.append(value)
            if not analysis_only:
                parts.write(safe)
            report['registros_exportados'] += 1
            if index % 10000 == 0:
                connection.commit()
            if progress and index % 100000 == 0:
                progress('Tratando e diagnosticando', index)
        connection.commit()
    finally:
        parts.close()
        connection.close()
        (folder / 'duplicates.sqlite').unlink(missing_ok=True)
    report['perfil'] = {header: profile.report() for header, profile in zip(headers, profiles)}
    report['datas_invalidas'] = sum(p.invalid_dates for p in profiles)
    report['valores_alterados'] = changes['espacos'] + changes['formulas_protegidas'] + changes['pontuacao']
    report['segundos'] = round(time.monotonic() - started, 3)
    report['partes'] = [p.name for p in parts.files]
    assert total == report['registros_exportados'] + changes['linhas_vazias'] + changes['duplicatas_removidas']
    report['registros_avaliados'] = report['registros_exportados']
    if analysis_only:
        report['registros_exportados'] = 0
    write_report(report, folder)
    return report, parts.files
