"""Offline regression checks for recipient selection and ambiguous send handling."""
import sys
import tempfile
import threading
import unittest
import time
from datetime import date, datetime, timezone
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tiktok_browser import BADGE_JS, DAY_CLOCK_JS, TikTokBrowser
from playwright.sync_api import sync_playwright


class BrowserChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = sync_playwright().start()
        cls.browser = cls.p.chromium.launch(headless=True, channel='chrome' if sys.platform == 'win32' else None)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.p.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.tmp = tempfile.TemporaryDirectory()
        self.adapter = TikTokBrowser(Path(self.tmp.name))
        self.adapter.page = self.page
        self.page.set_default_timeout(5000)

    def tearDown(self):
        self.context.close()
        self.tmp.cleanup()

    def test_fire_emoji_and_number_in_message_do_not_count_as_streak(self):
        self.page.set_content('<div id="row"><strong>Alice 🔥 99</strong><p>Giữ chuỗi 🔥 30</p></div>')
        self.assertIsNone(self.page.locator('#row').evaluate(BADGE_JS))

    def test_profile_alt_text_is_not_a_streak_badge(self):
        self.page.set_content('<div id="row"><img alt="streak 99" src="data:,avatar"><span aria-label="streak 99">A profile name</span></div>')
        self.assertIsNone(self.page.locator('#row').evaluate(BADGE_JS))

    def test_modern_chat_scan_keeps_unknown_rows_and_distinguishes_duplicate_names(self):
        self.fixture()
        self.page.set_content('''<div data-e2e="dm-new-conversation-item" data-conv-id="one">
          <p data-e2e="dm-new-conversation-nickname">Alice</p><span>🔥 30</span></div>
          <div data-e2e="dm-new-conversation-item" data-conv-id="two">
          <p data-e2e="dm-new-conversation-nickname">Alice</p><span>Another conversation</span></div>''')
        rows, total = self.adapter.scan(threading.Event())
        self.assertEqual(total, 2)
        self.assertEqual({row['key'] for row in rows}, {'conv:one', 'conv:two'})
        self.assertTrue(all(row['streak_status'] == 'unknown' for row in rows))

    def test_streak_invitation_metadata_is_not_proof_of_active_streak(self):
        self.fixture()
        self.page.set_content('''<div data-e2e="dm-new-conversation-item" data-conv-id="one">
          <p data-e2e="dm-new-conversation-nickname">Alice</p></div>''')
        self.page.evaluate('''() => {
          const row=document.querySelector('[data-conv-id]');
          row['__reactFiber$fixture']={memoizedState:{memoizedState:{current:{id:'one',ext:{'a:streak_info':{invite_source:'old invitation'}}}}}};
        }''')
        rows, _ = self.adapter.scan(threading.Event())
        self.assertTrue(rows[0]['metadata_checked'])
        self.assertEqual(rows[0]['metadata_streak_keys'], ['a:streak_info'])
        self.assertEqual(rows[0]['streak_status'], 'unknown')

    def test_scan_keeps_row_and_badge_together_when_list_rerenders(self):
        from playwright.sync_api import Locator
        self.fixture()
        self.page.set_content('''<div data-e2e="dm-new-conversation-item" data-conv-id="one">
          <p data-e2e="dm-new-conversation-nickname">Alice</p><span class="streak">30</span></div>
          <div data-e2e="dm-new-conversation-item" data-conv-id="two">
          <p data-e2e="dm-new-conversation-nickname">Bob</p></div>''')
        original = Locator.evaluate_all
        replaced = False
        def rerender(locator, expression, *args, **kwargs):
            nonlocal replaced
            result = original(locator, expression, *args, **kwargs)
            if not replaced:
                replaced = True
                self.page.locator('[data-conv-id="two"]').evaluate('el => el.remove()')
            return result
        with patch.object(Locator, 'evaluate_all', rerender):
            rows, total = self.adapter.scan(threading.Event())
        rows = {row['name']: row for row in rows}
        self.assertEqual(total, 2)
        self.assertEqual(rows['Alice']['streak_status'], 'verified')
        self.assertEqual(rows['Bob']['streak_status'], 'unknown')

    def test_hidden_and_expired_badges_are_excluded(self):
        self.page.set_content('<div id="row"><span class="streak expired">99</span><span class="streak" style="display:none">42</span></div>')
        self.assertIsNone(self.page.locator('#row').evaluate(BADGE_JS))

    def test_sleep_reminder_returns_to_inbox_without_changing_settings(self):
        target = self.fixture()
        self.page.evaluate('''() => {
          const reminder=document.createElement('div');
          reminder.className='css-fixture--SleepHoursContainer';
          reminder.style='position:fixed;inset:0;background:black;z-index:9999';
          reminder.innerHTML='<h1>Sleep hours</h1><button>Return for now</button><button>Edit sleep hours</button>';
          reminder.querySelector('button').onclick=()=>reminder.remove();
          reminder.lastElementChild.onclick=()=>window.changedSleepSettings=true;
          document.body.append(reminder);
        }''')
        self.adapter.prepare(target)
        self.assertFalse(self.page.locator('[class*="SleepHoursContainer"]').count())
        self.assertFalse(self.page.evaluate('Boolean(window.changedSleepSettings)'))
        self.assertEqual(self.adapter.editor.inner_text(), '')

    def test_unrecognized_sleep_gate_and_other_dialogs_are_not_bypassed(self):
        self.fixture()
        self.page.evaluate('''() => {
          document.body.insertAdjacentHTML('beforeend', '<div class="SleepHoursContainer"><button>Ask parent for more time</button></div>');
        }''')
        with self.assertRaisesRegex(RuntimeError, 'nhắc giờ ngủ'):
            self.adapter.dismiss_sleep_reminder()
        self.page.locator('[class*="SleepHoursContainer"]').evaluate('el=>el.remove()')
        self.page.evaluate('''() => {
          document.body.insertAdjacentHTML('beforeend', '<div role="dialog"><button>Return for now</button></div>');
        }''')
        self.assertFalse(self.adapter.dismiss_sleep_reminder())
        self.assertTrue(self.page.get_by_role('dialog').is_visible())

    def test_account_identity_comes_from_own_profile_navigation(self):
        self.fixture()
        self.page.set_content('''<a data-e2e="nav-profile" href="/@owner">Profile<img src="/avatar.png"></a>
          <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
          {"__DEFAULT_SCOPE__":{"webapp.app-context":{"user":{"uniqueId":"owner","nickName":"My account"}},
          "webapp.user-detail":{"userInfo":{"user":{"uniqueId":"friend","nickname":"Someone else"}}}}}
          </script>''')
        account = self.adapter.read_account()
        self.assertTrue(account['authenticated'])
        self.assertEqual(account['username'], 'owner')
        self.assertEqual(account['display_name'], 'My account')
        self.assertTrue(account['avatar_url'].endswith('/avatar.png'))

    def test_logged_out_dom_ignores_stale_account_hydration(self):
        self.fixture()
        self.page.set_content('''<button data-e2e="top-login-button">Log in</button>
          <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
          {"__DEFAULT_SCOPE__":{"webapp.app-context":{"user":{"uniqueId":"oldowner","nickName":"Old account"}}}}
          </script>''')
        self.assertFalse(self.adapter.read_account()['authenticated'])

    def test_loading_page_without_profile_is_unknown_not_logged_out(self):
        self.fixture()
        self.page.set_content('<main>Loading TikTok…</main>')
        self.assertIsNone(self.adapter.read_account())

    def test_account_name_cannot_come_from_mismatched_hydration(self):
        self.fixture()
        self.page.set_content('''<a data-e2e="nav-profile" href="/@newowner">Profile</a>
          <script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">
          {"__DEFAULT_SCOPE__":{"webapp.app-context":{"user":{"uniqueId":"oldowner","nickName":"Old account"}}}}
          </script>''')
        self.assertEqual(self.adapter.read_account()['display_name'], 'newowner')

    def fixture(self, header='Alice', badge=True):
        self.page.route('https://www.tiktok.com/**', lambda route: route.fulfill(body=f'''<html><body>
          <div data-e2e="chat-list-item"><b data-e2e="chat-list-item-name">Alice</b><span class="streak">30</span></div>
          <div data-e2e="chat-header"><b data-e2e="chat-title">{header}</b>{'<span class="streak">30</span>' if badge else ''}</div>
          <div data-e2e="chat-message"><span>Old message</span></div>
          <div contenteditable="true" data-e2e="message-input"></div>
          </body></html>''', content_type='text/html'))
        self.page.goto('https://www.tiktok.com/messages')
        return {'name': 'Alice', 'href': '', 'key': 'name:Alice'}

    def test_changed_recipient_header_blocks_sending(self):
        target = self.fixture(header='Bob')
        with self.assertRaisesRegex(RuntimeError, 'không khớp'):
            self.adapter.prepare(target)

    def test_missing_header_badge_blocks_sending(self):
        target = self.fixture(badge=False)
        with self.assertRaisesRegex(RuntimeError, 'huy hiệu'):
            self.adapter.prepare(target)

    def test_history_target_is_rechecked_before_opening_or_sending(self):
        target = self.fixture()
        target.update(streak_status='history_confirmed', conversation_id='one')
        with patch.object(self.adapter, 'history_evidence', return_value={'status':'unknown','reason':'later_end_notice'}):
            with self.assertRaisesRegex(RuntimeError, 'không còn đủ'):
                self.adapter.prepare(target)
        self.assertEqual(self.page.locator('[contenteditable]').inner_text(), '')

    def test_existing_draft_is_preserved(self):
        target = self.fixture()
        editor = self.page.locator('[contenteditable]')
        editor.fill('My unfinished draft')
        with self.assertRaisesRegex(RuntimeError, 'bản nháp'):
            self.adapter.prepare(target)
        self.assertEqual(editor.inner_text(), 'My unfinished draft')

    def test_qr_login_uses_tiktok_and_only_closes_rejected_google_popup(self):
        self.fixture()
        self.adapter.context = self.context
        self.adapter.channel = 'chrome'
        popup = self.context.new_page()
        popup.route('https://accounts.google.com/**', lambda route: route.fulfill(body='Sign-in rejected'))
        popup.goto('https://accounts.google.com/v3/signin/rejected')
        other = self.context.new_page()
        self.adapter.login(qr=True)
        self.assertTrue(self.page.url.startswith('https://www.tiktok.com/login/qrcode?'))
        self.assertTrue(popup.is_closed())
        self.assertFalse(other.is_closed())

    def test_send_requires_new_message_in_chat(self):
        target = self.fixture()
        self.adapter.prepare(target)
        self.page.evaluate('''() => document.querySelector('[contenteditable]').addEventListener('keydown', event => {
          if(event.key === 'Enter') {
            event.preventDefault();
            const item = document.createElement('div'); item.dataset.e2e='chat-message';
            const text = document.createElement('span'); text.textContent=event.target.textContent;
            item.appendChild(text); document.body.appendChild(item); event.target.textContent='';
          }
        })''')
        self.adapter.send('Giữ chuỗi nha 🔥')
        self.assertEqual(self.page.locator('[data-e2e="chat-message"]').count(), 2)

    def modern_send_fixture(self, rejected=False):
        self.page.set_content('''<div data-e2e="dm-new-conversation-item" data-conv-id="one">Alice</div>
          <div data-e2e="dm-new-chatbox"><div data-e2e="dm-new-chat-item"><span>Old message</span></div>
          <div data-e2e="dm-new-input-editor"><div contenteditable="true"></div></div>
          <button data-e2e="dm-new-send-btn">Send</button></div>''')
        self.page.evaluate('''rejected => {
          const messages=[];
          const conv={id:'one',isSingleChat:true,isStrangerConversation:false,toParticipantUserId:'peer',getMessageList:()=>messages};
          const sdk={getConversationList:()=>[conv],ctx:{option:{userId:'self'}}};
          const row=document.querySelector('[data-conv-id]');
          row['__reactFiber$fixture']={memoizedState:{memoizedState:{current:{instance:sdk,stateStore:{}}}}};
          document.querySelector('[data-e2e="dm-new-send-btn"]').onclick=()=>{
            const editor=document.querySelector('[contenteditable]');const text=editor.innerText;
            const item=document.createElement('div');item.dataset.e2e='dm-new-chat-item';
            const span=document.createElement('span');span.textContent=text;item.append(span);document.querySelector('[data-e2e="dm-new-chatbox"]').prepend(item);
            messages.push({type:7,sender:'self',content:JSON.stringify({text}),clientId:'new-client',serverId:rejected?'':'new-server',flightStatus:rejected?-2:3,ext:{'s:send_response_status':rejected?'1':'0'}});
            editor.innerText='';
          };
        }''', rejected)
        self.adapter.editor = self.page.locator('[contenteditable]')
        self.adapter.active_target = {'conversation_id': 'one'}

    def test_modern_send_waits_for_tiktok_acknowledgement(self):
        self.modern_send_fixture()
        self.adapter.send('Keep the streak')
        self.assertEqual(self.page.locator('[data-e2e="dm-new-chat-item"]').count(), 2)

    def test_visible_bubble_with_rejected_status_is_not_success(self):
        self.modern_send_fixture(rejected=True)
        with self.assertRaisesRegex(RuntimeError, 'từ chối'):
            self.adapter.send('Keep the streak')

    def video_share_fixture(self, group=False, success=True, server_id='999'):
        self.fixture()
        self.page.set_content('<a data-e2e="nav-profile" href="/@owner">Me</a><div data-e2e="dm-new-conversation-item" data-conv-id="one" aria-selected="true"></div>')
        self.page.evaluate('''options=>{
          window.sentVideos=[];window.createdVideos=[];
          const conv={id:'one',isSingleChat:!options.group,isGroupChat:options.group,isMember:true,isStrangerConversation:false};
          const sdk={ctx:{option:{userId:'10'}},getConversationList:()=>[conv],
            createMessage:async args=>{window.createdVideos.push({cid:args.conversation.id,type:args.type,content:JSON.parse(args.content)});return{serverId:'0'}},
            sendMessage:async()=>{window.sentVideos.push(true);return{success:options.success,serverMessageId:options.server_id}}};
          document.querySelector('[data-conv-id]')['__reactFiber$fixture']={memoizedState:{memoizedState:{current:{instance:sdk,stateStore:{}}}}};
        }''',{'group':group,'success':success,'server_id':server_id})
        return {'conversationId':'one','expectedSelfId':'10','expectedUsername':'owner',
                'video':{'id':'7000000000000000001','author_id':'42','caption':'fixture'}}

    def test_native_video_share_preserves_type_and_group_recipient(self):
        source=(Path(__file__).resolve().parents[1]/'browser'/'share_video.js').read_text()
        for group in (False,True):
            args=self.video_share_fixture(group=group)
            self.assertTrue(self.page.evaluate(source,{**args,'dryRun':True})['ready'])
            self.assertFalse(self.page.evaluate('window.createdVideos.length'))
            self.assertTrue(self.page.evaluate(source,args)['sent'])
            created=self.page.evaluate('window.createdVideos[0]')
            self.assertEqual(created['cid'],'one');self.assertEqual(created['type'],8)
            self.assertEqual(created['content']['itemId'],args['video']['id'])

    def test_video_share_rejects_changed_owner_and_zero_ack(self):
        source=(Path(__file__).resolve().parents[1]/'browser'/'share_video.js').read_text()
        args=self.video_share_fixture()
        self.assertEqual(self.page.evaluate(source,{**args,'expectedUsername':'other'})['error'],'account_mismatch')
        self.assertFalse(self.page.evaluate('window.sentVideos.length'))
        args=self.video_share_fixture(server_id='0')
        self.assertEqual(self.page.evaluate(source,args)['error'],'video_not_confirmed')

    def test_metadata_reader_does_not_copy_chat_text_without_context_flag(self):
        self.page.set_content('<div data-e2e="dm-new-conversation-item" data-conv-id="one"></div>')
        self.page.evaluate('''()=>{
          class Long {static fromString(){return new Long()}static fromNumber(){return new Long()}add(){return this}toString(){return'10'}}
          const messages=[{server_message_id:'12',message_type:7,create_time:Date.now()/1000-10,sender:'20',status:0,content:JSON.stringify({text:'fixture-private-chat'})}];
          const c={id:'one',isSingleChat:true,shortId:'1',toParticipantUserId:'20',firstMessageIndex:new Long(),lastMessageIndex:new Long()};
          const sdk={getConversationList:()=>[c],ctx:{option:{userId:'10'},resolve:()=>({GetMessagesByConversation:async()=>({status_code:0,body:{messages_in_conversation_body:{messages,has_more:false}}})})}};
          document.querySelector('[data-conv-id]')['__reactFiber$fixture']={memoizedState:{memoizedState:{current:{instance:sdk,stateStore:{}}}}};
        }''')
        source=(Path(__file__).resolve().parents[1]/'browser'/'history.js').read_text()
        self.assertNotIn('text',self.page.evaluate(source,{'conversationId':'one'})['messages'][0])
        self.assertEqual(self.page.evaluate(source,{'conversationId':'one','chatContext':True})['messages'][0]['text'],'fixture-private-chat')

    def test_reply_check_paginates_to_manual_reply_before_deciding(self):
        now=time.time();today=date.today().isoformat()
        base={'today':today,'timezone':'Asia/Bangkok','checked_at':now,'has_more':True}
        peer={'id':'one','at':now-60,'day':today,'type':7,'direction':'peer','valid':True}
        own={**peer,'id':'two','direction':'self'}
        with patch.object(self.page,'evaluate',side_effect=[{**base,'messages':[peer],'next_cursor':'2'},
                                                           {**base,'messages':[own],'next_cursor':'1'}]) as evaluate:
            self.assertEqual(self.adapter.reply_status('one')['status'],'replied')
            self.assertEqual(evaluate.call_count,2)

    def test_reply_check_does_not_assume_not_replied_when_history_is_limited(self):
        now=time.time();today=date.today().isoformat()
        page={'today':today,'timezone':'Asia/Bangkok','checked_at':now,'has_more':True,'next_cursor':'2',
              'messages':[{'id':'one','at':now-60,'day':today,'type':7,'direction':'peer','valid':True}]}
        with patch.object(self.page,'evaluate',return_value=page):
            self.assertEqual(self.adapter.reply_status('one',max_pages=1)['status'],'unknown')

    def test_sdk_reader_includes_groups_and_distinguishes_member_senders(self):
        self.page.set_content('<div data-e2e="dm-new-conversation-item" data-conv-id="group"></div>')
        self.page.evaluate('''() => {
          class Long {static fromString(x){return new Long()} static fromNumber(x){return new Long()} add(x){return this} toString(){return '10'}}
          const now=Date.now()/1000;
          const messages=['10','20','30','0'].map((sender,i)=>({sender,message_type:7,server_message_id:String(i+1),create_time:now-i,status:0,ext:{}}));
          const conv={id:'group',type:2,shortId:'10',isSingleChat:false,isGroupChat:true,isMember:true,
            firstMessageIndex:new Long(),lastMessageIndex:new Long(),getMessageList:()=>[],participantCount:3};
          const sdk={getConversationList:()=>[conv],ctx:{option:{userId:'10'},resolve:()=>({GetMessagesByConversation:async()=>({status_code:0,body:{messages_in_conversation_body:{messages,has_more:false,next_cursor:'0'}}})})}};
          document.querySelector('[data-conv-id]')['__reactFiber$fixture']={memoizedState:{memoizedState:{current:{instance:sdk,stateStore:{}}}}};
        }''')
        source=(Path(__file__).resolve().parents[1]/'browser'/'history.js').read_text(encoding='utf-8')
        manifest=self.page.evaluate(source,{})
        self.assertTrue(manifest['conversations'][0]['is_group'])
        result=self.page.evaluate(source,{'conversationId':'group'})
        self.assertTrue(result['is_group'])
        self.assertEqual([m['direction'] for m in result['messages']],['self','peer','peer','system'])

    def test_midnight_clock_uses_browser_timezone_and_rolls_to_new_day(self):
        context=self.browser.new_context(timezone_id='Asia/Bangkok')
        try:
            page=context.new_page()
            page.clock.install(time=datetime(2026,11,14,16,59,50,tzinfo=timezone.utc))
            clock=page.evaluate(DAY_CLOCK_JS)
            self.assertEqual(clock['day'],'2026-11-14')
            self.assertEqual(clock['valid_until'],datetime(2026,11,14,17,tzinfo=timezone.utc).timestamp())
            page.clock.fast_forward(11000)
            self.assertEqual(page.evaluate(DAY_CLOCK_JS)['day'],'2026-11-15')
        finally:
            context.close()


if __name__ == '__main__':
    unittest.main()
