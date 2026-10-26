# Vision4 발표용 대시보드

기존 Protobuf 수신 저장소와 Qwen 한국어 보고서 생성 대기열을 읽는 별도 UI이다. 기존 Streamlit, 모델, MQTT/.NET/MariaDB 시스템, Protobuf 계약을 변경하지 않는다.

## 데이터 계약

- `edge_bridge/data/tcp-reports.sqlite3`의 `sensor_records`, `reports`, `report_batches`를 사용한다.
- Sensor 302는 JSON의 `flame_detected`, `fire_alarm`, `danger_signal`, `alarm_level`, `temperature_c`, `humidity_pct`, `mq2`, `mq7`을 사용한다. 불꽃 감지와 화재 경보는 따로 표시한다.
- Sensor 305는 확인된 `SensorMsg.msg` 형식 `305|2|RealSensor/305|0`의 마지막 값을 사용한다. `0=정상(OK)`, `1=불량(NG)`이며 화재 경보로 해석하지 않는다.
- 최근 수신이 120초를 넘으면 현재 상태를 `데이터 없음`으로 표시한다. 과거 판정은 이력으로 보존한다.
- 보고서 업무 상태와 자동 검사 결과를 분리한다. `REVIEWED`는 검토자, 검토 시각, 메모가 모두 있는 기존 기록만 인정한다. 작업자의 유지 선택은 검사 결과나 업무 상태를 바꾸지 않는다.
- Granite 단계는 사용하거나 표시하지 않는다. 흐름은 데이터 수신 → 생성 대기 → 기존 한국어 어댑터 Qwen 생성 → 기존 자동 검사 → 저장·작업자 검토이다.

## 실행

```bash
systemctl --user status vision4-dashboard.service
systemctl --user status vision4-dashboard-tunnel.service
```

로컬 주소는 `http://127.0.0.1:8600`이다. 별도 Cloudflare Quick Tunnel 주소는 `output/project-report-viewer/vision4-tunnel.log`에 기록된다.

## 테스트

```bash
.venv/bin/python -m unittest vision4_dashboard.test_dashboard vision4_dashboard.test_browser -v
```

브라우저 테스트는 격리된 임시 DB를 사용하므로 실제 최근 100개 작업을 생성하지 않는다.
