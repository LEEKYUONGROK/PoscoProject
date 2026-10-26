import json
import math
import re
from datetime import datetime, timezone

from edge_bridge.report_archive import ReportArchive, DEFAULT_PATH
from edge_bridge.sensor_stream import SensorStream
from edge_bridge.report_batches import ReportBatches

STATUS_LABELS = {'INSPECTION_COMPLETE': '검사 수신', 'REPORT_PENDING': '생성 대기',
                 'REPORT_GENERATED': '생성 완료', 'REPORT_FAILED': '생성 실패',
                 'REVIEW_REQUIRED': '검토 필요', 'REVIEWED': '검토 완료'}
EVENTS = {'302': '화재 감지', '305': '비전 검사', '301': '센서 이벤트'}


def decode(sensor_id, text):
    """Decode actual SensorMsg.msg, keeping sensor-specific semantics separate."""
    body = re.sub(r'^\[sensorID=-?\d+\]\s*', '', text).strip()
    if sensor_id == '305':
        # Position confirmed by the equipment owner: 305|2|RealSensor/305|0.
        parts = body.split('|')
        if len(parts) == 4 and parts[0] == '305' and parts[2] == 'RealSensor/305' and parts[3] in ('0', '1'):
            return {'inspection_result': int(parts[3]), 'source_field': 'SensorMsg.msg[pipe:last]'}
        return {}
    try:
        payload = json.loads(body)
    except ValueError:
        try:
            payload = json.loads(body.split('|')[1]) if sensor_id == '301' else {}
        except (ValueError, IndexError):
            payload = {}
    if not isinstance(payload, dict):
        return {}
    return {k: v for k, v in payload.items() if isinstance(v, (str, int, float, bool, type(None)))
            and (not isinstance(v, float) or math.isfinite(v))}


def sensor_state(sensor_id, text, received_at, current=None, stale_seconds=120):
    current = current or datetime.now(timezone.utc)
    values = decode(sensor_id, text)
    try:
        fresh = (current - datetime.fromisoformat(received_at)).total_seconds() <= stale_seconds
    except (ValueError, TypeError):
        fresh = False
    result = {'sensor_id': sensor_id, 'values': values, 'received_at': received_at,
              'fresh': fresh, 'tone': 'muted', 'label': '데이터 없음', 'event_type': EVENTS.get(sensor_id, '센서 이벤트')}
    if sensor_id == '305':
        value = values.get('inspection_result')
        result['last_result'] = '정상 (OK)' if value == 0 else '불량 (NG)' if value == 1 else '데이터 없음'
        if fresh and value in (0, 1):
            result.update(label=result['last_result'], tone='success' if value == 0 else 'danger')
    elif sensor_id == '302':
        flame = values.get('flame_detected')
        alarm = values.get('fire_alarm')
        result['alarm'] = '활성' if fresh and alarm == 1 else '비활성' if fresh and alarm == 0 else '데이터 없음'
        result['alarm_level'] = {0: '안전 단계', 1: '경고 단계', 2: '위험 단계'}.get(values.get('alarm_level'), '미제공')
        if fresh and flame in (0, 1):
            result.update(label='화재 감지' if flame == 1 else '정상 · 불꽃 미감지', tone='danger' if flame == 1 else 'success')
    elif fresh and values:
        result.update(label='수신 중 · 상태 정의 미등록', tone='info')
    return result


