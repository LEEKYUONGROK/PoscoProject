"""Length-prefixed protobuf framing, independent of inference."""
import re
import json
import uuid
import struct
from . import protocol_pb2 as pb

HEADER = struct.Struct('<HH')
MAX_PACKET = 65535


class TruncatedPacket(ConnectionError):
    """EOF after a packet has begun (unlike clean EOF between packets)."""


class InvalidLength(ValueError):
    pass


def recv_exact(sock, count, clean_eof=False):
    result = bytearray()
    while len(result) < count:
        data = sock.recv(count - len(result))
        if not data:
            if clean_eof and not result:
                return None
            raise TruncatedPacket(f'expected {count} bytes, received {len(result)}')
        result.extend(data)
    return bytes(result)


def receive_packet(sock):
    header = recv_exact(sock, HEADER.size, clean_eof=True)
    if header is None:
        return None
    length, msg_id = HEADER.unpack(header)
    if length < HEADER.size:
        raise InvalidLength(f'invalid total length: {length}')
    return msg_id, recv_exact(sock, length - HEADER.size)


def message_id(message):
    name = re.sub(r'(?<!^)(?=[A-Z])', '_', message.DESCRIPTOR.name).upper()
    return pb.MsgId.Value(name)


def encode_packet(message):
    length = HEADER.size + message.ByteSize()
    if length > MAX_PACKET:
        raise ValueError('message exceeds maximum packet size')
    return HEADER.pack(length, message_id(message)) + message.SerializeToString()


def bounded_report(content):
    report = pb.Report(Content=content)
    if report.ByteSize() <= MAX_PACKET - HEADER.size:
        return report
    marker = '\n[응답 크기 제한으로 일부 생략]'
    raw = content.encode('utf-8')
    lo, hi = 0, min(len(raw), MAX_PACKET)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = pb.Report(Content=raw[:mid].decode('utf-8', errors='ignore') + marker)
        if candidate.ByteSize() <= MAX_PACKET - HEADER.size:
            lo = mid
        else:
            hi = mid - 1
    return pb.Report(Content=raw[:lo].decode('utf-8', errors='ignore') + marker)


def input_records(msg_id, body):
    types = {pb.SENSOR_MSG: pb.SensorMsg, pb.SENSORS_MSG: pb.SensorsMsg, pb.REPORT: pb.Report}
    if msg_id not in types:
        raise ValueError(f'unsupported MsgId: {msg_id}')
    message = types[msg_id]()
    message.ParseFromString(body)
    sensors = [(None, message.Content)] if msg_id == pb.REPORT else [
        (item.sensorID, item.msg) for item in (message.info if msg_id == pb.SENSORS_MSG else [message])]
    packet_id = uuid.uuid4().hex
    records = []
    for sensor_index, (sensor, text) in enumerate(sensors):
        metadata = None
        try:
            obj = json.loads(text)
        except (ValueError, TypeError):
            obj = None
        if isinstance(obj, dict) and '_bridge' in obj:
            metadata = obj['_bridge']
            if not isinstance(metadata, dict) or not isinstance(obj.get('log'), str):
                raise ValueError('invalid _bridge/log envelope')
            if any(not isinstance(metadata.get(key), str) or not 0 < len(metadata[key]) <= 256
                   for key in ('source', 'row_id')):
                raise ValueError('invalid remote source/row ID')
            text = obj['log']
        for line_index, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            records.append({
                'sensor_id': str(sensor) if sensor is not None else None,
                'text': f'[sensorID={sensor}] {line}' if sensor is not None else line,
                'source': 'remote:' + metadata['source'] if metadata else 'protobuf',
                'row_key': f"{metadata['row_id']}:{line_index}" if metadata else f'{packet_id}:{sensor_index}:{line_index}',
            })
    return records


def extract_logs(msg_id, body):
    return '\n'.join(record['text'] for record in input_records(msg_id, body))
