# TCP 센서 로그 분석과 외부 보고서 열람

2026-10-22 본문 생성 수정: 개별 로그는 기존 가설 선택에 더해 Qwen이 해석·확인 문단을 직접 생성한다.
수치는 원본 값으로 연결하고, 필드·수치·형식 및 일부 근거 없는 단정을 검사한다. 아래의
자유 서술을 사용하지 않던 구현 설명과 당시 검증 수치는 이전 단계의 기록이다.
현재 방식과 실제 273건 재생성 검증은 [본문 생성 수정 기록](../results/qwen_narrative_20261022/README_KO.md)을 따른다.
Judge·작업자 검토는 미실행이며, 자동 검사를 의미적 정확성 보증으로 해석하지 않는다.

최신 실시간 수신 설정은 [원격 센서 보고서 안내](REMOTE_SENSOR_STREAM.md)를 따릅니다.
현재 서버 수신은 `0.0.0.0:7777`, 클라이언트 목적지는 `3.37.166.127:7777`입니다.
아래 `127.0.0.1:9000`과 75행 검증 결과는 앞선 단일 요청 분석 구현 시점의 기록입니다.

2026-10-22 수정. 이전 자유 서술 방식의 검증 내역은
[TCP_PROTOBUF_V1_VALIDATION.md](TCP_PROTOBUF_V1_VALIDATION.md)에 보존했다.

## 현재 처리 흐름

```
TCP Protobuf → 원본 로그 문자열 → Python 파싱·계산 → 검증 사실/허용 후보
→ 기존 Qwen의 구조화 선택 → 후보·형식 검사 → 한국어 보고서 구성
→ SQLite 저장 → 동일 TCP 연결의 Report 응답 + 기존 Streamlit 화면 열람
```

이전 방식의 숫자 토큰 포함 여부 검사만으로는 "MQ7은 22로 일관" 같은 잘못된
관계 서술을 잡지 못했다. 현재는 수치·빈도·정상 판정 문장을 모델이 생성하지 않는다.
원본 로그 문장도 모델 입력에 전달하지 않는다. 모델은 Python이 검증한 사실을 읽고
허용된 근거 기반 원인 가설과 확인 항목을 선택·정렬한다. 실제 Qwen 추론을 사용하며
고정 결과/에코 또는 모델 실패 시 고정 분석으로 대체하는 경로는 없다.
최종 한국어 문장은 계산된 사실과 선택된 후보 문장으로 구성한다.

## 사실 계산과 제약

- 정규식으로 TCP 센서 ID 접두사, RealSensor 토픽 ID, key=value/필드:값,
  ISO 날짜·시각을 추출한다. JSON Payload는 정규식으로 내부 구조를 해석하지 않고
  표준 JSON 파서로 읽으며 중복 키, 잘못된 JSON과 비유한 수치를 거부한다.
- 지원 필드: sensor_id/sensorID, temperature_c, humidity_pct, mq2, mq7,
  flame_detected, fire_alarm, alarm_level, person_detected, dht_ok.
- 센서별 레코드 수, 측정값의 관측 수·최솟값·최댓값·필드 누락 수,
  플래그·경보 수준별 횟수와 원본 행 번호를 Python에서 계산한다.
- 플래그는 숫자 0/1, alarm_level은 음수가 아닌 정수다. bool/문자열로 된 숫자는
  자동 보정하지 않는다. envelope/topic/payload 센서 ID가 충돌하면 그 행을 오류로 기록한다.
- 지원하지 않는 행과 오류 행은 버리지 않고 개수와 위치를 보고한다. 일부 필드만 있으면
  그 필드만 계산한다. 파싱 가능한 수치가 전혀 없으면 판단 불가로 표시한다.
- 알려지지 않은 필드의 값, 임의의 자연어 사건/명령은 사실 후보로 사용하지 않는다.
  새 장치의 필드·단위·경보 조건은 명시적인 파서/계약 확장이 필요하다.
- 최대 센서 그룹 128개. ID 미제공은 별도 그룹이며 장치 ID를 만들어내지 않는다.
- 시각은 파싱된 센서 행에 있는 유효한 ISO 날짜·시각만 사용한다. 행 번호는
  입력 위치이며 시각이나 장치 발급 레코드 ID가 아니다. 시각이 없으면 시간 간격이나
  날짜를 만들지 않는다. 시각 문자열을 실제 장치의 정확한 시계라고 인증하지 않는다.
- MQ 물리 단위·보정·정상 임계값은 정의되지 않았다. 경보 보고를 실제 화재나 가스
  누출의 독립적인 증거로 확정하지 않고, 경보가 없다고 장치/환경 정상도 단정하지 않는다.

Qwen 응답 형식은 아래 JSON 하나다. 선택 가능한 ID는 요청별 후보 목록으로 제한한다.

