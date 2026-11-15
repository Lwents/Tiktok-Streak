"""One-time import of explicitly supplied TikTok session cookies.

The private import file is removed only after the expected account is verified.
Cookie values are never logged or exposed by the web API.
"""
import json


def apply_session_import(context, path):
    if not path.exists():
        return None
    if path.stat().st_size > 2_000_000:
        raise ValueError('File phiên đăng nhập không hợp lệ.')
    data = json.loads(path.read_text(encoding='utf-8'))
    username = data.get('account_username')
    cookies = data.get('cookies')
    if not isinstance(username, str) or not username or not isinstance(cookies, list):
        raise ValueError('File phiên đăng nhập thiếu tài khoản hoặc cookie.')
    allowed = []
    fields = {'name', 'value', 'domain', 'path', 'expires', 'httpOnly', 'secure', 'sameSite', 'partitionKey'}
    for cookie in cookies:
        if not isinstance(cookie, dict):
            raise ValueError('Định dạng cookie không hợp lệ.')
        domain = str(cookie.get('domain', '')).lstrip('.').lower()
        if domain != 'tiktok.com' and not domain.endswith('.tiktok.com'):
            continue
        if not all(isinstance(cookie.get(key), str) for key in ('name', 'value', 'domain', 'path')):
            raise ValueError('Định dạng cookie không hợp lệ.')
        allowed.append({key: value for key, value in cookie.items() if key in fields})
    if not allowed:
        raise ValueError('Không có cookie TikTok trong file phiên đăng nhập.')
    context.add_cookies(allowed)
    return username
