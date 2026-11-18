"""DOM adapter. Fails closed when TikTok doesn't expose a verifiable badge."""
import re
import time
from pathlib import Path
from datetime import date, timedelta
from streak_history import analyze_history, analyze_reply
from session_import import apply_session_import
from streak_recovery import RecoveryManager, restore_request

# Deliberately ignore the preview text/emoji: a message containing 🔥 is not a streak.
ROW_SELECTOR = '[data-e2e="dm-new-conversation-item"], [data-e2e="chat-list-item"], [data-e2e="chat-list-item-wrapper"]'
DAY_CLOCK_JS = '''() => {
 const now = new Date(); const midnight = new Date(now); midnight.setHours(24, 0, 0, 0);
 const day = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`;
 return {day, timezone:Intl.DateTimeFormat().resolvedOptions().timeZone, valid_until:midnight.getTime()/1000};
}'''
ACCOUNT_JS = r'''() => {
 const visible = el => el && el.getClientRects().length > 0;
 const login = document.querySelector('[data-e2e="top-login-button"], [data-e2e="nav-login-button"]');
 const profile = document.querySelector('a[data-e2e="nav-profile"][href^="/@"]');
 if (visible(login)) return {authenticated:false};
 if (!profile || !visible(profile)) return null;
 const url = new URL(profile.href, location.origin);
 const match = url.pathname.match(/^\/@([^/]+)\/?$/);
 if (!match || url.hostname !== 'www.tiktok.com') return null;
 const username = decodeURIComponent(match[1]);
 let current = null;
 try {
   const data = JSON.parse(document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent || '{}');
   const user = data.__DEFAULT_SCOPE__?.['webapp.app-context']?.user;
   if (user?.uniqueId?.toLowerCase() === username.toLowerCase()) current = user;
 } catch {}
 const img = profile.querySelector('img');
 return {authenticated:true, username,
   display_name: current?.nickName || current?.nickname || username,
   avatar_url: img?.currentSrc || img?.src || '',
   profile_url: 'https://www.tiktok.com/@' + encodeURIComponent(username)};
}'''
BADGE_JS = r'''element => {
 const nodes = [...element.querySelectorAll('[data-e2e*="streak" i], [class*="streak" i]')];
 for (const el of nodes) {
   if (!el.getClientRects().length) continue;
   const evidence = [el.getAttribute('data-e2e'), el.getAttribute('aria-label'), el.getAttribute('title'), el.getAttribute('alt'), el.textContent].filter(Boolean).join(' ').trim();
   const attrs = [el.getAttribute('class'), evidence].join(' ');
   if (/expired|inactive|restore|ended|khôi phục|kết thúc/i.test(attrs)) continue;
   const match = evidence.match(/\b(\d{1,5})\b/);
   if (match && Number(match[1]) >= 3) return evidence.slice(0, 160);
 }
 return null;
}'''

ROW_JS = r'''(elements) => elements.map(el => {
 const nameEl = el.querySelector('[data-e2e="dm-new-conversation-nickname"], [data-e2e="chat-list-item-name"], [data-e2e="chat-list-item-title"], [class*="Nickname"], [class*="NickName"], [class*="UserName"]');
 const link = el.matches('a') ? el : el.querySelector('a[href*="/messages"]');
 const conversationId = el.getAttribute('data-conv-id') || el.closest('[data-conversation-id]')?.getAttribute('data-conversation-id') || '';
 let fiber = el[Object.keys(el).find(k => k.startsWith('__reactFiber$'))];
 let conversation = null;
 for (let depth=0; fiber && depth<8 && !conversation; depth++,fiber=fiber.return) {
   let hook=fiber.memoizedState;
   for (let n=0; hook && n<60; n++,hook=hook.next) {
     const value=hook.memoizedState?.current;
     if (conversationId && value?.id===conversationId && 'ext' in value) { conversation=value; break; }
   }
 }
 const metadataKeys = [];
 if (conversation) for (const source of ['ext','bizCorePersistentExtra','bizSettingPersistentExtra','extend']) {
   try { metadataKeys.push(...Object.keys(conversation[source]||{}).filter(k=>/streak|flame/i.test(k))); } catch {}
 }
 return {name: nameEl ? nameEl.textContent.trim() : '', href: link ? link.href : '',
   conversation_id:conversationId, metadata_checked:Boolean(conversation), metadata_streak_keys:metadataKeys};
})'''

