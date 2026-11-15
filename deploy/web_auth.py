"""Private login and session service for the public Nginx dashboard."""
import argparse
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

COOKIE = '__Host-streak_session'
LIFETIME = 7 * 24 * 3600


def safe_next(value):
    if not isinstance(value, str) or not value.startswith('/') or value.startswith('//'):
        return '/'
    if any(ord(char) < 32 or ord(char) > 126 for char in value) or '\\' in value:
        return '/'
    parsed = urlsplit(value)
    if parsed.path in ('/login', '/logout', '/auth') or parsed.path.startswith('/login/'):
        return '/'
    if parsed.path.startswith('/browser/') or parsed.path == '/browser':
        return '/browser/'
    return value


class Sessions:
    def __init__(self, credentials, database):
        self.credentials = Path(credentials)
        self.database = str(database)
        self.lock = threading.Lock()
        self.attempts = {}
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, credential TEXT NOT NULL, expires REAL NOT NULL)')
        Path(self.database).chmod(0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        try:
            with db:
                yield db
        finally:
            db.close()

    def credential(self):
        raw = self.credentials.read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest()

    def allowed(self, address):
        now = time.time()
        with self.lock:
            self.attempts = {ip: [at for at in ats if at > now - 300]
                             for ip, ats in self.attempts.items() if any(at > now - 300 for at in ats)}
            attempts = self.attempts.setdefault(address, [])
            if len(attempts) >= 8 or len(self.attempts) > 5000:
                return False
            attempts.append(now)
        return True

    def login(self, username, password, address):
        if not self.allowed(address):
            return 429, None
        credential, fingerprint = self.credential()
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(credential['salt']), n=16384, r=8, p=1).hex()
        valid_password = hmac.compare_digest(candidate, credential['password_hash'])
        valid_user = hmac.compare_digest(username.encode(), credential['username'].encode())
        if not (valid_password and valid_user):
            return 401, None
        token = secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE expires <= ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?, ?, ?)',
                       (hashlib.sha256(token.encode()).hexdigest(), fingerprint, time.time() + LIFETIME))
        with self.lock:
            self.attempts.pop(address, None)
        return 200, token

    def authenticated(self, token):
        if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
            return False
        _, fingerprint = self.credential()
        with self.connect() as db:
            row = db.execute('SELECT credential, expires FROM sessions WHERE token = ?',
                             (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return bool(row and row[1] > time.time() and hmac.compare_digest(row[0], fingerprint))

    def logout(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token = ?', (hashlib.sha256(token.encode()).hexdigest(),))


class AuthServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, origin, sessions, assets):
        self.origin = origin.rstrip('/')
        self.host = urlsplit(self.origin).netloc
        self.sessions = sessions
        self.assets = Path(assets)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data=b'', kind='application/json; charset=utf-8', headers=None):
        raw = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def token(self):
        try:
            cookies = SimpleCookie(self.headers.get('Cookie', ''))
            return cookies[COOKIE].value if COOKIE in cookies else ''
        except CookieError:
            return ''

    def host_valid(self):
        return self.headers.get('Host') == self.server.host

    def do_GET(self):
        if not self.host_valid():
            return self.reply(403, {'error': 'Invalid host'})
        path = urlsplit(self.path).path
        if path == '/auth':
            return self.reply(204 if self.server.sessions.authenticated(self.token()) else 401)
        if path in ('/login', '/login/'):
            if self.server.sessions.authenticated(self.token()):
                target = safe_next(parse_qs(urlsplit(self.path).query).get('next', ['/'])[0])
                return self.reply(302, headers={'Location': target})
            return self.reply(200, (self.server.assets / 'login.html').read_bytes(), 'text/html; charset=utf-8')
        files = {'/login/style.css': ('login.css', 'text/css; charset=utf-8'),
                 '/login/app.js': ('login.js', 'text/javascript; charset=utf-8'),
                 '/login/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        if path in files:
            filename, kind = files[path]
            return self.reply(200, (self.server.assets / filename).read_bytes(), kind)
        self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 <= length <= 65536:
                raise ValueError()
            self.connection.settimeout(10)
            raw = self.rfile.read(length)
        except (ValueError, OSError):
            return self.reply(400, {'error': 'Yêu cầu không hợp lệ.'})
        if not self.host_valid() or self.headers.get('Origin') != self.server.origin:
            return self.reply(403, {'error': 'Vui lòng đăng nhập từ trang của tool.'})
        path = urlsplit(self.path).path
        if path == '/logout':
            self.server.sessions.logout(self.token())
            return self.reply(200, {'ok': True}, headers={'Set-Cookie': f'{COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age=0'})
        if path != '/login':
            return self.reply(404, {'error': 'Not found'})
        try:
            if not 0 < length <= 4096 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                raise ValueError()
            data = json.loads(raw)
            username, password = data['username'], data['password']
            if not isinstance(username, str) or not isinstance(password, str) or len(username) > 128 or len(password) > 512:
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            return self.reply(400, {'error': 'Vui lòng nhập tài khoản và mật khẩu hợp lệ.'})
        address = self.headers.get('X-Real-IP', self.client_address[0])
        status, token = self.server.sessions.login(username, password, address)
        if status != 200:
            message = 'Bạn thử quá nhiều lần. Vui lòng đợi 5 phút rồi thử lại.' if status == 429 else 'Tài khoản hoặc mật khẩu chưa đúng.'
            return self.reply(status, {'error': message})
        self.reply(200, {'ok': True, 'next': safe_next(data.get('next', '/'))},
                   headers={'Set-Cookie': f'{COOKIE}={token}; Path=/; Secure; HttpOnly; SameSite=Lax; Max-Age={LIFETIME}'})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--credentials', required=True)
    parser.add_argument('--sessions', required=True)
    args = parser.parse_args()
    origin = urlsplit(args.origin)
    if origin.scheme != 'https' or not origin.netloc or origin.path or origin.query or origin.fragment or origin.username:
        parser.error('An exact HTTPS origin is required')
    server = AuthServer(('127.0.0.1', args.port), args.origin,
                        Sessions(args.credentials, args.sessions), Path(__file__).resolve().parents[1] / 'web')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
