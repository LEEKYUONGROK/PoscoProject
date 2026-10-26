"""Deterministic, line-addressable sensor facts. No model-generated measurements."""
from collections import Counter, defaultdict
from datetime import datetime
import json
import math
import re

ALARM_STAGES = {0: '안전', 1: '경고', 2: '위험'}


def alarm_stage(value):
    if isinstance(value, bool) or int(value) != value:
        return None
    return ALARM_STAGES.get(int(value))


FIELDS = {
    'temperature_c': '온도(°C)', 'humidity_pct': '습도(%)',
    'mq2': 'MQ2(단위 미제공)', 'mq7': 'MQ7(단위 미제공)',
    'flame_detected': '불꽃 감지 플래그', 'fire_alarm': '화재 경보 플래그',
    'alarm_level': '경보 수준', 'person_detected': '사람 감지 플래그', 'dht_ok': 'DHT 상태 플래그',
}
FLAGS = {'flame_detected', 'fire_alarm', 'person_detected', 'dht_ok'}
ENVELOPE = re.compile(r'^\[sensorID=(-?\d+)\]\s*')
TOPIC = re.compile(r'\bRealSensor/(-?\d+)\b')
PAIR = re.compile(r'(?<![\w])(' + '|'.join(['sensor_id', 'sensorID', *FIELDS]) +
                  r')\s*[:=]\s*(-?\d+(?:\.\d+)?)(?![\w.])')
