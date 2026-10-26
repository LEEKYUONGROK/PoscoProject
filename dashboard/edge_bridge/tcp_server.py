"""TCP request/Report response service. Run from models with python -m edge_bridge.tcp_server."""
import argparse
from collections import deque
import logging
import socketserver
import threading
from .log_analyzer import LogAnalyzer
from .report_archive import ReportArchive, DEFAULT_PATH
from .sensor_stream import SensorStream
from .tcp_protocol import (receive_packet, input_records, encode_packet, bounded_report,
                           InvalidLength, TruncatedPacket)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        self.request.settimeout(self.server.read_timeout)
        logging.info('CONNECTED peer=%s', self.client_address)
        packets, record_count, reports = 0, 0, 0
        sent_reports = deque(maxlen=128)
        while True:
            try:
                packet = receive_packet(self.request)
                if packet is None:
                    logging.info('EOF peer=%s packets=%d records=%d reports=%d',
                                 self.client_address, packets, record_count, reports)
                    return
                packets += 1
                logging.info('RECEIVED peer=%s packet=%d msg_id=%d bytes=%d',
                             self.client_address, packets, packet[0], len(packet[1]) + 4)
                if packet[0] == 10 and packet[1] in sent_reports:
                    logging.warning('response echo detected; closing connection: %s', self.client_address)
                    return
                text, details, records = '', {}, []
                try:
                    records = input_records(*packet)
                    record_count += len(records)
                    logging.info('DECODED peer=%s packet=%d records=%d total_records=%d',
                                 self.client_address, packets, len(records), record_count)
                    text = '\n'.join(record['text'] for record in records)
                    details = self.server.analyzer.analyze(text)
                    analysis = details['report']
                except Exception as exc:
                    logging.exception('request failed: %s', self.client_address)
                    analysis = f'ERROR: {type(exc).__name__}: {exc}'
                # Send exactly once; responses are never dispatched as new requests locally.
                report = bounded_report(analysis)
                if self.server.archive is not None:
                    try:
                        identifier = self.server.archive.save(packet[0], text, report.Content, details)
                        if self.server.sensor_stream is not None and records:
                            self.server.sensor_stream.ingest(records, completed_report=(
                                identifier if not report.Content.startswith('ERROR:') else None))
                    except Exception:
                        logging.exception('report archive failed')
                        report = bounded_report('ERROR: report storage failed')
                encoded = encode_packet(report)
                self.request.sendall(encoded)
                reports += 1
                logging.info('REPORT_SENT peer=%s packet=%d msg_id=10 bytes=%d reports=%d error=%s',
                             self.client_address, packets, len(encoded), reports,
                             report.Content.startswith('ERROR:'))
                sent_reports.append(report.SerializeToString())
            except (InvalidLength, TruncatedPacket, OSError) as exc:
                logging.warning('connection closed peer=%s packets=%d records=%d reports=%d (%s): %s',
                                self.client_address, packets, record_count, reports, type(exc).__name__, exc)
                return


class LogTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    block_on_close = True

    def __init__(self, address, analyzer, read_timeout=120, max_clients=8, archive=None, sensor_stream=None):
        self.analyzer = analyzer
        self.archive = archive
        self.sensor_stream = sensor_stream
        self.read_timeout = read_timeout
        self.slots = threading.BoundedSemaphore(max_clients)
        super().__init__(address, Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--model', default='Qwen/Qwen3-4B-Instruct-2507')
    parser.add_argument('--max-tokens', type=int, default=1200)
    parser.add_argument('--selection-retry-max-tokens', type=int, default=None,
                        help='Selection retry ceiling; only expanded after truncated output')
    parser.add_argument('--report-max-tokens', type=int, default=1024,
                        help='Qwen prose budget per valid single record; 0 keeps evidence rendering only')
    parser.add_argument('--read-timeout', type=float, default=120)
    parser.add_argument('--max-clients', type=int, default=8)
    parser.add_argument('--report-db', default=str(DEFAULT_PATH))
    parser.add_argument('--allow-download', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or min(args.max_tokens, args.read_timeout, args.max_clients) <= 0 or args.report_max_tokens < 0:
        parser.error('invalid port or nonpositive limit')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if args.selection_retry_max_tokens is not None and args.selection_retry_max_tokens < args.max_tokens:
        parser.error('selection retry ceiling must be >= max-tokens')
    analyzer = LogAnalyzer(args.model, args.max_tokens, args.allow_download,
                           retry_max_tokens=args.selection_retry_max_tokens, report_max_tokens=args.report_max_tokens)
    archive = ReportArchive(args.report_db)
    stream = SensorStream(archive)
    stream.start(analyzer)
    try:
        with LogTCPServer((args.host, args.port), analyzer, args.read_timeout, args.max_clients,
                          archive=archive, sensor_stream=stream) as server:
            logging.info('READY %s:%s model=%s', *server.server_address, args.model)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    finally:
        stream.close()
        analyzer.close()


if __name__ == '__main__':
    main()
