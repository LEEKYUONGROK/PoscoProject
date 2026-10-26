"""Durable per-record report queue, processed by the already loaded local model."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
import fcntl
import logging
import sqlite3
import threading
import time
import uuid
from .tcp_protocol import bounded_report


def now():
    return datetime.now(timezone.utc).isoformat()


class SensorStream:
    def __init__(self, archive):
        self.archive = archive
        self.path = archive.path
        self.stop = threading.Event()
        self.thread = None
        self.owner_lock = None
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS sensor_records (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL, row_key TEXT NOT NULL, sensor_id TEXT,
                    log_text TEXT NOT NULL, received_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    retry_at REAL NOT NULL DEFAULT 0, report_id TEXT, error TEXT,
                    UNIQUE(source, row_key));
                CREATE INDEX IF NOT EXISTS sensor_queue ON sensor_records(state, retry_at);
                CREATE TABLE IF NOT EXISTS sensor_stream_status (
                    name TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ingest(self, records, completed_report=None):
        """A retry with the same source/record ID is idempotent; changed content conflicts."""
        identifiers = []
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for index, record in enumerate(records):
                source = record.get('source', 'protobuf')
                key = record.get('row_key') or uuid.uuid4().hex
                text = record['text']
                old = conn.execute('SELECT seq, log_text FROM sensor_records WHERE source=? AND row_key=?',
                                   (source, key)).fetchone()
                if old:
                    if old['log_text'] != text:
                        raise ValueError('source record ID reused with different log content')
                    identifiers.append(old['seq'])
                    continue
                report = completed_report if len(records) == 1 else None
                cursor = conn.execute('''INSERT INTO sensor_records
                    (source,row_key,sensor_id,log_text,received_at,state,report_id) VALUES (?,?,?,?,?,?,?)''',
                    (source, key, record.get('sensor_id'), text, now(), 'complete' if report else 'pending', report))
                identifiers.append(cursor.lastrowid)
            conn.execute('INSERT OR REPLACE INTO sensor_stream_status VALUES (?,?)', ('last_received', now()))
        return identifiers

    def claim(self, newest=False):
        with self.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            order = 'DESC' if newest else 'ASC'
            row = conn.execute(f'''SELECT * FROM sensor_records
                WHERE state='pending' OR (state='retry' AND retry_at<=?)
                ORDER BY seq {order} LIMIT 1''', (time.time(),)).fetchone()
            if row:
                conn.execute("UPDATE sensor_records SET state='running',attempts=attempts+1 WHERE seq=?", (row['seq'],))
                return dict(row)
        return None

    def process_one(self, analyzer, newest=False):
        row = self.claim(newest=newest)
        if row is None:
            return False
        try:
            details = analyzer.analyze(row['log_text'])
            details['source_record'] = {key: row[key] for key in ('seq', 'source', 'row_key', 'sensor_id', 'received_at')}
            report = bounded_report(details['report']).Content
            # Report insertion and completion are atomic, including across process crashes.
            identifier = uuid.uuid4().hex
            with self.connect() as conn:
                conn.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)',
                    (identifier, now(), 0, row['log_text'], report, 'complete', json.dumps(details, ensure_ascii=False)))
                conn.execute("UPDATE sensor_records SET state='complete',report_id=?,error=NULL WHERE seq=?",
                             (identifier, row['seq']))
        except Exception as exc:
            logging.exception('sensor report failed seq=%s', row['seq'])
            attempts = row['attempts'] + 1
            with self.connect() as conn:
                conn.execute('UPDATE sensor_records SET state=?,retry_at=?,error=? WHERE seq=?',
                    ('failed' if attempts >= 3 else 'retry', time.time() + min(60, 2 ** attempts),
                     f'{type(exc).__name__}: {exc}', row['seq']))
        return True

    def status(self, limit=200):
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute('SELECT * FROM sensor_records ORDER BY seq DESC LIMIT ?', (limit,))]
            counts = {row['state']: row['n'] for row in conn.execute('SELECT state,COUNT(*) AS n FROM sensor_records GROUP BY state')}
            worker = {row['name']: row['value'] for row in conn.execute('SELECT * FROM sensor_stream_status')}
        return {'records': rows, 'counts': counts, 'total_received': sum(counts.values()), 'worker': worker}

    def process_batch(self, analyzer, size=4, newest=False):
        rows = []
        for _ in range(size):
            row = self.claim(newest=newest)
            if row is None:
                break
            rows.append(row)
        if not rows:
            return False
        try:
            previous = [self.archive.get(row['report_id'])['details'] if row['report_id'] else None for row in rows]
            results = analyzer.analyze_batch([row['log_text'] for row in rows], prior_details=previous)
            if len(results) != len(rows):
                raise RuntimeError('analysis batch result count mismatch')
        except Exception as exc:
            results = [exc] * len(rows)
        for row, details in zip(rows, results):
            with self.connect() as conn:
                if isinstance(details, Exception):
                    attempts = row['attempts'] + 1
                    conn.execute('UPDATE sensor_records SET state=?,retry_at=?,error=? WHERE seq=?',
                        ('failed' if attempts >= 3 else 'retry', time.time() + min(60, 2 ** attempts),
                         f'{type(details).__name__}: {details}', row['seq']))
                    logging.error('sensor narrative failed seq=%d: %s', row['seq'], details)
                    continue
                details['source_record'] = {key: row[key] for key in ('seq', 'source', 'row_key', 'sensor_id', 'received_at')}
                details['supersedes_report_id'] = row['report_id']
                identifier = uuid.uuid4().hex
                report = bounded_report(details['report']).Content
                conn.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)',
                    (identifier, now(), 0, row['log_text'], report, 'complete', json.dumps(details, ensure_ascii=False)))
                conn.execute("UPDATE sensor_records SET state='complete',report_id=?,error=NULL WHERE seq=?", (identifier, row['seq']))
                logging.info('SENSOR_REPORT_GENERATED seq=%d method=%s tokens=%s', row['seq'],
                    details.get('report_generation', {}).get('method'),
                    details.get('report_generation', {}).get('output_tokens'))
        return True

    def start(self, analyzer, newest=False):
        if self.thread and self.thread.is_alive():
            raise RuntimeError('sensor worker already running')
        self.owner_lock = self.path.with_suffix('.worker.lock').open('a')
        try:
            fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.owner_lock.close()
            self.owner_lock = None
            raise RuntimeError('another sensor report worker owns this database')
        # A single worker lives in the model server process; restart interrupted jobs.
        with self.connect() as conn:
            conn.execute("UPDATE sensor_records SET state='pending' WHERE state='running'")
        def run():
            try:
                while not self.stop.is_set():
                    try:
                        with self.connect() as conn:
                            conn.execute('INSERT OR REPLACE INTO sensor_stream_status VALUES (?,?)', ('heartbeat', now()))
                        worked = (self.process_batch(analyzer, size=16, newest=newest) if getattr(analyzer, 'report_max_tokens', 0)
                                  and hasattr(analyzer, 'analyze_batch') else self.process_one(analyzer, newest=newest))
                        if not worked:
                            self.stop.wait(0.5)
                    except Exception:
                        logging.exception('sensor worker iteration failed')
                        self.stop.wait(2)
            finally:
                with self.connect() as conn:
                    conn.execute('INSERT OR REPLACE INTO sensor_stream_status VALUES (?,?)', ('stopped', now()))
        self.thread = threading.Thread(target=run, name='sensor-report-worker', daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join()
        if self.owner_lock:
            self.owner_lock.close()
            self.owner_lock = None
