"""Restore an explicitly ended streak; persist every attempt before spending a restore."""
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from streak import read_json, save_state
from streak_history import RESTORE_SCENES, GROUP_RESTORE_SCENES

RESTORE_URL = 'https://api.tiktokv.com/tiktok/v1/im/streaks/restore'
AUTH_COOKIE_NAMES = {'sessionid', 'sessionid_ss', 'sid_tt', 'sid_guard', 'uid_tt', 'uid_tt_ss',
                     'passport_csrf_token', 'passport_csrf_token_default'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def restore_request(context, cookies, user_agent, opener=None):
    """Use the native panel's form contract with the owner's existing TikTok session."""
    self_id = str(context.get('self_id', ''))
    cid = context.get('conversation_id', '')
    if not self_id.isdecimal() or int(self_id) <= 0 or not context.get('is_member'):
        raise ValueError('Chưa xác nhận thành viên và tài khoản của cuộc trò chuyện.')
    if context.get('is_group'):
        short_id = str(context.get('conversation_short_id', ''))
        if not short_id.isdecimal() or int(short_id) <= 0:
            raise ValueError('Chưa xác nhận ID nhóm để khôi phục.')
        body = {'peer_user_id': '0', 'conversation_short_id': short_id}
    else:
        peer = str(context.get('peer_user_id', ''))
        if not peer.isdecimal() or int(peer) <= 0 or peer == self_id or set(cid.split(':')[2:]) != {self_id, peer}:
            raise ValueError('ID người nhận không khớp cuộc trò chuyện.')
        body = {'peer_user_id': peer}
    cookies = [c for c in cookies if c['name'] in AUTH_COOKIE_NAMES
               and c.get('domain', '').lstrip('.') in ('tiktok.com', 'www.tiktok.com')]
    if not any(c['name'] == 'sessionid' for c in cookies):
        raise ValueError('Phiên TikTok chưa có cookie đăng nhập để khôi phục.')
    request = urllib.request.Request(RESTORE_URL, data=urllib.parse.urlencode(body).encode(), method='POST', headers={
        'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': user_agent,
        'Cookie': '; '.join(c['name'] + '=' + c['value'] for c in cookies),
        'Origin': 'https://www.tiktok.com', 'Referer': 'https://www.tiktok.com/messages'})
    opener = opener or urllib.request.build_opener(NoRedirect)
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        raw = response.read(65536)
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return {'http_status': response.status, 'status_code': None, 'status_msg': 'TikTok chưa trả kết quả khôi phục hợp lệ.'}
        if not isinstance(data, dict):
            return {'http_status': response.status, 'status_code': None, 'status_msg': 'Kết quả khôi phục chưa xác định.'}
        return {'http_status': response.status, 'status_code': data.get('status_code'),
                'status_msg': str(data.get('status_msg', ''))[:200],
                'restore_count': data.get('current_window_restore_cnt')}


class RecoveryManager:
    def __init__(self, path):
        self.path = Path(path)

    def restore(self, account, channel, target, evidence, request, verify, now=None):
        now = time.time() if now is None else now
        notice = evidence.get('recovery') or {}
        if notice.get('status') != 'available' or not notice.get('event_id') or not notice.get('ended_at', 0) <= now < notice.get('deadline_at', 0):
            return {'status': 'unavailable', 'reason': 'TikTok chưa có thông báo cho phép khôi phục còn hạn.'}
        identity = [account.casefold(), target['conversation_id'], str(notice['event_id'])]
        key = hashlib.sha256(json.dumps(identity, separators=(',', ':')).encode()).hexdigest()
        records = read_json(self.path, {})
        if not isinstance(records, dict):
            raise ValueError('Chưa đọc được sổ khôi phục; không thử để tránh dùng trùng lượt.')
        record = records.get(key, {})
        def confirmed(proof):
            return (proof.get('status') == 'history_confirmed'
                    and proof.get('marker_scene') in RESTORE_SCENES | GROUP_RESTORE_SCENES
                    and proof.get('marker_at', 0) >= notice['ended_at'])
        def verified():
            try:
                return verify()
            except Exception:
                return {}
        if record.get('status') in ('pending', 'acknowledged', 'restored'):
            proof = verified()
            if confirmed(proof):
                if record['status'] != 'restored':
                    records[key] = {**record, 'status': 'restored', 'restored_at': time.time()}
                    save_state(self.path, records)
                return {'status': 'restored', 'evidence': proof, 'restore_count': record.get('restore_count')}
            return {'status': 'uncertain', 'reason': 'Lần khôi phục trước chưa rõ kết quả; không tự dùng thêm lượt.'}
        if record.get('retry_after', 0) > now:
            return {'status': 'failed', 'reason': record.get('reason', ''), 'retry_after': record['retry_after']}
        records[key] = {'status': 'pending', 'account': account, 'channel': channel,
                        'conversation_id': target['conversation_id'], 'event_id': notice['event_id'], 'attempt_at': now}
        save_state(self.path, records)
        try:
            result = request()
        except Exception:
            return {'status': 'uncertain', 'reason': 'Chưa nhận được kết quả từ TikTok; đã khóa thử lại để tránh dùng trùng lượt.'}
        if result.get('http_status') != 200 or result.get('status_code') != 0:
            # A non-JSON/redirect result is ambiguous; never automatically repeat it.
            if result.get('status_code') is None:
                return {'status': 'uncertain', 'reason': result.get('status_msg', 'Chưa rõ kết quả khôi phục.')}
            record = {**records[key], 'status': 'failed', 'reason': result.get('status_msg') or 'TikTok chưa cho phép khôi phục.',
                      'status_code': result['status_code'], 'retry_after': min(notice['deadline_at'], now + 3600)}
            records[key] = record
            save_state(self.path, records)
            return {'status': 'failed', 'reason': record['reason'], 'retry_after': record['retry_after']}
        records[key].update(status='acknowledged', restore_count=result.get('restore_count'))
        save_state(self.path, records)
        proof = verified()
        if not confirmed(proof):
            return {'status': 'uncertain', 'reason': 'TikTok đã nhận khôi phục; đang chờ thông báo xác nhận trong chat.'}
        records[key].update(status='restored', restored_at=time.time())
        save_state(self.path, records)
        return {'status': 'restored', 'evidence': proof, 'restore_count': result.get('restore_count')}
