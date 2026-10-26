"""Produce a reviewable local comparison without treating field presence as quality."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    lines = ['# Qwen·Phi RCAEval 보고서 학습 결과', '',
        '2026-10-06 실행. RE2-OB 90건을 그룹별 학습 60·검증 15·시험 15건으로 분리하고, 각 모델을 동일 데이터로 2 epoch QLoRA 학습했습니다. 시험에서는 동일한 6건을 비교했습니다.', '',
        '외부 판정과 원인 주석을 입력으로 주는 보고서 작성 실험입니다. 합성 템플릿을 정답으로 사용했으며, 독립적인 원인 진단이나 사람이 승인한 보고서 품질을 측정하지 않습니다.', '',
        '| 모델 | 단계 | JSON/스키마/판정·위치·신뢰도/근거 모두 통과 | 조치 배열 비어 있지 않음 | 누락 정보 배열 비어 있지 않음 | 평균 출력 토큰 |',
        '| --- | --- | --- | --- | --- | --- |']
    samples = []
    ids = None
    for name in ('qwen', 'phi'):
        for stage in ('base', 'tuned'):
            directory = ROOT / f'runs/{name}-{stage}'
            summary = json.loads((directory / 'summary.json').read_text())
            predictions = json.loads((directory / 'predictions.json').read_text())
            if ids is None:
                ids = summary['case_ids']
            if ids != summary['case_ids']:
                raise ValueError('Evaluation cases differ')
            reports = []
            for item in predictions:
                raw = item['raw'].strip()
                if raw.startswith('```'):
                    raw = raw.split('\n', 1)[1].rsplit('```', 1)[0].strip()
                try:
                    report = json.loads(raw)
                    reports.append(report if isinstance(report, dict) else {})
                except ValueError:
                    reports.append({})
            count = len(predictions)
            passed = sum(p['checks']['all_checks'] for p in predictions)
            actions = sum(bool(r.get('recommended_actions')) for r in reports)
            missing = sum(bool(r.get('missing_information')) for r in reports)
            tokens = sum(p['output_tokens'] for p in predictions)/count
            lines.append(f'| {name} | {stage} | {passed}/{count} | {actions}/{count} | {missing}/{count} | {tokens:.1f} |')
            samples.extend(['', f'## {name} / {stage} 첫 사례', '', f'사례: `{predictions[0]["case_id"]}`', '', '```json', predictions[0]['raw'], '```'])
    lines.extend(['', '배열이 채워졌다는 것은 내용이 적절하다는 판정이 아닙니다. 기본 검사는 원인 설명의 정확성, 조치의 실행 가능성 또는 안전성을 측정하지 않습니다.', '', '## 학습 기록', '',
                  '| 모델 | 학습 시간(초) | 최대 GPU 할당 메모리(GiB) | 마지막 검증 loss |', '| --- | --- | --- | --- |'])
    for name in ('qwen', 'phi'):
        m = json.loads((ROOT / f'runs/{name}-pilot-v2/metrics.json').read_text())
        lines.append(f'| {name} | {m["elapsed_seconds"]:.1f} | {m["peak_gpu_gib"]:.2f} | {m["validation"]["eval_loss"]:.4f} |')
    lines.extend(['', '모델별 토크나이저가 다르므로 두 모델의 loss 숫자로 우열을 판단하지 않습니다. GPU 메모리는 PyTorch 최대 할당값이며 장치 전체 사용량과 다릅니다.', '',
        '## 파일', '',
        '- 데이터 리비전·분할·해시: [data/manifest.json](data/manifest.json)',
        '- Qwen adapter: `runs/qwen-pilot-v2/adapter/`',
        '- Phi adapter: `runs/phi-pilot-v2/adapter/`',
        '- 전후 24개 보고서 전체: 각 `runs/{qwen,phi}-{base,tuned}/predictions.json`', '',
        '최초 Qwen 시도는 TRL 데이터 구조 검사에서 학습 시작 전에 중단됐으며 `runs/qwen-pilot.log`에 보존했습니다. 수정 후 실행은 `pilot-v2`입니다. 기존 QA Factory에는 adapter를 연결하지 않았습니다.', '',
        '## 다음 검증', '',
        '합성 템플릿과 다른 표현의 입력, 정상 사례, 근거가 부족한 사례를 별도 평가해야 합니다. 실제 HDFS 로그 보고서 개선은 이 결과로 입증되지 않았습니다.'] )
    lines.extend(samples)
    (ROOT / 'RESULTS.md').write_text('\n'.join(lines)+'\n')
    print('\n'.join(lines[:13]))


if __name__ == '__main__':
    main()
