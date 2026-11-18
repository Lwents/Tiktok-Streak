"""Web API validation and browser interaction checks. Never contacts TikTok."""
import json
import queue
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from web_app import Dashboard, WebServer, normalize_public_origin


class FakeWorker:
    def __init__(self, events, inspect=False, root=None):
        self.commands = queue.Queue()
        self.stop_sending = threading.Event()
        self.closing = threading.Event()
    def start(self):
        pass
    def join(self, timeout=None):
        pass


class WebChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Dashboard(Path(self.tmp.name), worker_factory=FakeWorker)
        self.server = WebServer(('127.0.0.1', 0), self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'
        self.app.rows = [
            {'key': 'chat-alice', 'name': 'Alice', 'href': '', 'badge': 'streak 30', 'streak_status': 'verified'},
            {'key': 'chat-bob', 'name': 'Bob', 'href': '', 'badge': 'streak 7', 'streak_status': 'verified'}]
        self.app.status.update(browser_connected=True, scanned_at=1, total=2)
        self.app.account = {'authenticated': True, 'username': 'owner', 'display_name': 'My account', 'avatar_url': ''}

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.app.close()
        self.tmp.cleanup()

    def request(self, path, body, token=True, origin=True, host=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-App-Token'] = self.server.token
        if origin:
            headers['Origin'] = self.url if origin is True else origin
        if host:
            headers['Host'] = host
        request = Request(self.url + path, data=json.dumps(body).encode(), headers=headers, method='POST')
        try:
            response = urlopen(request)
        except HTTPError as error:
            response = error
        try:
            return response.status, json.loads(response.read())
        finally:
            response.close()

    def test_rejects_missing_token_and_foreign_origin(self):
        self.assertEqual(self.request('/api/action', {'command': 'login'}, token=False)[0], 403)
        self.assertEqual(self.request('/api/action', {'command': 'login'}, origin='https://example.com')[0], 403)
        self.assertEqual(self.request('/api/action', {'command': 'login'}, host='evil.example')[0], 403)
        self.assertTrue(self.app.worker.commands.empty())

    def test_configured_https_origin_works_without_relaxing_other_origins(self):
        public='https://160.250.180.133:8443'
        self.server.origins.add(normalize_public_origin(public))
        self.server.hosts.add('160.250.180.133:8443')
        self.assertEqual(self.request('/api/action',{'command':'account'},origin=public,host='160.250.180.133:8443')[0],200)
        self.assertEqual(self.app.worker.commands.get_nowait()[0],'account')
        self.app.status['busy']=False
        self.assertEqual(self.request('/api/action',{'command':'account'},origin='https://untrusted.example',host='160.250.180.133:8443')[0],403)
        self.assertEqual(self.request('/api/action',{'command':'account'},origin=public,host='untrusted.example')[0],403)

    def test_public_origin_rejects_credentials_paths_and_wildcards(self):
        for origin in ('http://example.com','https://user:secret@example.com','https://example.com/path','https://*.example.com','https://example.com?x=1'):
            with self.subTest(origin=origin),self.assertRaises(ValueError):
                normalize_public_origin(origin)
        self.assertEqual(normalize_public_origin('https://example.com/'),'https://example.com')

    def test_unknown_recipient_never_reaches_worker(self):
        status, _ = self.request('/api/action', {'command': 'send', 'target_keys': ['unscanned-chat']})
        self.assertEqual(status, 400)
        self.assertTrue(self.app.worker.commands.empty())

    def test_restore_setting_allows_only_canonical_ended_chats(self):
        self.app.rows[0].update(streak_status='unknown',conversation_id='one',
            history_evidence={'recovery':{'status':'available','event_id':'end-one','deadline_at':time.time()+3600}})
        self.assertEqual(self.request('/api/action',{'command':'auto','target_keys':['chat-alice']})[0],400)
        body={'command':'auto','target_keys':['chat-alice'],'settings':{**self.app.settings,'auto_restore':True}}
        self.assertEqual(self.request('/api/action',body)[0],200)
        command,payload=self.app.worker.commands.get_nowait()
        self.assertEqual(command,'auto')
        self.assertTrue(payload['auto_restore'])
        self.assertEqual([target['key'] for target in payload['targets']],['chat-alice'])

    def test_restore_setting_requires_boolean(self):
        self.assertEqual(self.request('/api/settings',{'auto_restore':'true'})[0],400)

    def test_ai_provider_key_is_never_exposed_in_snapshot(self):
        (Path(self.tmp.name)/'ai-provider.json').write_text(json.dumps({'base_url':'https://ai.example/v1','model':'fixture-model','api_key':'fixture-provider-secret'}))
        with urlopen(self.url+'/api/state?v=2') as response:body=json.loads(response.read())
        self.assertTrue(body['ai']['configured'])
        self.assertEqual(body['ai']['model'],'fixture-model')
        self.assertNotIn('fixture-provider-secret',json.dumps(body))
        try:urlopen(self.url+'/ai-provider.json')
        except HTTPError as error:self.assertEqual(error.code,404);error.close()
        else:self.fail('AI config became a public asset')

    def test_ai_sample_requires_owner_origin_and_does_not_queue_tiktok_send(self):
        from unittest.mock import patch
        with patch('web_app.AIClient.from_root') as factory:
            factory.return_value.reply.return_value='Chào bạn nè!';factory.return_value.model='fixture-model'
            self.assertEqual(self.request('/api/ai/draft',{'sample':'Xin chào'},origin='https://foreign.example')[0],403)
            factory.assert_not_called()
            status,body=self.request('/api/ai/draft',{'sample':'Xin chào'})
            self.assertEqual(status,200);self.assertEqual(body['message'],'Chào bạn nè!')
            self.assertTrue(self.app.worker.commands.empty())

    def test_video_preview_does_not_stop_or_reconfigure_running_job(self):
        from unittest.mock import patch
        self.app.status['automatic']=True
        before=dict(self.app.settings)
        with patch('web_app.AIClient.public_status',return_value={'configured':True}):
            self.assertEqual(self.request('/api/action',{'command':'video_preview'})[0],200)
        command,payload=self.app.worker.commands.get_nowait()
        self.assertEqual(command,'video_preview');self.assertTrue(self.app.status['automatic'])
        self.assertFalse(self.app.worker.stop_sending.is_set());self.assertEqual(self.app.settings,before)

    def test_recovery_filter_and_selection_need_the_restore_option(self):
        from playwright.sync_api import sync_playwright,expect
        self.app.rows[0].update(streak_status='unknown',conversation_id='one',
            history_evidence={'recovery':{'status':'available','event_id':'end-one','ended_day':'2026-11-18','deadline_at':time.time()+3600}})
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            page=browser.new_page();page.goto(self.url)
            expect(page.locator('#selected-count')).to_have_text('01')
            page.locator('#auto-restore').check()
            expect(page.locator('#selected-count')).to_have_text('02')
            page.locator('#streak-filter').select_option('recovery')
            expect(page.locator('.friend-row')).to_have_count(1)
            expect(page.locator('.friend-badge')).to_have_text('Cần khôi phục')
            expect(page.locator('.friend-row input')).to_be_enabled()
            page.locator('#auto-restore').uncheck()
            expect(page.locator('.friend-row input')).to_be_disabled()
            browser.close()

    def test_sending_requires_authenticated_account(self):
        self.app.account = {'authenticated': False}
        status, _ = self.request('/api/action', {'command': 'send', 'target_keys': ['chat-alice']})
        self.assertEqual(status, 400)
        self.assertTrue(self.app.worker.commands.empty())

    def test_unknown_streak_cannot_be_sent_even_if_client_requests_it(self):
        self.app.rows[0].update(streak_status='unknown', badge='')
        status, _ = self.request('/api/action', {'command': 'send', 'target_keys': ['chat-alice']})
        self.assertEqual(status, 400)
        self.assertTrue(self.app.worker.commands.empty())

    def test_history_evidence_is_forwarded_without_accepting_client_invented_proof(self):
        self.app.rows[0].update(streak_status='history_confirmed', conversation_id='one',
                                history_evidence={'marker_day':'2026-11-01','days_lower_bound':14})
        status, _ = self.request('/api/action', {'command':'send','target_keys':['chat-alice'],
                                                'history_evidence':{'days_lower_bound':999}})
        self.assertEqual(status, 200)
        command, payload = self.app.worker.commands.get_nowait()
        self.assertEqual(command, 'send')
        self.assertEqual(payload['targets'][0]['history_evidence']['days_lower_bound'], 14)

    def test_history_candidate_has_lower_bound_label_and_can_be_selected(self):
        from playwright.sync_api import sync_playwright, expect
        self.app.rows[0].update(streak_status='history_confirmed', conversation_id='one',badge='≥14 ngày · lịch sử TikTok',
                                history_evidence={'marker_day':'2026-11-01','days_lower_bound':14,'timezone':'Asia/Bangkok'})
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page()
                page.goto(self.url)
                expect(page.get_by_label('Chọn Alice')).to_be_enabled()
                expect(page.locator('.friend-row').filter(has=page.get_by_label('Chọn Alice')).locator('.friend-badge')).to_have_text('≥14 ngày')
                page.get_by_label('Chọn Alice').check()
                expect(page.locator('#send-button')).to_be_enabled()
                page.locator('#send-button').click()
                command,payload=self.app.worker.commands.get(timeout=3)
                self.assertEqual(command,'send')
                self.assertEqual(payload['targets'][0]['streak_status'],'history_confirmed')
            finally:
                browser.close()

    def test_old_ui_never_receives_unknown_rows_as_flames(self):
        self.app.rows[0].update(streak_status='unknown', badge='')
        with urlopen(self.url + '/api/state') as response:
            old = json.load(response)
        with urlopen(self.url + '/api/state?v=2') as response:
            current = json.load(response)
        self.assertEqual([row['key'] for row in old['rows']], ['chat-bob'])
        self.assertEqual(len(current['rows']), 2)

    def test_unknown_rows_are_visible_without_flames_or_send_controls(self):
        from playwright.sync_api import sync_playwright, expect
        for row in self.app.rows:
            row.update(streak_status='unknown', badge='')
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel='chrome' if sys.platform == 'win32' else None)
            try:
                page = browser.new_page()
                page.goto(self.url)
                expect(page.get_by_label('Chọn Alice')).to_be_visible()
                expect(page.get_by_label('Chọn Alice')).to_be_disabled()
                expect(page.locator('#friends-count')).to_have_text('2')
                expect(page.locator('#streak-count')).to_have_text('—')
                expect(page.locator('#select-all')).to_be_disabled()
                expect(page.locator('#auto-button')).to_be_disabled()
                expect(page.locator('.friend-badge.unknown')).to_have_count(2)
                expect(page.locator('.friend-badge use[href="#i-fire"]')).to_have_count(0)
                page.locator('#streak-filter').select_option('verified')
                expect(page.locator('.friend-row')).to_have_count(0)
            finally:
                browser.close()

    def test_account_switch_clears_previous_recipient_list(self):
        self.app.events.put(('account', {'authenticated': True, 'username': 'newowner'}))
        deadline = time.monotonic() + 2
        while self.app.snapshot()['account'].get('username') != 'newowner' and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.app.snapshot()['account']['username'], 'newowner')
        self.assertEqual(self.app.snapshot()['rows'], [])
        self.assertIsNone(self.app.snapshot()['status']['scanned_at'])

    def test_initial_autoscan_shows_progress_in_empty_chat_list(self):
        from playwright.sync_api import sync_playwright, expect
        self.app.rows = []
        self.app.status.update(busy=True, operation='scan', scanned_at=None,
                               history_checked=4, history_total=22, history_matches=3)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel='chrome' if sys.platform == 'win32' else None)
            try:
                page = browser.new_page()
                page.goto(self.url)
                expect(page.locator('#empty-title')).to_have_text('Đang tải cuộc trò chuyện và tìm chuỗi…')
                expect(page.locator('#empty-description')).to_contain_text('4/22')
                expect(page.locator('#empty-description')).to_contain_text('3 chuỗi')
                expect(page.locator('#send-button')).to_be_disabled()
            finally:
                browser.close()

    def test_duplicate_send_is_rejected_while_busy(self):
        body = {'command': 'send', 'target_keys': ['chat-alice', 'chat-alice']}
        self.assertEqual(self.request('/api/action', body)[0], 200)
        command, payload = self.app.worker.commands.get_nowait()
        self.assertEqual(command, 'send')
        self.assertEqual([row['key'] for row in payload['targets']], ['chat-alice'])
        self.assertEqual(self.request('/api/action', body)[0], 409)
        self.assertTrue(self.app.worker.commands.empty())

    def test_rescan_keeps_previous_rows_and_counts(self):
        previous = self.app.snapshot()
        self.assertEqual(self.request('/api/action', {'command': 'scan'})[0], 200)
        current = self.app.snapshot()
        self.assertEqual(current['rows'], previous['rows'])
        self.assertEqual(current['status']['scanned_at'], previous['status']['scanned_at'])
        self.assertEqual(current['status']['total'], 2)
        self.assertTrue(current['status']['busy'])

    def test_uncertain_account_or_cached_rows_block_send_on_server(self):
        for flag in ('account_checking', 'rows_cached'):
            self.app.status.update(account_checking=False, rows_cached=False)
            self.app.status[flag] = True
            self.assertEqual(self.request('/api/action', {'command': 'send', 'target_keys': ['chat-alice']})[0], 400)
            self.assertTrue(self.app.worker.commands.empty())

    def test_saved_conversations_return_only_for_verified_matching_account(self):
        self.app.events.put(('scan', {'account_username': 'owner', 'channel': 'chrome',
                                       'scanned_at': 123, 'total': 2, 'verified_count': 2,
                                       'unknown_count': 0, 'rows_cached': False}))
        cache_path = Path(self.tmp.name) / 'conversation-cache.json'
        deadline = time.monotonic() + 3
        while not cache_path.exists() and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(cache_path.exists())
        restored = Dashboard(Path(self.tmp.name), worker_factory=FakeWorker)
        try:
            self.assertEqual(restored.snapshot()['rows'], [])
            restored.events.put(('status', {'browser_connected': True}))
            restored.events.put(('account', {'authenticated': True, 'username': 'owner'}))
            deadline = time.monotonic() + 3
            while not restored.snapshot()['rows'] and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(len(restored.snapshot()['rows']), 2)
            self.assertTrue(restored.snapshot()['status']['rows_cached'])
            with self.assertRaisesRegex(ValueError, 'cập nhật danh sách'):
                restored.action({'command': 'send', 'target_keys': ['chat-alice']})
            restored.events.put(('account', {'authenticated': True, 'username': 'other'}))
            deadline = time.monotonic() + 3
            while restored.snapshot()['account']['username'] != 'other' and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertEqual(restored.snapshot()['rows'], [])
        finally:
            restored.close()

    def test_wrong_account_scan_cannot_replace_cached_metadata(self):
        self.app.events.put(('scan', {'account_username': 'someone-else', 'scanned_at': 123, 'total': 99}))
        self.app.events.put(('status', {'test_marker': True}))
        deadline = time.monotonic() + 3
        while not self.app.snapshot()['status'].get('test_marker') and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertEqual(self.app.snapshot()['status']['total'], 2)
        self.assertFalse((Path(self.tmp.name) / 'conversation-cache.json').exists())

    def test_cached_rows_remain_visible_during_refresh_without_send_access(self):
        from playwright.sync_api import sync_playwright, expect
        self.app.status.update(busy=True, operation='scan', rows_cached=True,
                               history_checked=2, history_total=22, history_matches=1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel='chrome' if sys.platform == 'win32' else None)
            try:
                page = browser.new_page()
                page.goto(self.url)
                expect(page.locator('.friend-row')).to_have_count(2)
                expect(page.locator('#empty-state')).to_be_hidden()
                expect(page.get_by_label('Chọn Alice')).to_be_disabled()
                expect(page.locator('#scan-notice')).to_contain_text('lần quét trước')
                expect(page.locator('#send-button')).to_be_disabled()
            finally:
                browser.close()

    def test_group_and_reply_filters_show_own_today_status(self):
        from playwright.sync_api import sync_playwright, expect
        today=datetime.now(timezone.utc).date().isoformat()
        self.app.rows[0].update(is_group=True,reply={'status':'replied','day':today,'timezone':'UTC'})
        self.app.rows[1]['reply']={'status':'needed','day':today,'timezone':'UTC'}
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page()
                page.goto(self.url)
                alice=page.locator('.friend-row').filter(has=page.get_by_label('Chọn Alice'))
                expect(alice.locator('.friend-sub')).to_contain_text('Nhóm')
                expect(alice.locator('.friend-sub')).to_contain_text('đã rep hôm nay')
                page.locator('#streak-filter').select_option('needed')
                expect(page.locator('.friend-row')).to_have_count(1)
                expect(page.get_by_label('Chọn Bob')).to_be_visible()
                page.locator('#streak-filter').select_option('replied')
                expect(page.locator('.friend-row')).to_have_count(1)
                expect(page.get_by_label('Chọn Alice')).to_be_visible()
            finally:
                browser.close()

    def test_reply_from_previous_day_is_not_shown_as_today(self):
        from playwright.sync_api import sync_playwright, expect
        yesterday=(datetime.now(timezone.utc).date()-timedelta(days=1)).isoformat()
        self.app.rows[0]['reply']={'status':'replied','day':yesterday,'timezone':'UTC'}
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page();page.goto(self.url)
                page.locator('#streak-filter').select_option('replied')
                expect(page.locator('.friend-row')).to_have_count(0)
            finally:
                browser.close()

    def test_desktop_recovers_edits_when_closed_before_server_save(self):
        from playwright.sync_api import sync_playwright, expect

        self.app.runtime_mode = 'desktop'
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel='chrome' if sys.platform == 'win32' else None)
            try:
                context = browser.new_context()
                context.route('**/api/settings', lambda route: route.fulfill(status=409, json={'error': 'Busy'}))
                page = context.new_page()
                page.goto(self.url + '/#composer')
                page.get_by_text('AI và video', exact=True).click()
                page.locator('#ai-enabled').check()
                page.locator('#daily-mode').select_option('video')
                page.locator('#auto-restore').check()
                page.locator('#message').fill('Tin nhắn đã chỉnh')
                page.close()
                self.assertFalse(self.app.settings['ai_enabled'])

                context.unroute('**/api/settings')
                reopened = context.new_page()
                reopened.goto(self.url + '/#composer')
                reopened.get_by_text('AI và video', exact=True).click()
                expect(reopened.locator('#ai-enabled')).to_be_checked()
                expect(reopened.locator('#daily-mode')).to_have_value('video')
                expect(reopened.locator('#auto-restore')).to_be_checked()
                expect(reopened.locator('#message')).to_have_value('Tin nhắn đã chỉnh')
                reopened.wait_for_function("localStorage.getItem('streak.desktop-settings-draft.v1') === null")
                saved = json.loads((Path(self.tmp.name) / 'desktop-settings.json').read_text(encoding='utf-8'))
                self.assertTrue(saved['ai_enabled'] and saved['auto_restore'])
                self.assertEqual(saved['daily_mode'], 'video')
                self.assertEqual(saved['message'], 'Tin nhắn đã chỉnh')
                self.assertTrue(self.app.worker.commands.empty())
            finally:
                browser.close()

    def test_chats_are_selected_by_default_but_no_messages_start(self):
        from playwright.sync_api import sync_playwright, expect
        self.app.rows.append({'key':'unknown','name':'Unverified','badge':'','streak_status':'unknown'})
        today=datetime.now(timezone.utc).date().isoformat()
        self.app.rows[0].update(is_group=True,reply={'status':'needed','day':today,'timezone':'UTC'})
        self.app.rows[1]['reply']={'status':'replied','day':today,'timezone':'UTC'}
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page();page.goto(self.url)
                expect(page.get_by_label('Chọn Alice')).to_be_checked()
                expect(page.get_by_label('Chọn Bob')).to_be_checked()
                expect(page.locator('#selected-count')).to_have_text('02')
                expect(page.locator('#send-note')).to_contain_text('1 chat đã rep hôm nay sẽ được bỏ qua')
                expect(page.locator('#auto-button')).to_be_enabled()
                page.locator('#streak-filter').select_option('all')
                expect(page.get_by_label('Chọn Unverified')).not_to_be_checked()
                expect(page.get_by_label('Chọn Unverified')).to_be_disabled()
                self.assertTrue(self.app.worker.commands.empty())
            finally:
                browser.close()

    def test_manual_exclusion_survives_poll_reload_and_isolated_account_switch(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page();page.goto(self.url)
                expect(page.get_by_label('Chọn Alice')).to_be_checked()
                page.get_by_label('Chọn Alice').uncheck()
                for _ in range(2):
                    with page.expect_response(lambda r:'/api/state' in r.url):
                        pass
                expect(page.get_by_label('Chọn Alice')).not_to_be_checked()
                page.reload()
                expect(page.get_by_label('Chọn Alice')).not_to_be_checked()
                expect(page.get_by_label('Chọn Bob')).to_be_checked()
                rows=[dict(row) for row in self.app.rows]
                self.app.events.put(('account',{'authenticated':True,'username':'other'}))
                self.app.events.put(('rows',rows))
                self.app.events.put(('scan',{'account_username':'other','channel':'chrome','scanned_at':2,'total':2,'rows_cached':False}))
                expect(page.locator('#account-top-handle')).to_have_text('@other')
                expect(page.get_by_label('Chọn Alice')).to_be_checked()
            finally:
                browser.close()

    def test_saved_rows_wait_for_fresh_scan_before_automatic_selection(self):
        from playwright.sync_api import sync_playwright, expect
        self.app.status['rows_cached']=True
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page();page.goto(self.url)
                expect(page.locator('#selected-count')).to_have_text('00')
                expect(page.locator('#auto-button')).to_be_disabled()
                self.app.events.put(('scan',{'account_username':'owner','channel':'chrome','scanned_at':2,'total':2,'rows_cached':False}))
                expect(page.get_by_label('Chọn Alice')).to_be_checked()
                expect(page.get_by_label('Chọn Bob')).to_be_checked()
                expect(page.locator('#selected-count')).to_have_text('02')
                self.assertTrue(self.app.worker.commands.empty())
            finally:
                browser.close()

    def test_daily_schedule_is_visible_instead_of_hour_interval(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser=p.chromium.launch(headless=True,channel='chrome' if sys.platform=='win32' else None)
            try:
                page=browser.new_page();page.goto(self.url)
                expect(page.locator('#daily-schedule')).to_contain_text('00:00 mỗi ngày')
                expect(page.locator('#hours')).to_be_hidden()
                self.assertEqual(self.app.snapshot()['status']['schedule'],'daily_midnight')
                self.assertTrue(self.app.worker.commands.empty())
            finally:
                browser.close()

    def test_invalid_intervals_are_rejected(self):
        for hours in (0, 169, True, 'NaN', 'Infinity'):
            status, _ = self.request('/api/settings', {'hours': hours})
            self.assertEqual(status, 400, hours)

    def test_stop_interrupts_send_wait(self):
        self.app.status['automatic'] = True
        status, _ = self.request('/api/action', {'command': 'stop'})
        self.assertEqual(status, 200)
        self.assertTrue(self.app.worker.stop_sending.is_set())
        self.assertFalse(self.app.status['automatic'])

    def test_qr_login_is_forwarded_to_worker(self):
        self.assertEqual(self.request('/api/action', {'command': 'login', 'method': 'qr'})[0], 200)
        self.assertEqual(self.app.worker.commands.get_nowait()[0], 'stop')
        command, payload = self.app.worker.commands.get_nowait()
        self.assertEqual(command, 'login')
        self.assertEqual(payload['login_method'], 'qr')

    def test_browser_selection_search_preview_and_send(self):
        from playwright.sync_api import sync_playwright, expect
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel='chrome' if sys.platform == 'win32' else None)
            try:
                page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.goto(self.url)
                expect(page.locator('#account-top-handle')).to_have_text('@owner')
                expect(page.locator('#workspace-name')).to_have_text('My account')
                expect(page.locator('#qr-login')).to_be_hidden()
                expect(page.get_by_label('Chọn Alice')).to_be_visible()
                expect(page.locator('#auto-button')).to_be_enabled()
                page.get_by_label('Chọn Bob').uncheck()
                page.get_by_label('Chọn Alice').check()
                expect(page.locator('#selected-count')).to_have_text('01')
                page.locator('#search').fill('Bob')
                expect(page.get_by_label('Chọn Alice')).to_have_count(0)
                page.locator('#select-all').check()
                expect(page.locator('#selected-count')).to_have_text('02')
                message = '<img src=x onerror=alert(1)> giữ chuỗi 🔥'
                page.locator('#message').fill(message)
                expect(page.locator('#preview-bubble')).to_have_text(message)
                self.assertEqual(page.locator('#preview-bubble img').count(), 0)
                page.locator('#send-button').click()
                expect(page.locator('#send-button')).to_be_disabled()
                command, payload = self.app.worker.commands.get(timeout=3)
                self.assertEqual(command, 'send')
                self.assertEqual(payload['message'], message)
                self.assertEqual({r['key'] for r in payload['targets']}, {'chat-alice', 'chat-bob'})
                self.assertEqual(errors, [])
                page.set_viewport_size({'width': 390, 'height': 844})
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth > innerWidth'))
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
