import json
import tempfile
import unittest
from pathlib import Path

from . import broker_prose
from .report_archive import ReportArchive
from .sensor_stream import SensorStream
from .worker_report import process_windows


class BrokerProseTests(unittest.TestCase):
    def record(self, temperature=24.7):
        return {'sensor_id': '302', 'text': '[sensorID=302] ' + json.dumps({
            'temperature_c': temperature, 'humidity_pct': 46.5, 'mq2': 56, 'mq7': 23,
            'alarm_level': 0, 'flame_detected': 0, 'fire_alarm': 0, 'dht_ok': 1})}

    def output(self, facts):
        return json.dumps({'observations': facts['observation_text'],
            'analysis': '가스 센서 측정값의 단위와 임계값 정보가 부족하여 이상 여부는 미확정이다. 현장 환경과 장치 설정·감지 경로의 영향은 구별하여 확인할 가능성이다.',
            'checks': '측정 시각의 현장 관측과 장치 설정을 대조하고 센서 보정 기준을 확인한다. 반복 관측 자료를 확보하여 환경 변화와 측정 패턴을 비교한다.'}, ensure_ascii=False)

    def test_source_values_replace_example_and_dht_is_not_accuracy(self):
        facts = broker_prose.facts_for(self.record(31.2))
        _, text, _ = broker_prose.validate(self.output(facts), facts)
        self.assertIn('31.2°C', text)
        self.assertNotIn('24.7', text)
        self.assertIn('가용 상태(1)', text)
        self.assertNotIn('정상(1)', text)
        self.assertEqual(len(text.split('\n\n')), 3)
        with self.assertRaisesRegex(ValueError, 'observation text was changed'):
            broker_prose.validate(self.output(facts).replace('31.2', '24.7'), facts)
        with self.assertRaisesRegex(ValueError, 'unbound numeric'):
            broker_prose.validate(self.output(facts).replace('이상 여부는', '농도는 50이며 이상 여부는'), facts)
        with self.assertRaisesRegex(ValueError, 'unsupported safety'):
            broker_prose.validate(self.output(facts).replace('이상 여부는 미확정이다', '측정값은 정상 범위 내에서 나타났으나 원인은 미확정이다'), facts)

    def test_failed_check_does_not_substitute_a_report(self):
        facts = broker_prose.facts_for(self.record())
        bad = self.output(facts).replace('24.7', '99')
        backend = type('Backend', (), {'generate': lambda *a, **k: {'raw_text': bad}})()
        outcome = broker_prose.generate(backend, [self.record()])
        self.assertFalse(outcome['passed'])
        self.assertIn('99°C', outcome['text'])
        self.assertEqual(outcome['raw'], bad)

    def test_repeated_sentence_and_wrong_identifier_fail(self):
        facts = broker_prose.facts_for(self.record())
        obj = json.loads(self.output(facts))
        obj['checks'] += ' ' + obj['checks']
        with self.assertRaisesRegex(ValueError, 'repeated'):
            broker_prose.validate(json.dumps(obj, ensure_ascii=False), facts)
        obj = json.loads(self.output(facts))
        obj['checks'] += ' 센서 ID 303의 기록을 확인한다.'
        with self.assertRaisesRegex(ValueError, 'unbound numeric'):
            broker_prose.validate(json.dumps(obj, ensure_ascii=False), facts)
        obj['checks'] = obj['checks'].replace('303', '302')
        broker_prose.validate(json.dumps(obj, ensure_ascii=False), facts)

    def test_worker_saves_source_prose_and_preserves_older_record(self):
        def generate(backend, messages, *a, **k):
            facts = json.loads(messages[1]['content'])
            return {'raw_text': self.output(facts), 'output_tokens': 100, 'finish_reason': 'eos'}
        backend = type('Backend', (), {'model_id': 'Qwen+korean-adapter', 'generate': generate})()
        with tempfile.TemporaryDirectory() as temp:
            archive = ReportArchive(Path(temp) / 'reports.db')
            stream = SensorStream(archive)
            seqs = stream.ingest([self.record(), self.record(31.2)])
            process_windows(stream, backend=backend, report_style='prose')
            rows = {r['seq']: r for r in stream.status()['records']}
            self.assertEqual(rows[seqs[0]]['state'], 'pending')
            saved = archive.get(rows[seqs[1]]['report_id'])
            self.assertIn('31.2°C', saved['report'])
            self.assertTrue(saved['details']['validation']['passed'])
            self.assertEqual(saved['details']['report_generation']['method'], 'qwen_broker_prose')
            self.assertIn('31.2', saved['log_text'])
            self.assertEqual(saved['log_text'], self.record(31.2)['text'])


if __name__ == '__main__':
    unittest.main()
