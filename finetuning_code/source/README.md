# RCAEval → Qwen/Phi 보고서 학습 실험

실행 결과와 전후 보고서 예시는 [RESULTS.md](RESULTS.md)에 기록합니다.

현재 QA Factory처럼 **외부 판정과 원인 주석을 보고서로 변환**하는 소규모 실험입니다. 원인을 독립적으로 찾는 학습이나 RCAEval 진단 벤치마크가 아닙니다.

## 데이터

- 출처: https://huggingface.co/datasets/phamquiluan/RCAEval
- RE2-OB 장애 90건의 메트릭만 사용합니다. 로그·트레이스는 이 첫 실험에 포함하지 않습니다.
- 서비스/장애 유형 그룹 30개를 시드 42로 분리합니다. 반복 사례는 같은 분할에만 들어갑니다. 학습 60, 검증 15, 시험 15건입니다.
- 외부 판정, 서비스, 장애 유형을 입력에 명시합니다. 해당 서비스의 처음 8개 메트릭에 대해 주입 전후 5분의 중앙값·최댓값을 계산합니다. 가장 중요한 메트릭이라는 주장은 하지 않습니다.
- 정답 보고서는 외부 주석과 계산된 통계를 사용하는 고정 템플릿입니다. 사람이 검수한 보고서 데이터가 아닙니다.
- 신뢰도와 물리적 위치·단위를 발명하지 않습니다. 조치는 확인·점검으로 제한합니다.
- 정상 사례가 없으므로 정상 로그의 행동 개선은 평가할 수 없습니다. 전후 변동의 원인 판단이나 복구 효과도 평가하지 않습니다.

## 실행

작업 공간 루트에서 기존 `.venv`를 사용합니다. 설치된 환경 버전은 각 학습 실행의 manifest에 남깁니다.

```bash
.venv/bin/python llm/finetuning/prepare.py
.venv/bin/python llm/finetuning/evaluate.py --model qwen --output llm/finetuning/runs/qwen-base
.venv/bin/python llm/finetuning/train.py --model qwen --output llm/finetuning/runs/qwen-pilot-v2
.venv/bin/python llm/finetuning/evaluate.py --model qwen --adapter llm/finetuning/runs/qwen-pilot-v2/adapter --output llm/finetuning/runs/qwen-tuned
.venv/bin/python llm/finetuning/evaluate.py --model phi --output llm/finetuning/runs/phi-base
.venv/bin/python llm/finetuning/train.py --model phi --output llm/finetuning/runs/phi-pilot-v2
.venv/bin/python llm/finetuning/evaluate.py --model phi --adapter llm/finetuning/runs/phi-pilot-v2/adapter --output llm/finetuning/runs/phi-tuned
```

GPU를 공유하므로 모델 실행은 순차적으로 진행합니다. 모델은 기존 로컬 캐시를 사용합니다. 기본은 NF4 4비트 기반 LoRA rank 8, alpha 16, dropout 0.05, 모든 linear 대상, 2 epoch, 학습률 1e-4, 배치 1·누적 4, 최대 2048 토큰입니다. 정답 completion에만 loss를 적용하고, 초과 길이는 조용히 자르지 않고 거부합니다.

`evaluate.py`는 기본 시험 6건을 그룹별로 골라 같은 순서로 비교합니다. `--limit 15`는 전체 시험 분할입니다. 보고서의 JSON·필수 타입·판정·위치·신뢰도 보존·원본 근거 인용만 자동 평가하며, 원인·조치의 의미적 적절성을 승인하지 않습니다. 기준 모델과 adapter는 같은 4비트 로딩을 사용합니다.

각 실행 디렉터리는 기존 파일이 있으면 거부합니다. adapter는 기반 모델과 별도로 저장하며 현재 QA Factory에 자동 적용하지 않습니다. 원본 모델 가중치는 변경하지 않습니다.

## 산출물

`data/manifest.json`에 데이터 리비전·분할·해시가 남습니다. 각 학습의 `manifest.json`, `metrics.json`, `trainer_history.json`, `adapter/`에는 설정·loss·메모리·학습 기록·LoRA가 남습니다. 평가는 `summary.json`, `predictions.json`으로 저장합니다.

테스트:

```bash
cd llm/finetuning
/home/ubuntu/models/.venv/bin/python -B -m unittest test_data
```

이 실험에서 좋아진 수치는 합성 보고서 형식에 대한 학습 효과입니다. 실제 HDFS 보고서 개선과 운영 품질은 다른 데이터와 사람 검수로 확인해야 합니다.
