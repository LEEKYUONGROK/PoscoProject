"""Local presentation service. Existing receiver/model worker own all generation."""
import argparse
import json
import logging
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .data import Dashboard
from edge_bridge.report_archive import DEFAULT_PATH

WEB = Path(__file__).with_name('web')


def make_handler(dashboard):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, kind='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False, allow_nan=False).encode() if 'application/json' in kind else data
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store' if 'json' in kind else 'no-cache')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'same-origin')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                parsed = urlparse(self.path)
                path = unquote(parsed.path)
                filters = {k: v[-1] for k, v in parse_qs(parsed.query).items()}
                if filters.get('sensor') not in (None, '', '301', '302', '305'):
                    raise ValueError('지원하지 않는 센서입니다.')
                if filters.get('event') not in (None, '', 'fire', 'vision', 'other'):
                    raise ValueError('지원하지 않는 이벤트 유형입니다.')
                if path == '/api/health':
                    return self.reply(200, {'status': 'ok', 'source': 'existing_protobuf_archive'})
                if path == '/api/reports':
                    return self.reply(200, dashboard.reports(filters))
                if path.startswith('/api/reports/'):
                    return self.reply(200, dashboard.detail(path[len('/api/reports/'):]))
                if path == '/api/monitoring':
                    return self.reply(200, dashboard.monitoring(filters))
                if path == '/api/batches':
                    return self.reply(200, {'items': dashboard.batches.list_recent(filters.get('sensor') or None)})
                if path.startswith('/api/batches/'):
                    return self.reply(200, dashboard.batches.get(path[len('/api/batches/'):]))
                if path.startswith('/api/'):
                    return self.reply(404, {'error': '찾을 수 없는 API입니다.'})
                asset = WEB / ('index.html' if path == '/' else path.lstrip('/'))
                if asset.parent != WEB or not asset.is_file():
                    return self.reply(404, {'error': '파일을 찾을 수 없습니다.'})
                self.reply(200, asset.read_bytes(), (mimetypes.guess_type(asset.name)[0] or 'application/octet-stream') + '; charset=utf-8')
            except KeyError:
                self.reply(404, {'error': '보고서 또는 생성 목록을 찾을 수 없습니다.'})
            except (ValueError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except Exception:
                logging.exception('dashboard read failed')
                self.reply(500, {'error': '데이터를 불러오지 못했습니다. 잠시 후 다시 시도하세요.'})

        def do_POST(self):
            try:
                if self.headers.get('Origin') and urlparse(self.headers['Origin']).netloc != self.headers.get('Host'):
                    return self.reply(403, {'error': '동일한 대시보드에서 요청하세요.'})
                if not self.headers.get('Content-Type', '').startswith('application/json'):
                    return self.reply(415, {'error': 'JSON 요청이 필요합니다.'})
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('요청 크기가 올바르지 않습니다.')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('객체 요청이 필요합니다.')
                if self.path == '/api/batches':
                    batch_id = dashboard.batches.create(body.get('sensor') or None)
                    batch = dashboard.batches.get(batch_id)
                    return self.reply(201, {'id': batch_id, 'total': len(batch['items']),
                                            'first_key': dashboard.batch_key(batch['items'][0])})
                if self.path == '/api/retention':
                    dashboard.batches.retain(body['batch_id'], int(body['position']), body['report_id'], body['decision'])
                    return self.reply(200, {'saved': True})
                self.reply(404, {'error': '찾을 수 없는 API입니다.'})
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(400, {'error': str(exc)})
            except Exception:
                logging.exception('dashboard write failed')
                self.reply(500, {'error': '요청을 저장하지 못했습니다. 다시 시도하세요.'})

        def log_message(self, fmt, *args):
            logging.info(fmt, *args)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8600)
    parser.add_argument('--db', default=str(DEFAULT_PATH))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    server = ThreadingHTTPServer((args.host, args.port), make_handler(Dashboard(args.db)))
    logging.info('Vision4 dashboard ready http://%s:%s', args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
