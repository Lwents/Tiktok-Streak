"""Shared browser worker for desktop and local web interfaces."""
import queue
import threading
import time
from pathlib import Path
from streak import read_json, save_state
from tiktok_browser import TikTokBrowser
from profile_lock import BrowserProfileLock
from account_state import AccountState
from daily_schedule import next_check_delay

ROOT = Path(__file__).resolve().parent


class Worker(threading.Thread):
    def __init__(self, events, inspect=False, root=None, persist_automation=False):
        super().__init__(daemon=True)
        self.commands = queue.Queue()
        self.events = events
        self.inspect = inspect
        self.root = Path(root) if root is not None else ROOT
        self.stop_sending = threading.Event()
        self.closing = threading.Event()
        self.persist_automation = persist_automation
        self.automation_lock = threading.Lock()

    def forget_automation(self):
        if self.persist_automation:
            with self.automation_lock:
                (self.root / 'automation.json').unlink(missing_ok=True)

    def remember_automation(self, payload):
        if self.persist_automation:
            with self.automation_lock:
                if not self.stop_sending.is_set():
                    save_state(self.root / 'automation.json', payload)

    def emit(self, kind, value):
        self.events.put((kind, value))

    def run(self):
        browser = None
        automatic = None
        next_run = 0
        profile_lock = BrowserProfileLock(self.root / '.running.lock')
        account = None
        next_account_check = 0
        auto_scan_pending = None
        account_state = AccountState()
        replied_until = {}
        try:
            resume_payload = read_json(self.root / 'automation.json', None) if self.persist_automation else None
            if resume_payload is not None and (not isinstance(resume_payload, dict)
                    or not isinstance(resume_payload.get('account_username'), str)
                    or not isinstance(resume_payload.get('targets'), list)
                    or not isinstance(resume_payload.get('message'), str)
                    or not resume_payload.get('message', '').strip()
                    or len(resume_payload.get('message', '')) > 500
                    or any(not isinstance(target, dict) or not isinstance(target.get('key'), str)
                           for target in resume_payload.get('targets', []))
                    or resume_payload.get('channel') not in ('chrome', 'msedge')):
                resume_payload = None
        except (OSError, ValueError):
            resume_payload = None

        def refresh_account(force=False):
            nonlocal account, next_account_check, automatic, auto_scan_pending, resume_payload
            if not browser or (not force and time.monotonic() < next_account_check):
                return account
            next_account_check = time.monotonic() + 3
            try:
                current = browser.read_account()
            except Exception:
                current = None
            was_checking = account_state.checking
            stable = account_state.observe(current)
            if was_checking != account_state.checking:
                self.emit('status', {'account_checking': account_state.checking})
            previous_username = (account or {}).get('username')
            username = (stable or {}).get('username')
            if stable != account:
                account = stable
                if username != previous_username:
                    auto_scan_pending = username if (stable or {}).get('authenticated') else None
                if previous_username and username != previous_username:
                    automatic = None
                    resume_payload = None
                    self.forget_automation()
                    self.stop_sending.set()
                    self.emit('status', {'automatic': False, 'scanned_at': None, 'total': None})
                    self.emit('rows', [])
                    self.emit('log', 'Tài khoản đã thay đổi hoặc đăng xuất. Đã dừng tự động; hãy quét và chọn lại người nhận.')
                self.emit('account', stable)
                if username and username != previous_username:
                    self.emit('log', f'Đã đăng nhập TikTok: @{username}.')
            # Sending and scan commits always require a fresh positive observation.
            if force and (current is None or not current.get('authenticated')):
                return None
            return account

        try:
            while not self.closing.is_set():
                try:
                    command, payload = self.commands.get(timeout=0.3)
                except queue.Empty:
                    if browser is not None and browser.context is not None and not browser.pump():
                        browser.close()
                        automatic = None
                        resume_payload = None
                        self.forget_automation()
                        account = None
                        auto_scan_pending = None
                        account_state = AccountState()
                        self.emit('account', None)
                        self.emit('status', {'browser_connected': False, 'automatic': False, 'account_checking': False})
                        self.emit('log', 'Trình duyệt đã đóng. Bấm Đăng nhập để mở lại; tự động đã dừng.')
                    refresh_account()
                    if auto_scan_pending and not account_state.checking and (account or {}).get('username') == auto_scan_pending:
                        auto_scan_pending = None
                        command, payload = 'scan', {'channel': getattr(browser, 'channel', None) or 'chrome'}
                        self.emit('log', 'Đã nhận tài khoản. Đang tự tải cuộc trò chuyện và kiểm tra chuỗi…')
                    elif automatic and not account_state.checking and time.monotonic() >= next_run:
                        command, payload = 'send', automatic
                        next_run = time.monotonic() + 60
                    else:
                        continue
                if command == 'stop':
                    automatic = None
                    resume_payload = None
                    self.forget_automation()
                    self.emit('status', {'automatic': False})
                    self.emit('log', 'Đã dừng tự động.')
                    continue
                try:
                    self.emit('status', {'busy': True, 'operation': command})
                    if browser is None:
                        profile_lock.acquire(timeout=10 if command == 'restore' else 0,
                                             cancel=self.closing)
                        browser = TikTokBrowser(self.root, self.inspect)
                    channel = (payload or {}).get('channel', 'chrome')
                    opened = browser.ensure_open(channel)
                    if opened:
                        self.emit('log', 'Đã mở ' + ('Chrome' if channel == 'chrome' else 'Edge') + '.')
                    self.emit('status', {'browser_connected': True, 'channel': channel})
                    if command in ('restore', 'account'):
                        if opened:
                            browser.login()
                        refresh_account(force=True)
                    elif command == 'login':
                        qr = payload.get('login_method') == 'qr'
                        browser.login(qr=qr)
                        self.emit('log', 'Quét mã QR trên trang TikTok bằng điện thoại, xác nhận đăng nhập rồi vào Tin nhắn.' if qr else 'Đăng nhập trong trình duyệt vừa mở, vào Tin nhắn rồi bấm Quét danh sách.')
                    elif command == 'scan':
                        scan_account = refresh_account(force=True)
                        if not scan_account or not scan_account.get('authenticated'):
                            raise RuntimeError('TikTok đang tải hoặc chưa xác nhận đăng nhập. Danh sách cũ được giữ lại; thử quét khi trang tải xong.')
                        auto_scan_pending = None
                        def scan_progress(done, total, matched):
                            self.emit('status', {'history_checked': done, 'history_total': total, 'history_matches': matched})
                        self.emit('status', {'history_checked': 0, 'history_total': 0, 'history_matches': 0})
                        rows, total = browser.scan(self.closing, on_progress=scan_progress)
                        final_account = refresh_account(force=True)
                        if not final_account or final_account.get('username') != scan_account['username']:
                            raise RuntimeError('Chưa xác nhận đúng tài khoản sau khi quét. Không thay danh sách bằng kết quả chưa xác minh.')
                        self.emit('rows', rows)
                        verified = sum(row.get('streak_status') in ('verified', 'history_confirmed') for row in rows)
                        history_confirmed = sum(row.get('streak_status') == 'history_confirmed' for row in rows)
                        unknown = len(rows) - verified
                        metadata_checked = sum(bool(row.get('metadata_checked')) for row in rows)
                        self.emit('scan', {'total': total, 'scanned_at': time.time(), 'verified_count': verified,
                                           'unknown_count': unknown, 'metadata_checked': metadata_checked,
                                           'account_username': scan_account['username'], 'channel': channel,
                                           'rows_cached': False})
                        self.emit('log', f'Đã đọc {total} cuộc trò chuyện: {verified} đủ bằng chứng chuỗi ({history_confirmed} qua thông báo và lịch sử TikTok), {unknown} chưa xác minh.')
                        if resume_payload:
                            saved = resume_payload
                            resume_payload = None
                            if saved['account_username'] == scan_account['username'] and saved['channel'] == channel:
                                approved = {target.get('key') for target in saved['targets'] if isinstance(target, dict)}
                                targets = [row for row in rows if row['key'] in approved and row.get('streak_status') in ('verified', 'history_confirmed')]
                                if targets:
                                    automatic = {**saved, 'targets': targets}
                                    self.stop_sending.clear()
                                    next_run = time.monotonic()
                                    self.emit('status', {'automatic': True})
                                    self.emit('log', 'Đã khôi phục lịch tự động đã bật cho đúng tài khoản và các chat đã được chọn trước đó.')
                                else:
                                    self.emit('log', 'Lịch đã lưu chưa có chat đủ bằng chứng sau khi quét; chưa tự bật gửi.')
                            else:
                                self.forget_automation()
                                self.emit('log', 'Lịch đã lưu thuộc tài khoản hoặc trình duyệt khác; không tự bật gửi.')
                    elif command in ('send', 'auto'):
                        current_account = refresh_account(force=True)
                        if not current_account or not current_account.get('authenticated'):
                            raise RuntimeError('Chưa xác nhận đăng nhập TikTok. Kết nối tài khoản rồi quét lại danh sách.')
                        if payload.get('account_username') and payload['account_username'] != current_account.get('username'):
                            raise RuntimeError('Tài khoản đã thay đổi. Quét và chọn lại người nhận trước khi gửi.')
                        if command == 'auto':
                            if self.stop_sending.is_set():
                                raise RuntimeError('Đã hủy yêu cầu bật tự động.')
                            automatic = payload
                            self.remember_automation(payload)
                            self.emit('status', {'automatic': True})
                            self.emit('log', 'Đã bật giữ chuỗi theo ngày. Sang 00:00 tự kiểm tra và gửi cho chat chưa rep; chat đã rep hôm nay được bỏ qua.')
                        clock = browser.day_clock()
                        state_path = self.root / 'state.json'
                        state = read_json(state_path, {})
                        for target in payload['targets']:
                            if self.stop_sending.is_set() or self.closing.is_set():
                                break
                            key = 'gui:' + current_account['username'].casefold() + ':' + target['key']
                            if replied_until.get(key, 0) > time.time():
                                continue
                            record = state.get(key, {})
                            legacy_pending = state.get('gui:' + target['key'], {}).get('status') == 'pending'
                            if record.get('status') == 'pending' or legacy_pending:
                                self.emit('log', f"Bỏ qua {target['name']}: lần trước chưa rõ kết quả; kiểm tra chat và state.json.")
                                continue
                            if record.get('reply_day') == clock['day'] and record.get('reply_timezone') == clock['timezone']:
                                continue
                            attempted = False
                            try:
                                active_account = refresh_account(force=True)
                                if not active_account or active_account.get('username') != current_account['username']:
                                    raise RuntimeError('Phiên tài khoản đã thay đổi; dừng gửi và quét lại danh sách.')
                                reply = browser.reply_status(target.get('conversation_id'), stop=self.closing)
                                self.emit('reply', {'key': target['key'], 'account_username': current_account['username'], 'reply': reply})
                                if reply['status'] == 'replied':
                                    replied_until[key] = reply.get('valid_until', 0)
                                    self.emit('log', f"Bỏ qua {target['name']}: bạn đã rep hôm nay trên TikTok.")
                                    continue
                                if reply['status'] != 'needed':
                                    self.emit('log', f"Bỏ qua {target['name']}: chưa đọc đủ lịch sử hôm nay để tránh gửi trùng.")
                                    continue
                                # Navigate and recheck identity/streak before recording an attempt.
                                browser.prepare(target)
                                active_account = refresh_account(force=True)
                                if not active_account or active_account.get('username') != current_account['username']:
                                    raise RuntimeError('Phiên tài khoản đã thay đổi; dừng gửi và quét lại danh sách.')
                                # Recheck after navigation, including a reply just sent on a phone.
                                reply = browser.reply_status(target.get('conversation_id'), stop=self.closing)
                                self.emit('reply', {'key': target['key'], 'account_username': current_account['username'], 'reply': reply})
                                if reply['status'] != 'needed':
                                    if reply['status'] == 'replied':
                                        replied_until[key] = reply.get('valid_until', 0)
                                    self.emit('log', f"Bỏ qua {target['name']}: " + ('bạn vừa rep hôm nay trên TikTok.' if reply['status'] == 'replied' else 'chưa xác nhận được trạng thái rep hôm nay.'))
                                    continue
                                if self.stop_sending.is_set() or self.closing.is_set():
                                    break
                                state[key] = {'status': 'pending', 'attempt_at': time.time(), 'name': target['name']}
                                save_state(state_path, state)
                                attempted = True
                                browser.send(payload['message'])
                                state[key] = {'status': 'sent', 'sent_at': time.time(), 'name': target['name']}
                                save_state(state_path, state)
                                self.emit('log', f"Đã thấy tin nhắn mới trong chat: {target['name']}.")
                                self.emit('sent', {'key': target['key'], 'name': target['name'], 'at': state[key]['sent_at']})
                                try:
                                    reply = browser.reply_status(target.get('conversation_id'), stop=self.closing)
                                    self.emit('reply', {'key': target['key'], 'account_username': current_account['username'], 'reply': reply})
                                    if reply['status'] == 'replied':
                                        replied_until[key] = reply.get('valid_until', 0)
                                        state[key].update(reply_day=reply['day'], reply_timezone=reply['timezone'])
                                        save_state(state_path, state)
                                except Exception:
                                    pass
                            except Exception as exc:
                                self.emit('log', f"Không gửi {target['name']}: {exc}")
                                if attempted:
                                    self.emit('log', 'Đã khóa thử lại cho người này vì kết quả chưa chắc chắn.')
                                if not browser.pump():
                                    self.forget_automation()
                                    automatic = None
                                    self.emit('status', {'browser_connected': False, 'automatic': False})
                                    self.emit('log', 'Trình duyệt đã đóng. Đã dừng lượt gửi; bấm Đăng nhập để mở lại.')
                                    break
                            self.stop_sending.wait(3)
                        if automatic:
                            next_run = time.monotonic() + next_check_delay(clock.get('valid_until'))
                        self.emit('log', 'Hoàn tất lượt kiểm tra/gửi.')
                except Exception as exc:
                    if automatic:
                        self.forget_automation()
                    automatic = None
                    self.emit('status', {'automatic': False, 'browser_connected': bool(browser and browser.pump())})
                    self.emit('log', f'Lỗi: {exc}')
                finally:
                    refresh_account(force=True)
                    self.emit('status', {'busy': False, 'operation': None})
                    self.emit('ready', None)
        except Exception as exc:
            self.emit('log', f'Lỗi khởi động: {exc}')
        finally:
            try:
                if browser:
                    browser.close()
            finally:
                profile_lock.release()
