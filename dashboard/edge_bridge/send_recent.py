"""Remote-side sender: latest 200 JSONL records first, then append-only live records.
Each JSONL entry: {"id":123,"sensor_id":302,"log":{...sensor fields...}}.
"""
import argparse
import json
from pathlib import Path
import socket
import time
from . import protocol_pb2 as pb
from .tcp_protocol import encode_packet, receive_packet, MAX_PACKET


def sensor_message(entry, source):
    if not isinstance(entry, dict) or not isinstance(entry.get('sensor_id'), int) or isinstance(entry['sensor_id'], bool):
        raise ValueError('JSONL record requires integer sensor_id')
    if 'id' not in entry or not isinstance(entry['id'], (str, int)) or isinstance(entry['id'], bool):
        raise ValueError('JSONL record requires stable string/integer id')
    log = entry.get('log')
    if isinstance(log, dict):
        log = json.dumps(log, ensure_ascii=False, allow_nan=False)
    if not isinstance(log, str) or not log.strip():
        raise ValueError('JSONL record requires nonempty log string or object')
    return pb.SensorMsg(sensorID=entry['sensor_id'], msg=json.dumps({
        '_bridge': {'source': source, 'row_id': str(entry['id'])}, 'log': log}, ensure_ascii=False))


def batches(messages):
    batch = pb.SensorsMsg()
    for message in messages:
        candidate = pb.SensorsMsg()
        candidate.CopyFrom(batch)
        candidate.info.add().CopyFrom(message)
        if candidate.ByteSize() + 4 > MAX_PACKET:
            if not batch.info:
                raise ValueError('one sensor record exceeds TCP packet size')
            yield batch
            batch = pb.SensorsMsg()
            batch.info.add().CopyFrom(message)
            if batch.ByteSize() + 4 > MAX_PACKET:
                raise ValueError('one sensor record exceeds TCP packet size')
        else:
            batch = candidate
    if batch.info:
        yield batch


def send_and_receive(sock, message):
    sock.sendall(encode_packet(message))
    packet = receive_packet(sock)
    if packet is None or packet[0] != pb.REPORT:
        raise ConnectionError('expected Report on same TCP connection')
    content = pb.Report.FromString(packet[1]).Content
    print(content, flush=True)
    if content.startswith('ERROR:'):
        raise RuntimeError('model returned ERROR; input cursor was not advanced')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--host', required=True)
    p.add_argument('--port', type=int, default=7777)
    p.add_argument('--jsonl', type=Path, required=True)
    p.add_argument('--source', required=True, help='Stable source name, e.g. vision4.sensorlog')
    p.add_argument('--recent', type=int, default=200)
    p.add_argument('--follow', action='store_true')
    p.add_argument('--interval', type=float, default=1)
    p.add_argument('--timeout', type=float, default=600)
    args = p.parse_args()
    if args.recent < 1 or args.interval <= 0 or not 0 < len(args.source) <= 256:
        p.error('invalid recent/interval/source')
    # Retain the open file position so history appended during backfill is not skipped.
    with args.jsonl.open(encoding='utf-8') as file:
        from collections import deque
        recent = deque(maxlen=args.recent)
        while True:
            position = file.tell()
            line = file.readline()
            if not line:
                break
            if not line.endswith('\n'):
                file.seek(position)
                break
            if line.strip():
                recent.append(json.loads(line))
        pending = list(batches(sensor_message(entry, args.source) for entry in recent))
        while True:
            try:
                with socket.create_connection((args.host, args.port), timeout=args.timeout) as sock:
                    while pending:
                        send_and_receive(sock, pending[0])
                        pending.pop(0)
                    if not args.follow:
                        return
                    while True:
                        position = file.tell()
                        line = file.readline()
                        if not line or not line.endswith('\n'):
                            file.seek(position)
                            time.sleep(args.interval)
                            continue
                        if line.strip():
                            message = sensor_message(json.loads(line), args.source)
                            pending = [message]
                            send_and_receive(sock, message)
                            pending = []
            except (OSError, ConnectionError):
                # Reconnect and resend the same stable IDs; receiver deduplicates them.
                if not args.follow:
                    raise
                time.sleep(args.interval)


if __name__ == '__main__':
    main()
