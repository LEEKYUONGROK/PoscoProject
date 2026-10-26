import json
import unittest
from . import narrative
from .log_facts import build_facts
from .log_analyzer import LogAnalyzer
from human_eval.single_sensor_report import display_report


def report(value=23):
    return json.dumps({
        'observations': f'이 기록의 관측값은 sensor_id=7, mq7={value}, fire_alarm=1이다. 이는 장치가 전송한 측정값과 경보 보고를 원본 필드에 맞추어 보존한 것이며 별도의 현장 관측 자료를 추가한 것은 아니다.',
        'analysis': '화재 경보가 보고되었으나 가스 값의 단위와 경보 조건이 제공되지 않아 실제 현장 상황은 미확정이다. 현장 영향과 장치 설정 또는 측정 경로의 영향을 구별할 근거가 부족하므로 판단을 유보한다. 단일 기록을 시간에 따른 변화로 해석할 수 없다.',
        'checks': '이 경보 기록을 현장의 별도 관측 자료와 대조하고 장치의 경보 조건 및 센서 보정 정보를 확인한다. 측정 경로와 장치 설정을 함께 점검하되 점검이 이미 수행되었다고 간주하지 않는다. 원본 기록과 센서 식별자가 일치하는지도 확인한다.'}, ensure_ascii=False)


