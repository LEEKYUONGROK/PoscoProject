"""Sequential pilot SFT of existing Qwen/Phi models using four-bit LoRA."""
import argparse
import importlib.metadata
import json
from pathlib import Path
import time

import torch
from datasets import Dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, set_seed
from trl import SFTConfig, SFTTrainer

ROOT = Path(__file__).resolve().parent
MODELS = {'qwen': 'Qwen/Qwen3-4B-Instruct-2507', 'phi': 'microsoft/Phi-4-mini-instruct'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--epochs', type=float, default=2)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--max-length', type=int, default=2048)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Output already exists; choose a new directory')
    if not torch.cuda.is_available():
        raise RuntimeError('This QLoRA pilot requires CUDA')
    set_seed(42)
    model_id = MODELS[args.model]
    tokenizer = AutoTokenizer.from_pretrained(model_id, local_files_only=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = 'right'
    splits = {}
    lengths = {}
    for split in ('train', 'validation'):
        rows = [json.loads(x) for x in (args.data_dir / f'{split}.jsonl').read_text().splitlines()]
        lengths[split] = []
        for row in rows:
            ids = tokenizer.apply_chat_template(row['prompt'] + row['completion'], tokenize=True, return_dict=False)
            lengths[split].append(len(ids))
            if len(ids) > args.max_length:
                raise ValueError(f'Would truncate {row["case_id"]}: {len(ids)} tokens')
        splits[split] = Dataset.from_list([{'prompt': r['prompt'], 'completion': r['completion']} for r in rows])
    model = AutoModelForCausalLM.from_pretrained(model_id, local_files_only=True,
        dtype=torch.bfloat16, device_map={'': 0}, attn_implementation='sdpa',
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type='nf4',
            bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True))
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    config = SFTConfig(output_dir=str(args.output), num_train_epochs=args.epochs,
        per_device_train_batch_size=1, per_device_eval_batch_size=1,
        gradient_accumulation_steps=4, learning_rate=1e-4, warmup_steps=2,
        bf16=True, gradient_checkpointing=True, gradient_checkpointing_kwargs={'use_reentrant': False},
        max_length=args.max_length, completion_only_loss=True, packing=False,
        eval_strategy='epoch', save_strategy='no', logging_steps=1,
        report_to='none', seed=42, data_seed=42, optim='adamw_torch',
        dataloader_num_workers=0)
    trainer = SFTTrainer(model=model, args=config, processing_class=tokenizer,
        train_dataset=splits['train'], eval_dataset=splits['validation'],
        peft_config=LoraConfig(r=8, lora_alpha=16, lora_dropout=0.05,
            target_modules='all-linear', bias='none', task_type='CAUSAL_LM'))
    # Verify completion-only loss exists and neither side was silently truncated.
    first = trainer.train_dataset[0]
    labels = first.get('labels', [])
    if not labels or not any(x == -100 for x in labels) or not any(x != -100 for x in labels):
        raise RuntimeError('Missing completion supervision mask')
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = {'model_id': model_id, 'model_revision': getattr(model.config, '_commit_hash', None),
        'data_manifest': json.loads((args.data_dir / 'manifest.json').read_text()),
        'settings': config.to_dict(), 'max_tokens': {s: max(v) for s, v in lengths.items()},
        'packages': {p: importlib.metadata.version(p) for p in ['torch', 'transformers', 'peft', 'trl', 'datasets', 'bitsandbytes']}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2, default=str))
    started = time.monotonic()
    result = trainer.train()
    trainer.save_model(str(args.output / 'adapter'))
    tokenizer.save_pretrained(args.output / 'adapter')
    metrics = dict(result.metrics, elapsed_seconds=time.monotonic()-started,
        peak_gpu_gib=torch.cuda.max_memory_allocated()/2**30,
        validation=trainer.evaluate())
    (args.output / 'metrics.json').write_text(json.dumps(metrics, indent=2))
    (args.output / 'trainer_history.json').write_text(json.dumps(trainer.state.log_history, indent=2))
    print(json.dumps(metrics, indent=2), flush=True)


if __name__ == '__main__':
    main()