```json
{"hypotheses":["H_SIGNAL"],"checks":["C_SIGNAL","C_THRESHOLD","C_TIME"]}
```

후보 밖 ID, 자유 서술, 추가 키, 빈 선택, 중복 선택, 불완전한 모델 출력은 거부한다.
한 번 재시도하고 다시 실패하면 ERROR Report를 반환한다. 모델은 매 요청 새로운
메시지로 호출하며 로그 안 프롬프트는 모델 입력에 전달되지 않는다. 선택의 적절성까지
정답으로 보증하는 것은 아니므로 화면에는 Judge 미실행/작업자 미확인 상태를 표시한다.
기존 Judge와 사람 승인 기록은 별도로 유지한다.

## TCP 실행

작업 경로 `/home/ubuntu/models`에서:

```bash
.venv/bin/python -m pip install -r edge_bridge/requirements-protobuf.txt
.venv/bin/python -m edge_bridge.tcp_server --host 127.0.0.1 --port 9000 --max-tokens 256
```

기존 torch/transformers 환경을 재사용한다. 기본 모델은
`Qwen/Qwen3-4B-Instruct-2507`, 로컬 캐시 전용이며 `--allow-download`로 다운로드를
허용할 수 있다. `--model`로 로컬 경로/모델 ID를 지정한다.
모델은 listen 전 한 번 로드하고 공유 Lock으로 추론을 직렬화한다.
`--read-timeout` 기본 120초, `--max-clients` 기본 8, `--max-tokens` 코드 기본 1200.
제약된 JSON 선택에는 현재 실행값 256을 사용했다.
`--report-db`로 저장 DB 경로를 변경할 수 있다. 기본:
`edge_bridge/data/tcp-reports.sqlite3`.

TCP는 현재 127.0.0.1:9000에서 실행 중이다. 외부 로그 송신 서버가 직접 접속하려면
해당 네트워크 인터페이스로 `--host`를 설정해야 한다. 일반 TCP 서비스와 외부 보고서의
HTTPS 주소는 별개이며, HTTP Cloudflare 터널로 이 TCP 프로토콜을 보내면 안 된다.

실제 센서 로그 한 번 전송 및 Report.Content 출력:

```bash
.venv/bin/python -m edge_bridge.tcp_client --host 127.0.0.1 --port 9000 \
  --log-file human_eval_inputs/realsensor302_received.txt --sensor-id 302
```

`--type sensor|sensors|report`(기본 sensor), `--timeout`(기본 600초)을 지정할 수 있다.
로그 파일은 사용자가 전달한 실제 센서 로그의 전사본으로, 독립 인증한 MQTT 캡처는 아니다.

## 기존 화면 재사용과 외부 접속

`human_eval/app.py`의 기존 Qwen 화면을 재사용한다. 기본 메뉴에 "TCP 로그 분석 보고서"를
추가했고, 기존 화면과 새 화면이 같은 원본/보고서 열 표시 함수를 사용한다.
보고서, 원본, 센서별 계산 사실, 근거 행, 모델 선택과 처리 정보를 함께 읽을 수 있다.
TCP Report로 반환한 본문과 저장·표시하는 본문은 동일하다.

```bash
.venv/bin/python -m pip install -r human_eval/requirements.txt
.venv/bin/python -m streamlit run human_eval/app.py \
  --server.address 127.0.0.1 --server.port 8501 --server.headless true \
  --browser.gatherUsageStats false -- --read-only
```

별도 터미널:

```bash
edge_bridge/bin/cloudflared tunnel --url http://127.0.0.1:8501 --no-autoupdate
```

현재 외부 열람 주소:
**https://any-refine-technique-friendship.trycloudflare.com**

익명 외부 열람 화면은 `--read-only`로 실행하므로 라벨링 메뉴와 작업자 승인·반려
저장 폼을 제공하지 않는다. 기존 과거 Qwen 보고서는 읽을 수 있다. 새 요청 완료 후
"보고서 새로고침"으로 목록을 갱신하고 내려받을 수 있다. 이 주소를 아는 사용자는
표시된 보고서와 원본을 열람할 수 있다. Quick Tunnel 임시 주소이며 터널 재시작 시 바뀐다.

현재 TCP/UI/터널은 분리된 백그라운드 프로세스로 실행 중이다. 자동 재부팅 복구를
설정한 운영 서비스는 아니다. PID와 실행 인자는 `edge_bridge/data/services-v2.json`,
로그는 `tcp-v2.log`, `ui-v2.log`, `tunnel-v2.log`에 있다. 재시작 전 해당 프로세스의
실행 인자를 확인하고 기존 프로세스를 정상 종료한 뒤 위 명령으로 실행한다.
UI의 DB를 바꿀 때는 `-- --read-only --tcp-report-db 경로`로 TCP 서버와 일치시킨다.

