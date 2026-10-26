"""Stay connected to the equipment protobuf server and queue one report per log line.

The equipment host pushes packets as soon as we connect. Only SensorMsg (0) and
SensorsMsg (1) are sensor logs. MsgId 6 and the other undefined bodies are not
logs. This client does not send Report back: that reply belongs to the listener
where they connect to us.

When the sender does not include a _bridge row id, the row key is the SHA-256 of
the exact decoded line. That is payload identity, not a sender-assigned id.
Identical lines are not queued twice after a reconnect. A changed line is a new
record.
"""
import argparse
import hashlib
import logging
import socket
import threading
import time

from . import protocol_pb2 as pb
from .report_archive import ReportArchive, DEFAULT_PATH
from .sensor_stream import SensorStream, now
from .worker_report import process_windows
from .tcp_protocol import receive_packet, input_records, InvalidLength, TruncatedPacket

SENSOR_IDS = {pb.SENSOR_MSG, pb.SENSORS_MSG}


def identity_records(msg_id, body, source):
    """Return sensor-log records, or None when this packet is not a sensor log."""
    if msg_id not in SENSOR_IDS:
        return None
    records = input_records(msg_id, body)
    for record in records:
        if record['source'] != 'protobuf':
            continue
        record['source'] = source
        record['row_key'] = hashlib.sha256(record['text'].encode('utf-8')).hexdigest()
    return records


def run_client(host, port, stream, stop, read_timeout=120):
    source = f'remote:{host}:{port}'
    delay = 1
    while not stop.is_set():
        try:
            with socket.create_connection((host, port), timeout=10) as sock:
                sock.settimeout(read_timeout)
                logging.info('CONNECTED %s:%s', host, port)
                delay = 1
                while not stop.is_set():
                    try:
                        packet = receive_packet(sock)
                    except TimeoutError:
                        continue
                    if packet is None:
                        logging.info('EOF %s:%s', host, port)
                        break
                    msg_id, body = packet
                    records = identity_records(msg_id, body, source)
                    if records is None:
                        logging.info('SKIP msg_id=%s bytes=%s', msg_id, len(body))
                        continue
                    seqs = stream.ingest(records) if records else []
                    logging.info('INGESTED msg_id=%s records=%d seqs=%s', msg_id, len(records), seqs[:8])
        except (InvalidLength, TruncatedPacket, OSError, TimeoutError):
            logging.exception('remote connection failed %s:%s', host, port)
        if stop.wait(delay):
            return
        delay = min(delay * 2, 30)


def serve_cards(stream, stop, backend, report_style='rcaeval'):
    from .report_batches import ReportBatches
    batches = ReportBatches(stream)
    batches.recover()
    while not stop.is_set():
        try:
            if batches.process_one(backend):
                continue
            if not process_windows(stream, backend=backend, report_style=report_style):
                stop.wait(0.5)
        except Exception:
            logging.exception('worker card failed')
            stop.wait(2)


def heartbeat(stream, stop):
    while not stop.is_set():
        with stream.connect() as conn:
            conn.execute('INSERT OR REPLACE INTO sensor_stream_status VALUES (?,?)', ('heartbeat', now()))
        stop.wait(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='3.39.173.120')
    parser.add_argument('--port', type=int, default=7777)
    parser.add_argument('--read-timeout', type=float, default=120)
    parser.add_argument('--report-db', default=str(DEFAULT_PATH))
    parser.add_argument('--adapter', default='llm/finetuning/runs/qwen-korean-rcaeval/adapter')
    parser.add_argument('--report-style', choices=('prose', 'rcaeval'), default='prose')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or args.read_timeout <= 0:
        parser.error('invalid port or nonpositive limit')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    archive = ReportArchive(args.report_db)
    stream = SensorStream(archive)
    stream.owner_lock = stream.path.with_suffix('.worker.lock').open('a')
    try:
        import fcntl
        fcntl.flock(stream.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        stream.owner_lock.close()
        raise RuntimeError('another sensor report worker owns this database')
    with stream.connect() as conn:
        conn.execute("UPDATE sensor_records SET state='pending' WHERE state='running'")
    from llm.qa_factory.model import LocalModel
    backend = LocalModel('Qwen/Qwen3-4B-Instruct-2507', adapter=args.adapter, load_in_4bit=True)
    stop = threading.Event()
    with stream.connect() as conn:
        conn.executemany('INSERT OR REPLACE INTO sensor_stream_status VALUES (?,?)',
                         [('model', backend.model_id), ('adapter', args.adapter), ('started', now()),
                          ('report_style', args.report_style)])
    monitor = threading.Thread(target=heartbeat, args=(stream, stop), name='sensor-heartbeat', daemon=True)
    monitor.start()
    worker = threading.Thread(target=serve_cards, args=(stream, stop, backend, args.report_style), name='sensor-report-worker', daemon=True)
    worker.start()
    logging.info('READY remote=%s:%s format=%s adapter=%s db=%s', args.host, args.port, args.report_style, args.adapter, args.report_db)
    try:
        run_client(args.host, args.port, stream, stop, args.read_timeout)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        worker.join()
        monitor.join()
        stream.owner_lock.close()


if __name__ == '__main__':
    main()
