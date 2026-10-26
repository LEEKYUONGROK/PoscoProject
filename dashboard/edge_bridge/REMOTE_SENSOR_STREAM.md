# 원격 센서 최근 200개 + 실시간 Qwen 보고서

## 주소와 현재 상태

- 모델 서버 공인 IP: **3.37.166.127**, TCP **7777**.
- 모델 서버 수신: `0.0.0.0:7777` (현재 실행 중).
- 원격 로그 서버: **3.39.173.120**. 그쪽에서 모델 주소로 접속하여 로그를 보낸다.
- 보고서 화면: https://any-refine-technique-friendship.trycloudflare.com
  기본 "센서 보고서 · 실시간" 메뉴. 외부 화면은 읽기 전용.
- 이 서버에는 원격 7,500개 센서 기록이 없다. 원격이 최근 200개를 선택해 먼저 보내야 한다.
  구현 완료 시 실제 원격 수신은 **0/200**이며 보고서 200개를 생성했다고 주장하지 않는다.
- 원격 `3.39.173.120:7777`에 수동 접속했을 때는 MsgId=6, 본문 0바이트만 수신했다.
  이후 3초 안에는 센서 메시지가 오지 않았다. MsgId 6은 이 분석 계약의 입력이 아니다.

## 송신 측 동작

1. 3.39.173.120의 원본 DB에서 증가 ID(또는 명확한 사건 시각+동률 ID)로 최신 200개를 선택한다.
2. 선택된 200개를 오래된 것부터 SensorMsg(0) 또는 SensorsMsg(1)로 전송한다.
3. 이후 신규 기록을 SensorMsg로 계속 보낸다. 같은 기록의 재시도는 같은 원본 ID를 사용한다.
4. 요청마다 **같은 소켓에서 Report(10) 하나**를 수신한다. 응답을 입력으로 되돌리지 않는다.

일반 TCP 연결 예:

```python
sock = socket.create_connection(('3.37.166.127', 7777), timeout=600)
```

수신 포트와 응답 포트는 같다. 모델 서버의 OS UFW는 비활성 상태이며 listen 확인은
완료했다. 원격 측에서 이 모델 서버에 연결하는 실제 수신은 아직 확인하지 못했다.
EC2 보안 그룹 등 외부 네트워크 규칙은 이 세션에서 수정하지 않았으므로 그쪽에서
접속이 실패하면 모델 서버의 TCP 7777 인바운드 허용을 확인해야 한다.
HTTP 보고서 URL이나 0.0.0.0을 TCP 클라이언트 접속 주소로 사용하지 않는다.

기존 protobuf 스키마를 유지한다. 본문 프레임은 `<HH`: 전체 길이(4바이트 헤더 포함),
MsgId, protobuf 본문. 최대 65535바이트. `SensorsMsg.info` 안 SensorMsg 하나가 로그
한 행이면 기록별 보고서 하나가 생성된다. 여러 행을 넣으면 비어 있지 않은 행마다
개별 보고서를 만든다. 센서 필드 매핑은 [TCP_PROTOBUF.md](TCP_PROTOBUF.md)를 따른다.

## 선택 사항: 재전송 중복 방지용 msg JSON 래퍼

프로토콜 메시지 필드를 추가하지 않고 SensorMsg.msg에 다음 JSON을 담을 수 있다.
이 래퍼를 쓰지 않아도 일반 센서 로그 문자열은 계속 지원한다.

```json
{
  "_bridge": {"source":"vision4.sensorlog", "row_id":"7500"},
  "log":"{\"sensor_id\":302,\"mq7\":23,\"fire_alarm\":0}"
}
```

`source`와 `row_id`는 원격 시스템의 안정적인 식별자로, 비어 있지 않은 문자열이며
최대 256자다. 같은 출처/ID의 같은 내용은 재수신해도 보고서를 중복 생성하지 않는다.
같은 ID의 다른 내용은 오류다. 측정값이 같아도 서로 다른 실제 기록이면 서로 다른
ID를 사용해야 한다. 래퍼가 없으면 수신별 ID를 발급하므로 재전송 중복을 구별할 수 없다.
행 위치·수신 시각은 실제 장치 발급 ID나 사건 시각으로 표시하지 않는다.

## Python 송신 예제

`send_recent.py`와 protobuf 모듈을 묶은 `data/remote-sender.zip`을 원격으로 복사해
압축을 풀고 실행할 수 있다. MySQL 접속은 모델 서버에서 하지 않는다. 원격 DB에서
다음 형식의 JSONL을 **원본 증가 ID 순서**로 내보내거나 동일한 전송 루틴을 DB 조회
코드에 연결한다. JSONL 한 행은 newline으로 끝나야 한다.