STAMP = re.compile(r'(?<!\d)\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?(?!\d)')


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def build_facts(log_text):
    if not log_text.strip():
        raise ValueError('empty logs')
    groups = defaultdict(list)
    invalid, unmatched, timestamps = [], [], []
    lines = [(i, line) for i, line in enumerate(log_text.splitlines(), 1) if line.strip()]
    for line_no, original in lines:
        envelope_id = None
        line = original
        match = ENVELOPE.match(line)
        if match:
            envelope_id = int(match[1])
            line = line[match.end():]
        try:
            start = line.find('{')
            if start >= 0:
                # Only parse an object that consumes the remainder; never repair malformed JSON.
                data = json.loads(line[start:], object_pairs_hook=no_duplicates,
                                  parse_constant=lambda value: (_ for _ in ()).throw(ValueError('nonfinite JSON')))
                if not isinstance(data, dict):
                    raise ValueError('expected object')
            else:
                pairs = PAIR.findall(line)
                if len({key for key, _ in pairs}) != len(pairs):
                    raise ValueError('duplicate key/value field')
                data = {key: float(value) if '.' in value else int(value) for key, value in pairs}
            values = {key: data[key] for key in FIELDS if key in data}
            if not values:
                unmatched.append(line_no)
                continue
            for key, value in values.items():
                if type(value) not in (int, float) or not math.isfinite(value):
                    raise ValueError('invalid numeric field')
                if key in FLAGS and value not in (0, 1):
                    raise ValueError('invalid binary flag')
                if key == 'alarm_level' and (value < 0 or int(value) != value):
                    raise ValueError('invalid alarm level')
            identities = [data[key] for key in ('sensor_id', 'sensorID') if key in data]
            topic = TOPIC.search(line)
            if topic:
                identities.append(int(topic[1]))
            if envelope_id is not None:
                identities.append(envelope_id)
            if any(type(value) is not int for value in identities) or len(set(identities)) > 1:
                raise ValueError('sensor identity mismatch')
            sensor = str(identities[0]) if identities else '미제공'
            stamps = []
            for stamp in STAMP.findall(line):
                datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                stamps.append(stamp)
            timestamps.extend({'line': line_no, 'value': stamp} for stamp in stamps)
            groups[sensor].append({'line': line_no, 'values': values, 'timestamps': stamps})
        except (ValueError, TypeError, OverflowError):
            invalid.append(line_no)
    facts = []
    def add(kind, text, **details):
        fact = {'id': f'F{len(facts)+1:03}', 'kind': kind, 'text': text, **details}
        facts.append(fact)
        return fact['id']
    add('coverage', f'입력 {len(lines)}행 중 센서 수치 파싱 {sum(map(len, groups.values()))}행, '
        f'형식·값 오류 {len(invalid)}행, 지원 형식 미일치 {len(unmatched)}행.',
        total_lines=len(lines), invalid_lines=invalid, unmatched_lines=unmatched)
    if len(groups) > 128:
        raise ValueError('too many sensor groups (maximum 128)')
    for sensor, rows in sorted(groups.items()):
        add('sensor', f'센서 ID {sensor}: 파싱된 레코드 {len(rows)}행.', sensor_id=sensor,
            source_lines=[r['line'] for r in rows])
        for key, label in FIELDS.items():
            observed = [(r['line'], r['values'][key]) for r in rows if key in r['values']]
            if not observed:
                continue
            values = [value for _, value in observed]
            details = dict(sensor_id=sensor, field=key, observed=len(values), missing=len(rows)-len(values))
            if key in FLAGS or key == 'alarm_level':
                counts = dict(sorted(Counter(values).items()))
                active = [(line, value) for line, value in observed if (value == 0 if key == 'dht_ok' else value > 0)]
                if key == 'alarm_level':
                    described = []
                    for value, count in counts.items():
                        stage = alarm_stage(value)
                        described.append(f'{value:g}={count}행' + (f'({stage} 단계)' if stage else '(0=안전, 1=경고, 2=위험 정의 밖)'))
                    meaning = '경보 수준은 장치 정의상 0=안전, 1=경고, 2=위험이다. 이는 장치 보고 단계이며 현장 안전·위험의 독립 확인은 아니다.'
                else:
                    described = [f'{value:g}={count}행' for value, count in counts.items()]
                    meaning = '이는 장치 보고값이며 실제 상황의 독립 검증 결과가 아니다.'
                add('signal' if active else 'flag',
                    f'센서 {sensor} · {label}: ' + ', '.join(described) +
                    f'. 필드 누락 {details["missing"]}행. {meaning}',
                    **details, counts=counts, event_lines=[line for line, _ in active],
                    source_lines=[line for line, _ in observed])
            else:
                low, high = min(values), max(values)
                add('measurement', f'센서 {sensor} · {label}: 관측 {len(values)}행, 최솟값 {low:g}, '
                    f'최댓값 {high:g}, 필드 누락 {details["missing"]}행. 정상·위험 임계값은 미제공.',
                    **details, minimum=low, maximum=high,
                    minimum_lines=[line for line, value in observed if value == low],
                    maximum_lines=[line for line, value in observed if value == high])
    add('time', '시각 정보 없음: 지원하는 ISO 날짜·시각이 파싱된 센서 레코드에 없다.' if not timestamps else
        '원문 시각: ' + ', '.join(f'{x["value"]} (입력 행 {x["line"]})' for x in timestamps[:12]) +
        (' · 나머지 시각은 상세 근거 참조.' if len(timestamps) > 12 else ''), timestamps=timestamps,
        policy='입력 행 번호는 수신 순서이며 실제 시각·장치 레코드 ID가 아니다.')
    add('limits', '시각이 없는 행의 경과 시간·발생 간격은 계산하지 않는다. 정상 기준, MQ 단위·보정, '
        '장치 설정과 외부 현장 확인 자료가 없어 실제 화재·가스 누출·장치 정상 여부는 확정할 수 없다.')
    signals = [f['id'] for f in facts if f['kind'] == 'signal']
    environment_signals = [f['id'] for f in facts if f['kind'] == 'signal' and f.get('field') != 'dht_ok']
    health_signals = [f['id'] for f in facts if f['kind'] == 'signal' and f.get('field') == 'dht_ok']
    hypotheses = [{'id': 'H_UNKNOWN', 'evidence': [facts[-1]['id']],
                   'text': '원인 미확정: 제공된 관측값만으로 실제 환경 변화와 장치·측정 경로의 영향을 구별할 수 없다.'}]
    if environment_signals:
        hypotheses.extend([
            {'id': 'H_SIGNAL', 'evidence': environment_signals,
             'text': '확인할 가설: 장치가 보고한 감지·경보가 실제 현장 상태와 관련됐을 수 있다. 독립적인 현장 관측이 없어 원인은 미확정이다.'},
            {'id': 'H_DEVICE', 'evidence': environment_signals,
             'text': '대안 가설: 같은 감지·경보 보고에 외란이나 장치 설정·측정 경로가 영향을 주었을 수 있다. 장치 이상이 확인된 것은 아니다.'},
        ])
    if health_signals:
        hypotheses.append({'id': 'H_SENSOR_HEALTH', 'evidence': health_signals,
            'text': '확인할 가설: DHT 상태 오류 보고에 장치 또는 측정 경로의 문제가 관련됐을 수 있다. 오류 원인은 확인되지 않았다.'})
    quality_evidence = ([facts[0]['id']] if invalid or unmatched else []) + [
        f['id'] for f in facts if f.get('missing', 0) > 0]
    if quality_evidence:
        hypotheses.append({'id': 'H_DATA', 'evidence': quality_evidence,
            'text': '확인할 가설: 형식·값 오류, 지원 형식 미일치 또는 필드 누락이 해석 범위를 제한했을 수 있다. 수집·전송·원본 형식 중 발생 위치는 미확정이다.'})
    alarm_facts = [fact['id'] for fact in facts if fact.get('field') == 'alarm_level']
    if alarm_facts:
        hypotheses.extend([
            {'id': 'H_ALARM_SITE', 'evidence': alarm_facts,
             'text': '현장 단계 가설: 보고된 경보 단계(0 안전, 1 경고, 2 위험)가 장치가 구분하도록 설정된 현장 상태와 관련됐을 수 있다. 독립 확인 전 현장 안전·위험은 확정되지 않는다.'},
            {'id': 'H_ALARM_PATH', 'evidence': alarm_facts,
             'text': '설정·경로 가설: 같은 경보 단계 보고에 장치 설정, 감지 경로 또는 외란이 영향을 줬을 수 있다. 장치 이상이 확인된 것은 아니다.'},
        ])
    checks = [
        {'id': 'C_SOURCE', 'evidence': [facts[0]['id']], 'text': '원본 행과 센서 ID를 대조하고 누락·파싱 오류가 있으면 원본 형식과 필드 타입을 확인한다.'},
        {'id': 'C_THRESHOLD', 'evidence': [facts[-1]['id']], 'text': '장치별 경보 조건, 측정 단위, 정상 기준과 센서 보정 정보를 확보한다.'},
        {'id': 'C_TIME', 'evidence': [facts[-2]['id']], 'text': '원본 시각과 시간대·장치 시계 정보를 확인한다. 없는 시각을 수신 순서로 대체하지 않는다.'},
    ]
    if signals or alarm_facts:
        checks.append({'id': 'C_SIGNAL', 'evidence': signals or alarm_facts,
            'text': '감지·경보 및 경보 단계가 보고된 원본 행을 현장 상태·장치 설정·별도 관측 자료와 대조한다. 0=안전, 1=경고, 2=위험은 장치 정의이며 현장 확정이 아니다.'})
    if health_signals:
        checks.append({'id': 'C_HEALTH', 'evidence': health_signals,
            'text': 'DHT 오류 상태의 원본 기록을 장치 진단·배선·전원·측정 경로와 대조한다. 실제 고장은 점검 전 확정하지 않는다.'})
    for candidate in hypotheses:
        candidate.update(counter_evidence=[], verification_result='not_performed',
                         causal_verdict='withheld', limitations=[facts[-1]['id']])
        if candidate['id'] == 'H_SENSOR_HEALTH':
            affected = {f['sensor_id'] for f in facts if f['id'] in health_signals}
            candidate['counter_evidence'] = [f['id'] for f in facts
                if f.get('sensor_id') in affected and f.get('field') == 'dht_ok'
                and f.get('counts', {}).get(1, 0)]
        candidate['verification_checks'] = {
            'H_UNKNOWN': ['C_SOURCE', 'C_THRESHOLD'], 'H_SIGNAL': ['C_SIGNAL', 'C_THRESHOLD'],
            'H_DEVICE': ['C_SIGNAL', 'C_THRESHOLD'], 'H_SENSOR_HEALTH': ['C_HEALTH'],
            'H_DATA': ['C_SOURCE'], 'H_ALARM_SITE': ['C_SIGNAL', 'C_THRESHOLD'],
            'H_ALARM_PATH': ['C_SIGNAL', 'C_THRESHOLD'],
        }[candidate['id']]
    return {'version': 2, 'facts': facts, 'hypotheses': hypotheses, 'checks': checks}