# Capture each row and its badge in the same browser turn. TikTok can replace
# virtualized rows between separate calls; indexing the old snapshot loses rows.
SCAN_ROWS_JS = '''elements => {
 const read = (''' + ROW_JS + ''');
 const badge = (''' + BADGE_JS + ''');
 return read(elements).map((info, i) => ({...info, badge: badge(elements[i])}));
}'''


class TikTokBrowser:
    def __init__(self, root, inspect=False):
        self.root = root
        self.inspect = inspect
        self.playwright = None
        self.context = None
        self.page = None
        self.channel = None
        self.row_selector = ROW_SELECTOR
        self.editor = None
        self.active_target = None
        self.imported_username = None
        self.message_selector = '[data-e2e="dm-new-chat-item"], [data-e2e="chat-message"]'

    def open(self, channel='chrome'):
        from playwright.sync_api import sync_playwright
        if channel not in ('chrome', 'msedge'):
            raise ValueError('Chọn Chrome hoặc Edge.')
        self.close()
        try:
            self.playwright = sync_playwright().start()
            args = ['--start-maximized']
            if self.inspect:
                args += ['--remote-debugging-address=127.0.0.1', '--remote-debugging-port=9223']
            self.context = self.playwright.chromium.launch_persistent_context(
                str(self.root / 'browser-profile' / channel), channel=channel,
                headless=False, args=args, no_viewport=True, timeout=30000)
            self.channel = channel
            self.imported_username = apply_session_import(self.context, self.root / 'session-import.json')
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
            self.page.set_default_timeout(15000)
        except Exception as exc:
            self.close()
            name = 'Chrome' if channel == 'chrome' else 'Edge'
            raise RuntimeError(f'Không mở được {name}. Kiểm tra đã cài trình duyệt hoặc chọn trình duyệt khác. {str(exc).splitlines()[0]}') from exc

    def pump(self):
        """Process close/navigation events even while the worker is idle."""
        if self.context is None:
            return False
        try:
            live = [page for page in self.context.pages if not page.is_closed()]
            if not live:
                return False
            if self.page not in live:
                self.page = next((p for p in live if 'tiktok.com' in p.url), live[0])
                self.page.set_default_timeout(15000)
            self.page.wait_for_timeout(1)
            return not self.page.is_closed() and self.context.browser.is_connected()
        except Exception:
            return False

    def ensure_open(self, channel='chrome'):
        if self.channel != channel or not self.pump():
            self.open(channel)
            return True
        return False

    def read_account(self):
        from urllib.parse import urlparse
        if self.page is None or self.page.is_closed():
            return {'authenticated': False}
        url = urlparse(self.page.url)
        if url.hostname != 'www.tiktok.com':
            return None
        account = self.page.evaluate(ACCOUNT_JS)
        if account and account.get('authenticated') and self.imported_username:
            if account.get('username', '').casefold() != self.imported_username.casefold():
                raise RuntimeError('Phiên nhập không khớp tài khoản yêu cầu. Kiểm tra lại tài khoản trên trình duyệt VPS.')
            (self.root / 'session-import.json').unlink(missing_ok=True)
            self.imported_username = None
        return account

    def day_clock(self):
        return self.page.evaluate(DAY_CLOCK_JS)

    def reply_candidates(self, targets):
        source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        snapshot = self.page.evaluate(source, {'replyScan': True,
            'allowedIds': [target['conversation_id'] for target in targets if target.get('conversation_id')]})
        if snapshot.get('error'):
            raise RuntimeError('Chưa đọc được tin mới từ TikTok.')
        return snapshot.get('candidates', [])

    def chat_context(self, conversation_id):
        from streak_history import USER_TYPES
        source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        snapshot = self.page.evaluate(source, {'conversationId': conversation_id, 'chatContext': True, 'limit': 50})
        if snapshot.get('error'):
            raise RuntimeError('Chưa đọc được ngữ cảnh cuộc trò chuyện.')
        messages = [message for message in snapshot.get('messages', []) if message.get('valid')
                    and message.get('type') in USER_TYPES and message.get('direction') in ('self', 'peer')]
        messages.sort(key=lambda message: (message['at'], len(message['id']), message['id']))
        return {'messages': [{'id': message['id'], 'at': message['at'],
                 'role': 'assistant' if message['direction'] == 'self' else 'user', 'content': message.get('text', '')}
                 for message in messages[-12:]], 'day': snapshot['today'], 'timezone': snapshot['timezone']}

    def login(self, qr=False):
        from playwright.sync_api import Error
        from urllib.parse import urlparse
        channel = self.channel or 'chrome'
        self.ensure_open(channel)
        url = ('https://www.tiktok.com/login/qrcode?redirect_url=https%3A%2F%2Fwww.tiktok.com%2Fmessages'
               if qr else 'https://www.tiktok.com/messages')
        if qr:
            for popup in list(self.context.pages):
                parsed = urlparse(popup.url)
                if popup != self.page and parsed.hostname == 'accounts.google.com' and '/signin/rejected' in parsed.path:
                    popup.close()
        try:
            self.page.bring_to_front()
            self.page.goto(url, wait_until='domcontentloaded', timeout=60000)
        except Error:
            if self.pump():
                raise
            # Only navigation is retried. Sending is never retried automatically.
            self.open(channel)
            self.page.goto(url, wait_until='domcontentloaded', timeout=60000)

    def ensure_inbox(self):
        from urllib.parse import urlparse
        url = urlparse(self.page.url)
        if url.hostname != 'www.tiktok.com' or not url.path.startswith('/messages'):
            self.login()
        self.page.locator(self.row_selector).first.wait_for(state='visible', timeout=20000)
        self.dismiss_sleep_reminder()

    def dismiss_sleep_reminder(self, page=None):
        """Use TikTok's temporary return button without changing reminder settings."""
        reminder = (page or self.page).locator('[class*="SleepHoursContainer"]:visible')
        if not reminder.count():
            return False
        button = reminder.get_by_role('button', name=re.compile(r'^Return for now$', re.I))
        if button.count() != 1 or not button.is_visible():
            raise RuntimeError('TikTok đang hiện nhắc giờ ngủ. Mở Màn hình Chrome để xác nhận trước khi gửi.')
        button.click(timeout=5000)
        reminder.first.wait_for(state='hidden', timeout=5000)
        return True

    def rows(self):
        return self.page.locator(self.row_selector)

    def history_evidence(self, conversation_id, stop=None, max_pages=16):
        source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        messages = {}
        cursor = None
        evidence = {'status': 'unknown', 'reason': 'history_not_loaded'}
        for _ in range(max_pages):
            if stop is not None and stop.is_set():
                return {'status': 'unknown', 'reason': 'cancelled'}
            page = self.page.evaluate(source, {'conversationId': conversation_id, 'cursor': cursor, 'limit': 50})
            if page.get('error'):
                return {'status': 'unknown', 'reason': page['error']}
            for message in page.get('messages', []):
                messages[message['id']] = message
            snapshot = {**page, 'messages': list(messages.values())}
            evidence = analyze_history(snapshot)
            evidence['reply'] = analyze_reply(snapshot)
            if (evidence['status'] == 'history_confirmed' and evidence['reply']['status'] != 'unknown') or evidence['reason'] == 'later_end_notice':
                return evidence
            if messages:
                oldest = min(date.fromisoformat(message['day']) for message in messages.values())
                missing = date.fromisoformat(evidence['anchor_day']) - timedelta(days=evidence['days_lower_bound'])
                if oldest < missing:
                    return evidence
            next_cursor = page.get('next_cursor')
            if not page.get('has_more') or not next_cursor or next_cursor == cursor:
                return evidence
            cursor = next_cursor
            self.page.wait_for_timeout(250)
        evidence['history_limited'] = True
        return evidence

    def reply_status(self, conversation_id, stop=None, max_pages=40):
        if not conversation_id:
            return {'status': 'unknown', 'reason': 'conversation_id_missing'}
        source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        cursor = None
        messages = {}
        result = {'status': 'unknown'}
        for _ in range(max_pages):
            if stop is not None and stop.is_set():
                return {'status': 'unknown', 'reason': 'cancelled'}
            snapshot = self.page.evaluate(source, {'conversationId': conversation_id, 'cursor': cursor, 'limit': 50})
            if snapshot.get('error'):
                return {'status': 'unknown', 'reason': snapshot['error']}
            for message in snapshot.get('messages', []):
                messages[message['id']] = message
            result = analyze_reply({**snapshot, 'messages': list(messages.values())})
            if result['status'] != 'unknown':
                return result
            next_cursor = snapshot.get('next_cursor')
            if not snapshot.get('has_more') or not next_cursor or next_cursor == cursor:
                break
            cursor = next_cursor
            self.page.wait_for_timeout(150)
        return result

    def restore_streak(self, target, expected_username, stop=None):
        account = self.read_account()
        if not account or not account.get('authenticated') or account.get('username') != expected_username:
            raise RuntimeError('Chưa xác nhận đúng tài khoản để khôi phục chuỗi.')
        evidence = self.history_evidence(target['conversation_id'], stop=stop)
        notice = evidence.get('recovery')
        if not notice:
            return {'status': 'not_needed', 'evidence': evidence}
        if notice['status'] != 'available':
            return {'status': 'unavailable', 'evidence': evidence}
        source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        context = self.page.evaluate(source, {'conversationId': target['conversation_id'], 'recoveryContext': True})
        if context.get('conversation_id') != target['conversation_id']:
            raise RuntimeError('Chưa xác nhận ID cuộc trò chuyện để khôi phục.')
        cookies = self.context.cookies('https://www.tiktok.com')
        user_agent = self.page.evaluate('navigator.userAgent')
        def verify():
            result = {}
            for _ in range(10):
                if stop is not None and stop.is_set():
                    break
                current = self.read_account()
                if not current or current.get('username') != expected_username:
                    break
                result = self.history_evidence(target['conversation_id'], stop=stop)
                if result.get('restored') and result.get('marker_at', 0) >= notice['ended_at']:
                    break
                self.page.wait_for_timeout(1000)
            return result
        manager = RecoveryManager(self.root / 'recovery-state.json')
        result = manager.restore(expected_username, self.channel, target, evidence,
                                 lambda: restore_request(context, cookies, user_agent), verify)
        return {'evidence': evidence, **result}

    def scan(self, stop, on_progress=None):
        self.ensure_inbox()
        # Scroll the chat list itself, including virtualized lists, then return to top.
        self.rows().first.evaluate('el => { let p=el.parentElement; while(p && p.scrollHeight <= p.clientHeight+5) p=p.parentElement; if(p) p.scrollTop=0; }')
        self.page.wait_for_timeout(500)
        found = {}
        seen = set()
        unchanged = 0
        for _ in range(150):
            if stop.is_set():
                break
            rows = self.rows()
            infos = rows.evaluate_all(SCAN_ROWS_JS)
            old_count = len(seen)
            names = [i['name'] for i in infos]
            for info in infos:
                name = info['name']
                if not name:
                    continue
                key = ('conv:' + info['conversation_id']) if info['conversation_id'] else info['href'] or 'name:' + name
                seen.add(key)
                badge = info['badge']
                unique = bool(info['conversation_id']) or names.count(name) == 1
                found[key] = {'key': key, 'name': name, 'href': info['href'], 'conversation_id': info['conversation_id'],
                              'badge': badge or '', 'streak_status': 'verified' if badge and unique else 'unknown',
                              'metadata_checked': info['metadata_checked'], 'metadata_streak_keys': info['metadata_streak_keys']}
            unchanged = unchanged + 1 if len(seen) == old_count else 0
            if unchanged >= 3:
                break
            self.rows().last.evaluate('el => { let p=el.parentElement; while(p && p.scrollHeight <= p.clientHeight+5) p=p.parentElement; if(p) p.scrollTop += Math.max(p.clientHeight * .8, 200); }')
            self.page.wait_for_timeout(450)
        self.rows().first.evaluate('el => { let p=el.parentElement; while(p && p.scrollHeight <= p.clientHeight+5) p=p.parentElement; if(p) p.scrollTop=0; }')
        source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        try:
            manifest = self.page.evaluate(source, {})
        except Exception:
            manifest = {'error': 'messaging_sdk_unavailable'}
        if not manifest.get('error'):
            metadata = {item['conversation_id']: item for item in manifest.get('conversations', [])}
            for row in found.values():
                row['is_group'] = metadata.get(row['conversation_id'], {}).get('is_group', False)
            recent = {item['conversation_id'] for item in manifest.get('conversations', [])
                      if item['latest_at'] >= manifest['checked_at'] - 3 * 86400}
            candidates = [row for row in found.values() if row['conversation_id'] in recent]
            errors = 0
            for i, row in enumerate(candidates):
                if stop.is_set():
                    break
                if on_progress:
                    on_progress(i, len(candidates), sum(r['streak_status'] == 'history_confirmed' for r in found.values()))
                try:
                    evidence = self.history_evidence(row['conversation_id'], stop=stop)
                except Exception:
                    evidence = {'status': 'unknown', 'reason': 'history_read_failed'}
                    errors += 1
                row['history_evidence'] = evidence
                row['reply'] = evidence.get('reply', {'status': 'unknown'})
                if evidence['status'] == 'history_confirmed' and row['streak_status'] != 'verified':
                    row.update(streak_status='history_confirmed', verification_source='system_history',
                               badge=f"≥{evidence['days_lower_bound']} ngày · lịch sử TikTok")
                if errors >= 3:
                    break
            if on_progress:
                on_progress(len(candidates), len(candidates), sum(r['streak_status'] == 'history_confirmed' for r in found.values()))
        return list(found.values()), len(seen)

    def find_target(self, target, history_validated=False):
        self.ensure_inbox()
        self.rows().first.evaluate('el => { let p=el.parentElement; while(p && p.scrollHeight <= p.clientHeight+5) p=p.parentElement; if(p) p.scrollTop=0; }')
        self.page.wait_for_timeout(350)
        last = None
        for _ in range(150):
            rows = self.rows()
            infos = rows.evaluate_all(ROW_JS)
            matches = [i for i, info in enumerate(infos) if
                       (info['conversation_id'] == target['conversation_id'] if target.get('conversation_id') else
                        info['name'] == target['name'] and (not target['href'] or info['href'] == target['href']))]
            if len(matches) > 1:
                raise RuntimeError('Tên trùng; không đủ thông tin để chọn đúng người.')
            if matches:
                row = rows.nth(matches[0])
                if not history_validated and not row.evaluate(BADGE_JS):
                    raise RuntimeError('Không còn xác minh được huy hiệu chuỗi trên người nhận.')
                return row
            signature = repr(infos)
            if signature == last:
                break
            last = signature
            rows.last.evaluate('el => { let p=el.parentElement; while(p && p.scrollHeight <= p.clientHeight+5) p=p.parentElement; if(p) p.scrollTop += Math.max(p.clientHeight * .8, 200); }')
            self.page.wait_for_timeout(450)
        raise RuntimeError('Không tìm thấy đúng người nhận trong danh sách.')

    def prepare(self, target):
        from playwright.sync_api import expect
        history_validated = False
        if target.get('streak_status') == 'history_confirmed':
            self.ensure_inbox()
            evidence = self.history_evidence(target['conversation_id'])
            if evidence['status'] != 'history_confirmed':
                raise RuntimeError('Lịch sử hiện tại không còn đủ bằng chứng chuỗi. Quét lại trước khi gửi.')
            history_validated = True
        row = self.find_target(target, history_validated=history_validated)
        self.dismiss_sleep_reminder()
        row.click()
        if target.get('conversation_id'):
            selected = self.page.locator('[data-e2e="dm-new-conversation-item"][aria-selected="true"]')
            expect(selected).to_have_count(1)
            expect(selected).to_have_attribute('data-conv-id', target['conversation_id'])
        # Verify chat header independently of the clicked sidebar row.
        header = self.page.locator('[data-e2e="dm-new-chatbox"] > [class*="DivChatHeader"], [data-e2e="chat-header"]')
        expect(header).to_be_visible()
        name = header.locator('[data-e2e="dm-new-chat-nickname"], [data-e2e="chat-title"], [data-e2e="chat-header-name"]')
        try:
            expect(name).to_have_text(target['name'], timeout=5000)
        except Exception:
            raise RuntimeError('Tên trên đầu cuộc trò chuyện không khớp người đã chọn.')
        if not history_validated and not header.evaluate(BADGE_JS):
            raise RuntimeError('Không thấy huy hiệu chuỗi trên đầu cuộc trò chuyện; không gửi.')
        self.editor = self.page.locator('[data-e2e="dm-new-input-editor"] [contenteditable="true"], [contenteditable="true"][data-e2e="message-input"]')
        expect(self.editor).to_be_visible()
        if self.editor.count() != 1 or self.editor.inner_text().strip():
            raise RuntimeError('Ô nhập không duy nhất hoặc có bản nháp.')
        try:
            self.page.locator(self.message_selector).first.wait_for(state='visible', timeout=15000)
        except Exception:
            raise RuntimeError('Chưa xác định được vùng tin nhắn để kiểm chứng gửi thành công.') from None
        self.active_target = target

    def send(self, message):
        from playwright.sync_api import expect
        self.dismiss_sleep_reminder()
        # Count occurrences inside chat message nodes, excluding the editor and sidebar.
        matches = self.page.locator(self.message_selector).filter(has=self.page.get_by_text(message, exact=True))
        before = matches.count()
        modern = self.page.locator('[data-e2e="dm-new-chatbox"]').count() > 0
        history_source = (Path(__file__).parent / 'browser' / 'history.js').read_text(encoding='utf-8')
        check_payload = {'conversationId': (self.active_target or {}).get('conversation_id'), 'sentText': message}
        known_ids = set()
        if modern:
            if not check_payload['conversationId']:
                raise RuntimeError('Chưa xác định ID người nhận để kiểm tra kết quả gửi.')
            snapshot = self.page.evaluate(history_source, check_payload)
            if 'matches' not in snapshot:
                raise RuntimeError('Chưa kết nối dữ liệu xác nhận gửi của TikTok.')
            known_ids = {item['id'] for item in snapshot['matches']}
        self.editor.fill(message)
        if modern:
            button = self.page.locator('[data-e2e="dm-new-send-btn"]')
            expect(button).to_be_visible(timeout=5000)
            button.click()
        else:
            self.editor.press('Enter')
        expect(self.editor).to_be_empty(timeout=15000)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if modern:
                result = self.page.evaluate(history_source, check_payload)
                new_messages = [item for item in result.get('matches', []) if item['id'] not in known_ids]
                if any(item['server_id'] and (item['response_status'] == '0' or item['state'] in (3, 4)) for item in new_messages):
                    return
                if any(item['state'] in (-1, -2, -3) or item['response_status'] not in (None, '', '0') for item in new_messages):
                    raise RuntimeError('TikTok báo lỗi hoặc từ chối tin nhắn. Kiểm tra cuộc trò chuyện trước khi thử lại.')
            elif matches.count() > before:
                return
            self.page.wait_for_timeout(300)
        raise RuntimeError('Chưa xác nhận được tin mới đã gửi thành công. Kiểm tra chat trước khi thử lại.')

    def send_video(self, video, dry_run=False, expected_username=None):
        if not self.active_target or not self.active_target.get('conversation_id'):
            raise RuntimeError('Chưa xác nhận người nhận video.')
        source=(Path(__file__).parent/'browser'/'history.js').read_text(encoding='utf-8')
        context=self.page.evaluate(source,{'conversationId':self.active_target['conversation_id'],'recoveryContext':True})
        if not context.get('self_id'):raise RuntimeError('Chưa xác nhận tài khoản chia sẻ video.')
        account=self.read_account()
        if not account or not account.get('authenticated') or (expected_username and account['username']!=expected_username):
            raise RuntimeError('Tài khoản đã thay đổi trước khi chia sẻ video.')
        script=(Path(__file__).parent/'browser'/'share_video.js').read_text(encoding='utf-8')
        result=self.page.evaluate(script,{'conversationId':self.active_target['conversation_id'],
            'expectedSelfId':context['self_id'],'expectedUsername':expected_username or account['username'],'video':video,'dryRun':dry_run})
        if not result.get('ready' if dry_run else 'sent'):
            raise RuntimeError('Chưa xác nhận chia sẻ video thành công: '+str(result.get('error','unknown')))
        return result

    def close(self):
        context, playwright = self.context, self.playwright
        self.context = self.playwright = self.page = self.editor = None
        self.active_target = None
        self.channel = None
        try:
            if context:
                context.close()
        except Exception:
            pass
        finally:
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass
