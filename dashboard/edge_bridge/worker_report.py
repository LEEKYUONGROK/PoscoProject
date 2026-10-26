"""Korean operator card using the RCAEval report fields. Not the English LoRA."""
from datetime import datetime, timedelta
import json
import logging
import re
import uuid
from collections import Counter

from .log_facts import ALARM_STAGES, alarm_stage

ENVELOPE = re.compile(r'^\[sensorID=(-?\d+)\]\s*')
FIELDS = ('status', 'problem_location', 'observed_issue', 'evidence', 'possible_cause',
          'recommended_actions', 'confidence', 'missing_information')
LABELS = {'status': '상태', 'problem_location': '위치', 'observed_issue': '관측',
          'evidence': '근거', 'possible_cause': '가능한 원인', 'recommended_actions': '권고 조치',
          'confidence': '신뢰도', 'missing_information': '부족 정보'}


def parse_record(text):
    sensor = None
    match = ENVELOPE.match(text)
    if match:
        sensor = match.group(1)
        text = text[match.end():]
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        obj = None
    if not isinstance(obj, dict):
        return {'sensor_id': sensor, 'raw': text.strip(), 'values': {}}
    values = {}
    for key, value in obj.items():
        if key == 'timestamp' and isinstance(value, str):
            values['timestamp'] = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            values[key] = value
    return {'sensor_id': sensor, 'raw': text.strip(), 'values': values}


def _counts(records, key):
    return Counter(record['values'][key] for record in records if key in record['values'])


def build_card(records):
    """One Korean card for a same-sensor interval. Does not invent units or fault types."""
    parsed = [parse_record(record['text']) for record in records]
    sensor = next((record.get('sensor_id') or item['sensor_id'] for record, item in zip(records, parsed)
                   if record.get('sensor_id') or item['sensor_id']), '미제공')
    readable = [item for item in parsed if item['values']]
    if not readable:
        report = {'status': '형식 미지원', 'problem_location': f'센서 {sensor}',
                  'observed_issue': '이 구간은 센서 302 JSON이 아니라 기존 파서가 수치로 읽지 못하는 원문이다.',
                  'evidence': [item['raw'][:240] for item in parsed[:3]],
                  'possible_cause': None,
                  'recommended_actions': ['원본 형식과 센서 식별자를 대조한다. 원인이나 수리 완료로 쓰지 않는다.'],
                  'confidence': None,
                  'missing_information': ['지원 필드가 없어 경보 단계와 변화 방향을 계산하지 않았다.']}
        return report, render(report)
    alarms = _counts(readable, 'alarm_level')
    danger = _counts(readable, 'danger_signal')
    person = _counts(readable, 'person_detected')
    flame = _counts(readable, 'flame_detected')
    fire = _counts(readable, 'fire_alarm')
    stages = {int(value): alarm_stage(value) for value in alarms if alarm_stage(value)}
    flickering = len(danger) > 1 or len(person) > 1
    if 2 in stages:
        status = '위험 단계 보고'
    elif 1 in stages:
        status = '경고 단계 보고'
    elif flickering:
        status = '흔들림'
    elif stages:
        status = f'{next(iter(stages.values()))} 단계 보고'
    else:
        status = '단계 미보고'
    stamps = [item['values']['timestamp'] for item in readable if 'timestamp' in item['values']]
    span = stamps[0] if len(set(stamps)) == 1 else (f'{min(stamps)}–{max(stamps)}' if stamps else '시각 미제공')
    stage_text = ', '.join(f'{value:g}={ALARM_STAGES[value]} 단계' for value in sorted(stages)) or '경보 수준 없음'
    if flickering and 2 not in stages and 1 not in stages:
        issue = (f'경보 수준은 {stage_text}로 유지된다. 위험 신호와 사람 감지가 이 구간에서 반복해서 바뀐다. '
                 '현장 사건으로 확정하지 않는다.')
        cause = '이 구간만으로 현장 출입과 신호 흔들림을 구별할 수 없다.'
        action = '같은 시각의 현장과 센서 연결을 한 번 확인한다. 수리나 복구 완료로 쓰지 않는다.'
    elif 2 in stages or 1 in stages:
        issue = f'장치가 경보 수준을 {stage_text}로 보고했다. 이는 장치 단계이며 현장 위험의 독립 확인은 아니다.'
        cause = '보고된 경보 단계가 현장 상태와 관련됐을 수 있고, 장치 설정이나 감지 경로의 영향일 수도 있다. 둘 다 미검증이다.'
        action = '보고된 경보 단계와 같은 시각의 현장을 대조하고, 불일치하면 경보 조건과 감지 경로를 확인한다.'
    else:
        issue = f'경보 수준은 {stage_text}로 보고되었고, 이 구간에서 위험 신호·사람 감지의 반복 변화는 없다.'
        cause = '안전 단계 보고는 현장이 안전하다는 확정이 아니다.'
        action = '별도 현장 관측이 없으면 추가 조치로 확대하지 않는다.'
    evidence = [f'구간 {len(readable)}건, 시각 {span}.', f'alarm_level: ' + _fmt(alarms, stage=True)]
    if danger:
        evidence.append('danger_signal: ' + _fmt(danger) + '. 단계 의미는 미제공')
    if person:
        evidence.append('person_detected: ' + _fmt(person))
    if flame or fire:
        evidence.append('flame_detected: ' + _fmt(flame) + '; fire_alarm: ' + _fmt(fire))
    for key in ('mq2', 'mq7', 'temperature_c', 'humidity_pct'):
        values = [item['values'][key] for item in readable if key in item['values']]
        if values:
            evidence.append(f'{key}: 최솟값 {min(values):g}, 최댓값 {max(values):g}. 단위·임계값은 미제공')
    missing = ['MQ2·MQ7 단위와 물리 위치는 미제공이다.']
    if danger:
        missing.append('danger_signal의 단계 의미는 제공되지 않았다.')
    missing.append('독립적인 현장 관측, 로그·트레이스, 복구 결과는 없다.')
    report = {'status': status, 'problem_location': f'센서 {sensor}', 'observed_issue': issue,
              'evidence': evidence, 'possible_cause': cause, 'recommended_actions': [action],
              'confidence': None, 'missing_information': missing}
    return report, render(report)


