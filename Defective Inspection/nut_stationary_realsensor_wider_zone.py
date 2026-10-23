#!/usr/bin/env python3

# -*- coding: utf-8 -*-

"""HCAM0 정지형 너트 검사: 기존 화재감지·모터 프로그램과 별도로 실행한다.



팀원의 jetson_fire_mqtt_hcam_bridge.py는 LifeCam, 화재/연기 YOLO,

Arduino 광전센서 STOP/CLEAR, 모터 GPIO를 전담한다.

이 파일은 화재감지 모듈·GPIO·모터·시리얼 포트를 제어하지 않는다.

기존 모터 프로그램의 인증된 localhost 검사 연동 API만 사용하고,

너트 검사 결과는 별도의 MQTT 클라이언트로 송신한다.



새로운 센서 정지 회차가 발생하고 모터 출력 OFF 상태가 유지되면,

HCAM0로 3프레임을 촬영하여 Heat 검정 픽셀 비율 중앙값을 판정한다.

기본 판정 임계값은 0.168이며 검사 완료를 같은 센서 회차에 통보한다.

모터 출력 OFF는 실제 벨트 완전 정지를 증명하지 않는다.

실제 장비 시험 시 안전 커버와 독립적인 비상정지 장치가 필요하다.

"""

from __future__ import annotations



import argparse

import csv

import json

import sqlite3

from contextlib import contextmanager

import urllib.request

import urllib.error

import secrets

import stat

import queue

import re

import subprocess

import threading

import time

from datetime import datetime

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from pathlib import Path

from urllib.parse import parse_qs, urlparse



import cv2

import numpy as np



# MQTT 장애 또는 paho-mqtt 미설치가 너트 검사와 모터 완료 통보를 막지 않도록 분리한다.

try:

    import paho.mqtt.client as mqtt

    MQTT_IMPORT_ERROR = None

except ImportError as exc:

    mqtt = None

    MQTT_IMPORT_ERROR = str(exc)



BASE = Path(__file__).resolve().parent

WIDTH, HEIGHT, FPS, ROI_SIZE = 1280, 720, 30, 400

DIFF_THRESHOLD = 45

AREA_MIN, AREA_MAX = 5000, 55000

RATIO_MIN, RATIO_MAX = 0.50, 1.80

SOLIDITY_MIN = 0.45

CX, CY = WIDTH // 2, HEIGHT // 2

ZONE_X, ZONE_Y = 180, 130

SETTLE_SECONDS = 0.35

MAX_CENTER_DRIFT = 12.0

CAPTURE_INTERVAL = 0.15

CAPTURE_TIMEOUT = 8.0

DARK_PIXEL_CUTOFF = 60

DEFAULT_HEAT_THRESHOLD = 0.168



state_lock = threading.Lock()

image_lock = threading.Lock()

shutdown = threading.Event()

commands = queue.Queue(maxsize=1)

latest_jpg = None

status = {"phase": "BOOT", "message": "카메라 준비 중", "captures": 0,

          "background_registered": False, "mode": "SENSOR_STOP_ONLY"}





def set_status(**kwargs):

    with state_lock:

        status.update(kwargs)





def get_status():

    with state_lock:

        return dict(status)





# 화재감지용 LifeCam을 절대 대체 카메라로 사용하지 않고 HCAM0만 식별한다.

def hcam_capture_nodes():

    by_group = set()

    try:

        result = subprocess.run(['v4l2-ctl', '--list-devices'], capture_output=True,

                                text=True, timeout=4, check=False)

        group = ''

        for line in result.stdout.splitlines():

            if not line.strip():

                continue

            if not line[0].isspace():

                group = line.strip()

            elif 'hcam0' in group.lower():

                match = re.search(r'/dev/video\d+', line)

                if match:

                    by_group.add(match.group())

    except (OSError, subprocess.TimeoutExpired):

        pass

    result = []

    for node in sorted(Path('/dev').glob('video[0-9]*'),

                       key=lambda p: int(p.name[5:])):

        name_path = Path('/sys/class/video4linux') / node.name / 'name'

        index_path = Path('/sys/class/video4linux') / node.name / 'index'

        try:

            name = name_path.read_text(encoding='utf-8', errors='replace').strip()

        except OSError:

            name = ''

        if 'hcam0' not in name.lower() and str(node) not in by_group:

            continue

        try:

            if index_path.exists() and int(index_path.read_text().strip()) != 0:

                print(f'[CAMERA] HCAM0 보조/메타데이터 노드 제외: {node}', flush=True)

                continue

        except (OSError, ValueError):

            pass

        result.append((str(node), name or 'HCAM0'))

    return result





class Camera:

    def __init__(self, cap, device, native_size, fmt, fps, allow_resize):

        self.cap = cap

        self.device = device

        self.native_size = native_size

        self.format = fmt

        self.fps = fps

        self.normalized = native_size != (WIDTH, HEIGHT)

        self.allow_resize = allow_resize



    def read(self):

        # MJPEG 프레임 수신이 일시적으로 실패할 수 있으므로 실패·빈 프레임은 제외한다.

        for _ in range(3):

            ok, frame = self.cap.read()

            if not ok or frame is None or not frame.size:

                continue

            if frame.shape[:2] == (HEIGHT, WIDTH):

                return True, frame

            if not self.allow_resize:

                return False, None

            h, w = frame.shape[:2]

            scale = min(WIDTH / w, HEIGHT / h)

            sw, sh = round(w * scale), round(h * scale)

            resized = cv2.resize(frame, (sw, sh))

            canvas = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

            x0, y0 = (WIDTH - sw) // 2, (HEIGHT - sh) // 2

            canvas[y0:y0 + sh, x0:x0 + sw] = resized

            return True, canvas

        return False, None



    def release(self):

        self.cap.release()





def open_camera(selection, allow_resize=False):

    found = hcam_capture_nodes()

    if selection != 'auto':

        name = f'/dev/video{selection}'

        found = [x for x in found if x[0] == name]

    if not found:

        raise RuntimeError('HCAM0 영상 노드를 찾지 못했습니다. v4l2-ctl --list-devices 확인. LifeCam 대체 금지.')

    # HCAM0의 index 0은 영상 노드이고 index 1은 메타데이터 노드라 제외한다.

    device, name = found[0]

    print(f'[CAMERA] HCAM0 전용 노드: {device} ({name})', flush=True)

    modes = [('MJPG', 1280, 720, 30)]

    if allow_resize:

        modes += [('MJPG', 640, 480, 30), ('YUYV', 640, 480, 22),

                  ('MJPG', 480, 320, 30), ('YUYV', 320, 240, 30)]

    failures = []

    for fmt, w, h, fps in modes:

        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)

        if not cap.isOpened():

            cap.release()

            raise RuntimeError(f'{device} 열기 실패. 카메라 점유/USB 확인.')

        success = False

        try:

            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fmt))

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)

            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)

            cap.set(cv2.CAP_PROP_FPS, fps)

            print(f'[CAMERA] 시도: {device} {fmt} {w}x{h}@{fps}', flush=True)

            for _ in range(5):

                ok, frame = cap.read()

                if ok and frame is not None and frame.size:

                    real_h, real_w = frame.shape[:2]

                    if (real_w, real_h) != (w, h):

                        failures.append(f'{fmt} {w}x{h} 요청, 실제 {real_w}x{real_h}')

                        break

                    print(f'[CAMERA OK] {device} | 실제 {fmt} {real_w}x{real_h}', flush=True)

                    if (real_w, real_h) != (WIDTH, HEIGHT):

                        print('[CAMERA WARN] 리사이즈 모드: 이번 데이터는 1280x720 기준과 별도 보정 필요!', flush=True)

                    success = True

                    return Camera(cap, device, (real_w, real_h), fmt, fps, allow_resize)

                time.sleep(.15)

            failures.append(f'{fmt} {w}x{h}: 프레임 수신 실패')

        finally:

            if not success:

                cap.release()

    raise RuntimeError('HCAM0 영상 수신 실패: ' + '; '.join(failures))





def detect_nut(frame, background):

    delta = cv2.absdiff(background, frame)

    diff = cv2.cvtColor(delta, cv2.COLOR_BGR2GRAY)

    diff = cv2.GaussianBlur(diff, (7, 7), 0)

    _, mask = cv2.threshold(diff, DIFF_THRESHOLD, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    valid = []

    for contour in contours:

        area = cv2.contourArea(contour)

        if not AREA_MIN <= area <= AREA_MAX:

            continue

        x, y, w, h = cv2.boundingRect(contour)

        if h <= 0 or not RATIO_MIN <= w/h <= RATIO_MAX:

            continue

        hull_area = cv2.contourArea(cv2.convexHull(contour))

        if hull_area <= 0 or area/hull_area < SOLIDITY_MIN:

            continue

        center = (x+w//2, y+h//2)

        valid.append((abs(center[0]-CX) + abs(center[1]-CY), center, (x,y,w,h), contour, area))

    if not valid:

        return None

    _, (cx,cy), bbox, contour, area = min(valid, key=lambda x:x[0])

    dx, dy = cx-CX, cy-CY

    if abs(dx) > ZONE_X or abs(dy) > ZONE_Y:

        return {"in_zone":False,"center":(cx,cy),"bbox":bbox}

    x1 = max(0, min(cx-ROI_SIZE//2, WIDTH-ROI_SIZE))

    y1 = max(0, min(cy-ROI_SIZE//2, HEIGHT-ROI_SIZE))

    roi = frame[y1:y1+ROI_SIZE,x1:x1+ROI_SIZE].copy()

    if roi.shape[:2] != (ROI_SIZE,ROI_SIZE):

        return None

    fullmask = np.zeros_like(mask)

    cv2.drawContours(fullmask,[contour],-1,255,thickness=-1)

    surface_mask = cv2.bitwise_and(mask, fullmask)[y1:y1+ROI_SIZE,x1:x1+ROI_SIZE].copy()

    sharpness = float(cv2.Laplacian(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.CV_64F).var())

    return {"in_zone":True,"center":(cx,cy),"bbox":bbox,"roi":roi,

            "mask":surface_mask,"sharpness":sharpness,"area":float(area),"dx":dx,"dy":dy}





def draw(frame, det):

    """검사 영상과 분리된 표시용 프레임에만 안내선을 그린다."""

    display = frame.copy()

    cv2.rectangle(display, (CX-ZONE_X, CY-ZONE_Y),

                  (CX+ZONE_X, CY+ZONE_Y), (0, 255, 255), 2)

    cv2.circle(display, (CX, CY), 6, (255, 255, 255), 2)

    if det is not None:

        x, y, w, h = det['bbox']

        in_zone = det['in_zone']

        color = (0, 255, 0) if in_zone else (0, 165, 255)

        cv2.rectangle(display, (x, y), (x+w, y+h), color, 2)

        cv2.circle(display, det['center'], 4, (0, 0, 255), -1)

    current = get_status()

    info = (f"{current.get('phase', 'WAIT')} / "

            f"INSPECTED={current.get('captures', 0)} / "

            f"ARMED={int(bool(current.get('armed', False)))}")

    cv2.putText(display, info, (20, 38), cv2.FONT_HERSHEY_SIMPLEX,

                0.65, (255, 255, 255), 2)

    return display





def stationary_capture(camera, background, count=3, timeout=CAPTURE_TIMEOUT):

    """확인된 광전센서 정지 회차에서만 호출되는 3프레임 안정 촬영 함수."""

    start = time.monotonic()

    samples = []

    anchor = None

    stable_start = None

    next_sample = 0.0

    stats = {"no_detection":0,"outside_zone":0,"drift_reset":0,"collected_max":0}

    while time.monotonic()-start < timeout:

        ok, frame = camera.read()

        if not ok:

            raise RuntimeError('카메라 프레임 수신 실패 (HCAM0 USB/MJPEG 확인)')

        det = detect_nut(frame, background)

        now = time.monotonic()

        if det is None:

            stats['no_detection'] += 1

            samples, anchor, stable_start = [],None,None

            continue

        if not det['in_zone']:

            stats['outside_zone'] += 1

            samples,anchor,stable_start = [],None,None

            continue

        center = det['center']

        if anchor is None or np.hypot(center[0]-anchor[0],center[1]-anchor[1]) > MAX_CENTER_DRIFT:

            stats['drift_reset'] += int(anchor is not None)

            samples = []

            anchor = center

            stable_start = now

            next_sample = now + SETTLE_SECONDS

            continue

        if now < next_sample or now-stable_start < SETTLE_SECONDS:

            continue

        if samples and np.hypot(center[0]-samples[0]['center'][0],

                                center[1]-samples[0]['center'][1]) > MAX_CENTER_DRIFT:

            stats['drift_reset'] += 1

            samples=[]

            anchor=center

            stable_start=now

            next_sample=now+SETTLE_SECONDS

            continue

        samples.append(det)

        stats['collected_max'] = max(stats['collected_max'],len(samples))

        next_sample = now + CAPTURE_INTERVAL

        if len(samples) >= count:

            return samples

    raise RuntimeError(f'{timeout:.0f}초 안에 {count}프레임 수집 실패: {stats}. '

                       '너트를 중앙에 고정하고 암막 상자 문을 닫은 뒤 촬영하세요.')





def heat_score_one(sample):

    # 기존 Heat 단독 검사와 동일하게 마스크 안에서 회색조 60 미만 픽셀 비율을 계산한다.

    valid = sample['mask']>0

    if int(np.count_nonzero(valid)) < 100:

        valid = np.ones(sample['roi'].shape[:2],dtype=bool)

    gray = cv2.cvtColor(sample['roi'],cv2.COLOR_BGR2GRAY)

    return float(np.mean(gray[valid] < DARK_PIXEL_CUTOFF))



FRAME_COLUMNS = ['object_id','object_index','physical_id','dataset_split','actual_label',

                 'defect_type','frame_idx','timestamp','center_x','center_y','dx','dy',

                 'sharpness','area','dark_ratio_60','roi_path','mask_path','capture_mode']

OBJECT_COLUMNS = ['object_id','object_index','timestamp','physical_id','dataset_split',

                  'actual_label','defect_type','frame_count','heat_score','heat_threshold',

                  'heat_ng','predicted_label','decision_reason','processing_sec','capture_mode']











# 정지형 너트는 SensorID 305, 이동형 너트는 SensorID 304를 사용한다.

# Type 2는 유지하며 화재감지 bridge 방식(등록, 토픽, 결과 포맷)을 기본 사용한다.

# 정상(OK): 305|2|RealSensor/305|0

# 불량(NG): 305|2|RealSensor/305|1

# 기본 발행 토픽은 RealSensor/305이고, 등록 토픽은 factory/register이다.

# 등록 payload는 같은 형식의 끝값 0으로 전송하되, 등록 성공 여부는 서버에서 확인한다.

# 이는 프로젝트에서 사용한 응용 프로토콜이며 MQTT 표준 payload 형식은 아니다.

# MQTT 결과 통신은 팀원의 화재감지·모터 GPIO 제어와 독립적이다.

class NutMqttOutbox:

    """검사 결과를 SQLite에 먼저 저장하고 MQTT QoS 1로 전송한다.



    PUBACK는 MQTT 브로커 수신 확인이며 공장 응용 서버의 처리 완료 확인은 아니다.

    통신이 불확실하면 재전송할 수 있으므로 수신 측에서는 중복 제거가 필요하다.

    """



    def __init__(self, broker, port, topic, register_topic, sensor_id, sensor_type,

                 client_id, db_path, enabled=True, mqtt_format="bridge", mqtt_period=3.0):

        self.enabled = bool(enabled)

        self.broker = broker

        self.port = int(port)

        self.topic = topic

        self.register_topic = register_topic

        self.sensor_id = int(sensor_id)

        self.sensor_type = int(sensor_type)

        self.client_id = client_id

        self.db_path = Path(db_path)

        self.mqtt_format = mqtt_format

        self.mqtt_period = float(mqtt_period)

        self.registration_info = None

        self.last_confirmed_value = None  # 검사 결과가 하나도 없으면 정상(0)을 임의 전송하지 않음

        self.last_periodic_at = time.monotonic()

        self.lock = threading.RLock()

        self.stop_event = threading.Event()

        self.wake = threading.Event()

        self.connected = threading.Event()

        self.registered = threading.Event()

        self.client = None

        self.worker = None

        if not self.enabled:

            set_status(mqtt_enabled=False, mqtt_connected=False, mqtt_pending=0)

            print('[NUT MQTT] disabled by --no-mqtt', flush=True)

            return

        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with self.lock, self._db() as con:

            con.execute('''CREATE TABLE IF NOT EXISTS mqtt_outbox (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                cycle_id TEXT NOT NULL UNIQUE,

                topic TEXT NOT NULL,

                payload TEXT NOT NULL,

                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP

            )''')

        # 구버전 대기 결과도 회차를 유지하면서 현재 통신 형식으로 변환한다.

        # 다른 SensorID의 결과는 변환하지 않는다.

        with self.lock, self._db() as con:

            queued = con.execute('SELECT id,topic,payload,created_at FROM mqtt_outbox').fetchall()

            for row_id, old_topic, old_payload, created in queued:

                if not old_payload.startswith(f'{self.sensor_id}|'):

                    continue

                try:

                    if '|{"result":' in old_payload:

                        value = int(json.loads(old_payload.split('|', 2)[1])['result'])

                    else:

                        value = int(old_payload.rsplit('|', 1)[-1])

                except (ValueError, TypeError, KeyError, json.JSONDecodeError):

                    continue

                if value not in (0, 1):

                    continue

                new_payload = self._result_payload(value, str(created))

                if old_topic != self.topic or old_payload != new_payload:

                    con.execute('UPDATE mqtt_outbox SET topic=?,payload=? WHERE id=?',

                                (self.topic, new_payload, row_id))

        set_status(mqtt_enabled=True, mqtt_connected=False,

                   mqtt_pending=self.pending_count(), mqtt_topic=self.topic,

                   mqtt_broker=f'{broker}:{port}', mqtt_format=self.mqtt_format)

        if mqtt is None:

            print(f'[NUT MQTT WARN] paho-mqtt 미설치: {MQTT_IMPORT_ERROR}. '

                  '결과는 SQLite에 보관되며 너트 검사와 모터 제어는 계속됩니다.', flush=True)

            set_status(mqtt_error='paho-mqtt 미설치: '+str(MQTT_IMPORT_ERROR))

            return

        try:

            try:

                self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,

                                          client_id=client_id)

            except (AttributeError, TypeError):

                self.client = mqtt.Client(client_id=client_id)

            self.client.on_connect = self._on_connect

            self.client.on_disconnect = self._on_disconnect

            self.client.reconnect_delay_set(min_delay=1, max_delay=30)

            self.client.connect_async(self.broker, self.port, keepalive=60)

            rc = self.client.loop_start()

            if rc != mqtt.MQTT_ERR_SUCCESS:

                raise RuntimeError(f"MQTT loop_start 실패 rc={rc}")

            self.worker = threading.Thread(target=self._sender,

                                           name='nut-mqtt-outbox', daemon=True)

            self.worker.start()

            print(f'[NUT MQTT] start: {broker}:{port} | topic={topic} | '

                  f'SensorID={sensor_id} Type={sensor_type} | QoS=1', flush=True)

        except Exception as exc:

            set_status(mqtt_error=str(exc))

            print(f'[NUT MQTT WARN] 연결 초기화 실패: {exc}. 저장 큐 유지; 모터 독립.',

                  flush=True)



    def _result_payload(self, value, timestamp=None):

        if self.mqtt_format == "bridge":

            dt = timestamp or datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            return f'{self.sensor_id}|{{"result": {value}}}|{dt}'

        # legacy 모드: 사용자가 지정한 공장 서버용 문자열 형태를 그대로 사용한다.

        return (f'{self.sensor_id}|{self.sensor_type}|'

                f'RealSensor/{self.sensor_id}|{value}')



    def _registration_payload(self):

        if self.mqtt_format == "bridge":

            return f'{self.sensor_id}|{self.sensor_type}|0'

        return (f'{self.sensor_id}|{self.sensor_type}|'

                f'RealSensor/{self.sensor_id}|0')



    @contextmanager

    def _db(self):

        con = sqlite3.connect(str(self.db_path), timeout=10.0)

        try:

            with con:

                yield con

        finally:

            con.close()



    def pending_count(self):

        if not self.enabled:

            return 0

        with self.lock, self._db() as con:

            return int(con.execute('SELECT COUNT(*) FROM mqtt_outbox').fetchone()[0])



    def enqueue(self, cycle_id, record):

        """모터 완료 ACK와 무관하게 센서 정지 회차당 검사 결과 한 건을 등록한다."""

        if not self.enabled:

            return

        value = 0 if record['predicted_label'] == 'OK' else 1

        payload = self._result_payload(value)

        with self.lock, self._db() as con:

            cur = con.execute(

                'INSERT OR IGNORE INTO mqtt_outbox(cycle_id, topic, payload) '

                'VALUES(?,?,?)', (cycle_id, self.topic, payload))

            added = cur.rowcount == 1

        set_status(mqtt_pending=self.pending_count(),

                   mqtt_last_queued=payload, mqtt_last_cycle=cycle_id)

        if added:

            print(f'[NUT MQTT QUEUED] {record["object_id"]} => {payload} '

                  f'pending={self.pending_count()}', flush=True)

        else:

            print(f'[NUT MQTT] 동일 센서 회차 중복 전송 방지: {cycle_id}', flush=True)

        self.wake.set()



    def _on_connect(self, client, userdata, flags, reason_code, properties=None):

        try:

            ok = int(reason_code) == 0

        except (TypeError, ValueError):

            ok = reason_code == 0

        if not ok:

            self.connected.clear()

            self.registered.clear()

            set_status(mqtt_connected=False, mqtt_error=f'connect: {reason_code}')

            print(f'[NUT MQTT WARN] 브로커 연결 실패: {reason_code}', flush=True)

            return

        self.connected.set()

        set_status(mqtt_connected=True, mqtt_error=None)

        print('[NUT MQTT CONNECTED]', self.broker, self.port, flush=True)

        # 선택된 MQTT 모드의 센서 등록 문자열을 생성한다.

        registration = self._registration_payload()

        try:

            info = client.publish(self.register_topic, registration, qos=1, retain=False)

            if info.rc != mqtt.MQTT_ERR_SUCCESS:

                print(f'[NUT MQTT WARN] 등록 발행 실패 rc={info.rc}', flush=True)

                return

            # publish() 반환 성공은 전송 요청만 의미함. PUBACK는 송신 스레드에서 확인.

            self.registration_info = info

            self.wake.set()

            print(f'[NUT MQTT REGISTER REQUEST] {self.register_topic} : {registration}', flush=True)

        except Exception as exc:

            print('[NUT MQTT WARN] registration:', exc, flush=True)



    def _on_disconnect(self, client, userdata, *args):

        # Paho v2의 인자는 (disconnect_flags, reason_code, properties),

        # v1은 (rc,)다. 연결 종료 이유를 로그에 남겨 클라이언트 ID 중복 등과 구분한다.

        reason = args[1] if len(args) >= 2 else (args[0] if args else 'unknown')

        self.connected.clear()

        self.registered.clear()

        self.registration_info = None

        set_status(mqtt_connected=False, mqtt_disconnect_reason=str(reason), mqtt_error=f"disconnect: {reason}")

        if not self.stop_event.is_set():

            print(f'[NUT MQTT DISCONNECTED] reason={reason}; 미전송 결과 보관 후 재연결 대기', flush=True)



    def _sender(self):

        """등록 PUBACK 이후 결과를 전송하고, 판정이 있으면 3초마다 최신 상태 송신."""

        while not self.stop_event.is_set():

            if not self.connected.is_set():

                self.wake.wait(timeout=1.0)

                self.wake.clear()

                continue

            try:

                if not self.registered.is_set():

                    reg = self.registration_info

                    if reg is None:

                        self.wake.wait(timeout=1.0)

                        self.wake.clear()

                        continue

                    reg.wait_for_publish(timeout=5.0)

                    if not reg.is_published():

                        print('[NUT MQTT WARN] 등록 PUBACK 대기 중. 결과 전송 보류', flush=True)

                        self.stop_event.wait(2.0)

                        continue

                    self.registered.set()

                    set_status(mqtt_registered_broker=True)

                    print('[NUT MQTT REGISTER PUBACK] 브로커 등록 메시지 수신 확인 (서버 등록 승인과 별개)', flush=True)



                with self.lock, self._db() as con:

                    row = con.execute('SELECT id,topic,payload FROM mqtt_outbox '

                                      'ORDER BY id ASC LIMIT 1').fetchone()

                if row is not None:

                    row_id, topic, payload = row

                    send_type = 'RESULT'

                elif self.last_confirmed_value is not None and (time.monotonic() - self.last_periodic_at) >= self.mqtt_period:

                    row_id = None

                    topic = self.topic

                    payload = self._result_payload(self.last_confirmed_value)

                    send_type = 'PERIODIC'

                else:

                    self.wake.wait(timeout=0.5)

                    self.wake.clear()

                    continue



                print(f'[NUT MQTT SEND {send_type}] {topic} : {payload}', flush=True)

                info = self.client.publish(topic, payload, qos=1, retain=False)

                if info.rc != mqtt.MQTT_ERR_SUCCESS:

                    print(f'[NUT MQTT WARN] publish rc={info.rc}; 전송 실패, 결과 큐 보존', flush=True)

                    self.stop_event.wait(2.0)

                    continue

                info.wait_for_publish(timeout=8.0)

                if not info.is_published():

                    print('[NUT MQTT WARN] PUBACK timeout; 브로커 수신 미확인', flush=True)

                    self.stop_event.wait(2.0)

                    continue

                if not self.connected.is_set():

                    continue

                if row_id is not None:

                    with self.lock, self._db() as con:

                        con.execute('DELETE FROM mqtt_outbox WHERE id=?', (row_id,))

                try:

                    self.last_confirmed_value = int(json.loads(payload.split('|', 2)[1])['result']) if self.mqtt_format == 'bridge' else int(payload.rsplit('|', 1)[-1])

                except (ValueError, KeyError, json.JSONDecodeError):

                    pass

                self.last_periodic_at = time.monotonic()

                set_status(mqtt_pending=self.pending_count(), mqtt_last_sent=payload,

                           mqtt_last_sent_at=datetime.now().isoformat(),

                           mqtt_last_send_type=send_type)

                print(f'[NUT MQTT PUBACK {send_type}] {topic} : {payload}', flush=True)

            except Exception as exc:

                set_status(mqtt_error=str(exc))

                print(f'[NUT MQTT WARN] 전송 오류: {exc}; 결과 큐 보존', flush=True)

                self.stop_event.wait(2.0)



    def close(self):

        self.stop_event.set()

        self.wake.set()

        if self.worker is not None:

            self.worker.join(timeout=2.0)

        if self.client is not None:

            try:

                self.client.disconnect()

                self.client.loop_stop()

            except Exception as exc:

                print('[NUT MQTT WARN] 종료:', exc, flush=True)

        if self.enabled:

            print(f'[NUT MQTT] 종료; 미전송 결과 {self.pending_count()}건 SQLite 보관',

                  flush=True)





WEB_TOKEN = secrets.token_urlsafe(32)

BRIDGE_BASE = 'http://127.0.0.1:5000'

BRIDGE_KEY = Path.home() / '.config' / 'jetson_inspection_bridge.key'

BRIDGE_TIMEOUT = 0.7

STOP_SETTLE_SECONDS = 0.6  # 모터 출력 OFF 확인 뒤 안정화 시간. 벨트 회전 속도를 측정하는 엔코더는 없다.

POLL_SECONDS = 0.20





def motor_request(path, payload=None):

    if not BRIDGE_KEY.is_file():

        raise RuntimeError('모터 연동 인증키 파일 없음. 모터 프로그램 먼저 실행하세요.')

    if BRIDGE_KEY.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):

        raise RuntimeError('연동키 권한이 너무 넓습니다 (chmod 600 필요)')

    key = BRIDGE_KEY.read_text(encoding='utf-8').strip()

    if len(key) < 32:

        raise RuntimeError('모터 연동 인증키 길이 오류')

    data = None if payload is None else json.dumps(payload).encode('utf-8')

    req = urllib.request.Request(

        BRIDGE_BASE + path, data=data,

        headers={'X-Inspection-Key': key, 'Content-Type': 'application/json'},

        method='POST' if data is not None else 'GET')

    with urllib.request.urlopen(req, timeout=BRIDGE_TIMEOUT) as response:

        return json.load(response)





def eligible_stopped_cycle(info, consumed):

    if not isinstance(info, dict) or not info.get('ok'):

        return None

    cid = info.get('cycle_id')

    last = info.get('last_completed') or {}

    if (not isinstance(cid, str) or not cid or cid in consumed or

            last.get('cycle_id') == cid or info.get('inspection_bypass') or

            not info.get('sensor_connected') or not info.get('sensor_fresh') or

            not info.get('sensor_stopped') or info.get('motor_active')):

        return None

    return cid





def save_sensor_result(session, samples, threshold, number, cycle_id):

    """카메라 점수와 촬영 이미지를 저장하고 실제 정답 라벨을 임의로 지정하지 않는다."""

    oid = f'OBJ{number:05d}'

    stamp = datetime.now().isoformat(timespec='milliseconds')

    begin = time.perf_counter()

    rows, scores = [], []

    physical_id = f'CY{number:05d}'

    for i, det in enumerate(samples, 1):

        name = f'{oid}_sensor_UNLABELED_F{i:02d}'

        roi_path = session/'roi'/(name+'.png')

        mask_path = session/'mask'/(name+'_mask.png')

        if not cv2.imwrite(str(roi_path), det['roi']):

            raise RuntimeError('ROI 저장 실패: '+str(roi_path))

        if not cv2.imwrite(str(mask_path), det['mask']):

            raise RuntimeError('MASK 저장 실패: '+str(mask_path))

        score = heat_score_one(det)

        scores.append(score)

        rows.append([oid, number, physical_id, 'auto', 'UNLABELED', 'UNKNOWN',

                     i, stamp, det['center'][0], det['center'][1],

                     det['dx'], det['dy'], f"{det['sharpness']:.4f}",

                     f"{det['area']:.1f}", f'{score:.8f}', str(roi_path),

                     str(mask_path), 'auto'])

    med = float(np.median(scores))

    ng = med >= threshold

    record = dict(object_id=oid, object_index=number, timestamp=stamp,

                  physical_id=physical_id, dataset_split='auto',

                  actual_label='UNLABELED', defect_type='UNKNOWN',

                  frame_count=len(samples), heat_score=med,

                  heat_threshold=threshold, heat_ng=bool(ng),

                  predicted_label='NG' if ng else 'OK',

                  decision_reason='DARK_RATIO_60' if ng else 'NONE',

                  processing_sec=time.perf_counter()-begin, capture_mode='auto')

    with (session/'frame_scores.csv').open('a', encoding='utf-8-sig', newline='') as f:

        csv.writer(f).writerows(rows)

    with (session/'object_scores.csv').open('a', encoding='utf-8-sig', newline='') as f:

        csv.DictWriter(f, fieldnames=OBJECT_COLUMNS).writerow(record)

    # 기존 CSV 열 구조를 변경하지 않고 센서 정지 회차와 검사 결과를 별도로 기록한다.

    with (session/'sensor_cycles.jsonl').open('a', encoding='utf-8') as f:

        f.write(json.dumps({'cycle_id':cycle_id,'record':record},ensure_ascii=False)+'\n')

    return record





HTML = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8">

<meta name="viewport" content="width=device-width,initial-scale=1">

<title>정지 금속 너트 검사</title>

<style>body{background:#141b23;color:#f0f2f8;font:15px system-ui,sans-serif;margin:20px}

main{display:flex;gap:18px;flex-wrap:wrap}img{max-width:100%;width:830px}

section{background:#25303b;padding:18px;max-width:400px;border-radius:10px;flex:1;min-width:290px}

button{padding:12px;width:100%;font:inherit;margin:8px 0;cursor:pointer}

pre{font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}

small{color:#c5d0df}#notice{padding:10px;background:#364756;border-radius:6px}

</style></head><body>

<h2>정지 금속 너트 검사</h2>

<p>광전센서 STOP → 모터 출력 OFF 확인 → 안정화 → HCAM0 3프레임 → Heat 0.168 → 검사 완료 통보 → 조건 충족 시 벨트 재가동</p>

<main><div><img src="/video" alt="HCAM0 영상"></div>

<section><h3>검사 준비</h3>

<small>안전 커버와 물리 비상정지 장치를 확인하세요. 배경 등록은 빈 벨트·LED 켜짐·상자 문 닫힘 상태에서만 합니다.</small>

<button id="background">1. 빈 벨트 배경 등록</button>

<button id="arm">2. 센서 연동 자동검사 시작</button>

<button id="disarm">센서 연동 검사 대기 중지 (모터 정지 명령 아님)</button>

<button id="retry">검사 실패한 정지 회차 다시 시도</button>

<button id="manualRecovery" style="background:#a65a14;color:white">검사 실패 시 모터 수동 재시작 제어 열기</button>

<small>감별 실패만으로 임의의 정상 검사 결과를 생성하지 않습니다. 이 버튼은 화재 감지 프로그램의 기존 모터 제어 화면을 열며, 화재·연기·외부 정지·센서 장애가 있으면 재시작할 수 없습니다. 모터 주변에 사람이 없는지 확인하세요.</small>

<div id="notice">상태 확인 중</div>

<small>검사 실패 시 완료 신호를 보내지 않아 광전센서 정지 잠금이 유지됩니다. 실제 벨트 정지는 GPIO 상태만으로 확인할 수 없으며 별도 0.6초 안정화 시간이 적용됩니다.</small>

 <small id="mqttInfo">MQTT 상태 확인 중</small>

<details><summary>전체 상태</summary><pre id="status"></pre></details>

</section></main><script>

const controlToken='__NUT_CONTROL_TOKEN__';

let busy=false;function msg(s){document.getElementById('notice').textContent=s;}

async function cmd(c){if(busy)return;busy=true;try{

const r=await fetch('/command?cmd='+encodeURIComponent(c),{method:'POST',headers:{'X-Nut-Control-Token':controlToken}});

const j=await r.json();msg(j.error||j.message||'접수됨');

}catch(e){msg(String(e));}finally{busy=false;}}

for(const c of ['background','arm','disarm','retry'])

document.getElementById(c).onclick=()=>cmd(c);

document.getElementById('manualRecovery').onclick = async () => {

  const confirmed = confirm('검사가 완료되지 않았습니다. 설비 주변의 사람과 장애물을 확인했습니까?**\n**화재·연기·외부 정지·센서 오류가 있다면 재시작하지 마세요.**\n\n**화재 감지 프로그램의 수동 모터 제어 화면을 여시겠습니까?');

  if (!confirmed) return;

  try {

    const response = await fetch('/recovery-status', {cache:'no-store'});

    const data = await response.json();

    if (!response.ok || !data.ok) {msg('모터 서버 상태 확인 실패: '+(data.error||'알 수 없음')); return;}

    if (data.hazard) {msg('안전 정지 조건 감지: 모터 재시작 제어로 이동하지 않습니다.'); return;}

    const url = window.location.protocol + '//' + window.location.hostname + ':5000/';

    msg('모터 안전 제어 화면을 엽니다. 광전센서 CLEAR 확인 후 기존 정지 해제 버튼을 사용하세요.');

    window.open(url, '_blank', 'noopener,noreferrer');

  } catch(e) {msg('모터 제어 서버 확인 불가: '+String(e));}

};

async function poll(){try{const r=await fetch('/status',{cache:'no-store'});

const s=await r.json();document.getElementById('status').textContent=JSON.stringify(s,null,2);

msg(s.message||s.phase);

 document.getElementById('mqttInfo').textContent =

 '너트 MQTT: ' + (s.mqtt_enabled===false?'사용 안 함':(s.mqtt_connected?'연결':'미연결')) +

 ' / 대기 ' + (s.mqtt_pending??0) + '건 / 마지막 송신 ' + (s.mqtt_last_sent??'-');

 }catch(e){msg('연결 오류: '+e);}setTimeout(poll,700);}poll();

</script></body></html>"""





class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):

        pass



    def send(self, value, mimetype='application/json; charset=utf-8', code=200):

        blob = value.encode('utf-8') if isinstance(value, str) else value

        self.send_response(code)

        self.send_header('Content-Type',mimetype)

        self.send_header('Cache-Control','no-store')

        self.send_header('Content-Length',str(len(blob)))

        self.end_headers()

        self.wfile.write(blob)



    def do_GET(self):

        path=urlparse(self.path).path

        if path=='/':return self.send(HTML.replace('__NUT_CONTROL_TOKEN__',WEB_TOKEN),'text/html; charset=utf-8')

        if path=='/status':return self.send(json.dumps(get_status(),ensure_ascii=False))

        if path=='/recovery-status':

            try:

                with urllib.request.urlopen(BRIDGE_BASE + '/status', timeout=BRIDGE_TIMEOUT) as response:

                    data = json.load(response)

                # Read-only preflight. The fire bridge remains final authority.

                hazard = (data.get('live_detection') in ('FIRE', 'SMOKE', 'ERROR') or

                          data.get('mqtt_report_state') in ('FIRE','SMOKE','ERROR') or

                          data.get('remote_stop_requested') is True or

                          data.get('camera_running') is False)

                return self.send(json.dumps({'ok':True, 'hazard':bool(hazard)}, ensure_ascii=False))

            except Exception as exc:

                return self.send(json.dumps({'ok':False,'error':str(exc)},ensure_ascii=False),code=503)

        if path=='/video':

            self.send_response(200)

            self.send_header('Content-Type','multipart/x-mixed-replace; boundary=frame')

            self.end_headers()

            try:

                while not shutdown.is_set():

                    with image_lock: frame=latest_jpg

                    if frame:

                        self.wfile.write(b'--frame\r\nContent-Type: image/jpeg\r\n')

                        self.wfile.write(('Content-Length: %d\r\n\r\n'%len(frame)).encode())

                        self.wfile.write(frame+b'\r\n')

                    time.sleep(.14)

            except (BrokenPipeError, ConnectionResetError, OSError): pass

            return

        self.send('{"error":"not found"}',code=404)



    def do_POST(self):

        if urlparse(self.path).path!='/command':

            return self.send('{"error":"not found"}',code=404)

        if not secrets.compare_digest(self.headers.get('X-Nut-Control-Token',''), WEB_TOKEN):

            return self.send('{"error":"control token mismatch"}',code=403)

        cmd=parse_qs(urlparse(self.path).query).get('cmd',[''])[0]

        if cmd not in ('background','arm','disarm','retry'):

            return self.send('{"error":"invalid command"}',code=400)

        if get_status().get('phase') in ('CAPTURING','SAVING','NOTIFYING'):

            return self.send('{"error":"currently busy"}',code=409)

        try:commands.put_nowait((cmd,{}))

        except queue.Full:return self.send('{"error":"already queued"}',code=409)

        return self.send('{"queued":true,"message":"명령 접수"}')





def main():

    global latest_jpg

    ap=argparse.ArgumentParser(description='HCAM0 정지형 너트 검사: 기존 모터 프로그램과 독립 실행, MQTT 결과 송신')

    ap.add_argument('--camera-index',default='auto')

    ap.add_argument('--host',default='127.0.0.1')

    ap.add_argument('--port',type=int,default=8001)

    ap.add_argument('--heat-threshold',type=float,default=DEFAULT_HEAT_THRESHOLD)

    ap.add_argument('--stop-settle-seconds',type=float,default=STOP_SETTLE_SECONDS,

                    help='모터 출력 OFF 확인 후 안정화 시간(초), 실제 정지 속도 센서 아님')

    ap.add_argument('--session-root',type=Path,default=BASE/'camera_heat_sensor_sessions')

    # 최근 Type 2 연결 사례와 사용자 지정 결과 payload를 MQTT 기본값으로 한다.

    ap.add_argument('--mqtt-broker',default='3.39.173.120',

                    help='MQTT 브로커 주소(기본값은 프로젝트 외부 IP)')

    ap.add_argument('--mqtt-port',type=int,default=1883)

    ap.add_argument('--mqtt-topic',default='RealSensor/305')

    ap.add_argument('--mqtt-register-topic',default='factory/register')

    ap.add_argument('--mqtt-format',choices=('bridge','legacy'),default='legacy',

                     help='legacy=305|2|RealSensor/305|0/1; bridge=JSON result/시간')

    ap.add_argument('--sensor-id',type=int,default=305)

    ap.add_argument('--sensor-type',type=int,default=2)

    ap.add_argument('--mqtt-client-id',default='nut-heat-stationary-305-type2')

    ap.add_argument('--mqtt-period',type=float,default=3.0, help='판정 완료 후 최신 결과 재발행 간격(초)')

    ap.add_argument('--mqtt-test-result',type=int,choices=(0,1),default=None,

                    help='시험용 OK(0)/NG(1) 메시지를 1건 큐에 추가. 실제 검사 결과로 사용 금지')

    ap.add_argument('--mqtt-outbox',type=Path,default=BASE/'nut_heat_mqtt_outbox_305_type2.sqlite3')

    ap.add_argument('--no-mqtt',action='store_true')



    args=ap.parse_args()

    if not args.no_mqtt and (not args.mqtt_broker.strip() or not args.mqtt_topic.strip()):

        ap.error('MQTT broker and topic cannot be empty; use --no-mqtt to disable')

    if args.camera_index != 'auto' and not re.fullmatch(r'\d+',args.camera_index):

        ap.error('--camera-index must be auto or a numeric HCAM0 index')

    if not 0.5 <= args.mqtt_period <= 3600:

        ap.error('--mqtt-period must be in [0.5,3600]')

    if not np.isfinite(args.heat_threshold) or not 0<=args.heat_threshold<=1:

        ap.error('heat threshold outside [0,1]')

    if not np.isfinite(args.stop_settle_seconds) or args.stop_settle_seconds < 0.3:

        ap.error('--stop-settle-seconds must be >= 0.3')

    args.session_root.mkdir(parents=True,exist_ok=True)

    session=args.session_root/datetime.now().strftime('%Y%m%d_%H%M%S_%f')

    session.mkdir()

    for d in ('roi','mask'): (session/d).mkdir()

    for name,cols in [('frame_scores.csv',FRAME_COLUMNS),('object_scores.csv',OBJECT_COLUMNS)]:

        with (session/name).open('w',encoding='utf-8-sig',newline='') as f:

            csv.writer(f).writerow(cols)

    mqtt_pub = None

    cfg=dict(method='dark_ratio_60_median',threshold=args.heat_threshold,

             frame_count=3,trigger='arduino_stop_via_fire_bridge',

             gpiomotor_stop_settle_s=args.stop_settle_seconds,

             optical_sensor='Arduino STOP/CLEAR',camera='HCAM0',

              resolution=[WIDTH,HEIGHT],roi=ROI_SIZE,mqtt=not args.no_mqtt,

              mqtt_broker=args.mqtt_broker if not args.no_mqtt else None,

              mqtt_topic=args.mqtt_topic if not args.no_mqtt else None,

              mqtt_sensor_id=args.sensor_id if not args.no_mqtt else None,

              mqtt_sensor_type=args.sensor_type if not args.no_mqtt else None,

              mqtt_ok_value=0,mqtt_ng_value=1,



             note='Real physical belt standstill and door closure have no sensor confirmation. '

                  'All automated actual labels are UNLABELED. Threshold provisional.')

    cap=None;web=None

    try:

        try:

            mqtt_pub = NutMqttOutbox(

                args.mqtt_broker, args.mqtt_port, args.mqtt_topic,

                args.mqtt_register_topic, args.sensor_id, args.sensor_type,

                args.mqtt_client_id, args.mqtt_outbox, enabled=not args.no_mqtt,

                mqtt_format=args.mqtt_format, mqtt_period=args.mqtt_period)

            if args.mqtt_test_result is not None:

                test_id = 'MQTT_TEST_' + datetime.now().strftime('%Y%m%d%H%M%S%f')

                mqtt_pub.enqueue(test_id, {'predicted_label': 'OK' if args.mqtt_test_result == 0 else 'NG',

                                           'object_id': test_id})

                print('[MQTT TEST] 시험용 판정 송신 요청, 실제 검사 아님:', args.mqtt_test_result, flush=True)

        except Exception as mqtt_exc:

            print(f'[NUT MQTT ERROR] 초기화 실패: {mqtt_exc}; 검사·모터 연동은 계속', flush=True)

            set_status(mqtt_enabled=False, mqtt_connected=False, mqtt_error=str(mqtt_exc))

            mqtt_pub = None

        cap=open_camera(args.camera_index,allow_resize=False)

        cfg.update(camera_device=cap.device,native_resolution=cap.native_size)

        (session/'run_config.json').write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')

        set_status(phase='WAIT_BACKGROUND',message='먼저 빈 벨트 배경을 등록하세요.',

                   session=str(session),threshold=args.heat_threshold,

                   background_registered=False,armed=False,attempted_cycles=[],

                   captures=0,bridge_state='WAIT',camera_device=cap.device)

        web=ThreadingHTTPServer((args.host,args.port),Handler)

        web.daemon_threads=True

        threading.Thread(target=web.serve_forever,daemon=True).start()

        print(f'[WEB] http://127.0.0.1:{args.port} (host={args.host})',flush=True)

        print('[MODE] SENSOR_STOP_ONLY; no camera-only AUTO. Threshold='+str(args.heat_threshold),flush=True)

        background=None;armed=False;count=0

        consumed=set(); failed_cycles=set()

        pending_id=None;pending_since=None

        ignored_cycle_on_arm=None  # 검사 시작 버튼을 누르기 전에 발생한 기존 STOP 회차를 다시 처리하지 않는다.

        next_poll=0.0

        last_motor_info=None

        while not shutdown.is_set():

            ok,frame=cap.read()

            if not ok:

                raise RuntimeError('HCAM0 프레임 수신 실패: 안전하게 모터를 검사 완료 통보 없이 유지')

            det=detect_nut(frame,background) if background is not None else None

            try:cmd,_=commands.get_nowait()

            except queue.Empty:cmd=None

            if cmd=='background':

                if armed:

                    set_status(message='검사 시작 상태에서는 배경을 다시 등록할 수 없습니다. 대기 중지 후 진행하세요.')

                else:

                    # 빈 벨트 배경 촬영 전에 작업자가 모터 정지를 확인해야 한다.

                    background=frame.copy()

                    saved=cv2.imwrite(str(session/'empty_background.jpg'),background)

                    set_status(phase='READY',background_registered=True,

                               message='배경 등록 완료. 안전 커버·모터 확인 후 자동검사를 시작하세요.',

                               background_saved=bool(saved))

                    print('[BACKGROUND] 빈 벨트 등록 완료',flush=True)

            elif cmd=='arm':

                if background is None:

                    set_status(message='먼저 빈 벨트 배경을 등록하세요.')

                else:

                    try:

                        i=motor_request('/inspection/pending')

                        if not i.get('ok') or not i.get('sensor_connected') or not i.get('sensor_fresh'):

                            raise RuntimeError('Arduino STOP/CLEAR 연결·신호가 준비되지 않았습니다.')

                        # 시작 버튼을 누르기 전 STOP 기록을 새 너트 검사로 오인하지 않는다.

                        ignored_cycle_on_arm=i.get('cycle_id')

                        armed=True

                        set_status(armed=True,phase='READY',

                                   message='센서 자동검사 준비 완료. 다음 새로운 센서 STOP 회차부터 검사',

                                   ignored_pre_arm_cycle=ignored_cycle_on_arm,bridge_state='ONLINE')

                        print('[ARM] 다음 NEW 센서 정지 회차부터 촬영 시작',flush=True)

                    except Exception as exc:

                        set_status(message='자동검사 시작 불가: '+str(exc),bridge_state='OFFLINE')

            elif cmd=='disarm':

                armed=False

                pending_id=None;pending_since=None

                ignored_cycle_on_arm=None

                set_status(armed=False,phase='READY',message='센서 자동검사 대기 중지. 모터는 별도로 제어됩니다.')

                print('[DISARM] 검사 대기 중지; 모터 출력 직접 조작 없음',flush=True)

            elif cmd=='retry':

                if armed and last_motor_info is not None:

                    retry_id=last_motor_info.get('cycle_id')

                    if retry_id in failed_cycles and retry_id not in consumed:

                        failed_cycles.discard(retry_id)

                        set_status(message='실패한 정지 회차 재검사 허용: '+retry_id)

                    else:

                        set_status(message='재검사 가능한 정지 회차가 없습니다.')

                else:

                    set_status(message='센서가 연결되고 자동검사 시작 상태여야 합니다.')

            now=time.monotonic()

            if armed and background is not None and now>=next_poll:

                next_poll=now+POLL_SECONDS

                try:

                    info=motor_request('/inspection/pending')

                    last_motor_info=info

                    set_status(bridge_state='ONLINE',sensor_state=info.get('sensor_state'),

                               motor_output_active=info.get('motor_active'),

                               inspection_cycle_id=info.get('cycle_id'))

                    cid=eligible_stopped_cycle(info,consumed|failed_cycles)

                    if cid == ignored_cycle_on_arm:

                        cid = None

                    if cid!=pending_id:

                        pending_id=cid

                        pending_since=now if cid else None

                    elif cid and pending_since is not None and now-pending_since>=args.stop_settle_seconds:

                        # 검사 직전에 동일한 STOP 회차가 계속 유효한지 다시 확인한다.

                        confirm=motor_request('/inspection/pending')

                        if cid == ignored_cycle_on_arm or eligible_stopped_cycle(confirm,consumed|failed_cycles)!=cid:

                            pending_id=None;pending_since=None

                            continue

                        record=None

                        completion_request_started=False

                        try:

                            set_status(phase='CAPTURING',message='센서 정지 확인 → 너트 중앙·안정화 검사 중...',

                                       current_cycle=cid)

                            print('[SENSOR STOP] '+cid+' → Heat 3프레임 검사',flush=True)

                            samples=stationary_capture(cap,background,count=3)

                            set_status(phase='SAVING',message='이미지/점수 저장 중...')

                            record=save_sensor_result(session,samples,args.heat_threshold,count+1,cid)

                            count+=1

                            print('[HEAT_RESULT]',json.dumps(record,ensure_ascii=False),flush=True)

                            # 검사 회차가 변경되었다면 과거 회차의 결과를 발송하거나 완료 통보하지 않는다.

                            end_info=motor_request('/inspection/pending')

                            if eligible_stopped_cycle(end_info,consumed|failed_cycles)!=cid:

                                raise RuntimeError('검사 중 센서 정지 회차가 변경되어 모터 재가동 불가')

                            # 회차 확인 뒤 SQLite 대기열에 보관한다. 브로커 장애로 모터 ACK를 막지 않는다.

                            if mqtt_pub is not None:

                                try:

                                    mqtt_pub.enqueue(cid, record)

                                except Exception as mq_exc:

                                    print('[NUT MQTT ERROR] 큐 저장 실패 (모터와 독립):',

                                          mq_exc, flush=True)

                                    set_status(mqtt_error='큐 저장 실패: '+str(mq_exc))

                            set_status(phase='NOTIFYING',message='검사 결과 저장 완료, 모터 복귀 승인 요청...')

                            completion_request_started=True

                            ack=motor_request('/inspection/complete',{'cycle_id':cid,'record':record})

                            if not ack.get('ok'):

                                raise RuntimeError('완료 승인 거부: '+str(ack.get('message')))

                            consumed.add(cid)

                            set_status(phase='READY',captures=count,last_result=record,

                                       bridge_state='ACK',message=f'{record["predicted_label"]} / '

                                       f'{record["heat_score"]:.6f} / 검사 완료 승인·운전 재개 허용')

                            print('[HCAM->MOTOR] ACK: '+cid+' / '+record['predicted_label'],flush=True)

                        except Exception as exc:

                            # 모터 서버가 완료를 승인한 뒤 응답만 유실될 수 있다.

                            # 실패로 확정하기 전 서버의 최근 완료 기록을 다시 조회한다.

                            confirmed=False

                            if completion_request_started and record is not None:

                                try:

                                    check=motor_request('/inspection/pending')

                                    completed=check.get('last_completed') or {}

                                    confirmed=(completed.get('cycle_id')==cid and

                                               completed.get('object_id')==record['object_id'])

                                except Exception:

                                    pass

                            if confirmed:

                                consumed.add(cid)

                                set_status(phase='READY',captures=count,last_result=record,

                                           bridge_state='ACK',message='검사 완료 확인. 서버가 모터 재가동을 허용했습니다.')

                                print('[HCAM->MOTOR] 완료 승인 사후 확인: '+cid,flush=True)

                            else:

                                failed_cycles.add(cid)

                                uncertainty=('완료 응답이 끊겨 모터 상태 불확실. 실제 모터 상태를 확인하세요: '

                                             if completion_request_started else

                                             '검사 실패, 완료 신호 미전송. 센서 정지 유지 예상: ')

                                set_status(phase='READY',bridge_state='UNKNOWN_ACK' if completion_request_started else 'FAILED',

                                           message=uncertainty+str(exc))

                                print('[INSPECTION FAILED]',cid,str(exc),flush=True)

                        pending_id=None;pending_since=None

                except (OSError, ValueError, urllib.error.URLError, RuntimeError) as exc:

                    pending_id=None;pending_since=None

                    set_status(bridge_state='OFFLINE',message='모터 연동 연결 오류: '+str(exc))

            disp=draw(frame,det)

            cv2.putText(disp,f'SENSOR STOP ONLY / Heat {args.heat_threshold:.3f}',

                        (20,75),cv2.FONT_HERSHEY_SIMPLEX,.65,(255,255,255),2)

            encoded,buf=cv2.imencode('.jpg',disp,[cv2.IMWRITE_JPEG_QUALITY,75])

            if encoded:

                with image_lock:latest_jpg=buf.tobytes()

    except KeyboardInterrupt:

        print('[EXIT] 사용자 종료',flush=True)

    except Exception as exc:

        set_status(phase='ERROR',message=str(exc),armed=False)

        raise

    finally:

        shutdown.set()

        if mqtt_pub is not None: mqtt_pub.close()

        if cap is not None:cap.release()

        if web is not None:

            web.shutdown();web.server_close()



if __name__=='__main__':

    main()
