"""Create a small, label-conditioned RCAEval reporting pilot; not an RCA benchmark."""
import hashlib
import json
from pathlib import Path
import random

import pandas as pd
from huggingface_hub import HfApi, hf_hub_download

ROOT = Path(__file__).resolve().parent
REPO = 'phamquiluan/RCAEval'
SYSTEM = '''Convert the supplied external anomaly decision and telemetry summaries into an operator QA report. Do not re-diagnose the incident. Preserve status, service location and unknown confidence. Attribute the fault type to the external annotation; telemetry summaries alone do not prove causality. Quote evidence strings exactly. Do not invent metric units, physical locations, repairs or successful recovery. Return ONLY a JSON object with status, problem_location, observed_issue, evidence (string array), possible_cause (string or null), recommended_actions (string array), confidence (null), missing_information (string array).'''


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def build(row, metrics):
    when = int(row['inject_time'])
    before = metrics[(metrics.time >= when - 300) & (metrics.time < when)]
    after = metrics[(metrics.time >= when) & (metrics.time < when + 300)]
    if before.empty or after.empty:
        raise ValueError('Missing baseline or incident window')
    evidence = []
    for col in metrics:
        if col == 'time' or not col.startswith(row['root_cause_service'] + '_'):
            continue
        a, b = before[col].dropna(), after[col].dropna()
        if a.empty or b.empty:
            continue
        text = f'{col}: baseline median={a.median():.6g}; incident median={b.median():.6g}; incident max={b.max():.6g}; samples={len(a)}/{len(b)}'
        evidence.append(text)
    if not evidence:
        raise ValueError('No service metrics')
    # Fixed column order, not a claim that these are the most diagnostic metrics.
    evidence = evidence[:8]
    location = row['root_cause_service']
    source = {'detection': {'result': 'Anomaly', 'confidence': None,
              'authority': 'RCAEval external fault annotation', 'service': location,
              'fault_type': row['fault'], 'fault_description': row['fault_description']},
              'evidence': evidence, 'metadata': {'system': row['system_name'],
              'baseline_window_seconds': 300, 'incident_window_seconds': 300,
              'physical_location': None, 'metric_units': None,
              'telemetry_selection': 'First eight available metric columns for the annotated service; median/max summary, no logs or traces'}}
    report = {'status': 'Anomaly', 'problem_location': location,
              'observed_issue': f'The external RCAEval annotation identifies {row["fault_description"]} affecting {location}. The supplied metrics summarize the five-minute windows before and after fault injection.',
              'evidence': evidence[:3],
              'possible_cause': f'Externally annotated fault: {row["fault_description"]}. These metric summaries do not independently establish the causal mechanism.',
              'recommended_actions': [f'Inspect {location} telemetry around the incident window and compare it with the baseline.',
                  f'Check {location} logs and traces to corroborate the externally annotated fault before choosing a corrective action.'],
              'confidence': None,
              'missing_information': ['Metric units and physical location are not supplied.',
                  'Logs, traces, confirmed causal mechanism and recovery outcome are not included.']}
    return {'case_id': row['case'], 'group': f'{location}/{row["fault"]}',
            'source': source, 'reference': report,
            'prompt': [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': json.dumps(source)}],
            'completion': [{'role': 'assistant', 'content': json.dumps(report)}]}


def main():
    raw = ROOT / 'data/raw'
    revision = HfApi().dataset_info(REPO).sha
    index = pd.read_parquet(hf_hub_download(REPO, 'cases.parquet', repo_type='dataset', revision=revision, local_dir=raw))
    rows = index[index.dataset == 'RE2-OB'].to_dict('records')
    groups = sorted({f'{r["root_cause_service"]}/{r["fault"]}' for r in rows})
    random.Random(42).shuffle(groups)
    assignment = {g: 'train' if i < 20 else 'validation' if i < 25 else 'test' for i, g in enumerate(groups)}
    records = {'train': [], 'validation': [], 'test': []}
    for i, row in enumerate(rows, 1):
        file = hf_hub_download(REPO, row['case'] + '/metrics.parquet', repo_type='dataset', revision=revision, local_dir=raw)
        item = build(row, pd.read_parquet(file))
        records[assignment[item['group']]].append(item)
        print(f'{i}/{len(rows)} {row["case"]}', flush=True)
    for split, items in records.items():
        path = ROOT / f'data/{split}.jsonl'
        path.write_text(''.join(json.dumps(x) + '\n' for x in items))
    dump(ROOT / 'data/manifest.json', {'repository': REPO, 'revision': revision, 'seed': 42,
         'task': 'External-label-conditioned reporting, not independent root cause analysis',
         'reference_policy': 'Deterministic synthetic templates from external annotation and real metric statistics; not human-reviewed reports',
         'suite': 'RE2-OB', 'normal_cases': 0, 'groups': assignment,
         'counts': {s: len(v) for s, v in records.items()},
         'sha256': {s: hashlib.sha256((ROOT / f'data/{s}.jsonl').read_bytes()).hexdigest() for s in records}})


if __name__ == '__main__':
    main()
