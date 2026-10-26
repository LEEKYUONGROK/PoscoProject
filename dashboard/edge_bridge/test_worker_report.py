import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from .worker_report import build_card, signature


def row(seq, body):
    return {'seq': seq, 'sensor_id': '302', 'text': f'[sensorID=302] {body}'}


class WorkerReportTests(unittest.TestCase):
    def test_changed_adapter_or_measurement_generates_new_report(self):
        from .report_archive import ReportArchive
        from .sensor_stream import SensorStream
        from .worker_report import process_windows
        from .korean_rcaeval import packet, training_target, validate
        def generate(backend, records):
            facts = packet(records)
            report = training_target(facts)
            _, text, terminology = validate(json.dumps(report, ensure_ascii=False), facts)
            return {'text': text, 'passed': True, 'report': report, 'facts': facts,
                    'error': None, 'terminology': terminology, 'history': []}
        with tempfile.TemporaryDirectory() as temp:
            archive = ReportArchive(Path(temp) / 'reports.db')
            stream = SensorStream(archive)
            backend = type('Backend', (), {'model_id': 'Qwen+adapter-one'})()
            with patch('edge_bridge.korean_rcaeval.generate', side_effect=generate) as mock:
                ids = []
                for key, model, measurement in [('a', 'one', 21), ('b', 'two', 21), ('c', 'two', 99)]:
                    backend.model_id = 'Qwen+adapter-' + model
                    seq = stream.ingest([{'sensor_id': '302', 'row_key': key,
                        'text': '[sensorID=302] ' + json.dumps({'alarm_level': 0, 'mq7': measurement})}])[0]
                    process_windows(stream, backend=backend)
                    with stream.connect() as conn:
                        ids.append(conn.execute('SELECT report_id FROM sensor_records WHERE seq=?', (seq,)).fetchone()[0])
                self.assertEqual(mock.call_count, 3)
                self.assertEqual(len(set(ids)), 3)
                self.assertIn('99', archive.get(ids[-1])['report'])

    def test_flicker_is_one_korean_card_not_a_confirmed_fault(self):
        records = [row(1, '{"alarm_level":0,"danger_signal":2,"person_detected":1,"flame_detected":0,"fire_alarm":0,"mq2":52,"timestamp":"2026-10-23 14:48:37"}'),
                   row(2, '{"alarm_level":0,"danger_signal":0,"person_detected":0,"flame_detected":0,"fire_alarm":0,"mq2":51,"timestamp":"2026-10-23 14:48:38"}')]
        report, text = build_card(records)
        self.assertEqual(report['status'], '흔들림')
        self.assertEqual(report['confidence'], None)
        self.assertIn('위험 신호', text)
        self.assertIn('근거:', text)
        self.assertIn('권고 조치:', text)
        self.assertIn('단계 의미는 미제공', text)
        self.assertNotIn('정상', text)
        self.assertNotIn('Anomaly', text)
        self.assertNotIn('안전하다', text)
        self.assertEqual(signature(records), signature(list(reversed(records))))

    def test_alarm_two_uses_provided_stage_without_inventing_a_cause(self):
        report, text = build_card([row(1, '{"alarm_level":2,"flame_detected":1,"fire_alarm":1}')])
        self.assertEqual(report['status'], '위험 단계 보고')
        self.assertIn('위험 단계', text)
        self.assertIn('미검증', report['possible_cause'])
        self.assertIsNone(report['confidence'])


if __name__ == '__main__':
    unittest.main()
