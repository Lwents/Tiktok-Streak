"""Account synchronization and account-switch guards, without a TikTok connection."""
import queue
import sys
import tempfile
import threading
import time
import json
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from worker import Worker
from profile_lock import BrowserProfileLock


class FakeBrowser:
    account = {'authenticated': False}
    sent = 0
    switch_during_prepare = False
    scans = 0
    switch_during_scan = False
    prepared = 0
    reply_answers = ['needed']
    reply_checks = 0
    day_override = None
    midnight_override = None
    scan_status = 'unknown'
    scan_extra_rows = []
    reply_conversations = []
    recovery_calls = 0
    recovery_result = None
    def __init__(self, root, inspect=False):
        self.context = None
    def ensure_open(self, channel):
        opened = self.context is None
        self.context = object()
        return opened
    def pump(self):
        return self.context is not None
    def login(self, qr=False):
        pass
    def read_account(self):
        return dict(type(self).account) if type(self).account is not None else None
    def prepare(self, target):
        type(self).prepared += 1
        if type(self).switch_during_prepare:
            type(self).account = {'authenticated': True, 'username': 'other', 'display_name': 'Other'}
    def reply_status(self, conversation_id, stop=None):
        cls=type(self)
        cls.reply_checks += 1
        cls.reply_conversations.append(conversation_id)
        status=cls.reply_answers.pop(0) if len(cls.reply_answers)>1 else cls.reply_answers[0]
        return {'status':status,**self.day_clock(),'checked_at':time.time()}
    def day_clock(self):
        return {'day':type(self).day_override or time.strftime('%Y-%m-%d'),'timezone':'Asia/Bangkok',
                'valid_until':type(self).midnight_override or time.time()+3600}
    def send(self, message):
        type(self).sent += 1
    def restore_streak(self, target, expected_username, stop=None):
        type(self).recovery_calls += 1
        return type(self).recovery_result or {'status':'not_needed','evidence':{'status':'history_confirmed','days_lower_bound':7}}
    def scan(self, stop, on_progress=None):
        type(self).scans += 1
        if type(self).switch_during_scan:
            type(self).account = {'authenticated': True, 'username': 'other'}
        rows=[{'key':'conv:one','conversation_id':'one','name':'Alice','streak_status':type(self).scan_status}, *type(self).scan_extra_rows]
        return rows,len(rows)
    def close(self):
        self.context = None


