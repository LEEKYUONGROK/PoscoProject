import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .report_archive import ReportArchive
from .sensor_stream import SensorStream
from .report_batches import ReportBatches


class ReportBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.stream = SensorStream(ReportArchive(Path(self.temp.name) / 'reports.db'))
        self.batches = ReportBatches(self.stream)

    def test_latest_hundred_are_frozen_and_sensor_filtered_in_reading_order(self):
        self.stream.ingest([{'sensor_id': sensor, 'text': f'{sensor}:{i}'}
                            for i in range(120) for sensor in ('301', '302', '305')])
        identifier = self.batches.create('302')
        first = self.batches.get(identifier)
        self.assertEqual(len(first['items']), 100)
        self.assertEqual(first['items'][0]['log_text'], '302:20')
        self.assertEqual(first['items'][-1]['log_text'], '302:119')
        self.assertTrue(all(row['sensor_id'] == '302' for row in first['items']))
        self.stream.ingest([{'sensor_id': '302', 'text': 'newer-log'}])
        self.assertEqual(first, self.batches.get(identifier))

    def test_invalid_report_and_generation_failure_keep_slots_and_retention(self):
        self.stream.ingest([{'sensor_id': '301', 'text': 'first'}, {'sensor_id': '301', 'text': 'second'}])
        identifier = self.batches.create('301')
        outcome = {'text': '검사 미통과 원문', 'passed': False, 'error': 'invalid number',
                   'facts': {}, 'report': None, 'raw': 'actual model output', 'history': [], 'terminology': None}
        backend = type('Backend', (), {'model_id': 'trained-qwen'})()
        with patch('edge_bridge.broker_prose.generate', return_value=outcome):
            self.assertTrue(self.batches.process_one(backend))
        with patch('edge_bridge.broker_prose.generate', side_effect=RuntimeError('model failure')):
            self.assertTrue(self.batches.process_one(backend))
        rows = self.batches.get(identifier)['items']
        self.assertEqual([row['state'] for row in rows], ['complete', 'failed'])
        self.assertTrue(all(row['report_id'] for row in rows))
        for row in rows:
            report = self.stream.archive.get(row['report_id'])
            self.assertFalse(report['details']['validation']['passed'])
            self.batches.retain(identifier, row['position'], row['report_id'], 'discard')
            self.assertEqual(self.batches.retention(identifier, row['position']), 'discard')
        self.assertEqual(len(self.batches.get(identifier)['items']), 2)
        self.batches.retain(identifier, 1, rows[0]['report_id'], 'keep')
        self.assertEqual(self.batches.retention(identifier, 1), 'keep')
        self.assertFalse(self.stream.archive.get(rows[0]['report_id'])['details']['validation']['passed'])

    def test_recover_interrupted_batch_without_restarting_completed_items(self):
        self.stream.ingest([{'sensor_id': '305', 'text': 'one'}])
        identifier = self.batches.create('305')
        with self.stream.connect() as conn:
            conn.execute("UPDATE report_batch_items SET state='running' WHERE batch_id=?", (identifier,))
        self.batches.recover()
        self.assertEqual(self.batches.get(identifier)['items'][0]['state'], 'pending')


if __name__ == '__main__':
    unittest.main()
