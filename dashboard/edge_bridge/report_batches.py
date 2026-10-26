"""Persistent snapshots of recent sensor logs, generated in reading order."""
import json
import logging
import uuid

from .sensor_stream import now


class ReportBatches:
    def __init__(self, stream):
        self.stream = stream
        with stream.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS report_batches (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, sensor_id TEXT);
                CREATE TABLE IF NOT EXISTS report_batch_items (
                    batch_id TEXT NOT NULL, position INTEGER NOT NULL, record_seq INTEGER NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', report_id TEXT, error TEXT,
                    PRIMARY KEY(batch_id, position));
                CREATE TABLE IF NOT EXISTS report_retention_events (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, position INTEGER NOT NULL,
                    report_id TEXT NOT NULL, decision TEXT NOT NULL, created_at TEXT NOT NULL);
            ''')

    def create(self, sensor_id=None, limit=100):
        if sensor_id not in (None, '301', '302', '305'):
            raise ValueError('unsupported sensor filter')
        if limit != 100:
            raise ValueError('batch size must be 100')
        with self.stream.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            where = 'WHERE sensor_id=?' if sensor_id else ''
            args = (sensor_id, limit) if sensor_id else (limit,)
            rows = conn.execute(f'SELECT seq FROM sensor_records {where} ORDER BY seq DESC LIMIT ?', args).fetchall()
            if not rows:
                raise ValueError('선택한 센서의 수신 로그가 없습니다.')
            identifier = uuid.uuid4().hex
            conn.execute('INSERT INTO report_batches VALUES (?,?,?)', (identifier, now(), sensor_id))
            conn.executemany('INSERT INTO report_batch_items (batch_id,position,record_seq) VALUES (?,?,?)',
                             [(identifier, i, row['seq']) for i, row in enumerate(reversed(rows), 1)])
        return identifier

    def get(self, identifier):
        with self.stream.connect() as conn:
            batch = conn.execute('SELECT * FROM report_batches WHERE id=?', (identifier,)).fetchone()
            if batch is None:
                raise KeyError(identifier)
            rows = conn.execute('''SELECT b.*,s.sensor_id,s.log_text,s.received_at,s.row_key,s.source
                FROM report_batch_items b JOIN sensor_records s ON s.seq=b.record_seq
                WHERE b.batch_id=? ORDER BY b.position''', (identifier,)).fetchall()
            return {**dict(batch), 'items': [dict(row) for row in rows]}

    def recover(self):
        with self.stream.connect() as conn:
            conn.execute("UPDATE report_batch_items SET state='pending' WHERE state='running'")

    def list_recent(self, sensor_id=None):
        with self.stream.connect() as conn:
            where = 'WHERE b.sensor_id=?' if sensor_id else ''
            return [dict(row) for row in conn.execute(f'''SELECT b.*,
                COUNT(i.position) AS total, SUM(i.state IN ('complete','failed')) AS finished
                FROM report_batches b JOIN report_batch_items i ON i.batch_id=b.id {where}
                GROUP BY b.id ORDER BY b.created_at DESC LIMIT 20''', (sensor_id,) if sensor_id else ())]

    def retention(self, identifier, position):
        with self.stream.connect() as conn:
            row = conn.execute('''SELECT decision FROM report_retention_events WHERE batch_id=? AND position=?
                ORDER BY created_at DESC, rowid DESC LIMIT 1''', (identifier, position)).fetchone()
        return row['decision'] if row else None

    def retain(self, identifier, position, report_id, decision):
        if decision not in ('keep', 'discard'):
            raise ValueError('invalid retention decision')
        with self.stream.connect() as conn:
            row = conn.execute('SELECT report_id FROM report_batch_items WHERE batch_id=? AND position=?',
                               (identifier, position)).fetchone()
            if not row or row['report_id'] != report_id:
                raise ValueError('보고서가 변경되었습니다. 새로고침하세요.')
            conn.execute('INSERT INTO report_retention_events VALUES (?,?,?,?,?,?)',
                         (uuid.uuid4().hex, identifier, position, report_id, decision, now()))

    def process_one(self, backend):
        from .broker_prose import generate, VERSION
        with self.stream.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('''SELECT i.*,s.sensor_id,s.log_text FROM report_batch_items i
                JOIN report_batches b ON b.id=i.batch_id JOIN sensor_records s ON s.seq=i.record_seq
                WHERE i.state='pending' ORDER BY b.created_at,b.id,i.position LIMIT 1''').fetchone()
            if row is None:
                return False
            row = dict(row)
            conn.execute("UPDATE report_batch_items SET state='running' WHERE batch_id=? AND position=?",
                         (row['batch_id'], row['position']))
        error = None
        try:
            outcome = generate(backend, [{'sensor_id': row['sensor_id'], 'text': row['log_text']}])
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
            outcome = {'text': '보고서 생성에 실패했습니다. 입력 로그와 오류를 확인하세요.',
                       'passed': False, 'error': error, 'facts': {}, 'report': None,
                       'raw': None, 'history': [], 'terminology': None}
            logging.exception('batch report failed position=%s', row['position'])
        details = {'model': getattr(backend, 'model_id', 'unknown'), 'facts': outcome['facts'],
                   'structured_report': outcome['report'], 'validation_error': outcome['error'],
                   'glossary_validation': outcome['terminology'],
                   'source_record': {'seq': row['record_seq'], 'sensor_id': row['sensor_id'], 'rows': 1},
                   'batch_id': row['batch_id'], 'batch_position': row['position'],
                   'report_generation': {'method': 'qwen_broker_prose', 'prompt_version': VERSION,
                                         'raw_model_output': outcome['raw'], 'attempts': outcome['history']},
                   'validation': {'passed': outcome['passed'], 'judge': 'not_run',
                                  'operator_review': 'not_performed'}}
        report_id = uuid.uuid4().hex
        with self.stream.connect() as conn:
            conn.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)',
                         (report_id, now(), 0, row['log_text'], outcome['text'], 'error' if error else 'complete',
                          json.dumps(details, ensure_ascii=False, allow_nan=False)))
            conn.execute('''UPDATE report_batch_items SET state=?,report_id=?,error=?
                WHERE batch_id=? AND position=?''', ('failed' if error else 'complete', report_id,
                outcome['error'], row['batch_id'], row['position']))
        logging.info('BATCH_REPORT batch=%s position=%s passed=%s', row['batch_id'], row['position'], outcome['passed'])
        return True
