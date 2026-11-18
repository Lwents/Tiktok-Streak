"""AI transport and new-message idempotency, without contacting TikTok or an AI service."""
import io,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from ai_client import AIClient,AIError
from ai_reply import AIReplies

class Reply(io.BytesIO):
    pass
class Opener:
    def __init__(self,text='Chào bạn nha 😊'):self.text=text;self.requests=[]
    def open(self,request,timeout):
        self.requests.append(request)
        return Reply(json.dumps({'choices':[{'message':{'content':self.text},'finish_reason':'stop'}]}).encode())
class ClientChecks(unittest.TestCase):
    def client(self,opener=None):return AIClient({'base_url':'https://ai.example/v1','model':'fixture-model','api_key':'fixture-private-key'},opener=opener or Opener())
    def test_exact_model_and_auth_only_go_to_configured_proxy(self):
        opener=Opener();client=self.client(opener)
        text=client.reply([{'role':'user','content':'Hôm nay ổn không?','id':'private-id','name':'private-name'}])
        request=opener.requests[0];body=json.loads(request.data)
        self.assertEqual(request.full_url,'https://ai.example/v1/chat/completions')
        self.assertEqual(body['model'],'fixture-model')
        self.assertEqual(request.get_header('Authorization'),'Bearer fixture-private-key')
        self.assertNotIn('private-id',request.data.decode());self.assertNotIn('private-name',request.data.decode())
        self.assertEqual(text,'Chào bạn nha 😊')
    def test_empty_or_secret_echo_is_rejected(self):
        for text in ('','fixture-private-key','x'*501,'a\nb'):
            with self.subTest(text=text[:20]),self.assertRaises(AIError):self.client(Opener(text)).reply([{'role':'user','content':'hi'}])
    def test_http_error_does_not_expose_body_or_token(self):
        class Failed:
            def open(self,*args,**kwargs):raise HTTPError('https://ai.example',401,'fixture-private-key',{},None)
        with self.assertRaises(AIError) as error:self.client(Failed()).reply([{'role':'user','content':'hi'}])
        self.assertNotIn('fixture-private-key',str(error.exception))
    def test_insecure_urls_and_embedded_credentials_are_rejected(self):
        for url in ('http://ai.example/v1','https://user:pass@ai.example/v1','https://ai.example/v1?key=secret'):
            with self.assertRaises(AIError):AIClient({'base_url':url,'model':'test','api_key':'fixture'})

class FakeClient:
    base_url='https://ai.example/v1';model='test-model'
    def __init__(self,on_reply=None):self.calls=0;self.on_reply=on_reply
    def reply(self,*args,**kwargs):
        self.calls+=1
        if self.on_reply:self.on_reply()
        return 'Mình ổn nè, còn bạn?'
class Browser:
    def __init__(self,now):
        self.latest={'conversation_id':'one','id':'incoming-1','at':now-10};self.role='user';self.content='Bạn ổn không?';self.prepared=0;self.sends=[];self.fail_send=False
    def reply_candidates(self,targets):return [dict(self.latest)]
    def chat_context(self,cid):return {'messages':[{'id':self.latest['id'],'at':self.latest['at'],'role':self.role,'content':self.content}]}
    def prepare(self,target):self.prepared+=1
    def day_clock(self):return {'day':'2026-11-18','timezone':'Asia/Bangkok','valid_until':time.time()+3600}
    def send(self,text):
        self.sends.append(text)
        if self.fail_send:raise TimeoutError('unknown ACK')
class ReplyChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.events=[];self.now=time.time()
        self.engine=AIReplies(self.root,lambda *args:self.events.append(args));self.browser=Browser(self.now)
        self.payload={'account_username':'owner','ai_started_at':self.now-60,'targets':[{'key':'conv:one','conversation_id':'one','name':'Alice','streak_status':'history_confirmed'}]}
        self.client=FakeClient()
    def tearDown(self):self.tmp.cleanup()
    def run_job(self,engine=None,owner=lambda:True,stop=lambda:False):
        with patch('ai_reply.AIClient.from_root',return_value=self.client):(engine or self.engine).process(self.browser,self.payload,owner,stop)
    def test_new_incoming_is_answered_once_even_after_restart(self):
        self.run_job();self.run_job(AIReplies(self.root,lambda *args:None))
        self.assertEqual(len(self.browser.sends),1);self.assertEqual(self.client.calls,1)
        state=json.loads((self.root/'state.json').read_text())['gui:owner:conv:one']
        self.assertEqual(state['reply_day'],'2026-11-18')
    def test_old_backlog_and_very_new_bursts_are_ignored(self):
        for at in (self.now-1000,self.now):
            self.browser.latest['at']=at;self.run_job()
        self.assertEqual(self.client.calls,0);self.assertFalse(self.browser.sends)
    def test_manual_reply_during_generation_cancels_send(self):
        self.client=FakeClient(lambda:setattr(self.browser,'role','assistant'));self.run_job()
        self.assertFalse(self.browser.sends);self.assertEqual(self.browser.prepared,0)
    def test_newer_peer_message_cancels_stale_draft(self):
        self.client=FakeClient(lambda:self.browser.latest.update(id='incoming-2'));self.run_job()
        self.assertFalse(self.browser.sends)
    def test_editing_same_message_cancels_the_old_context(self):
        self.client=FakeClient(lambda:setattr(self.browser,'content','Tin đã sửa'))
        self.run_job();self.assertFalse(self.browser.sends)
    def test_switching_account_or_stopping_during_generation_cancels(self):
        state={'stop':False};self.client=FakeClient(lambda:state.update(stop=True));self.run_job(stop=lambda:state['stop'])
        self.assertFalse(self.browser.sends)
    def test_switching_account_during_generation_does_not_open_or_send(self):
        state={'owner':True};self.client=FakeClient(lambda:state.update(owner=False))
        self.run_job(owner=lambda:state['owner'])
        self.assertFalse(self.browser.sends);self.assertEqual(self.browser.prepared,0)
    def test_uncertain_ack_never_retries_or_sends_daily_fallback(self):
        self.browser.fail_send=True;self.run_job();self.run_job()
        self.assertEqual(len(self.browser.sends),1)
        self.assertEqual(json.loads((self.root/'state.json').read_text())['gui:owner:conv:one']['status'],'pending')
    def test_pending_daily_send_blocks_ai_reply(self):
        (self.root/'state.json').write_text(json.dumps({'gui:owner:conv:one':{'status':'pending'}}));self.run_job()
        self.assertEqual(self.client.calls,0)
    def test_one_minute_chat_cooldown_does_not_repeat_on_bursts(self):
        self.run_job();self.browser.latest.update(id='incoming-2',at=self.now-6);self.run_job()
        self.assertEqual(len(self.browser.sends),1)
        with patch('ai_reply.time.time',return_value=self.now+65):self.run_job()
        self.assertEqual(len(self.browser.sends),2)
    def test_candidate_outside_approved_chats_is_not_read(self):
        self.browser.latest['conversation_id']='other';self.run_job()
        self.assertEqual(self.client.calls,0)

if __name__=='__main__':unittest.main()
