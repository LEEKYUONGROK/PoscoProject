import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from .data import Dashboard, decode, sensor_state
from .server import make_handler


class SensorTests(unittest.TestCase):
    def test_vision_uses_confirmed_payload_value_not_message_type(self):
        now = datetime.now(timezone.utc)
        for value, label, tone in ((0, '정상 (OK)', 'success'), (1, '불량 (NG)', 'danger')):
            state = sensor_state('305', f'[sensorID=305] 305|2|RealSensor/305|{value}', now.isoformat(), now)
            self.assertEqual((state['label'], state['tone']), (label, tone))
            self.assertNotIn('fire_alarm', state['values'])
        for raw in ('305|1|RealSensor/305|2', '305|0|RealSensor/305|', '{"fire_alarm":1}'):
            self.assertEqual(sensor_state('305', raw, now.isoformat(), now)['label'], '데이터 없음')
        stale = sensor_state('305', '305|2|RealSensor/305|1', (now-timedelta(minutes=5)).isoformat(), now)
        self.assertEqual(stale['label'], '데이터 없음')
        self.assertEqual(stale['last_result'], '불량 (NG)')

    def test_fire_detection_and_alarm_are_independent(self):
        now = datetime.now(timezone.utc)
        state = sensor_state('302', '{"flame_detected":0,"fire_alarm":1,"alarm_level":2,"mq2":999}', now.isoformat(), now)
        self.assertEqual(state['tone'], 'success')
        self.assertEqual(state['alarm'], '활성')
        self.assertEqual(state['alarm_level'], '위험 단계')
        state = sensor_state('302', '{"flame_detected":1,"fire_alarm":0}', now.isoformat(), now)
        self.assertEqual(state['tone'], 'danger')
        self.assertEqual(state['alarm'], '비활성')
        self.assertEqual(sensor_state('302', '{}', now.isoformat(), now)['tone'], 'muted')
        self.assertEqual(decode('301', '301|{"result":2}|2026-10-23')['result'], 2)


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.dashboard = Dashboard(Path(self.temp.name) / 'reports.db')

    def save(self, sensor, text, validation=None, **extra):
        details = {'source_record': {'sensor_id': sensor}, 'validation': {'passed': validation}, **extra}
        return self.dashboard.archive.save(0, '[sensorID='+sensor+'] {"mq2":56}', text, details)

    def test_counts_are_exclusive_and_review_is_not_retention_or_judge(self):
        self.save('302', '본문 A', True)
        self.save('302', '본문 B', True, review_status='REVIEWED', review_record={
            'reviewer_id':'operator','reviewed_at':datetime.now(timezone.utc).isoformat(),'note':'검토 근거'})
        self.save('305', '본문 C', False)
        self.save('305', 'ERROR: generation failure', False)
        self.save('302', '본문 D', True, judge_verdict='FAIL')
        r = self.dashboard.reports({})
        self.assertEqual(r['counts'], {'total':5,'generated':3,'pending':0,'failed':1,'review':1})
        self.assertEqual(sum(v for k,v in r['counts'].items() if k!='total'), r['total'])
        self.assertEqual(self.dashboard.reports({'status':'REVIEWED'})['total'],1)
        self.assertEqual(self.dashboard.reports({'sensor':'305','event':'fire'})['total'],0)

    def test_filters_pagination_keyword_and_no_duplicate_report_rows(self):
        identifier=self.save('302','특별 키워드',True)
        self.dashboard.stream.ingest([{'sensor_id':'302','text':f'log {i}'} for i in range(3)],completed_report=None)
        with self.dashboard.stream.connect() as c:
            c.execute('UPDATE sensor_records SET report_id=?,state=?',(identifier,'complete'))
        self.save('305','비전 보고서',False)
        self.assertEqual(self.dashboard.reports({})['total'],2)
        self.assertEqual(self.dashboard.reports({'q':'특별'})['total'],1)
        self.assertEqual(self.dashboard.reports({'q':"%' OR 1=1 --"})['total'],0)
        r=self.dashboard.reports({'size':'1','page':'2'})
        self.assertEqual(len(r['items']),1); self.assertEqual(r['page'],2)
        self.assertEqual(self.dashboard.reports({'from':'2099-01-01'})['total'],0)
        self.assertEqual(self.dashboard.reports({'event':'vision'})['total'],1)
        with self.assertRaises(ValueError):self.dashboard.reports({'from':'bad-date'})

    def test_existing_batch_queue_details_and_retention_preserve_failures(self):
        self.dashboard.stream.ingest([{'sensor_id':'302','text':f'row {i}'} for i in range(110)])
        identifier=self.dashboard.batches.create('302')
        r=self.dashboard.reports({'batch':identifier})
        self.assertEqual(r['total'],100); self.assertEqual(r['items'][0]['position'],1)
        key=r['items'][0]['key']; self.assertEqual(self.dashboard.detail(key)['log_text'],'row 10')
        outcome={'text':'미통과 본문','passed':False,'error':'check failed','facts':{},'report':None,'raw':'raw','history':[],'terminology':None}
        with patch('edge_bridge.broker_prose.generate',return_value=outcome):
            self.dashboard.batches.process_one(type('Backend',(),{'model_id':'unchanged-trained-qwen'})())
        d=self.dashboard.detail(key)
        self.assertFalse(d['auto_validation']); self.assertEqual(d['position'],1)
        self.dashboard.batches.retain(identifier,1,d['report_id'],'keep')
        d=self.dashboard.detail(key)
        self.assertEqual(d['retention'],'keep'); self.assertEqual(d['status'],'REVIEW_REQUIRED')
        self.assertEqual(self.dashboard.reports({'batch':identifier})['total'],100)
        self.assertIsNone(d['previous_key']); self.assertIsNotNone(d['next_key'])

    def test_http_reads_and_reuses_queue_with_same_origin_writes(self):
        self.dashboard.stream.ingest([{'sensor_id':'305','text':'305|2|RealSensor/305|0'}])
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.dashboard))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(server.server_close);self.addCleanup(server.shutdown)
        base=f'http://127.0.0.1:{server.server_port}'
        with urlopen(base+'/api/monitoring') as response:
            self.assertEqual(json.load(response)['sensors'][1]['ok_count'],1)
        request=Request(base+'/api/batches',data=b'{"sensor":"305"}',headers={'Content-Type':'application/json'},method='POST')
        with urlopen(request) as response:
            result=json.load(response);self.assertEqual(result['total'],1)
        self.assertEqual(len(self.dashboard.batches.get(result['id'])['items']),1)
        request.add_header('Origin','https://another.example')
        with self.assertRaises(HTTPError) as caught:urlopen(request)
        self.assertEqual(caught.exception.code,403)


if __name__=='__main__': unittest.main()
