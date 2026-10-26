"""Run models sequentially and retain logs even if training fails."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent


def main():
    for name in ('qwen', 'phi'):
        stages = [
            ('base', ['evaluate.py', '--model', name, '--output', str(ROOT / f'runs/{name}-base')]),
            ('pilot-v2', ['train.py', '--model', name, '--output', str(ROOT / f'runs/{name}-pilot-v2')]),
            ('tuned', ['evaluate.py', '--model', name, '--adapter', str(ROOT / f'runs/{name}-pilot-v2/adapter'), '--output', str(ROOT / f'runs/{name}-tuned')]),
        ]
        for stage, arguments in stages:
            output = ROOT / f'runs/{name}-{stage}'
            complete = output / ('metrics.json' if stage.startswith('pilot') else 'summary.json')
            if complete.exists():
                print(f'Skipping complete stage {name}/{stage}', flush=True)
                continue
            log = ROOT / f'runs/{name}-{stage}.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            print(f'Running {name}/{stage}; log={log}', flush=True)
            with log.open('x') as file:
                subprocess.run([sys.executable, '-u', str(ROOT / arguments[0]), *arguments[1:]], stdout=file, stderr=subprocess.STDOUT, check=True)
            print(f'Completed {name}/{stage}', flush=True)


if __name__ == '__main__':
    main()
