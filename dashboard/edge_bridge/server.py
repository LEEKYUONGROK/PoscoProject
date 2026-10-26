"""Authenticated event receiver; standard-library only."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sqlite3

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
TOKEN = DATA / 'api_token'
DB = DATA / 'events.sqlite3'


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.reply(200, {'status': 'ok'}) if self.path == '/health' else self.reply(404, {'error': 'not_found'})

    def do_POST(self):
        if self.path != '/events':
            return self.reply(404, {'error': 'not_found'})
        supplied = self.headers.get('Authorization', '')
        if not secrets.compare_digest(supplied, 'Bearer ' + self.server.api_token):
            return self.reply(401, {'error': 'unauthorized'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.reply(400, {'error': 'invalid_content_length'})
        if not 0 < length <= 65536:
            return self.reply(413, {'error': 'body_must_be_1_to_65536_bytes'})
        try:
            event = json.loads(self.rfile.read(length))
            json.dumps(event, allow_nan=False)
            if not isinstance(event, dict):
                raise ValueError('body must be an object')
            for key in ('event_id', 'device_id', 'timestamp', 'event_type'):
                if not isinstance(event.get(key), str) or not 0 < len(event[key]) <= 256:
                    raise ValueError(f'{key} must be a nonempty string, at most 256 characters')
            stamp = datetime.fromisoformat(event['timestamp'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('timestamp must include timezone')
            if 'confidence' in event and event['confidence'] is not None:
                value = event['confidence']
                if type(value) not in (int, float) or not 0 <= value <= 1:
                    raise ValueError('confidence must be null or a number from 0 to 1')
        except (ValueError, UnicodeError) as exc:
            return self.reply(400, {'error': str(exc)})
        payload = json.dumps(event, ensure_ascii=False, sort_keys=True, allow_nan=False)
        received = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(DB) as conn:
            cursor = conn.execute('INSERT OR IGNORE INTO events VALUES (?, ?, ?, ?)',
                                  (event['device_id'], event['event_id'], payload, received))
            duplicate = cursor.rowcount == 0
            if duplicate:
                old = conn.execute('SELECT payload FROM events WHERE device_id=? AND event_id=?',
                                   (event['device_id'], event['event_id'])).fetchone()[0]
                if old != payload:
                    return self.reply(409, {'error': 'event_id_conflict'})
        self.reply(200 if duplicate else 201, {'status': 'duplicate' if duplicate else 'accepted',
                                              'event_id': event['event_id']})

    def setup(self):
        super().setup()
        self.connection.settimeout(10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    DATA.mkdir(mode=0o700, exist_ok=True)
    if not TOKEN.exists():
        with TOKEN.open('x') as handle:
            TOKEN.chmod(0o600)
            handle.write(secrets.token_urlsafe(32) + '\n')
    with sqlite3.connect(DB) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS events (device_id TEXT, event_id TEXT, payload TEXT, received_at TEXT, PRIMARY KEY(device_id, event_id))')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.api_token = TOKEN.read_text().strip()
    print(f'Listening on 127.0.0.1:{args.port}; token file: {TOKEN}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
