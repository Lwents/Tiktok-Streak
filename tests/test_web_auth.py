"""Session authentication checks without contacting TikTok or the VPS."""
import hashlib
import http.client
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.web_auth import AuthServer, COOKIE, Sessions, safe_next


class LoginChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.credentials = self.root / 'auth.json'
        self.write_credentials('test-secret')
        self.sessions = Sessions(self.credentials, self.root / 'sessions.sqlite3')
        self.origin = 'https://streak.example:8443'
        self.server = AuthServer(('127.0.0.1', 0), self.origin, self.sessions,
                                 Path(__file__).resolve().parents[1] / 'web')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.tmp.cleanup()

    def write_credentials(self, password):
        salt = b'example-test-salt'
        self.credentials.write_text(json.dumps({'username': 'owner', 'salt': salt.hex(),
            'password_hash': hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()}))

    def request(self, path, data=None, cookie=None, origin=None, host=None, raw=None):
        headers = {'Host': host or 'streak.example:8443'}
        if cookie:
            headers['Cookie'] = cookie
        if data is not None or raw is not None:
            headers.update({'Content-Type': 'application/json', 'Origin': origin or self.origin})
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        body = raw if raw is not None else json.dumps(data) if data is not None else None
        connection.request('POST' if body is not None else 'GET', path, body, headers)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def login(self, **values):
        status, headers, body = self.request('/login', {'username': 'owner', 'password': 'test-secret', **values})
        self.assertEqual(status, 200)
        self.assertNotIn('test-secret', body.decode())
        return headers['Set-Cookie'].split(';')[0], headers

    def test_anonymous_is_blocked_and_login_assets_are_public(self):
        self.assertEqual(self.request('/auth')[0], 401)
        for path in ('/login', '/login/style.css', '/login/app.js', '/login/favicon.svg'):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertNotIn(b'password_hash', body)
            self.assertNotIn('WWW-Authenticate', headers)
        self.assertEqual(self.request('/auth', host='foreign.example')[0], 403)

    def test_login_cookie_and_authenticated_redirect(self):
        cookie, headers = self.login()
        for flag in ('Secure', 'HttpOnly', 'SameSite=Lax', 'Path=/', 'Max-Age=604800'):
            self.assertIn(flag, headers['Set-Cookie'])
        self.assertTrue(cookie.startswith(COOKIE + '='))
        self.assertEqual(self.request('/auth', cookie=cookie)[0], 204)
        status, headers, _ = self.request('/login?next=/browser/vnc.html', cookie=cookie)
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], '/browser/')
        with self.sessions.connect() as db:
            stored = db.execute('SELECT token FROM sessions').fetchone()[0]
        self.assertNotIn(cookie.split('=', 1)[1], stored)

    def test_invalid_credentials_and_foreign_origins(self):
        self.assertEqual(self.request('/login', {'username':'owner','password':'wrong'})[0], 401)
        self.assertEqual(self.request('/login', {'username':'other','password':'test-secret'})[0], 401)
        self.assertEqual(self.request('/login', {'username':'owner','password':'test-secret'}, origin='https://foreign.example')[0], 403)
        self.assertEqual(self.request('/login', raw='[]')[0], 400)
        self.assertEqual(self.request('/login', raw='x' * 4097)[0], 400)
        self.assertEqual(self.request('/auth', cookie=COOKIE+'=forged')[0], 401)

    def test_logout_revokes_session_and_rejects_csrf(self):
        cookie, _ = self.login()
        self.assertEqual(self.request('/logout', {}, cookie=cookie, origin='https://foreign.example')[0], 403)
        self.assertEqual(self.request('/auth', cookie=cookie)[0], 204)
        status, headers, _ = self.request('/logout', {}, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('Max-Age=0', headers['Set-Cookie'])
        self.assertEqual(self.request('/auth', cookie=cookie)[0], 401)

    def test_sessions_survive_restart_but_expire_and_password_changes_revoke_them(self):
        cookie, _ = self.login()
        token = cookie.split('=', 1)[1]
        restored = Sessions(self.credentials, self.sessions.database)
        self.assertTrue(restored.authenticated(token))
        self.write_credentials('changed-secret')
        self.assertFalse(restored.authenticated(token))
        _, token = restored.login('owner', 'changed-secret', '127.0.0.2')
        with restored.connect() as db:
            db.execute('UPDATE sessions SET expires = ?', (time.time() - 1,))
        self.assertFalse(restored.authenticated(token))

    def test_rate_limit_stops_password_guessing(self):
        for _ in range(8):
            self.assertEqual(self.sessions.login('owner', 'wrong', '192.0.2.1')[0], 401)
        self.assertEqual(self.sessions.login('owner', 'test-secret', '192.0.2.1')[0], 429)
        self.assertEqual(self.sessions.login('owner', 'test-secret', '192.0.2.2')[0], 200)

    def test_redirect_cannot_leave_tool_or_loop_into_login(self):
        for value in ('https://foreign.example', '//foreign.example', '/\\foreign.example', '/login', '/logout', '/auth', '/\r\nInjected: x', None):
            self.assertEqual(safe_next(value), '/')
        self.assertEqual(safe_next('/#friends'), '/#friends')
        _, _, body = self.request('/login', {'username':'owner','password':'test-secret','next':'https://foreign.example'})
        self.assertEqual(json.loads(body)['next'], '/')


if __name__ == '__main__':
    unittest.main()