```json
{"id":7500,"sensor_id":302,"log":{"sensor_id":302,"mq7":23,"fire_alarm":0}}
```

`id`와 수치 예시는 형식 설명이며 실제 운영 자료로 넣지 않는다.

```bash
python3 -m pip install protobuf==6.33.6
python3 -m edge_bridge.send_recent \
  --host 3.37.166.127 --port 7777 \
  --jsonl /path/to/actual-sensorlog.jsonl \
  --source vision4.sensorlog --recent 200 --follow
```

처음에는 파일의 마지막 200개를 전송하고, `--follow`에서는 파일에 새로 append되는
완성된 행을 계속 전송한다. 전체 길이를 고려해 SensorsMsg를 여러 패킷으로 나눈다.
응답은 표준 출력에 Report.Content를 출력한다. 연결 실패 시 같은 ID로 재전송하며,
모델 ERROR는 커서를 진행시키지 않고 중단한다. 프로세스 재시작 시 최근 200개를
재전송하지만 수신 측 안정적 ID로 중복 생성을 방지한다. 파일 교체/축소·수정·역순
레코드는 append-only follow 계약에 포함하지 않는다. 원본 DB의 신규 행 직접 조회와
파일 내보내기는 원격 데이터 보유 측 코드에 연결해야 한다.

## 모델 측 처리와 화면

- 기존 Qwen은 시작 시 한 번 로드하며 추론을 Lock으로 직렬화한다.
- 단일 기록 요청: 응답 Report를 해당 기록의 완성 보고서로 연결한다.
- 여러 기록 요청: TCP에는 계약대로 묶음 분석 Report 하나만 반환한다. 각 기록의
  보고서는 영속 큐에서 따로 Qwen 추론을 수행하여 화면에 순차 표시한다.
- 일시적 모델 오류는 최대 세 번까지 재시도하고 실패 상태와 원인을 화면에 표시한다.
- 수신 기록과 보고서 매핑은 `sensor_records`, 생성 결과는 기존 `reports`에 저장한다.
  재시작 시 중단된 작업을 복구하고 저장 중복을 방지한다. 단일 worker 소유 잠금을 쓴다.
- 화면은 최근 **수신 기록 200개**를 기준으로 완료·대기·실패 상태를 표시한다.
  초기 최신 200개 선택은 원격 책임이며 모델 서버는 없는 7,500개를 조회하지 않는다.
- 수신 이후에는 새 기록마다 자동 생성한다. 브라우저는 5초 간격으로 갱신한다.
  "최신 완성 보고서 따라보기"를 끄면 목록의 이전 기록도 선택할 수 있다.
- 큐 처리량을 초과해 들어오면 대기 기록이 쌓인다. 5초 갱신이 모델의 5초 내 완료를 뜻하지 않는다.
- TCP 요청별 묶음 분석은 별도 "TCP 로그 분석 보고서" 메뉴에서 계속 볼 수 있다.
- 숫자와 근거는 Python에서 계산하며, Qwen은 허용된 근거 기반 가설·확인 항목을
  선택한다. 정상 기준, 시각, 실제 사고 여부를 생성하거나 확정하지 않는다.

현재 프로세스 인자/PID: `data/services-v2.json`, 모델 서버 로그: `data/tcp-stream.log`.
TCP 수신 실행:

```bash
cd /home/ubuntu/models
.venv/bin/python -m edge_bridge.tcp_server --host 0.0.0.0 --port 7777 --max-tokens 256
```

## 검증

19개 검사 통과. 기존 프레임/사실 계산/UI 검사에 더하여 격리된 테스트 DB에서
7,500개 테스트 입력의 최신 200개 선택→개별 보고서 200개 생성, 동일 ID 재전송,
충돌의 전체 롤백, 신규 기록 1개 추가 후 최근 200개 이동, 큰 한글 패킷 분할,
모델 오류 재시도, 응답 에코 차단, 실시간 화면 대기/완료 표시를 확인했다.
이 7,500개/200개는 테스트용 대역이며 원격 실데이터 수신 검증과 구별한다.
실제 서버는 Qwen 로드·7777 listen·worker heartbeat·실데이터 0/200 대기 상태까지 확인했다.

```bash
.venv/bin/python -m unittest edge_bridge.test_tcp edge_bridge.test_log_facts \
  edge_bridge.test_sensor_stream human_eval.test_qwen_workflow \
  human_eval.test_tcp_reports human_eval.test_live_sensor_reports -v
```

출력: `data/tcp-stream-validation.log`.