def selection_schema(facts):
    """Describes locally validated output; not an unsupported generate() argument."""
    return {'type': 'object', 'additionalProperties': False,
            'required': ['hypotheses', 'checks'], 'properties': {
                key: {'type': 'array', 'minItems': 1, 'maxItems': limit, 'uniqueItems': True,
                      'items': {'type': 'string', 'enum': [entry['id'] for entry in facts[key]]}}
                for key, limit in [('hypotheses', len(facts['hypotheses'])), ('checks', 4)]}}


def hypothesis_evaluations(facts, selection):
    """Evaluate all gated alternatives; selecting one never verifies a cause."""
    known = {f['id'] for f in facts['facts']}
    allowed_checks = {c['id'] for c in facts['checks']}
    result = []
    for candidate in facts['hypotheses']:
        evidence = candidate['evidence']
        counter = candidate.get('counter_evidence', [])
        checks = candidate.get('verification_checks', [])
        if (not evidence or not set(evidence + counter + candidate.get('limitations', [])) <= known
                or not set(checks) <= allowed_checks):
            raise ValueError('invalid hypothesis evidence/check reference')
        result.append({**candidate, 'selected': candidate['id'] in selection['hypotheses'],
                       'evidence_validation': 'references_valid',
                       'counter_evidence_status': 'observed' if counter else 'not_available',
                       'verification_result': 'not_performed', 'causal_verdict': 'withheld'})
    return result


