import hashlib
import tempfile
import unittest
from pathlib import Path

from . import protocol_pb2 as pb
from .remote_protobuf import identity_records
from .report_archive import ReportArchive
from .sensor_stream import SensorStream


LINE = '{"temperature_c":24.5,"mq7":21,"timestamp":"2026-10-23 14:24:57"}'


def sensors_body(*items):
    return pb.SensorsMsg(info=[pb.SensorMsg(sensorID=sid, msg=text) for sid, text in items]).SerializeToString()


class RemoteProtobufTests(unittest.TestCase):
    def test_payload_identity_is_stable_and_position_packets_are_not_logs(self):
        body = sensors_body((302, LINE), (302, LINE.replace('21', '22')), (301, '301|{"result": 3}|2026-10-23 14:24:59'))
        first = identity_records(pb.SENSORS_MSG, body, 'remote:example:7777')
        second = identity_records(pb.SENSORS_MSG, body, 'remote:example:7777')
        self.assertEqual([row['row_key'] for row in first], [row['row_key'] for row in second])
        self.assertEqual(len(set(row['row_key'] for row in first)), 3)
        self.assertTrue(all(row['source'] == 'remote:example:7777' for row in first))
        self.assertEqual(first[0]['row_key'], hashlib.sha256(first[0]['text'].encode()).hexdigest())
        self.assertIsNone(identity_records(pb.SENSOR_INPOS, b'\x00' * 10, 'remote:example:7777'))

    def test_sender_row_id_is_kept_and_replay_does_not_duplicate(self):
        envelope = '{"_bridge":{"source":"equip","row_id":"row-9"},"log":"mq7=21"}'
        body = sensors_body((302, envelope))
        records = identity_records(pb.SENSORS_MSG, body, 'remote:example:7777')
        self.assertEqual(records[0]['source'], 'remote:equip')
        self.assertEqual(records[0]['row_key'], 'row-9:0')
        with tempfile.TemporaryDirectory() as temp:
            stream = SensorStream(ReportArchive(Path(temp) / 'reports.db'))
            self.assertEqual(stream.ingest(records), stream.ingest(identity_records(pb.SENSORS_MSG, body, 'remote:example:7777')))
            plain = identity_records(pb.SENSORS_MSG, sensors_body((302, LINE)), 'remote:example:7777')
            self.assertEqual(stream.ingest(plain), stream.ingest(plain))
            self.assertEqual(stream.status()['total_received'], 2)


if __name__ == '__main__':
    unittest.main()
