# Vision4 대시보드 전달 패키지

2026-10-23 현재 실제 구성에서 필요한 파일을 모은 패키지다.

## 포함 내용

- `model/Qwen3-4B-Instruct-2507/`: 기본 생성 모델의 Hugging Face snapshot (`cdbee75f17c01a7cc42f958dc650907174af0554`)
- `adapter/qwen-korean-rcaeval/`: 실제 생성 경로에서 사용하는 한국어 RCAEval QLoRA adapter
- `dataset/rcaeval/`: RCAEval 원본 추출 데이터, train/validation/test JSONL, 한국어 및 live 가공 데이터
- `glossary/technical_glossary.json`: 20개 프로젝트 한국어 기술 용어집
- `dashboard/vision4_dashboard/`: Vision4 발표용 대시보드 코드, 웹 자산, 테스트, README
- `dashboard/edge_bridge/`: 대시보드 및 생성 경로가 참조하는 Python/Protobuf 코드와 실행 문서
- `finetuning_code/`: RCAEval 준비·학습·평가 코드와 설명

## 제외 내용

API 토큰, 운영 SQLite DB, 운영 로그, Python 캐시와 불완전한 v2 adapter는 포함하지 않았다.
대시보드가 실제 데이터를 표시하려면 별도의 `edge_bridge/data/tcp-reports.sqlite3`가 필요하다.

## 모델 구성

- Base: `Qwen/Qwen3-4B-Instruct-2507`
- Revision/snapshot: `cdbee75f17c01a7cc42f958dc650907174af0554`
- Adapter: `qwen-korean-rcaeval` (완성본)
- 추론 구성: NF4 4-bit GPU 로딩

상세 실행 계약은 `dashboard/vision4_dashboard/README.md`, `dashboard/edge_bridge/ADAPTER_UI_HANDOFF_20261023.md`, `dashboard/edge_bridge/TCP_PROTOBUF.md`를 참고한다.