class NarrativeTests(unittest.TestCase):
    def test_distinct_detection_targets_and_unverified_hypothesis(self):
        facts = build_facts('sensor_id=7 mq7=23 fire_alarm=1')
        obj = json.loads(report())
        obj['analysis'] = ('화재 경보 기록을 근거로 현장 신호 관련 가설과 장치 설정 영향 가설을 검토한다. '
                           '두 가설은 미검증이며, 현장 관측과 경보 설정을 대조하여 확인할 대상이다.')
        narrative.validate(json.dumps(obj, ensure_ascii=False), facts)
        obj['analysis'] = '감지·경보가 발생했음에도 불구하고 사람 감지가 미감지되었고 원인 판단은 유보한다.'
        with self.assertRaisesRegex(ValueError, 'different detection targets'):
            narrative.validate(json.dumps(obj, ensure_ascii=False), facts)
        facts = build_facts('sensor_id=7 flame_detected=1 fire_alarm=1 person_detected=0')
        context = json.loads(narrative.messages_for({'facts': facts, 'selection': {}})[1]['content'])
        self.assertEqual(context['device_reports']['person_detected'], '사람 감지: 미감지 보고')
        self.assertEqual(context['device_reports']['flame_detected'], '불꽃 감지: 감지·경보 보고')
        alarm = build_facts('sensor_id=302 alarm_level=0 flame_detected=0 fire_alarm=0 person_detected=0 dht_ok=1')
        context = json.loads(narrative.messages_for({'facts': alarm, 'selection': {'hypotheses': ['H_UNKNOWN'], 'checks': ['C_THRESHOLD']}})[1]['content'])
        self.assertIn('안전 단계', context['device_reports']['alarm_level'])
        self.assertNotIn('미제공', context['device_reports']['alarm_level'])
        obj = {
            'observations': 'sensor_id=302, alarm_level=0, flame_detected=0, fire_alarm=0, person_detected=0, dht_ok=1',
            'analysis': '경보 수준은 장치 정의상 안전 단계로 보고되었다. 현장 단계 가설은 이 보고가 설정된 현장 구분과 관련됐을 수 있다는 것이고, 설정·경로 가설은 같은 보고에 장치 설정이나 감지 경로가 영향을 줬을 수 있다는 것이다. 두 가설은 미검증이다.',
            'checks': '현장 단계 가설은 같은 시각의 별도 현장 관측과 보고된 경보 단계가 일치하는지 대조하여 확인한다. 설정·경로 가설은 그 관측이 불일치할 때 장치 경보 조건과 감지 경로를 점검할 대상으로 남긴다. 점검 결과는 아직 생성하지 않는다.'}
        narrative.validate(json.dumps(obj, ensure_ascii=False), alarm)
        obj['analysis'] = obj['analysis'].replace('안전 단계로', '안전 단계(0)로').replace('장치 정의상', '장치 정의상 경보 수준(0),')
        narrative.validate(json.dumps(obj, ensure_ascii=False), alarm)
        obj['analysis'] = obj['analysis'].replace('안전 단계(0)', '위험 단계(2)')
        with self.assertRaisesRegex(ValueError, 'unbound numeric'):
            narrative.validate(json.dumps(obj, ensure_ascii=False), alarm)
        obj['analysis'] = '경보 수준은 단계 의미가 미제공되어 실제 경보의 심각성과 관련된 판단이 어렵다. 원인 판단은 유보한다. 원인 판단은 유보한다.'
        with self.assertRaisesRegex(ValueError, 'alarm stage meaning is provided'):
            narrative.validate(json.dumps(obj, ensure_ascii=False), alarm)

    def test_exact_field_value_matching_not_just_number_membership(self):
        facts = build_facts('sensor_id=7 mq7=23 fire_alarm=1')
        text = narrative.validate(report(), facts)
        self.assertEqual(len(text.split('\n\n')), 3)
        with self.assertRaisesRegex(ValueError, 'field/value mismatch'):
            narrative.validate(report(1), facts)
        with self.assertRaises(ValueError):
            narrative.validate(report().replace('sensor_id=7, ', ''), facts)
        with self.assertRaises(ValueError):
            narrative.validate(report().replace('실제 현장 상황은 미확정이다', '실제 현장 상황은 미확정이며 2025년에 측정했다'), facts)
        narrative.validate(report().replace('화재 경보가 보고되었으나', 'MQ2와 MQ7의 단위가 없고 화재 경보가 보고되었으나'), facts)
        with self.assertRaisesRegex(ValueError, 'unsupported categorical'):
            narrative.validate(report().replace('실제 현장 상황은 미확정이다', '실제 현장 상황은 미확정이나 온도는 정상 범위이다'), facts)

    def test_two_actual_stages_and_no_ui_template_replacement(self):
        class Backend:
            def __init__(self): self.calls = []
            def generate(self, messages, budget):
                self.calls.append(budget)
                return {'raw_text': '{"hypotheses":["H_SIGNAL"],"checks":["C_SIGNAL"]}' if len(self.calls) == 1 else report(),
                        'input_tokens': 100, 'output_tokens': 200, 'finish_reason': 'eos'}
        backend = Backend()
        details = LogAnalyzer(backend=backend, max_tokens=256, report_max_tokens=1024).analyze('sensor_id=7 mq7=23 fire_alarm=1')
        self.assertEqual(backend.calls, [256, 1024])
        self.assertEqual(details['report_generation']['method'], 'qwen_narrative')
        self.assertEqual(display_report(details, details['report']), details['report'])
        self.assertNotEqual(details['evidence_report'], details['report'])

    def test_invalid_prose_is_not_silently_replaced_by_template(self):
        class Backend:
            calls = 0
            def generate(self, messages, budget):
                self.calls += 1
                return {'raw_text': '{"hypotheses":["H_UNKNOWN"],"checks":["C_SOURCE"]}' if self.calls == 1 else report(99)}
        with self.assertRaisesRegex(RuntimeError, 'no template substituted'):
            LogAnalyzer(backend=Backend(), report_max_tokens=1024).analyze('sensor_id=7 mq7=23 fire_alarm=1')

    def test_batch_keeps_records_separate(self):
        class Backend:
            def generate(self, messages, budget):
                return {'raw_text': '{"hypotheses":["H_SIGNAL"],"checks":["C_SIGNAL"]}'}
            def generate_batch(self, prompts, budget):
                return [{'raw_text': report(json.loads(p[1]['content'])['observations']['mq7']),
                         'finish_reason': 'eos', 'output_tokens': 200} for p in prompts]
        results = LogAnalyzer(backend=Backend(), report_max_tokens=1024).analyze_batch([
            'sensor_id=7 mq7=23 fire_alarm=1', 'sensor_id=7 mq7=24 fire_alarm=1'])
        self.assertIn('mq7=23', results[0]['report'])
        self.assertIn('mq7=24', results[1]['report'])


if __name__ == '__main__': unittest.main()
