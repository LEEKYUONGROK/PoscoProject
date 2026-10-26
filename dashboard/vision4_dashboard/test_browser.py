"""Browser integration checks in an isolated database; never queues production work."""
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright, expect

from .data import Dashboard
from .server import make_handler


class BrowserTests(unittest.TestCase):
    def test_dashboard_filters_sensor_rules_batch_review_and_responsive_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            dashboard = Dashboard(Path(temp) / 'qa.db')
            dashboard.stream.ingest([{'sensor_id':'302','text':'[sensorID=302] '+json.dumps({
                'temperature_c':24+i/100,'humidity_pct':50,'flame_detected':0,'fire_alarm':1,'alarm_level':1,'mq2':56,'mq7':23})} for i in range(110)])
            dashboard.stream.ingest([{'sensor_id':'305','text':'[sensorID=305] 305|2|RealSensor/305|1'}])
            for i in range(16):
                dashboard.archive.save(0,'[sensorID=302] {"mq2":56}',f'보고서 본문 {i}',{
                    'source_record':{'sensor_id':'302'},'report_generation':{'method':'qwen_broker_prose'},
                    'validation':{'passed':True}})
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(dashboard))
            threading.Thread(target=server.serve_forever,daemon=True).start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch(args=['--no-sandbox'])
                    page=browser.new_page(viewport={'width':1920,'height':1080})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}',wait_until='networkidle')
                    expect(page.locator('#count-total')).to_have_text('16')
                    page.locator('#auto-refresh').uncheck()
                    expect(page.locator('#report-rows tr[data-key]')).to_have_count(12)
                    page.locator('#page-next').click()
                    expect(page.locator('#report-rows tr[data-key]')).to_have_count(4)
                    page.locator('[data-tab="analysis"]').click();expect(page.locator('#tab-content')).to_contain_text('입력 로그')
                    page.locator('[data-view="monitor"]').click()
                    expect(page.locator('.sensor-card').nth(0)).to_contain_text('정상 · 불꽃 미감지')
                    expect(page.locator('.sensor-card').nth(0)).to_contain_text('활성')
                    expect(page.locator('.sensor-card').nth(1)).to_contain_text('불량 (NG)')
                    page.locator('[data-view="reports"]').click()
                    page.locator('#search').fill('not-found-keyword')
                    expect(page.locator('#count-total')).to_have_text('0')
                    expect(page.locator('#preview-empty')).to_be_visible()
                    page.locator('#reset-filters').click()
                    expect(page.locator('#count-total')).to_have_text('16')
                    page.locator('#sensor-filter').select_option('302')
                    page.locator('#generate').click();expect(page.locator('#generate-dialog')).to_be_visible()
                    page.locator('#confirm-generate').click()
                    expect(page.locator('#report-position')).to_have_text('1 / 100')
                    identifier=dashboard.batches.list_recent('302')[0]['id']
                    self.assertEqual(dashboard.batches.get(identifier)['items'][0]['record_seq'],11)
                    outcome={'text':'검증 미통과 실제 테스트 출력','passed':False,'error':'numeric mismatch',
                        'facts':{},'report':None,'raw':'raw','history':[],'terminology':None}
                    with patch('edge_bridge.broker_prose.generate',return_value=outcome):
                        dashboard.batches.process_one(type('Backend',(),{'model_id':'test-adapter'})())
                    page.locator('#refresh').click()
                    expect(page.locator('#retention-panel')).to_be_visible()
                    expect(page.locator('#tab-content')).to_contain_text('검증 미통과 실제 테스트 출력')
                    page.locator('[data-retention="discard"]').click()
                    expect(page.locator('#retention-status')).to_contain_text('유지하지 않음')
                    self.assertEqual(dashboard.batches.retention(identifier,1),'discard')
                    page.locator('#report-next').click();expect(page.locator('#report-position')).to_have_text('2 / 100')
                    page.locator('#report-prev').click();expect(page.locator('#report-position')).to_have_text('1 / 100')
                    expect(page.locator('#retention-status')).to_contain_text('유지하지 않음')
                    page.set_viewport_size({'width':390,'height':844})
                    # The report table scrolls inside its card; the page itself must not pan horizontally.
                    self.assertLessEqual(page.evaluate('document.body.scrollWidth'),390)
                    self.assertEqual(page.evaluate('window.scrollX'),0)
                    page.locator('#mobile-menu').click();expect(page.locator('.sidebar')).to_have_class('sidebar open')
                    self.assertFalse(errors,errors)
                    browser.close()
            finally:
                server.shutdown();server.server_close()


if __name__=='__main__':unittest.main()
