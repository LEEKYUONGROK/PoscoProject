"""Synthetic contract tests; fixtures are not production sensor observations."""
import json
import unittest
from .log_facts import (build_facts, hypothesis_evaluations, selection_schema,
                        validate_selection, render_analysis, include_reported_hypotheses)
from .log_analyzer import LogAnalyzer


class EvaluationTests(unittest.TestCase):
    def test_signal_has_two_conditional_explanations_not_two_confirmed_causes(self):
        facts = build_facts('sensor_id=7 fire_alarm=1 dht_ok=1')
        self.assertEqual({h['id'] for h in facts['hypotheses']}, {'H_UNKNOWN', 'H_SIGNAL', 'H_DEVICE'})
        selection = validate_selection(json.dumps({'hypotheses': ['H_SIGNAL', 'H_DEVICE', 'H_UNKNOWN'],
                                                   'checks': ['C_SIGNAL']}), facts)
        evaluations = hypothesis_evaluations(facts, selection)
        self.assertTrue(all(e['causal_verdict'] == 'withheld' for e in evaluations))
        self.assertTrue(all(e['verification_result'] == 'not_performed' for e in evaluations))
        self.assertTrue(all(e['counter_evidence_status'] == 'not_available' for e in evaluations))
        self.assertIn('H_DEVICE', render_analysis(facts, selection))

    def test_alarm_stage_keeps_two_hypotheses_without_confirming_safety(self):
        facts = build_facts('sensor_id=302 alarm_level=0 flame_detected=0 fire_alarm=0')
        ids = [h['id'] for h in facts['hypotheses']]
        self.assertEqual(ids[:1], ['H_UNKNOWN'])
        self.assertEqual(set(ids), {'H_UNKNOWN', 'H_ALARM_SITE', 'H_ALARM_PATH'})
        alarm = next(f for f in facts['facts'] if f.get('field') == 'alarm_level')
        self.assertIn('0=1행(안전 단계)', alarm['text'])
        self.assertIn('현장 안전·위험의 독립 확인은 아니다', alarm['text'])
        selection = include_reported_hypotheses(
            validate_selection('{"hypotheses":["H_UNKNOWN"],"checks":["C_THRESHOLD"]}', facts), facts)
        self.assertEqual(selection['hypotheses'], ['H_UNKNOWN', 'H_ALARM_SITE', 'H_ALARM_PATH'])
        for level, stage in ((1, '경고'), (2, '위험')):
            text = build_facts(f'alarm_level={level}')['facts']
            self.assertIn(f'{stage} 단계', next(f['text'] for f in text if f.get('field') == 'alarm_level'))

    def test_no_signal_does_not_pad_hypotheses_or_claim_normal(self):
        facts = build_facts('sensor_id=7 mq7=23 fire_alarm=0')
        self.assertEqual([h['id'] for h in facts['hypotheses']], ['H_UNKNOWN'])
        self.assertEqual(selection_schema(facts)['properties']['hypotheses']['maxItems'], 1)
        with self.assertRaises(ValueError):
            validate_selection('{"hypotheses":["H_DEVICE"],"checks":["C_SOURCE"]}', facts)

    def test_dht_fault_has_relevant_counter_observation_not_environment_cause(self):
        facts = build_facts('sensor_id=7 dht_ok=0\nsensor_id=7 dht_ok=1\nsensor_id=8 dht_ok=1')
        candidates = {h['id']: h for h in facts['hypotheses']}
        self.assertNotIn('H_SIGNAL', candidates)
        self.assertTrue(candidates['H_SENSOR_HEALTH']['counter_evidence'])
        self.assertEqual(candidates['H_SENSOR_HEALTH']['verification_checks'], ['C_HEALTH'])
        ref = candidates['H_SENSOR_HEALTH']['counter_evidence'][0]
        self.assertEqual(next(f['sensor_id'] for f in facts['facts'] if f['id'] == ref), '7')

    def test_data_quality_candidate_requires_observed_quality_problem(self):
        facts = build_facts('sensor_id=7 mq7=23\nsensor_id=7 fire_alarm=0\n{"mq7":true}')
        candidate = next(h for h in facts['hypotheses'] if h['id'] == 'H_DATA')
        self.assertGreaterEqual(len(candidate['evidence']), 2)
        self.assertEqual(candidate['verification_result'], 'not_performed')

    def test_selection_duplicate_keys_and_invalid_references_rejected(self):
        facts = build_facts('mq7=23')
        with self.assertRaises(ValueError):
            validate_selection('{"hypotheses":["H_UNKNOWN"],"hypotheses":["H_UNKNOWN"],"checks":["C_TIME"]}', facts)
        facts['hypotheses'][0]['evidence'] = ['F_NOT_REAL']
        with self.assertRaises(ValueError):
            hypothesis_evaluations(facts, {'hypotheses': ['H_UNKNOWN'], 'checks': ['C_TIME']})

    def test_sensor_envelope_does_not_leak_between_independent_rows(self):
        facts = build_facts('[sensorID=7] mq7=23\nsensor_id=8 mq7=19\nmq7=18')
        self.assertEqual({f['sensor_id'] for f in facts['facts'] if f['kind'] == 'sensor'}, {'7', '8', '미제공'})
        self.assertEqual(facts['facts'][0]['invalid_lines'], [])

    def test_retry_expands_only_truncated_output_and_records_both_attempts(self):
        class Backend:
            def __init__(self, truncated):
                self.budgets = []
                self.truncated = truncated
            def generate(self, messages, budget):
                self.budgets.append(budget)
                first = len(self.budgets) == 1
                return {'raw_text': 'bad' if first else '{"hypotheses":["H_UNKNOWN"],"checks":["C_SOURCE"]}',
                        'output_tokens': budget if first else 20, 'input_tokens': 100,
                        'finish_reason': 'length' if first and self.truncated else 'eos',
                        'token_limit_reached': first and self.truncated}
        for truncated, expected in [(True, [16, 32]), (False, [16, 16])]:
            backend = Backend(truncated)
            details = LogAnalyzer(backend=backend, max_tokens=16, retry_max_tokens=32).analyze('mq7=23')
            self.assertEqual(backend.budgets, expected)
            self.assertEqual(details['generation']['attempts'], 2)
            self.assertEqual(details['generation']['attempt_history'][0]['validation'], 'failed')
            self.assertEqual(details['report_generation']['llm_output_tokens'], 0)
            self.assertEqual(details['decision'], 'withheld')

    def test_context_summarizes_indices_but_archives_all_evidence(self):
        class Backend:
            def generate(inner, messages, budget):
                inner.payload = json.loads(messages[1]['content'])
                return {'raw_text': '{"hypotheses":["H_UNKNOWN"],"checks":["C_SOURCE"]}'}
        backend = Backend()
        details = LogAnalyzer(backend=backend).analyze('\n'.join(['sensor_id=7 mq7=23'] * 200))
        self.assertEqual(len(next(f['source_lines'] for f in details['facts']['facts'] if f['kind'] == 'sensor')), 200)
        self.assertTrue(all('source_lines' not in f for f in backend.payload['verified_facts']['facts']))
        self.assertIn('output_schema', backend.payload)


if __name__ == '__main__':
    unittest.main()