CTE = '''WITH linked AS (
 SELECT report_id,MAX(seq) AS record_seq,MAX(sensor_id) AS sensor_id FROM sensor_records
 WHERE report_id IS NOT NULL GROUP BY report_id
), entries AS (
 SELECT 'report:'||r.id AS key,r.id AS report_id,r.created_at,r.report,r.details_json,r.log_text,
 COALESCE(CAST(json_extract(r.details_json,'$.source_record.sensor_id') AS TEXT),linked.sensor_id,
 CASE WHEN r.log_text LIKE '[sensorID=%' THEN substr(r.log_text,11,instr(r.log_text,']')-11) END) AS sensor_id,
 COALESCE(json_extract(r.details_json,'$.source_record.seq'),linked.record_seq) AS record_seq,
 json_extract(r.details_json,'$.batch_id') AS batch_id,json_extract(r.details_json,'$.batch_position') AS position,
 CASE WHEN r.status='error' OR json_extract(r.details_json,'$.report_status')='REPORT_FAILED' THEN 'REPORT_FAILED'
 ELSE 'REPORT_GENERATED' END AS report_status,
 CASE WHEN json_extract(r.details_json,'$.review_status')='REVIEWED'
 AND json_extract(r.details_json,'$.review_record.reviewer_id') IS NOT NULL
 AND json_extract(r.details_json,'$.review_record.reviewed_at') IS NOT NULL
 AND json_extract(r.details_json,'$.review_record.note') IS NOT NULL THEN 'REVIEWED'
 WHEN json_extract(r.details_json,'$.review_status')='REVIEW_REQUIRED'
 OR json_extract(r.details_json,'$.validation.passed')=0 THEN 'REVIEW_REQUIRED'
 ELSE 'NOT_REVIEWED' END AS review_status,
 'complete' AS queue_state
 FROM reports r LEFT JOIN linked ON linked.report_id=r.id
 UNION ALL
 SELECT 'batch:'||i.batch_id||':'||i.position,NULL,b.created_at,NULL,'{}',s.log_text,s.sensor_id,s.seq,
 i.batch_id,i.position,'REPORT_PENDING','NOT_REVIEWED',i.state
 FROM report_batch_items i JOIN report_batches b ON b.id=i.batch_id
 JOIN sensor_records s ON s.seq=i.record_seq WHERE i.report_id IS NULL
 UNION ALL
 SELECT 'live:'||s.seq,NULL,s.received_at,NULL,'{}',s.log_text,s.sensor_id,s.seq,NULL,NULL,
 'REPORT_PENDING','NOT_REVIEWED',s.state FROM sensor_records s WHERE s.state='running'
), normalized AS (
 SELECT *, CASE WHEN report_status='REPORT_FAILED' THEN 'REPORT_FAILED'
 WHEN review_status='REVIEWED' THEN 'REVIEWED'
 WHEN review_status='REVIEW_REQUIRED' THEN 'REVIEW_REQUIRED'
 ELSE report_status END AS status,
 CASE sensor_id WHEN '302' THEN 'fire' WHEN '305' THEN 'vision' ELSE 'other' END AS event_type
 FROM entries
) '''