class WorkerChecks(unittest.TestCase):
    def setUp(self):
        FakeBrowser.account = {'authenticated': False}
        FakeBrowser.sent = 0
        FakeBrowser.switch_during_prepare = False
        FakeBrowser.scans = 0
        FakeBrowser.switch_during_scan = False
        FakeBrowser.prepared = 0
        FakeBrowser.reply_answers = ['needed']
        FakeBrowser.reply_checks = 0
        FakeBrowser.day_override = None
        FakeBrowser.midnight_override = None
        FakeBrowser.scan_status = 'unknown'
        FakeBrowser.scan_extra_rows = []
        FakeBrowser.reply_conversations = []
        FakeBrowser.recovery_calls = 0
        FakeBrowser.recovery_result = None
        self.tmp = tempfile.TemporaryDirectory()
        self.events = queue.Queue()
        self.patch = patch('worker.TikTokBrowser', FakeBrowser)
        self.patch.start()
        self.worker = Worker(self.events, root=Path(self.tmp.name))
        self.worker.start()

    def tearDown(self):
        self.worker.closing.set()
        self.worker.join(timeout=3)
        self.patch.stop()
        self.assertFalse(self.worker.is_alive())
        self.tmp.cleanup()

    def wait_event(self, kind, predicate=lambda value: True, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event_kind, value = self.events.get(timeout=.1)
            except queue.Empty:
                continue
            if event_kind == kind and predicate(value):
                return value
        self.fail('Missing worker event: ' + kind)

    def test_login_is_detected_automatically_without_another_command(self):
        self.worker.commands.put(('account', {'channel': 'chrome'}))
        self.wait_event('account', lambda value: value is not None and not value.get('authenticated'))
        FakeBrowser.account = {'authenticated': True, 'username': 'owner', 'display_name': 'Owner'}
        account = self.wait_event('account', lambda value: value is not None and value.get('authenticated'))
        self.assertEqual(account['username'], 'owner')
        self.assertTrue(self.worker.commands.empty())

    def test_switch_between_preparing_and_sending_blocks_send(self):
        FakeBrowser.account = {'authenticated': True, 'username': 'owner', 'display_name': 'Owner'}
        FakeBrowser.switch_during_prepare = True
        payload = {'channel': 'chrome', 'message': 'test', 'hours': 20, 'account_username': 'owner',
                   'targets': [{'key': 'chat-alice', 'name': 'Alice'}]}
        self.worker.commands.put(('send', payload))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent, 0)
        self.assertTrue(self.worker.stop_sending.is_set())
        self.assertFalse((Path(self.tmp.name) / 'state.json').exists())

    def test_restore_waits_for_previous_instance_to_release_lock(self):
        lock = Path(self.tmp.name) / '.running.lock'
        previous = BrowserProfileLock(lock)
        previous.acquire()
        timer = threading.Timer(.2, previous.release)
        timer.start()
        self.worker.commands.put(('restore', {'channel': 'chrome'}))
        self.wait_event('account')
        self.wait_event('ready')
        timer.join()
        self.assertTrue(lock.exists())

    def test_restore_accepts_marker_left_by_previous_crashed_version(self):
        (Path(self.tmp.name) / '.running.lock').touch()
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.worker.commands.put(('restore', {'channel': 'chrome'}))
        self.wait_event('account', lambda value: value and value.get('username') == 'owner')
        self.wait_event('ready')

    def test_restored_account_automatically_loads_chat_list_once_without_sending(self):
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.worker.commands.put(('restore', {'channel': 'chrome'}))
        self.wait_event('rows', lambda value: value and value[0]['name'] == 'Alice')
        self.wait_event('scan', lambda value: value['total'] == 1)
        self.wait_event('ready')
        self.worker.commands.put(('account', {'channel': 'chrome'}))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.scans, 1)
        self.assertEqual(FakeBrowser.sent, 0)

    def test_late_login_automatically_loads_chats(self):
        self.worker.commands.put(('login', {'channel': 'chrome'}))
        self.wait_event('ready')
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.wait_event('rows', lambda value: bool(value))
        self.assertEqual(FakeBrowser.scans, 1)
        self.assertEqual(FakeBrowser.sent, 0)

    def test_logged_out_session_does_not_scan(self):
        self.worker.commands.put(('restore', {'channel': 'chrome'}))
        self.wait_event('ready')
        self.worker.commands.put(('account', {'channel': 'chrome'}))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.scans, 0)

    def test_explicit_scan_does_not_schedule_a_second_initial_scan(self):
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.worker.commands.put(('scan', {'channel': 'chrome'}))
        self.wait_event('scan')
        self.wait_event('ready')
        self.worker.commands.put(('account', {'channel': 'chrome'}))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.scans, 1)

    def test_unknown_current_identity_never_uses_old_account_to_send(self):
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.worker.commands.put(('restore', {'channel': 'chrome'}))
        self.wait_event('scan')
        self.wait_event('ready')
        FakeBrowser.account = None
        self.worker.commands.put(('send', {'channel': 'chrome', 'message': 'test', 'hours': 20,
                                           'account_username': 'owner', 'targets': []}))
        self.wait_event('log', lambda value: 'Chưa xác nhận đăng nhập' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent, 0)

    def test_scan_from_previous_account_is_discarded_on_switch(self):
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        FakeBrowser.switch_during_scan = True
        self.worker.commands.put(('scan', {'channel': 'chrome'}))
        self.wait_event('log', lambda value: 'Không thay danh sách' in value)
        self.assertEqual(FakeBrowser.sent, 0)

    def test_short_login_flash_keeps_account_and_does_not_schedule_rescan(self):
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.worker.commands.put(('restore', {'channel': 'chrome'}))
        self.wait_event('scan')
        self.wait_event('ready')
        FakeBrowser.account = {'authenticated': False}
        self.worker.commands.put(('account', {'channel': 'chrome'}))
        self.wait_event('status', lambda value: value.get('account_checking') is True)
        self.wait_event('ready')
        FakeBrowser.account = {'authenticated': True, 'username': 'owner'}
        self.worker.commands.put(('account', {'channel': 'chrome'}))
        self.wait_event('status', lambda value: value.get('account_checking') is False)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.scans, 1)

    def send_payload(self, username='owner', group=False):
        FakeBrowser.account={'authenticated':True,'username':username}
        return {'channel':'chrome','message':'test','hours':20,'account_username':username,
                'targets':[{'key':'conv:one','conversation_id':'one','name':'Alice','is_group':group}]}

    def test_existing_manual_reply_skips_chat_without_opening_or_sending(self):
        FakeBrowser.reply_answers=['replied']
        self.worker.commands.put(('send',self.send_payload()))
        self.wait_event('log',lambda value:'đã rep hôm nay' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent,0)
        self.assertEqual(FakeBrowser.prepared,0)
        self.assertFalse((Path(self.tmp.name)/'state.json').exists())

    def test_group_reply_sent_during_navigation_is_not_sent_again(self):
        FakeBrowser.reply_answers=['needed','replied']
        self.worker.commands.put(('send',self.send_payload(group=True)))
        self.wait_event('log',lambda value:'vừa rep hôm nay' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.prepared,1)
        self.assertEqual(FakeBrowser.sent,0)
        self.assertFalse((Path(self.tmp.name)/'state.json').exists())

    def test_unknown_reply_history_skips_instead_of_sending(self):
        FakeBrowser.reply_answers=['unknown']
        self.worker.commands.put(('send',self.send_payload()))
        self.wait_event('log',lambda value:'chưa đọc đủ lịch sử hôm nay' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent,0)
        self.assertEqual(FakeBrowser.prepared,0)

    def test_new_reply_is_allowed_when_today_has_no_self_message(self):
        self.worker.commands.put(('send',self.send_payload()))
        self.wait_event('sent')
        self.worker.stop_sending.set()
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent,1)
        self.assertGreaterEqual(FakeBrowser.reply_checks,2)

    def test_known_today_reply_is_not_fetched_repeatedly_until_expiry(self):
        FakeBrowser.reply_answers=['replied']
        payload=self.send_payload()
        self.worker.commands.put(('send',payload))
        self.wait_event('log',lambda value:'đã rep hôm nay' in value)
        self.wait_event('ready')
        self.worker.commands.put(('send',payload))
        self.wait_event('log',lambda value:'Hoàn tất lượt' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.reply_checks,1)
        self.assertEqual(FakeBrowser.sent,0)

    def test_new_calendar_day_sends_even_when_previous_send_was_two_minutes_ago(self):
        payload=self.send_payload()
        FakeBrowser.day_override='2026-11-15'
        state={'gui:owner:conv:one':{'status':'sent','sent_at':time.time()-120,
                                    'reply_day':'2026-11-14','reply_timezone':'Asia/Bangkok'}}
        (Path(self.tmp.name)/'state.json').write_text(json.dumps(state))
        self.worker.commands.put(('send',payload))
        self.wait_event('sent')
        self.worker.stop_sending.set()
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent,1)

    def test_confirmed_reply_day_survives_restart_without_sending_twice(self):
        payload=self.send_payload()
        FakeBrowser.day_override='2026-11-15'
        state={'gui:owner:conv:one':{'status':'sent','sent_at':time.time()-120,
                                    'reply_day':'2026-11-15','reply_timezone':'Asia/Bangkok'}}
        (Path(self.tmp.name)/'state.json').write_text(json.dumps(state))
        self.worker.commands.put(('send',payload))
        self.wait_event('log',lambda value:'Hoàn tất lượt' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent,0)
        self.assertEqual(FakeBrowser.reply_checks,0)

    def test_successful_send_saves_the_confirmed_reply_calendar_day(self):
        payload=self.send_payload()
        FakeBrowser.day_override='2026-11-15'
        FakeBrowser.reply_answers=['needed','needed','replied']
        self.worker.commands.put(('send',payload))
        self.wait_event('sent')
        self.worker.stop_sending.set()
        self.wait_event('ready')
        record=json.loads((Path(self.tmp.name)/'state.json').read_text())['gui:owner:conv:one']
        self.assertEqual(record['status'],'sent')
        self.assertEqual(record['reply_day'],'2026-11-15')
        self.assertEqual(record['reply_timezone'],'Asia/Bangkok')

    def test_automatic_wakes_at_day_boundary_and_replies_for_new_day(self):
        payload=self.send_payload()
        FakeBrowser.day_override='2026-11-14'
        FakeBrowser.midnight_override=time.time()+1.2
        FakeBrowser.reply_answers=['replied']
        self.worker.commands.put(('auto',payload))
        self.wait_event('log',lambda value:'đã rep hôm nay' in value)
        self.wait_event('ready')
        FakeBrowser.day_override='2026-11-15'
        FakeBrowser.midnight_override=time.time()+86400
        FakeBrowser.reply_answers=['needed']
        self.wait_event('sent',timeout=5)
        self.worker.stop_sending.set()
        self.worker.commands.put(('stop',None))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.sent,1)

    def persistent_worker(self, saved=None):
        self.worker.closing.set();self.worker.join(timeout=3)
        while not self.events.empty():self.events.get_nowait()
        if saved is not None:
            (Path(self.tmp.name)/'automation.json').write_text(json.dumps(saved))
        self.worker=Worker(self.events,root=Path(self.tmp.name),persist_automation=True)
        self.worker.start()

    def test_vps_mode_saves_approved_automation_and_stop_removes_it(self):
        payload=self.send_payload();FakeBrowser.reply_answers=['replied']
        self.persistent_worker()
        self.worker.commands.put(('auto',payload))
        self.wait_event('ready')
        path=Path(self.tmp.name)/'automation.json'
        saved=json.loads(path.read_text())
        self.assertEqual(saved['account_username'],'owner')
        self.assertEqual([target['key'] for target in saved['targets']],['conv:one'])
        self.worker.commands.put(('stop',None))
        self.wait_event('log',lambda value:'Đã dừng tự động' in value)
        self.assertFalse(path.exists())

    def test_vps_resume_waits_for_scan_and_keeps_only_original_approved_targets(self):
        saved=self.send_payload();FakeBrowser.reply_answers=['replied'];FakeBrowser.scan_status='verified'
        FakeBrowser.scan_extra_rows=[{'key':'conv:two','conversation_id':'two','name':'Bob','streak_status':'verified'}]
        self.persistent_worker(saved)
        self.worker.commands.put(('restore',{'channel':'chrome'}))
        self.wait_event('log',lambda value:'Đã khôi phục lịch tự động' in value)
        self.wait_event('log',lambda value:'đã rep hôm nay' in value)
        self.assertEqual(FakeBrowser.reply_conversations,['one'])
        self.assertEqual(FakeBrowser.sent,0)

    def test_vps_resume_refuses_a_different_account(self):
        saved=self.send_payload();FakeBrowser.account={'authenticated':True,'username':'other'}
        FakeBrowser.scan_status='verified'
        self.persistent_worker(saved)
        self.worker.commands.put(('restore',{'channel':'chrome'}))
        self.wait_event('log',lambda value:'thuộc tài khoản hoặc trình duyệt khác' in value)
        self.assertEqual(FakeBrowser.sent,0)
        self.assertFalse((Path(self.tmp.name)/'automation.json').exists())

    def test_vps_shutdown_keeps_schedule_when_browser_exits_during_pump(self):
        saved=self.send_payload();FakeBrowser.reply_answers=['replied'];FakeBrowser.scan_status='verified'
        self.persistent_worker(saved)
        self.worker.commands.put(('restore',{'channel':'chrome'}))
        self.wait_event('log',lambda value:'Đã khôi phục lịch tự động' in value)
        self.wait_event('ready')
        def shutdown_during_pump(browser):
            self.worker.closing.set()
            return False
        with patch.object(FakeBrowser,'pump',shutdown_during_pump):
            self.worker.join(timeout=3)
        self.assertFalse(self.worker.is_alive())
        self.assertTrue((Path(self.tmp.name)/'automation.json').exists())

    def test_vps_unexpected_browser_close_still_cancels_schedule(self):
        saved=self.send_payload();FakeBrowser.reply_answers=['replied'];FakeBrowser.scan_status='verified'
        self.persistent_worker(saved)
        self.worker.commands.put(('restore',{'channel':'chrome'}))
        self.wait_event('log',lambda value:'Đã khôi phục lịch tự động' in value)
        self.wait_event('ready')
        with patch.object(FakeBrowser,'pump',return_value=False):
            self.wait_event('status',lambda value:value.get('browser_connected') is False)
        self.assertFalse((Path(self.tmp.name)/'automation.json').exists())

    def test_restore_is_checked_even_when_this_account_already_replied_today(self):
        payload=self.send_payload();payload['auto_restore']=True
        FakeBrowser.reply_answers=['replied']
        FakeBrowser.recovery_result={'status':'restored','evidence':{'status':'history_confirmed','days_lower_bound':3}}
        self.worker.commands.put(('auto',payload))
        self.wait_event('log',lambda value:'Đã khôi phục chuỗi với Alice' in value)
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.recovery_calls,1)
        self.assertEqual(FakeBrowser.sent,0)

    def test_unconfirmed_restore_does_not_send_or_prepare_a_message(self):
        payload=self.send_payload();payload['auto_restore']=True
        FakeBrowser.recovery_result={'status':'uncertain','reason':'Waiting for server',
                                    'evidence':{'status':'unknown','recovery':{'status':'available'}}}
        self.worker.commands.put(('auto',payload))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.recovery_calls,1)
        self.assertEqual(FakeBrowser.sent,0)
        self.assertEqual(FakeBrowser.prepared,0)

    def test_restoration_stays_off_without_explicit_setting(self):
        payload=self.send_payload();FakeBrowser.reply_answers=['replied']
        self.worker.commands.put(('auto',payload))
        self.wait_event('ready')
        self.assertEqual(FakeBrowser.recovery_calls,0)

    def test_resume_retains_only_previously_approved_ended_chat_for_restore(self):
        saved=self.send_payload();saved['auto_restore']=True;FakeBrowser.reply_answers=['replied']
        ended={'key':'conv:one','conversation_id':'one','name':'Alice','streak_status':'unknown',
               'history_evidence':{'status':'unknown','recovery':{'status':'available'}}}
        unknown={**ended,'key':'conv:other','conversation_id':'other','name':'Other'}
        self.persistent_worker(saved)
        with patch.object(FakeBrowser,'scan',return_value=([ended,unknown],2)):
            self.worker.commands.put(('restore',{'channel':'chrome'}))
            self.wait_event('log',lambda value:'Đã khôi phục lịch tự động' in value)
            self.wait_event('log',lambda value:'đã rep hôm nay' in value)
        self.assertEqual(FakeBrowser.recovery_calls,1)
        self.assertEqual(FakeBrowser.reply_conversations,['one'])


if __name__ == '__main__':
    unittest.main()
