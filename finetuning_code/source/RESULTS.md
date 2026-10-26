# Qwen·Phi RCAEval 보고서 학습 결과

2026-10-06 실행. RE2-OB 90건을 그룹별 학습 60·검증 15·시험 15건으로 분리하고, 각 모델을 동일 데이터로 2 epoch QLoRA 학습했습니다. 시험에서는 동일한 6건을 비교했습니다.

외부 판정과 원인 주석을 입력으로 주는 보고서 작성 실험입니다. 합성 템플릿을 정답으로 사용했으며, 독립적인 원인 진단이나 사람이 승인한 보고서 품질을 측정하지 않습니다.

| 모델 | 단계 | JSON/스키마/판정·위치·신뢰도/근거 모두 통과 | 조치 배열 비어 있지 않음 | 누락 정보 배열 비어 있지 않음 | 평균 출력 토큰 |
| --- | --- | --- | --- | --- | --- |
| qwen | base | 6/6 | 3/6 | 3/6 | 434.3 |
| qwen | tuned | 6/6 | 6/6 | 6/6 | 312.2 |
| phi | base | 0/6 | 0/6 | 0/6 | 309.8 |
| phi | tuned | 3/6 | 6/6 | 3/6 | 264.0 |

배열이 채워졌다는 것은 내용이 적절하다는 판정이 아닙니다. 기본 검사는 원인 설명의 정확성, 조치의 실행 가능성 또는 안전성을 측정하지 않습니다.

Qwen은 기존 6/6 통과를 유지했고, 조치·누락 정보 배열을 채우는 비율이 각각 3/6에서 6/6으로 늘었습니다. Phi는 학습 전 모든 사례에서 배열 대신 null을 반환해 실패했고, 학습 후에는 3/6 통과했습니다. 나머지 Phi 사례는 `confidence`·`missing_information` 또는 `evidence` 필드를 생략했습니다. 외부 원인 주석을 명시하는 표현은 첫 Qwen 전후 샘플에서도 확인되지만, 이 작은 합성 데이터 실험만으로 전반적인 의미 품질 개선을 확정하지 않습니다.

## 학습 기록

| 모델 | 학습 시간(초) | 최대 GPU 할당 메모리(GiB) | 마지막 검증 loss |
| --- | --- | --- | --- |
| qwen | 136.8 | 5.01 | 0.2017 |
| phi | 98.4 | 6.16 | 0.1633 |

모델별 토크나이저가 다르므로 두 모델의 loss 숫자로 우열을 판단하지 않습니다. GPU 메모리는 PyTorch 최대 할당값이며 장치 전체 사용량과 다릅니다.

## 파일

- 데이터 리비전·분할·해시: [data/manifest.json](data/manifest.json)
- Qwen adapter: `runs/qwen-pilot-v2/adapter/`
- Phi adapter: `runs/phi-pilot-v2/adapter/`
- 전후 24개 보고서 전체: 각 `runs/{qwen,phi}-{base,tuned}/predictions.json`

최초 Qwen 시도는 TRL 데이터 구조 검사에서 학습 시작 전에 중단됐으며 `runs/qwen-pilot.log`에 보존했습니다. 수정 후 실행은 `pilot-v2`입니다. 기존 QA Factory에는 adapter를 연결하지 않았습니다.

## 다음 검증

합성 템플릿과 다른 표현의 입력, 정상 사례, 근거가 부족한 사례를 별도 평가해야 합니다. 실제 HDFS 로그 보고서 개선은 이 결과로 입증되지 않았습니다.

## qwen / base 첫 사례

사례: `re2ob_checkoutservice_cpu_1`

```json
{
  "status": "Anomaly",
  "problem_location": "checkoutservice",
  "observed_issue": "CPU stress",
  "evidence": [
    "checkoutservice_cpu: baseline median=0.429164; incident median=19.9802; incident max=20.0292; samples=300/300",
    "checkoutservice_mem: baseline median=1.17064e+07; incident median=1.61055e+07; incident max=1.68468e+07; samples=300/300",
    "checkoutservice_socket: baseline median=9; incident median=11; incident max=11; samples=300/300",
    "checkoutservice_workload: baseline median=0.933; incident median=1.1; incident max=1.733; samples=300/300",
    "checkoutservice_latency-50: baseline median=0.254808; incident median=0.307292; incident max=0.352273; samples=300/300",
    "checkoutservice_latency-90: baseline median=0.75; incident median=0.78; incident max=0.85; samples=300/300"
  ],
  "possible_cause": "cpu",
  "recommended_actions": [],
  "confidence": null,
  "missing_information": []
}
```

## qwen / tuned 첫 사례

사례: `re2ob_checkoutservice_cpu_1`

```json
{"status": "Anomaly", "problem_location": "checkoutservice", "observed_issue": "The external RCAEval annotation identifies CPU stress affecting checkoutservice. The supplied telemetry summaries are consistent with this annotation.", "evidence": ["checkoutservice_cpu: baseline median=0.429164; incident median=19.9802; incident max=20.0292; samples=300/300"], "possible_cause": "The external RCAEval annotation attributes the fault to CPU stress. The supplied telemetry summaries do not independently establish causality.", "recommended_actions": ["Inspect checkoutservice telemetry around the incident window to verify the externally annotated fault.", "Check the checkoutservice logs and traces to corroborate the externally annotated fault before taking corrective action."], "confidence": null, "missing_information": ["Metric units and physical location are not supplied.", "Logs, traces, and causal mechanism are not included in the supplied telemetry summary."]}
```

## phi / base 첫 사례

사례: `re2ob_checkoutservice_cpu_1`

```json
```json
{
  "status": "Anomaly",
  "problem_location": "checkoutservice",
  "observed_issue": "CPU stress",
  "evidence": [
    "checkoutservice_cpu: baseline median=0.429164; incident median=19.9802; incident max=20.0292; samples=300/300",
    "checkoutservice_mem: baseline median=1.17064e+07; incident median=1.61055e+07; incident max=1.68468e+07; samples=300/300",
    "checkoutservice_socket: baseline median=9; incident median=11; incident max=11; samples=300/300",
    "checkoutservice_workload: baseline median=0.933; incident median=1.1; incident max=1.733; samples=300/300",
    "checkoutservice_latency-50: baseline median=0.254808; incident median=0.307292; incident max=0.352273; samples=300/300",
    "checkoutservice_latency-90: baseline median=0.75; incident median=0.78; incident max=0.85; samples=300/300"
  ],
  "possible_cause": null,
  "recommended_actions": null,
  "confidence": null,
  "missing_information": null
}
```
```

## phi / tuned 첫 사례

사례: `re2ob_checkoutservice_cpu_1`

```json
{"status": "Anomaly", "problem_location": "checkoutservice", "observed_issue": "Externally annotated fault: CPU stress. Evidence strings are quoted exactly. Metric units and physical location are not provided. The supplied telemetry summaries do not independently establish causality.", "evidence": ["checkoutservice_cpu: baseline median=0.429164; incident median=19.9802; incident max=20.0292; samples=300/300", "checkoutservice_mem: baseline median=1.17064e+07; incident median=1.61055e+07; incident max=1.68468e+07; samples=300/300"], "possible_cause": "Externally annotated fault: CPU stress. The supplied telemetry summaries do not independently establish causality.", "recommended_actions": ["Inspect checkoutservice telemetry summaries. Attribute the externally annotated fault type: CPU stress. Metric units and physical location are not provided. The supplied telemetry summaries do not independently establish causality."], "confidence": null, "missing_information": ["Metric units and physical location are not provided. The supplied telemetry summaries do not independently establish causality."]}
```
