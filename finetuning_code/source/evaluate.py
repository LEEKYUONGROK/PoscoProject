"""Compare a frozen base and adapter on the same held-out reporting cases."""
import argparse
import json
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from train import MODELS, ROOT


def checks(raw, row):
    try:
        text = raw.strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        report = json.loads(text)
        required = {'status': str, 'problem_location': str, 'observed_issue': str,
            'evidence': list, 'possible_cause': (str, type(None)),
            'recommended_actions': list, 'confidence': type(None), 'missing_information': list}
        schema = isinstance(report, dict) and all(isinstance(report.get(k), t) and k in report for k,t in required.items())
        schema = schema and all(all(isinstance(x,str) for x in report[k]) for k in ('evidence','recommended_actions','missing_information'))
        evidence = schema and bool(report['evidence']) and all(q in row['source']['evidence'] for q in report['evidence'])
        preservation = schema and report['status'] == 'Anomaly' and report['problem_location'] == row['source']['detection']['service'] and report['confidence'] is None
        return {'json': True, 'schema': schema, 'evidence': evidence, 'preservation': preservation,
                'all_checks': bool(schema and evidence and preservation)}
    except (ValueError, TypeError, KeyError):
        return dict.fromkeys(('json','schema','evidence','preservation','all_checks'), False)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model', choices=MODELS, required=True)
    p.add_argument('--adapter', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit', type=int, default=6)
    args = p.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists')
    rows = [json.loads(x) for x in (ROOT/'data/test.jsonl').read_text().splitlines()]
    # One repetition per service/fault group to avoid evaluating only two groups.
    groups = {}
    for row in rows:
        groups.setdefault(row['group'], []).append(row)
    selected = []
    for i in range(max(map(len, groups.values()))):
        selected.extend(v[i] for v in groups.values() if i < len(v))
    rows = selected[:args.limit]
    tokenizer = AutoTokenizer.from_pretrained(MODELS[args.model], local_files_only=True)
    model = AutoModelForCausalLM.from_pretrained(MODELS[args.model], local_files_only=True,
        dtype=torch.bfloat16, device_map={'': 0}, attn_implementation='sdpa',
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))
    if args.adapter:
        model = PeftModel.from_pretrained(model, str(args.adapter))
    model.eval()
    results = []
    for row in rows:
        text = tokenizer.apply_chat_template(row['prompt'], tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors='pt', add_special_tokens=False).to('cuda')
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=768, do_sample=False, pad_token_id=tokenizer.eos_token_id)
        tokens = output[0, inputs.input_ids.shape[1]:]
        raw = tokenizer.decode(tokens, skip_special_tokens=True)
        results.append({'case_id': row['case_id'], 'group': row['group'], 'raw': raw,
            'checks': checks(raw, row), 'output_tokens': len(tokens), 'token_limit_reached': len(tokens)>=768})
        print(row['case_id'], results[-1]['checks'], flush=True)
    args.output.mkdir(parents=True)
    (args.output/'predictions.json').write_text(json.dumps(results, indent=2))
    summary = {'model': MODELS[args.model], 'adapter': str(args.adapter) if args.adapter else None,
               'count': len(results), 'case_ids': [r['case_id'] for r in results],
               'rates': {k: sum(r['checks'][k] for r in results)/len(results) for k in results[0]['checks']},
               'limitations': 'Mechanical report checks only; not semantic quality, RCA accuracy, normal-case behavior or human approval.'}
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
