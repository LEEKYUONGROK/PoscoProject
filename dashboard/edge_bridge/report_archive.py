"""Shared append-only report storage for the TCP server and existing Streamlit viewer."""
from datetime import datetime, timezone
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid

DEFAULT_PATH = Path(__file__).resolve().parent / 'data/tcp-reports.sqlite3'


class ReportArchive:
    def __init__(self, path=DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY, created_at TEXT NOT NULL, msg_id INTEGER NOT NULL,
                log_text TEXT NOT NULL, report TEXT NOT NULL, status TEXT NOT NULL,
                details_json TEXT NOT NULL)''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save(self, msg_id, log_text, report, details):
        identifier = uuid.uuid4().hex
        with self.connect() as conn:
            conn.execute('INSERT INTO reports VALUES (?, ?, ?, ?, ?, ?, ?)',
                (identifier, datetime.now(timezone.utc).isoformat(), msg_id, log_text, report,
                 'error' if report.startswith('ERROR:') else 'complete',
                 json.dumps(details, ensure_ascii=False, allow_nan=False)))
        return identifier

    def list_reports(self, limit=200):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(
                'SELECT id, created_at, msg_id, status FROM reports ORDER BY created_at DESC LIMIT ?', (limit,))]

    def get(self, identifier):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM reports WHERE id=?', (identifier,)).fetchone()
        if row is None:
            raise KeyError(identifier)
        value = dict(row)
        value['details'] = json.loads(value.pop('details_json'))
        return value