def signature(records):
    parsed = [parse_record(record['text']) for record in records]
    keys = ('alarm_level', 'danger_signal', 'person_detected', 'flame_detected', 'fire_alarm', 'dht_ok')
    return tuple(sorted({(key, item['values'].get(key)) for item in parsed for key in keys if key in item['values']}))


def _fmt(counts, stage=False):
    if not counts:
        return '없음'
    parts = []
    for value, count in sorted(counts.items()):
        label = f'{value:g}={count}건'
        if stage and alarm_stage(value):
            label += f'({alarm_stage(value)} 단계)'
        parts.append(label)
    return ', '.join(parts)


def _card_rows(records):
    rows = []
    for record in records:
        item = dict(record)
        item['text'] = item.get('text') or item.get('log_text') or ''
        rows.append(item)
    return rows


def process_windows(stream, seconds=45, backend=None, report_style='rcaeval'):
    """Write one Korean card for the newest sensor interval and drain that interval."""
    import time
    from .sensor_stream import now
    from .tcp_protocol import bounded_report
    row = stream.claim(newest=True)
    if row is None:
        return False
    try:
        cutoff = (datetime.fromisoformat(row['received_at']) - timedelta(seconds=seconds)).isoformat()
        with stream.connect() as conn:
            others = [dict(item) for item in conn.execute(
                '''SELECT * FROM sensor_records WHERE sensor_id IS ? AND state='pending' AND seq!=?
                   AND received_at>=? ORDER BY seq''', (row['sensor_id'], row['seq'], cutoff))]
            conn.execute('INSERT OR REPLACE INTO sensor_stream_status VALUES (?,?)', ('heartbeat', now()))
        group = _card_rows([row] if report_style == 'prose' else others + [row])
        current = [list(item) for item in signature(group)]
        if report_style == 'prose':
            from .broker_prose import facts_for
            current_facts = facts_for(group[-1])
        else:
            from .korean_rcaeval import packet
            current_facts = packet(group)
        method = 'qwen_broker_prose' if report_style == 'prose' else 'qwen_korean_rcaeval'
        with stream.connect() as conn:
            previous = conn.execute(
                '''SELECT r.id, r.details_json FROM sensor_records s JOIN reports r ON r.id=s.report_id
                   WHERE s.sensor_id IS ? AND s.state='complete'
                         AND json_extract(r.details_json,'$.report_generation.method')=?
                   ORDER BY s.seq DESC LIMIT 1''', (row['sensor_id'], method)).fetchone()
        old = json.loads(previous['details_json']) if previous else {}
        model_id = getattr(backend, 'model_id', None)
        reuse = previous['id'] if (model_id and old.get('model') == model_id
            and old.get('facts') == current_facts
            and old.get('window_signature') == current and old.get('card_revision') == 3
            and old.get('validation', {}).get('passed')) else None
        if reuse:
            outcome = {'passed': True}
            identifier = reuse
        else:
            if backend is None:
                raise RuntimeError('Korean report generation requires the trained Qwen backend')
            if report_style == 'prose':
                from .broker_prose import generate
            else:
                from .korean_rcaeval import generate
            outcome = generate(backend, group)
            text = bounded_report(outcome['text']).Content
            sample = group if len(group) <= 3 else group[:2] + group[-1:]
            details = {'report': text, 'rcaeval_report': outcome['report'], 'window_signature': current,
                       'facts': outcome['facts'],
                       'card_revision': 3, 'validation_error': outcome['error'],
                       'source_record': {'seq': row['seq'], 'sensor_id': row['sensor_id'], 'rows': len(group),
                                         'first_seq': group[0]['seq'], 'last_seq': group[-1]['seq']},
                       'report_generation': {'method': method,
                                             'raw_model_output': outcome.get('raw'),
                                             'prompt_version': 'broker_prose_v1' if report_style == 'prose' else 'rcaeval_fields',
                                             'llm_output_tokens': sum(item.get('output_tokens') or 0 for item in outcome['history']),
                                             'format': 'three Korean paragraphs' if report_style == 'prose' else 'RCAEval fields, Korean labels, 20 glossary terms',
                                             'validation': 'passed' if outcome['passed'] else 'failed',
                                             'validation_error': outcome['error'], 'attempts': outcome['history']},
                       'model': getattr(backend, 'model_id', 'Qwen/Qwen3-4B-Instruct-2507'), 'decision': 'withheld',
                       'glossary_validation': outcome['terminology'],
                       'validation': {'passed': outcome['passed'], 'judge': 'not_run',
                                      'operator_review': 'not_performed',
                                      'technical_glossary': None if not outcome['terminology'] else outcome['terminology']['status'],
                                      'notice': None if outcome['passed'] else '검증되지 않은 보고서'}}
            identifier = uuid.uuid4().hex
        seqs = [item['seq'] for item in group]
        with stream.connect() as conn:
            if not reuse:
                conn.execute('INSERT INTO reports VALUES (?,?,?,?,?,?,?)',
                             (identifier, now(), 0, '\n'.join(item['text'] for item in sample), text, 'complete',
                              json.dumps(details, ensure_ascii=False)))
            for start in range(0, len(seqs), 400):
                chunk = seqs[start:start + 400]
                marks = ','.join('?' for _ in chunk)
                conn.execute(f"UPDATE sensor_records SET state='complete',report_id=?,error=NULL WHERE seq IN ({marks})",
                             (identifier, *chunk))
    except Exception as exc:
        with stream.connect() as conn:
            conn.execute("UPDATE sensor_records SET state='retry',retry_at=?,error=? WHERE seq=? AND state='running'",
                         (time.time() + 5, f'{type(exc).__name__}: {exc}', row['seq']))
        raise
    logging.info('WORKER_CARD passed=%s rows=%d reuse=%s seq=%s', outcome['passed'], len(group), bool(reuse), row['seq'])
    return True


def render(report):
    if set(report) != set(FIELDS):
        raise ValueError('report does not use the RCAEval fields')
    lines = []
    for key in FIELDS:
        value = report[key]
        title = LABELS[key]
        if value is None:
            lines.append(f'{title}: 미제공')
        elif isinstance(value, list):
            lines.append(title + ':')
            lines.extend(f'- {item}' for item in value)
        else:
            lines.append(f'{title}: {value}')
    return '\n'.join(lines)