## 통신 계약

- `struct.Struct('<HH')`: uint16 전체 길이(헤더 4바이트 포함), uint16 MsgId, Protobuf 본문.
- 최대 65535바이트. 본문 크기는 ByteSize()로 계산하며 송신 MsgId는 타입 이름을
  SNAKE_CASE로 변환해 enum에서 조회한다.
- 입력 0=SensorMsg, 1=SensorsMsg, 10=Report. 요청마다 같은 연결로 Report(10) 하나.
- 분할/연속 패킷 처리. 패킷 사이 EOF는 정상 종료, 헤더/본문 중간 EOF는 TruncatedPacket.
  잘못된 전체 길이 0~3, 소켓 오류와 수신 시간 초과는 연결 종료.
- 빈 로그/미지원 ID/Protobuf 파싱 실패/모델 오류는 가능한 경우 ERROR Report.
  저장 실패도 ERROR Report로 알린다. 불완전한 패킷은 보고서로 저장하지 않는다.
- UTF-8 문자 경계와 직렬화 크기에 맞춰 응답을 자르고 생략 표시를 붙인다.
  상세 계산 근거는 DB와 화면에 보존한다. 모델 컨텍스트 초과 시 입력을 숨겨서 자르지 않고 오류 반환.
- 서버는 자신의 응답을 재입력하지 않는다. 클라이언트도 수신 Report를 재전송하지 않는다.
  Report에는 요청/응답 식별 필드가 없으므로 상대 서버도 응답을 새 요청으로 되돌리면 안 된다.

기존 .proto가 없어 제공된 enum 전체와 세 메시지로 만들었다. 전체 서버 스키마를
받으면 기존 정의를 보존하여 병합한다. 재컴파일:

```bash
.venv/bin/python -m grpc_tools.protoc -I edge_bridge \
  --python_out=edge_bridge edge_bridge/protocol.proto
```

## 검증 결과

```bash
.venv/bin/python -m unittest edge_bridge.test_tcp edge_bridge.test_log_facts \
  human_eval.test_qwen_workflow human_eval.test_tcp_reports -v
```

14개 검사 통과. 헤더/분할·연속 수신/정상·중간 EOF/한국어 크기 제한/오류 응답,
모델 잠금/후보 검사와 재시도, 수치·플래그 계산/누락·오류 행/센서 충돌/시각 없음,
실제 75행 회귀검사, 기존 승인 기록 보존 및 읽기 전용 UI/빈 목록/저장 원문 동일성 검증.
compileall 및 pip check 통과. 기존 과거 Qwen 화면도 읽기 전용 전환 후 오류 없이 표시됨.

실제 모델·TCP·화면 검증:

- Qwen/Qwen3-4B-Instruct-2507, A10G, 한 번 로드한 모델로 실제 센서 302의 75행 전송.
- Python 계산: 온도 24.7~25.3°C, 습도 45.7~51.4%, MQ2 55~745, MQ7 21~265.
  경보 수준별 0=55행/1=4행/2=16행. 원문 시각 없음.
- 실제 Qwen 선택: H_SIGNAL 및 C_SIGNAL/C_THRESHOLD/C_SOURCE. 1회 추론 성공,
  모델 입력 4255토큰/출력 20토큰. 모델 입력은 원본 대신 Python 검증 사실과 후보 목록.
- 반환 Report: `data/tcp-real-analysis-v2.txt`. DB 보고서 ID:
  `a6f3749ad52740cc8eb2ecc2e5af48be`. 저장 본문과 실제 화면 표시 일치 확인.
- 외부 HTTPS `/` 및 `/_stcore/health` HTTP 200 확인:
  `data/external-view-validation-v2.json`.
- 최신 테스트 출력: `data/tcp-all-validation-v2.log`.

## 변경 파일

- `edge_bridge/log_facts.py`: 정규식/JSON 파싱, 검증 사실 계산, 제약 후보, 보고서 구성.
- `edge_bridge/log_analyzer.py`: 기존 Qwen 재사용, 사실 기반 구조화 추론, 형식 검증/재시도.
- `edge_bridge/tcp_server.py`, `report_archive.py`: TCP 응답과 보고서·원본·근거 저장.
- `edge_bridge/test_log_facts.py`, `test_tcp.py`: 사실 계산 및 통신 회귀검사.
- `human_eval/app.py`, `qwen_workflow.py`, `tcp_reports.py`: 기존 화면 재사용과 읽기 전용 열람.
- `human_eval/test_tcp_reports.py`: 원문·보고서·근거 표시 및 외부 쓰기 폼 비노출 검사.
- 스키마/프레이밍/클라이언트: 기존 `protocol.proto`, `protocol_pb2.py`, `tcp_protocol.py`,
  `tcp_client.py`를 유지했다.
