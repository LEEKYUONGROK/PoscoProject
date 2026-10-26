# TCP + Protobuf 로그 분석

2026-10-22 구현. 기존 `llm.qa_factory.model.LocalModel`과 기본 모델
`Qwen/Qwen3-4B-Instruct-2507`을 사용한다. 고정 응답/에코 대체 경로는 없다.
이 서비스는 Qwen 분석을 직접 반환하며 기존 Judge 및 작업자 승인 UI는 호출하지 않는다.

## 실행

`/home/ubuntu/models`에서:

```bash
.venv/bin/python -m pip install -r edge_bridge/requirements-protobuf.txt
.venv/bin/python -m edge_bridge.tcp_server --host 127.0.0.1 --port 9000
```

기존 Transformers/PyTorch 모델 환경이 필요하다. 모델은 listen 전 한 번 로드한다.
기본은 로컬 캐시 전용이며 다운로드는 `--allow-download`로 허용한다.
`--model`로 모델 ID/로컬 경로, `--max-tokens`(기본 1200),
`--read-timeout`(수신 대기 초, 기본 120), `--max-clients`(기본 8)를 지정한다.
다른 서버에서 접속하려면 필요한 인터페이스로 host를 설정한다. 예: `--host 0.0.0.0`.
일반 TCP이며 기존 HTTPS `/events` 서버 및 Cloudflare HTTP 터널과는 별도다.
인증/암호화는 이 프로토콜에 없으므로 접근을 허용할 네트워크에서 실행한다.

저장된 실제 센서 로그를 한 번 전송하고 `Report.Content` 출력:

```bash
.venv/bin/python -m edge_bridge.tcp_client \
  --host 127.0.0.1 --port 9000 \
  --log-file human_eval_inputs/realsensor302_received.txt --sensor-id 302
```

이 파일은 사용자가 전달한 실제 센서 로그의 전사본이다. 직접 캡처/인증된 MQTT
덤프는 아니며 75행, 시각 정보 없음. `human_eval_inputs/README.md`에 출처가 있다.
`--type sensors` 또는 `--type report`로 다른 입력 종류도 확인할 수 있다.
클라이언트 기본 응답 대기는 600초이며 `--timeout`으로 조정한다.

## 통신과 오류

`struct.Struct('<HH')`: uint16 전체 길이(헤더 4바이트 포함), uint16 MsgId,
이후 Protobuf 본문. 최대 65535바이트. 송신 크기는 `ByteSize()`로 계산하며 타입의
CamelCase 이름을 SNAKE_CASE로 바꿔 MsgId enum에서 조회한다.
0/1/10을 각각 SensorMsg/SensorsMsg/Report로 해석한다. 여러 센서는 ID를 보존하여
함께 분석한다. 요청마다 같은 연결로 Report(10)를 한 번 전송하고 다음 요청을 기다린다.
서버는 자신의 응답을 입력 처리하지 않으며 클라이언트도 응답을 재전송하지 않는다.
**Report에는 요청/응답 구분 필드가 없으므로 상대 서버도 수신 Report를 다시 이
서버로 전달하지 않아야 한다.** 동일 내용의 새 요청과 에코를 wire 형식만으로 구별할 수 없다.

빈 로그/미지원 MsgId/파싱 실패/모델 예외는 `ERROR: ...` Report를 반환하고 연결을
유지한다. 길이 0~3은 연결 종료. TCP 분할/연속 수신을 처리한다. 패킷 사이 EOF는
정상 종료, 헤더/본문 중간 EOF는 TruncatedPacket으로 구별하여 로그에 남긴다.
수신 시간 초과/소켓 오류는 연결 종료한다. 출력은 UTF-8 문자 경계 및 실제
Protobuf 크기를 검사해서 생략 표시와 함께 자른다. 입력은 묵시적으로 자르지 않으며
모델 컨텍스트를 넘으면 ERROR 응답이다. 모델 토큰 한도 도달 시 불완전 표시를 붙인다.

