# sensorlog 자동 수집

`pull_sensorlog.py`는 원격 MySQL을 조회만 하며 로컬 SQLite에 저장합니다.
기본 접속 대상은 `3.39.173.120:3306`, DB `vision4`, 테이블 `sensorlog`, 사용자 `root`입니다.

```bash
cd /home/ubuntu/models
.venv/bin/python -m pip install -r edge_bridge/requirements.txt
read -rsp 'MySQL password: ' SENSORLOG_MYSQL_PASSWORD
export SENSORLOG_MYSQL_PASSWORD
.venv/bin/python -u edge_bridge/pull_sensorlog.py
```

비밀번호 프롬프트에 DB 비밀번호를 입력합니다. 기본 30초 간격으로 수집합니다.
`--once`는 현재 내역만 가져오고 종료하며, `--interval 60`으로 주기를 변경합니다.
비밀번호를 설정한 뒤 백그라운드 실행하려면:

```bash
mkdir -p edge_bridge/data
nohup .venv/bin/python -u edge_bridge/pull_sensorlog.py > edge_bridge/data/sensorlog-pull.log 2>&1 &
```

저장 위치는 `edge_bridge/data/sensorlog.sqlite3`입니다. `sensorlog` 테이블의
`payload_json`에 원본 열과 값을 JSON으로 보관하고 `sync_state`에 진행 위치를 저장합니다.
행과 진행 위치를 함께 커밋하므로 재시작 시 이어받으며 중복 저장하지 않습니다.
연결 실패 시 다음 주기에 재시도하고 `--once`에서는 종료 코드 1을 반환합니다.

최초 전체 수집 후 마지막 ID보다 큰 행만 조회합니다. 단일 증가 정수 기본 키가
필요합니다. 다른 증가 정수 열은 `--id-column 열이름`으로 지정할 수 있으며
해당 열에는 단일 열 UNIQUE 인덱스가 필요합니다. 기존 행의 수정·삭제, ID 재사용,
나중에 낮은 ID로 삽입·커밋한 행은 반영하지 않습니다. 추가 전용 로그에 사용하세요.
이 스크립트에는 LLM 보고서 자동 생성 연결은 포함하지 않습니다.

2026-10-22 접속 확인은 시간 초과되었습니다. 실제 스키마와 인증은 미확인입니다.
원격 서버 보안 그룹·방화벽의 3306 접속 허용 및 MySQL 원격 접속 설정을 확인해야 합니다.
