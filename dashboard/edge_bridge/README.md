# Jetson 이벤트 수신 프로토타입

Python 표준 라이브러리로 동작합니다. `/health`는 상태 확인, `/events`는 Bearer 인증이 필요한 이벤트 수신입니다. 이벤트는 `data/events.sqlite3`에 저장하고 장비 ID·이벤트 ID로 중복을 처리합니다. 동일 ID의 다른 내용은 409로 거부합니다.

## EC2 실행

```bash
cd /home/ubuntu/models
.venv/bin/python -u edge_bridge/server.py
```

별도 터미널에서:

```bash
edge_bridge/bin/cloudflared tunnel --url http://127.0.0.1:8000
```

출력되는 `https://...trycloudflare.com`이 Jetson의 전송 주소입니다. 서버와 터널 프로세스가 모두 실행 중이어야 합니다. 재시작 시 임시 주소가 변경될 수 있습니다.

## Jetson 실행

`send_event.py`, `example_event.json`을 Jetson으로 복사하고, EC2의 `data/api_token` 내용을 별도 안전한 경로로 전달해 Jetson의 `api_token` 파일에 저장합니다. 토큰은 로그나 저장소에 올리지 않습니다.

```bash
chmod 600 api_token
python3 send_event.py --url https://YOUR-URL.trycloudflare.com --token-file api_token --event-file example_event.json
```

이 예시는 합성 이벤트입니다. 실제 탐지 코드에서 사건 ID를 생성·보존하고 같은 사건의 재시도에는 같은 ID를 사용합니다. 신뢰도가 없는 탐지 결과는 confidence를 생략하거나 null로 보냅니다. 네트워크 장기 장애에 대응하는 디스크 전송 큐는 아직 구현하지 않았습니다.

현재 범위는 이벤트 수신·저장까지입니다. Unity 결합, LLM 보고서 생성, judge 평가는 아직 연결하지 않았습니다. 개발용 서버이며 운영 배포 전 요청 제한, 프로세스 관리 및 인증 관리를 보완해야 합니다.
