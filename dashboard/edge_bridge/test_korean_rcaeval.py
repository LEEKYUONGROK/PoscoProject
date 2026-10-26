import json
import unittest
from .korean_rcaeval import generate, glossary_entries, messages_for, packet, training_target, validate


def row(body, sensor='302'):
    return {'sensor_id': sensor, 'text': f'[sensorID={sensor}] {body}'}


class KoreanRcaevalTests(unittest.TestCase):
    def test_prompt_carries_all_twenty_standard_terms(self):
        facts = packet([row('{"alarm_level":0,"mq2":51,"timestamp":"2026-10-23 15:04:08"}')])
        self.assertEqual(len(glossary_entries()), 20)
        prompt = messages_for(facts)[1]['content']
        for entry in glossary_entries():
            self.assertIn(entry['korean'], prompt)
            self.assertIn(entry['english'], prompt)
        self.assertIn(facts['glossary_line'], facts['missing_information'])

    def test_training_target_uses_applicable_terms_and_passes_checks(self):
        facts = packet([row('{"alarm_level":2,"temperature_c":24.1,"flame_detected":1,"fire_alarm":1}')])
        report = training_target(facts)
        rendered = validate(json.dumps(report, ensure_ascii=False), facts)[1]
        for term in facts['applicable_terms']:
            self.assertIn(term, rendered)
        self.assertIn('현장 단계 가설', rendered)
        trailing = json.dumps(report, ensure_ascii=False) + '\n신뢰도 점수는 제공되지 않았다.'
        self.assertEqual(validate(trailing, facts)[0]['status'], report['status'])
        self.assertIn('설정·경로 가설', rendered)
        self.assertIsNone(report['confidence'])

    def test_alias_or_missing_term_fails_and_stays_visible(self):
        facts = packet([row('{"alarm_level":0,"mq2":51}')])
        good = training_target(facts)
        bad = dict(good)
        bad['observed_issue'] = bad['observed_issue'].replace('판단 근거', '에비던스')
        with self.assertRaises(ValueError):
            validate(json.dumps(bad, ensure_ascii=False), facts)
        outcome = generate(type('B', (), {'generate': lambda *a, **k: {'raw_text': '{"status":"틀"}', 'output_tokens': 3}})(), [row('{"alarm_level":0}')])
        self.assertFalse(outcome['passed'])
        self.assertEqual(outcome['text'], '{"status":"틀"}')
        self.assertTrue(outcome['error'])


if __name__ == '__main__':
    unittest.main()
