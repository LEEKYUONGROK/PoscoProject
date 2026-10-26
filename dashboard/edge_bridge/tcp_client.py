"""Send a UTF-8 real log file once, print one Report, and exit."""
import argparse
from pathlib import Path
import socket
from . import protocol_pb2 as pb
from .tcp_protocol import encode_packet, receive_packet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=9000)
    parser.add_argument('--log-file', type=Path, required=True)
    parser.add_argument('--sensor-id', type=int, default=302)
    parser.add_argument('--type', choices=['sensor', 'sensors', 'report'], default='sensor')
    parser.add_argument('--timeout', type=float, default=600)
    args = parser.parse_args()
    text = args.log_file.read_text(encoding='utf-8')
    sensor = pb.SensorMsg(sensorID=args.sensor_id, msg=text)
    message = {'sensor': sensor, 'sensors': pb.SensorsMsg(info=[sensor]),
               'report': pb.Report(Content=text)}[args.type]
    with socket.create_connection((args.host, args.port), timeout=args.timeout) as sock:
        sock.sendall(encode_packet(message))
        packet = receive_packet(sock)
        if packet is None or packet[0] != pb.REPORT:
            raise RuntimeError('expected Report response')
        print(pb.Report.FromString(packet[1]).Content)
        # Do not echo Report back: REPORT is also a valid input request type.


if __name__ == '__main__':
    main()
