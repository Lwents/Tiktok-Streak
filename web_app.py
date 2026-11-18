"""Local-only web interface for TikTok Streak. No framework or cloud account required."""
import argparse
import json
import math
import queue
import secrets
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from streak import read_json, save_state
from worker import Worker
from ai_client import AIClient, DEFAULT_STYLE

ROOT = Path(__file__).resolve().parent


def normalize_public_origin(value):
    parsed = urlparse(value)
    if (parsed.scheme != 'https' or not parsed.hostname or '*' in parsed.netloc
            or parsed.username or parsed.password or parsed.path not in ('', '/')
            or parsed.query or parsed.fragment):
        raise ValueError('Địa chỉ công khai phải là một HTTPS origin, không có đường dẫn hay mật khẩu.')
    parsed.port  # Reject invalid/out-of-range ports.
    return 'https://' + parsed.netloc


class Dashboard:
    def __init__(self, root=ROOT, inspect=False, worker_factory=Worker, persist_automation=False,
                 *, desktop_window=False):
        self.root = Path(root)
        self.server_mode = persist_automation
        self.runtime_mode = 'desktop' if desktop_window else ('vps' if persist_automation else 'local')
        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.settings = self.validate_settings(read_json(self.root / 'desktop-settings.json', {}))
        self.rows = []
        try:
            cache = read_json(self.root / 'conversation-cache.json', {})
            self.cached_accounts = cache.get('accounts', {}) if cache.get('version') == 1 else {}
            if not isinstance(self.cached_accounts, dict):
                self.cached_accounts = {}
        except (OSError, ValueError, TypeError, AttributeError):
            self.cached_accounts = {}
        self.account = None
        self.logs = []
        self.revision = 0
        self.status = {'busy': False, 'operation': None, 'automatic': False, 'browser_connected': False,
                       'channel': self.settings['channel'], 'scanned_at': None, 'total': None, 'sent': 0,
                       'rows_cached': False, 'account_checking': False, 'schedule': 'daily_midnight'}
        self.stopped = threading.Event()
        self.selected_video = None
        worker_args = {'root': self.root}
        if persist_automation:
            worker_args['persist_automation'] = True
        self.worker = worker_factory(self.events, inspect, **worker_args)
        self.worker.start()
        self.consumer = threading.Thread(target=self.consume, daemon=True)
        self.consumer.start()
        self.log('Chào bạn! Kết nối TikTok để bắt đầu một ngày giữ lửa mới.')
        if ((self.root / 'browser-profile' / self.settings['channel'] / 'Local State').exists()
                or (self.root / 'session-import.json').exists()):
            self.status.update(busy=True, operation='restore')
            self.worker.commands.put(('restore', dict(self.settings)))

    @staticmethod
    def validate_settings(data):
        if not isinstance(data, dict):
            raise ValueError('Cấu hình phải là một đối tượng hợp lệ.')
        message = data.get('message', 'Giữ chuỗi nha 🔥')
        if not isinstance(message, str) or len(message) > 500:
            raise ValueError('Nội dung tin nhắn tối đa 500 ký tự.')
        raw = data.get('hours', 20)
        if isinstance(raw, bool):
            raise ValueError('Khoảng cách gửi phải từ 1 đến 168 giờ.')
        try:
            hours = float(raw)
        except (TypeError, ValueError):
            raise ValueError('Khoảng cách gửi phải từ 1 đến 168 giờ.') from None
        if not math.isfinite(hours) or not 1 <= hours <= 168:
            raise ValueError('Khoảng cách gửi phải từ 1 đến 168 giờ.')
        channel = data.get('channel', 'chrome')
        if channel not in ('chrome', 'msedge'):
            raise ValueError('Chọn Chrome hoặc Edge.')
        auto_restore = data.get('auto_restore', False)
        if not isinstance(auto_restore, bool):
            raise ValueError('Tùy chọn khôi phục chuỗi phải là bật hoặc tắt.')
        ai_enabled = data.get('ai_enabled', False)
        ai_style = data.get('ai_style', DEFAULT_STYLE)
        if not isinstance(ai_enabled, bool) or not isinstance(ai_style, str) or not ai_style.strip() or len(ai_style) > 500:
            raise ValueError('Tùy chọn AI phải là bật/tắt và phong cách từ 1 đến 500 ký tự.')
        daily_mode = data.get('daily_mode', 'text')
        video_query = data.get('video_query', 'chuỗi')
        if daily_mode not in ('text','video') or not isinstance(video_query,str) or not video_query.strip() or len(video_query)>100:
            raise ValueError('Chọn tin nhắn hoặc video và nhập từ khóa video từ 1 đến 100 ký tự.')
        return {'message': message, 'hours': hours, 'channel': channel, 'auto_restore': auto_restore,
                'ai_enabled': ai_enabled, 'ai_style': ai_style, 'daily_mode': daily_mode, 'video_query': video_query}

    def log(self, text):
        with self.lock:
            level = 'error' if text.startswith(('Lỗi', 'Không gửi')) else ('success' if text.startswith('Đã thấy tin') else 'info')
            self.logs.append({'id': secrets.token_hex(5), 'at': time.time(), 'text': str(text)[:4000], 'level': level})
            self.logs = self.logs[-100:]
            self.revision += 1

    def consume(self):
        while not self.stopped.is_set():
            try:
                kind, value = self.events.get(timeout=.2)
            except queue.Empty:
                continue
            if kind == 'log':
                self.log(value)
                continue
            with self.lock:
                if kind == 'status':
                    self.status.update(value)
                elif kind == 'rows':
                    self.rows = value
                elif kind == 'scan':
                    if value.get('account_username') != (self.account or {}).get('username'):
                        continue
                    self.status.update(value)
                    self.save_conversations()
                elif kind == 'sent':
                    self.status['sent'] += 1
                elif kind == 'ai_sent':
                    self.status['sent'] += 1
                    self.status['ai_sent'] = self.status.get('ai_sent', 0) + 1
                elif kind == 'selected_video':
                    self.selected_video = dict(value)
                elif kind == 'reply':
                    if value.get('account_username') == (self.account or {}).get('username'):
                        for row in self.rows:
                            if row['key'] == value['key']:
                                row['reply'] = dict(value['reply'])
                                break
                elif kind == 'history':
                    if value.get('account_username') == (self.account or {}).get('username'):
                        for row in self.rows:
                            if row['key'] == value['key']:
                                proof = value['evidence']
                                row['history_evidence'] = dict(proof)
                                row['recovery'] = {k: v for k, v in value['recovery'].items() if k != 'evidence'}
                                if proof.get('status') == 'history_confirmed':
                                    row.update(streak_status='history_confirmed', badge=f"≥{proof['days_lower_bound']} ngày · lịch sử TikTok")
                                elif proof.get('recovery'):
                                    row.update(streak_status='unknown', badge='')
                                if proof.get('reply'):
                                    row['reply'] = dict(proof['reply'])
                                break
                        self.status['verified_count'] = sum(row.get('streak_status') in ('verified', 'history_confirmed') for row in self.rows)
                        self.status['unknown_count'] = len(self.rows) - self.status['verified_count']
                        self.save_conversations()
                elif kind == 'account':
                    previous = (self.account or {}).get('username')
                    self.account = value
                    if previous and (value or {}).get('username') != previous:
                        self.rows = []
                        self.selected_video = None
                        self.status.update(scanned_at=None, total=None, rows_cached=False)
                    if value and value.get('authenticated') and value.get('username') != previous:
                        self.restore_conversations(value['username'])
                self.revision += 1

    def restore_conversations(self, username):
        channel = self.status['channel']
        record = self.cached_accounts.get(channel + ':' + username.casefold())
        if not isinstance(record, dict) or record.get('username') != username or record.get('channel') != channel:
            return
        rows, scan = record.get('rows'), record.get('scan')
        if not isinstance(rows, list) or not isinstance(scan, dict) or not scan.get('scanned_at'):
            return
        if any(not isinstance(row, dict) or not isinstance(row.get('key'), str)
               or not isinstance(row.get('name'), str) or row.get('streak_status') not in
               ('verified', 'history_confirmed', 'unknown') for row in rows):
            return
        self.rows = [dict(row) for row in rows]
        self.status.update({k: scan[k] for k in ('scanned_at', 'total', 'verified_count', 'unknown_count') if k in scan})
        self.status['rows_cached'] = True
        self.log('Đã khôi phục danh sách lần quét trước của @' + username + '. Đang kiểm tra lại dữ liệu mới.')

    def save_conversations(self):
        if not (self.account or {}).get('authenticated') or self.status.get('rows_cached'):
            return
        username, channel = self.account['username'], self.status['channel']
        self.cached_accounts[channel + ':' + username.casefold()] = {
            'username': username, 'channel': channel, 'rows': [dict(row) for row in self.rows],
            'scan': {k: self.status[k] for k in ('scanned_at', 'total', 'verified_count', 'unknown_count') if k in self.status}}
        try:
            save_state(self.root / 'conversation-cache.json', {'version': 1, 'accounts': self.cached_accounts})
        except OSError:
            self.log('Chưa lưu được danh sách chat trên ổ đĩa. Danh sách hiện tại vẫn được giữ trong tool.')

    def snapshot(self):
        with self.lock:
            return {'revision': self.revision, 'status': dict(self.status), 'settings': dict(self.settings),
                    'runtime': {'platform': sys.platform, 'mode': self.runtime_mode},
                    'ai': AIClient.public_status(self.root),
                    'video': self.selected_video,
                    'account': dict(self.account) if self.account else None,
                    'rows': [dict(row) for row in self.rows], 'logs': list(self.logs)}

    def save_settings(self, data):
        with self.lock:
            if self.status['busy'] or self.status['automatic']:
                raise RuntimeError('Dừng tác vụ trước khi thay đổi cấu hình.')
            settings = self.validate_settings(data)
            save_state(self.root / 'desktop-settings.json', settings)
            self.settings = settings
            self.revision += 1

    def ai_draft(self, data):
        settings = self.validate_settings(data.get('settings', self.settings))
        sample = data.get('sample', 'Hôm nay bạn thế nào?')
        if not isinstance(sample, str) or not sample.strip() or len(sample) > 700:
            raise ValueError('Tin nhắn thử phải có từ 1 đến 700 ký tự.')
        client = AIClient.from_root(self.root)
        return {'message': client.reply([{'role':'user','content':sample}], settings['ai_style']), 'model': client.model}

    def action(self, data):
        command = data.get('command')
        if command not in ('login', 'account', 'scan', 'send', 'auto', 'stop','video_preview'):
            raise ValueError('Thao tác không hợp lệ.')
        with self.lock:
            if command == 'stop':
                self.worker.stop_sending.set()
                if hasattr(self.worker, 'forget_automation'):
                    self.worker.forget_automation()
                self.worker.commands.put(('stop', None))
                self.status['automatic'] = False
                self.log('Đã yêu cầu dừng. Thao tác đang thực hiện sẽ kết thúc trước.')
                return
            if self.status['busy'] or (self.status['automatic'] and command != 'video_preview'):
                raise RuntimeError('Một tác vụ đang chạy. Bấm Dừng hoặc chờ hoàn tất.')
            settings = self.validate_settings(data.get('settings', self.settings))
            payload = dict(settings)
            if command == 'video_preview':
                if not self.account or not self.account.get('authenticated') or not self.status['browser_connected'] or settings['channel']!=self.status['channel'] or not AIClient.public_status(self.root)['configured']:
                    raise ValueError('Kết nối TikTok và cấu hình AI trước khi chọn video.')
                payload['account_username'] = self.account['username']
                self.status.update(busy=True,operation=command)
                self.worker.commands.put((command,payload))
                return
            if command == 'login':
                method = data.get('method', 'standard')
                if method not in ('standard', 'qr'):
                    raise ValueError('Chọn cách đăng nhập hợp lệ.')
                payload['login_method'] = method
            if command in ('send', 'auto'):
                if (settings['ai_enabled'] or settings['daily_mode']=='video') and not AIClient.public_status(self.root)['configured']:
                    raise ValueError('Chưa cấu hình proxy và API key cho AI trên máy chạy tool.')
                if self.status.get('account_checking') or self.status.get('rows_cached'):
                    raise ValueError('Đang xác nhận tài khoản hoặc cập nhật danh sách đã lưu. Chờ quét xong trước khi gửi.')
                if not self.account or not self.account.get('authenticated'):
                    raise ValueError('Chưa xác nhận tài khoản TikTok. Kết nối tài khoản trước khi gửi.')
                if not settings['message'].strip():
                    raise ValueError('Nhập nội dung tin nhắn trước khi gửi.')
                keys = data.get('target_keys')
                if not isinstance(keys, list) or not keys or any(not isinstance(key, str) for key in keys):
                    raise ValueError('Chọn ít nhất một người nhận.')
                rows = {row['key']: row for row in self.rows}
                if any(key not in rows for key in keys):
                    raise ValueError('Danh sách đã thay đổi. Quét và chọn lại người nhận.')
                if any(rows[key].get('streak_status') not in ('verified', 'history_confirmed') and not
                       (settings['auto_restore'] and rows[key].get('conversation_id') and rows[key].get('history_evidence', {}).get('recovery', {}).get('status') == 'available'
                        and rows[key]['history_evidence']['recovery'].get('deadline_at', 0) > time.time()) for key in keys):
                    raise ValueError('Chưa xác minh được chuỗi hiện tại của người nhận. Tool chưa thể tự động gửi đúng người có lửa từ dữ liệu này.')
                if settings['channel'] != self.status['channel']:
                    raise ValueError('Kết nối và quét lại sau khi đổi trình duyệt.')
                payload['targets'] = [rows[key] for key in dict.fromkeys(keys)]
                payload['account_username'] = self.account['username']
                if settings['ai_enabled']:
                    payload['ai_started_at'] = time.time()
                self.worker.stop_sending.clear()
            elif command in ('login', 'scan'):
                self.worker.stop_sending.set()
                self.worker.commands.put(('stop', None))
                if settings['channel'] != self.status['channel']:
                    self.rows = []
                    self.status.update(scanned_at=None, total=None, rows_cached=False)
            save_state(self.root / 'desktop-settings.json', settings)
            self.settings = settings
            self.status.update(busy=True, operation=command)
            self.revision += 1
            self.worker.commands.put((command, payload))

    def close(self):
        self.worker.stop_sending.set()
        self.worker.closing.set()
        self.worker.join(timeout=70)
        self.stopped.set()


class WebServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, app, assets=ROOT / 'web', public_origin=None):
        self.app = app
        self.assets = Path(assets)
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)
        self.origins = {f'http://127.0.0.1:{self.server_port}', f'http://localhost:{self.server_port}'}
        if public_origin:
            self.origins.add(normalize_public_origin(public_origin))
        self.hosts = {urlparse(origin).netloc for origin in self.origins}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        raw = json.dumps(data, ensure_ascii=False).encode('utf-8') if content_type.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: https://*.tiktokcdn.com https://*.tiktokcdn-us.com https://*.tiktokcdn-eu.com https://*.byteoversea.com https://*.ibytedtos.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def valid_host(self):
        return self.headers.get('Host') in self.server.hosts

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Invalid host'})
        path = urlparse(self.path).path
        if path == '/api/state':
            data = self.server.app.snapshot()
            if parse_qs(urlparse(self.path).query).get('v') != ['2']:
                # Older UI versions treated every returned row as a verified flame.
                data['rows'] = [row for row in data['rows'] if row.get('streak_status') == 'verified']
            return self.reply(200, data)
        files = {'/': ('index.html', 'text/html; charset=utf-8'),
                 '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                 '/style.css': ('style.css', 'text/css; charset=utf-8'),
                 '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if path not in files:
            return self.reply(404, {'error': 'Not found'})
        name, kind = files[path]
        raw = (self.server.assets / name).read_bytes()
        if name == 'index.html':
            raw = raw.replace(b'__APP_TOKEN__', self.server.token.encode())
        self.reply(200, raw, kind)

    def do_POST(self):
        if not self.valid_host() or self.headers.get('Origin') not in self.server.origins:
            return self.reply(403, {'error': 'Yêu cầu phải gửi từ giao diện của tool.'})
        if not secrets.compare_digest(self.headers.get('X-App-Token', ''), self.server.token):
            return self.reply(403, {'error': 'Tải lại giao diện để kết nối.'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 64000 or not self.headers.get('Content-Type', '').startswith('application/json'):
                raise ValueError('Yêu cầu không hợp lệ.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('Yêu cầu không hợp lệ.')
            if self.path == '/api/action':
                self.server.app.action(data)
            elif self.path == '/api/ai/draft':
                return self.reply(200, self.server.app.ai_draft(data))
            elif self.path == '/api/settings':
                self.server.app.save_settings(data)
            elif self.path == '/api/shutdown':
                self.server.app.worker.stop_sending.set()
                if hasattr(self.server.app.worker, 'forget_automation'):
                    self.server.app.worker.forget_automation()
                self.reply(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            else:
                return self.reply(404, {'error': 'Not found'})
            self.reply(200, {'ok': True})
        except RuntimeError as exc:
            self.reply(409, {'error': str(exc)})
        except (ValueError, TypeError) as exc:
            self.reply(400, {'error': str(exc)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    parser.add_argument('--inspect', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--persist-automation', action='store_true', help='Khôi phục lịch đã bật sau khi dịch vụ VPS khởi động lại.')
    parser.add_argument('--public-origin', type=normalize_public_origin, help='HTTPS origin được cho phép qua reverse proxy đã bảo vệ.')
    args = parser.parse_args()
    app = Dashboard(inspect=args.inspect, persist_automation=args.persist_automation)
    try:
        try:
            server = WebServer(('127.0.0.1', args.port), app, public_origin=args.public_origin)
        except OSError:
            if args.open:
                webbrowser.open(f'http://127.0.0.1:{args.port}')
                return
            raise
        url = f'http://127.0.0.1:{server.server_port}'
        print(f'TikTok Streak: {url}', flush=True)
        if args.open:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        app.close()


if __name__ == '__main__':
    main()
