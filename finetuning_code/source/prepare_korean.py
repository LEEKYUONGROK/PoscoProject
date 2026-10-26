"""Korean RCAEval-field SFT rows. Evidence quotes stay exact. Not human-reviewed."""
import hashlib
import json
from pathlib import Path

from edge_bridge.korean_rcaeval import SYSTEM, messages_for, training_target, _with_terms

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'data/korean'


def rcaeval_facts(row):
    source = row['source']
    return _with_terms({
        'required_status': '이상 징후',
        'problem_location': row['reference']['problem_location'],
        'evidence': source['evidence'],
        'require_alarm_hypotheses': False,
        'has_measurement': True,
        'has_alarm': False,
        'has_temperature': False,
        'missing_information': ['메트릭 단위와 물리 위치는 제공되지 않았다.',
                                '로그, 트레이스, 확정된 인과, 복구 결과는 포함되지 않았다.'],
    })


def convert(row):
    facts = rcaeval_facts(row)
    report = training_target(facts)
    return {'case_id': row['case_id'], 'group': row['group'], 'source': facts,
            'reference': report, 'prompt': messages_for(facts),
            'completion': [{'role': 'assistant', 'content': json.dumps(report, ensure_ascii=False)}]}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    counts = {}
    for split in ('train', 'validation', 'test'):
        rows = [json.loads(line) for line in (ROOT / f'data/{split}.jsonl').read_text().splitlines()]
        converted = [convert(row) for row in rows]
        path = OUT / f'{split}.jsonl'
        path.write_text(''.join(json.dumps(item, ensure_ascii=False) + '\n' for item in converted))
        counts[split] = len(converted)
        print(split, counts[split], hashlib.sha256(path.read_bytes()).hexdigest()[:12], flush=True)
    if messages_for(rcaeval_facts(json.loads((ROOT / 'data/train.jsonl').read_text().splitlines()[0])))[0]['content'] != SYSTEM:
        raise RuntimeError('training prompt drifted from the live system prompt')
    (OUT / 'manifest.json').write_text(json.dumps({
        'task': 'Korean RCAEval field order and the 20 project glossary terms',
        'reference_policy': 'Deterministic Korean rendering of the existing synthetic references; not human-reviewed',
        'counts': counts, 'system_prompt': 'edge_bridge/korean_rcaeval.py:SYSTEM'}, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