class Dashboard:
    def __init__(self, path=DEFAULT_PATH):
        self.archive = ReportArchive(path)
        self.stream = SensorStream(self.archive)
        self.batches = ReportBatches(self.stream)

    def reports(self, filters):
        clauses, args = [], []
        for param, column in (('sensor', 'sensor_id'), ('status', 'status'), ('event', 'event_type'), ('batch', 'batch_id')):
            if filters.get(param):
                clauses.append(column + '=?'); args.append(filters[param])
        for param, op, suffix in (('from', '>=', 'T00:00:00'), ('to', '<=', 'T23:59:59.999999+00:00')):
            if filters.get(param):
                datetime.strptime(filters[param], '%Y-%m-%d')
                clauses.append('created_at' + op + '?'); args.append(filters[param] + suffix)
        if filters.get('q'):
            clauses.append("(COALESCE(report_id,'') LIKE ? ESCAPE '\\' OR CAST(record_seq AS TEXT) LIKE ? ESCAPE '\\' OR COALESCE(report,'') LIKE ? ESCAPE '\\' OR log_text LIKE ? ESCAPE '\\')")
            keyword = filters['q'][:200].replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            args.extend(['%' + keyword + '%'] * 4)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        size = max(1, min(50, int(filters.get('size', 12))))
        with self.stream.connect() as conn:
            counts = {row['status']: row['n'] for row in conn.execute(CTE + 'SELECT status,COUNT(*) AS n FROM normalized' + where + ' GROUP BY status', args)}
            total = sum(counts.values())
            pages = max(1, math.ceil(total / size))
            page = max(1, min(pages, int(filters.get('page', 1))))
            order = 'position ASC' if filters.get('batch') else 'created_at DESC,key DESC'
            rows = conn.execute(CTE + 'SELECT key,report_id,created_at,sensor_id,record_seq,batch_id,position,report_status,review_status,status,event_type,queue_state FROM normalized'
                                + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', [*args, size, (page - 1) * size]).fetchall()
        return {'items': [dict(row) for row in rows], 'total': total, 'page': page, 'pages': pages,
                'counts': {'total': total, 'generated': counts.get('REPORT_GENERATED', 0) + counts.get('REVIEWED', 0),
                           'pending': counts.get('REPORT_PENDING', 0), 'failed': counts.get('REPORT_FAILED', 0),
                           'review': counts.get('REVIEW_REQUIRED', 0)}, 'status_counts': counts}

    def detail(self, key):
        with self.stream.connect() as conn:
            row = conn.execute(CTE + 'SELECT * FROM normalized WHERE key=?', (key,)).fetchone()
        if row is None:
            if key.startswith('batch:'):
                _, batch_id, position = key.split(':')
                rows = self.batches.get(batch_id)['items']
                item = next((r for r in rows if r['position'] == int(position)), None)
                if item and item['report_id']:
                    return self.detail('report:' + item['report_id'])
            raise KeyError(key)
        item = dict(row)
        details = json.loads(item.pop('details_json'))
        item['details'] = details
        item['values'] = decode(item['sensor_id'], item['log_text'])
        validation = details.get('validation', {})
        item['auto_validation'] = validation.get('passed')
        item['retention'] = self.batches.retention(item['batch_id'], item['position']) if item['batch_id'] and item['position'] else None
        if item['batch_id']:
            rows = self.batches.get(item['batch_id'])['items']
            item['batch_total'] = len(rows)
            item['batch_finished'] = sum(r['state'] in ('complete', 'failed') for r in rows)
            item['previous_key'] = self.batch_key(rows[item['position'] - 2]) if item['position'] > 1 else None
            item['next_key'] = self.batch_key(rows[item['position']]) if item['position'] < len(rows) else None
        return item

    @staticmethod
    def batch_key(row):
        return 'report:' + row['report_id'] if row['report_id'] else f"batch:{row['batch_id']}:{row['position']}"

    def monitoring(self, filters=None):
        filters = filters or {}
        with self.stream.connect() as conn:
            states = []
            for sensor in ('302', '305', '301'):
                row = conn.execute('SELECT * FROM sensor_records WHERE sensor_id=? ORDER BY seq DESC LIMIT 1', (sensor,)).fetchone()
                state = sensor_state(sensor, row['log_text'], row['received_at']) if row else sensor_state(sensor, '', None)
                state['total_received'] = conn.execute('SELECT COUNT(*) FROM sensor_records WHERE sensor_id=?', (sensor,)).fetchone()[0]
                if sensor == '305':
                    results = [decode(sensor, r['log_text']).get('inspection_result') for r in conn.execute('SELECT log_text FROM sensor_records WHERE sensor_id=?', (sensor,))]
                    state['ok_count'], state['ng_count'] = results.count(0), results.count(1)
                states.append(state)
            clauses, args = [], []
            sensor = filters.get('sensor') or {'fire': '302', 'vision': '305', 'other': '301'}.get(filters.get('event'))
            if sensor:
                clauses.append('sensor_id=?'); args.append(sensor)
            if filters.get('event') and filters.get('sensor'):
                clauses.append('sensor_id=?'); args.append({'fire': '302', 'vision': '305', 'other': '301'}[filters['event']])
            if filters.get('from'):
                datetime.strptime(filters['from'], '%Y-%m-%d'); clauses.append('received_at>=?'); args.append(filters['from'] + 'T00:00:00')
            if filters.get('to'):
                datetime.strptime(filters['to'], '%Y-%m-%d'); clauses.append('received_at<=?'); args.append(filters['to'] + 'T23:59:59.999999+00:00')
            if filters.get('q'):
                clauses.append('(log_text LIKE ? OR CAST(seq AS TEXT) LIKE ?)'); args.extend(['%' + filters['q'][:200] + '%'] * 2)
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            total = conn.execute('SELECT COUNT(*) FROM sensor_records' + where, args).fetchone()[0]
            pages = max(1, math.ceil(total / 15)); page = max(1, min(pages, int(filters.get('page', 1))))
            rows = conn.execute('SELECT * FROM sensor_records' + where + ' ORDER BY seq DESC LIMIT 15 OFFSET ?', [*args, (page - 1) * 15]).fetchall()
            worker = dict(conn.execute('SELECT name,value FROM sensor_stream_status').fetchall())
        events = []
        for r in rows:
            # History describes the observed value at reception, not today's connectivity.
            state = sensor_state(r['sensor_id'], r['log_text'], r['received_at'], datetime.fromisoformat(r['received_at']))
            events.append({**state, 'seq': r['seq'], 'log_text': r['log_text']})
        return {'sensors': states, 'events': events, 'worker': worker, 'total': total, 'pages': pages, 'page': page,
                'updated_at': datetime.now(timezone.utc).isoformat(), 'stale_seconds': 120}