def include_reported_hypotheses(selection, facts):
    """Alarm-stage records keep both grounded alternatives, not only withheld judgment."""
    required = [item['id'] for item in facts['hypotheses'] if item['id'] in ('H_ALARM_SITE', 'H_ALARM_PATH')]
    if not required or set(required) <= set(selection['hypotheses']):
        return selection
    chosen = list(dict.fromkeys([*selection['hypotheses'], *required]))
    if len(chosen) > len(facts['hypotheses']):
        raise ValueError('expanded hypothesis selection exceeds candidates')
    return {**selection, 'hypotheses': chosen}


def validate_selection(raw, facts):
    selected = json.loads(raw, object_pairs_hook=no_duplicates)
    if not isinstance(selected, dict) or set(selected) != {'hypotheses', 'checks'}:
        raise ValueError('expected hypotheses/checks JSON object')
    for key, maximum in (('hypotheses', len(facts['hypotheses'])), ('checks', 4)):
        values = selected[key]
        allowed = {entry['id'] for entry in facts[key]}
        if (not isinstance(values, list) or not 1 <= len(values) <= maximum or
                any(type(value) is not str or value not in allowed for value in values) or
                len(values) != len(set(values))):
            raise ValueError(f'invalid grounded selection: {key}')
    return selected


def render_analysis(facts, selection):
    def lines(entries):
        return '\n'.join(f'- [{entry["id"]}] {entry["text"]}' for entry in entries)
    summary = [f for f in facts['facts'] if f['kind'] in ('coverage', 'sensor', 'measurement', 'time')]
    signals = [f for f in facts['facts'] if f['kind'] in ('signal', 'flag')]
    observed = any(f['kind'] in ('measurement', 'signal', 'flag') for f in facts['facts'])
    if not any(f['kind'] == 'signal' for f in facts['facts']):
        note = ('관측' + '된 지원 필드에서 경보·감지 또는 DHT 오류 플래그가 확인되지 않았다. '
                '이는 전체 환경에 이상이 없거나 장치가 정상이라는 판정이 아니다.' if observed else
                '지원되는 센서 필드가 파싱되지 않아 이상 징후를 판단할 수 없다.')
    else:
        note = '장치 보고 플래그에서 확인할 신호가 있다. 실제 사고 발생을 확정하지 않는다.'
    def chosen(key):
        lookup = {entry['id']: entry for entry in facts[key]}
        return '\n'.join('- ' + lookup[key_]['text'] + ' (근거: ' + ', '.join(lookup[key_]['evidence']) + ')'
                         for key_ in selection[key])
    evaluated = hypothesis_evaluations(facts, selection) if facts.get('version', 1) >= 2 else []
    comparisons = '\n'.join(
        f"- {item['id']} · {'선택' if item['selected'] else '검토 후보'}: {item['text']} "
        f"(근거: {', '.join(item['evidence'])}; 반증: {', '.join(item['counter_evidence']) or '제공 자료 없음'}; "
        "검증: 미실행; 원인 판단: 유보)" for item in evaluated)
    return ('1. 로그 요약\n' + lines(summary) + '\n\n2. 이상 징후 및 근거\n' + note + '\n' + lines(signals) +
            '\n\n3. 추정 원인\n' + (comparisons or chosen('hypotheses')) + '\n\n4. 권장 확인 사항\n' + chosen('checks') +
            '\n\n분석 제약\n' + facts['facts'][-1]['text'] +
            '\n수치·횟수·근거는 Python이 계산했으며, Qwen은 허용된 근거 기반 가설과 확인 항목을 선택했다.')