분석 함수는 `LogAnalyzer.analyze_logs(log_text: str) -> str`이며 TCP 코드와 분리돼 있다.
로그는 JSON 데이터로 전달하고 system 지시로 로그 안 명령 무시, 사실/추정 분리,
제공 근거만 사용, 정보 부족 표시 및 네 개 한국어 항목을 요구한다. 이는 모델 지시이며
모든 출력의 정확성/프롬프트 주입 저항성을 보증하지 않는다. 추가로 출력의 숫자 토큰을
원문과 대조하고(항목 번호 1~4 제외), 없는 숫자가 있으면 한 번 재추론한 뒤에도
남아 있으면 ERROR를 반환한다. 날짜/시각/측정값 환각에 대한 보수적 검사이며
새로운 집계값도 거부할 수 있다. 같은 숫자로 잘못 서술한 내용이나 숫자 없는
근거 없는 해석을 판별하는 의미 검증기는 아니다.
LocalModel은 동시 추론 안전성이 명시되지 않아 공유 Lock으로 직렬화한다.
최대 클라이언트 수를 넘으면 추가 연결은 닫는다. 종료 시 진행 중 작업 완료를 기다린다.

## 스키마와 파일

기존 프로젝트에서 `.proto`가 발견되지 않아 제공된 enum 전체와 세 메시지를
`protocol.proto`에 추가했다. 다른 메시지의 필드는 제공되지 않았으므로 만들지 않았다.
서버 전체 스키마를 받으면 **전체 정의를 유지하여 병합 후 다시 컴파일**한다.

```bash
.venv/bin/python -m grpc_tools.protoc -I edge_bridge \
  --python_out=edge_bridge edge_bridge/protocol.proto
```

- `protocol.proto`, `protocol_pb2.py`: 스키마, 컴파일 산출물
- `tcp_protocol.py`: 프레이밍/추출/크기 제한
- `log_analyzer.py`: 기존 모델 재사용 및 분석 프롬프트/잠금
- `tcp_server.py`, `tcp_client.py`: 서버와 1회 요청 클라이언트
- `requirements-protobuf.txt`: 새 통신 의존성 및 컴파일러 버전
- `test_tcp.py`: 모델 대역을 사용하는 통신/오류 검사

## 검증

```bash
.venv/bin/python -m unittest edge_bridge.test_tcp -v
```

6개 검사 통과: 리틀 엔디언 헤더/타입별 MsgId, 한글 및 이모지 응답 한도,
바이트 단위 분할/연속 패킷, 정상 EOF와 헤더/본문 중간 EOF, 잘못된 길이,
세 입력 종류, 빈 로그, 미지원 ID, 잘못된 Protobuf, 모델 오류 Report,
응답 재전송 없음, 프롬프트 역할 분리 및 추론 직렬화, 원문에 없는 숫자의 재추론/거부.
실제 모델 검증 결과는 아래에 추가한다.

### 실제 모델 TCP 검증 결과

로컬 캐시 Qwen/Qwen3-4B-Instruct-2507을 NVIDIA A10G에 로드하고
127.0.0.1:19000으로 실제 TCP 요청/응답을 확인했다. 테스트 서버는 검증 후 종료했다.

- 사용자 제공 센서 302 로그에서 그대로 추출한 4행을 SensorMsg로 전송하여
  네 항목의 한국어 분석 Report(10)를 수신했다. 고정 응답이나 에코가 아닌 모델 추론이다.
  입력: `data/tcp-real-sample.txt`, 수신 본문: `data/tcp-real-analysis.txt`.
- 75행 전체 로그에서는 모델이 원문에 없는 숫자를 생성했다. 검사 추가 후에는
  1회 재추론에도 근거 검사를 통과하지 못하여 `ERROR: RuntimeError: model produced
  numeric claims absent from source logs`를 Report로 반환했다.
  기록: `data/tcp-full-log-error.txt`.
- 최초 검사 전 출력에는 원문에 없는 날짜/시각이 있었다. 이 출력은 채택하지 않고
  `data/tcp-real-analysis-rejected.txt`로 보존했다.
- 짧은 입력의 반환 결과도 MQ7 값 23이 포함된 원문을 "22로 일관"이라고 서술하고,
  임계값 없이 "정상 범위"라고 표현하는 등 의미상 오류가 있었다. 숫자 검사는 이러한
  오류를 잡지 못한다. 실제 추론과 통신은 검증됐지만 분석 정확성은 검증 완료가 아니며,
  기존 Judge/작업자 검토를 붙이지 않은 이 응답을 검증된 판정으로 사용해서는 안 된다.
- 최종 단위 검사 6개 통과, Python compileall 통과, pip check 의존성 충돌 없음.
