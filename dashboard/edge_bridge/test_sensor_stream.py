import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from .report_archive import ReportArchive
from .sensor_stream import SensorStream
from .send_recent import sensor_message, batches
from .tcp_protocol import input_records, encode_packet, receive_packet, extract_logs
from .tcp_server import LogTCPServer
from . import protocol_pb2 as pb


class Analyzer:
    def analyze(self, text):
        return {'report': '검증된 한국어 보고서: ' + text, 'model': 'test'}


class SensorStreamTests(unittest.TestCase):
    def test_batch_revision_keeps_old_report_and_isolates_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = ReportArchive(Path(temp) / 'reports.db')
            stream = SensorStream(archive)
            old = archive.save(0, 'mq7=23', 'old report', {'model': 'test'})
            stream.ingest([{'text': 'mq7=23'}], completed_report=old)
            stream.ingest([{'text': 'mq7=24'}])
            with stream.connect() as conn:
                conn.execute("UPDATE sensor_records SET state='pending' WHERE seq=1")
            class BatchAnalyzer:
                def analyze_batch(inner, texts, prior_details):
                    self.assertEqual(texts, ['mq7=23', 'mq7=24'])
                    self.assertEqual(prior_details, [{'model': 'test'}, None])
                    return [{'report': 'new report', 'report_generation': {'method': 'qwen_narrative'}}, ValueError('test failure')]
            self.assertTrue(stream.process_batch(BatchAnalyzer()))
            with stream.connect() as conn:
                rows = conn.execute('SELECT report_id,state FROM sensor_records ORDER BY seq').fetchall()
            self.assertEqual(rows[0]['state'], 'complete')
            self.assertEqual(rows[1]['state'], 'retry')
            self.assertEqual(archive.get(old)['report'], 'old report')
            self.assertEqual(archive.get(rows[0]['report_id'])['details']['supersedes_report_id'], old)

    def test_latest_200_idempotency_atomic_conflict_and_next_live_record(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = ReportArchive(Path(temp) / 'reports.db')
            stream = SensorStream(archive)
            history = [{'id': i, 'sensor_id': 302, 'log': {'mq7': i}} for i in range(1, 7501)]
            for batch in batches(sensor_message(row, 'test.source') for row in history[-200:]):
                stream.ingest(input_records(1, batch.SerializeToString()))
            for _ in range(200):
                self.assertTrue(stream.process_one(Analyzer()))
            self.assertFalse(stream.process_one(Analyzer()))
            status = stream.status()
            self.assertEqual(status['total_received'], 200)
            self.assertEqual(status['counts'], {'complete': 200})
            self.assertEqual(status['records'][0]['row_key'], '7500:0')
            # Replaying IDs after restart does not generate or overwrite old reports.
            reopened = SensorStream(archive)
            message = sensor_message(history[-1], 'test.source')
            reopened.ingest(input_records(0, message.SerializeToString()))
            self.assertEqual(reopened.status()['total_received'], 200)
            conflict = sensor_message({'id': 7500, 'sensor_id': 302, 'log': {'mq7': -1}}, 'test.source')
            new = sensor_message({'id': 7501, 'sensor_id': 302, 'log': {'mq7': 42}}, 'test.source')
            records = input_records(1, pb.SensorsMsg(info=[new, conflict]).SerializeToString())
            with self.assertRaises(ValueError):
                reopened.ingest(records)
            self.assertEqual(reopened.status()['total_received'], 200)
            reopened.ingest(input_records(0, new.SerializeToString()))
            self.assertTrue(reopened.process_one(Analyzer()))
            status = reopened.status()
            self.assertEqual(status['total_received'], 201)
            self.assertEqual(len(status['records']), 200)
            self.assertEqual(status['records'][0]['row_key'], '7501:0')
            self.assertNotIn('7301:0', [r['row_key'] for r in status['records']])

    def test_restart_recovers_running_and_failed_model_is_visible(self):
        with tempfile.TemporaryDirectory() as temp:
            stream = SensorStream(ReportArchive(Path(temp) / 'reports.db'))
            stream.ingest([{'text': 'mq7=23'}])
            self.assertIsNotNone(stream.claim())
            stream.start(Analyzer())
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and stream.status()['records'][0]['state'] != 'complete':
                    time.sleep(0.01)
                self.assertEqual(stream.status()['records'][0]['state'], 'complete')
            finally:
                stream.close()
            stream.ingest([{'text': 'mq7=42'}])
            class Broken:
                def analyze(self, text):
                    raise RuntimeError('deliberate model failure')
            for _ in range(3):
                stream.process_one(Broken())
                with stream.connect() as conn:
                    conn.execute('UPDATE sensor_records SET retry_at=0')
            row = stream.status()['records'][0]
            self.assertEqual(row['state'], 'failed')
            self.assertIsNone(row['report_id'])
            self.assertIn('deliberate model failure', row['error'])

    def test_batch_fits_packet_and_preserves_ids_and_sensor_data(self):
        messages = [sensor_message({'id': i, 'sensor_id': 302, 'log': 'mq7=23 ' + '한' * 500}, 'source') for i in range(200)]
        packets = list(batches(messages))
        self.assertGreater(len(packets), 1)
        records = []
        for packet in packets:
            self.assertLessEqual(len(encode_packet(packet)), 65535)
            records.extend(input_records(1, packet.SerializeToString()))
        self.assertEqual(len(records), 200)
        self.assertEqual(records[199]['row_key'], '199:0')
        self.assertEqual(records[0]['source'], 'remote:source')
        self.assertNotIn('_bridge', records[0]['text'])
        self.assertTrue(records[0]['text'].startswith('[sensorID=302] mq7=23'))

    def test_live_socket_records_and_response_echo_closes_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            archive = ReportArchive(Path(temp) / 'reports.db')
            stream = SensorStream(archive)
            with LogTCPServer(('127.0.0.1', 0), Analyzer(), archive=archive, sensor_stream=stream) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    with socket.create_connection(server.server_address) as sock:
                        sock.settimeout(2)
                        message = sensor_message({'id': 5, 'sensor_id': 302, 'log': {'mq7': 23}}, 'source')
                        sock.sendall(encode_packet(message))
                        response_id, body = receive_packet(sock)
                        self.assertEqual(response_id, 10)
                        self.assertEqual(stream.status()['counts'], {'complete': 1})
                        self.assertIn('한국어 보고서', pb.Report.FromString(body).Content)
                        sock.sendall(encode_packet(pb.Report.FromString(body)))
                        self.assertIsNone(receive_packet(sock))
                finally:
                    server.shutdown()
                    thread.join()


if __name__ == '__main__':
    unittest.main()
