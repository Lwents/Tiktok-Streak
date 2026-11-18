"""Restore contract and duplicate-attempt guards. No network requests are made."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from streak_recovery import RecoveryManager, restore_request, RESTORE_URL


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, result=None):
        self.requests=[];self.result=result or {'status_code':0,'current_window_restore_cnt':1}
    def open(self, request, timeout):
        self.requests.append(request)
        return Response(json.dumps(self.result).encode())


class RestoreChecks(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'recovery-state.json'
        self.manager=RecoveryManager(self.path)
        self.target={'conversation_id':'0:1:10:20'}
        self.evidence={'status':'unknown','recovery':{'status':'available','event_id':'end-1','ended_at':10,'deadline_at':172810}}
        self.proof={'status':'history_confirmed','restored':True,'marker_scene':'streak_new_recover_with_pet','marker_at':110}
        self.calls=0
    def tearDown(self):self.tmp.cleanup()
    def post(self):
        self.calls+=1
        return {'http_status':200,'status_code':0,'restore_count':1}
    def restore(self, request=None, verify=None, **kwargs):
        return self.manager.restore('owner','chrome',self.target,self.evidence,request or self.post,verify or (lambda:self.proof),now=kwargs.get('now',100))
    def test_confirmed_restore_uses_one_request_and_is_idempotent(self):
        self.assertEqual(self.restore()['status'],'restored')
        self.assertEqual(self.restore()['status'],'restored')
        self.assertEqual(self.calls,1)
        record=next(iter(json.loads(self.path.read_text()).values()))
        self.assertEqual(record['status'],'restored')
        self.assertNotIn('cookie',record)
    def test_timeout_is_saved_before_request_and_never_retried(self):
        def timeout():
            record=next(iter(json.loads(self.path.read_text()).values()))
            self.assertEqual(record['status'],'pending')
            self.calls+=1;raise TimeoutError()
        self.assertEqual(self.restore(request=timeout)['status'],'uncertain')
        self.assertEqual(self.restore(verify=lambda:{})['status'],'uncertain')
        self.assertEqual(self.calls,1)
    def test_late_acknowledgement_is_verified_without_another_post(self):
        self.assertEqual(self.restore(verify=lambda:{})['status'],'uncertain')
        self.assertEqual(self.restore()['status'],'restored')
        self.assertEqual(self.calls,1)
    def test_switching_browser_cannot_repeat_an_uncertain_restore(self):
        self.assertEqual(self.restore(verify=lambda:{})['status'],'uncertain')
        result=self.manager.restore('OWNER','msedge',self.target,self.evidence,self.post,lambda:{},now=101)
        self.assertEqual(result['status'],'uncertain')
        self.assertEqual(self.calls,1)
    def test_old_notice_or_http_200_without_success_cannot_claim_restore(self):
        old={**self.proof,'marker_at':1}
        self.assertEqual(self.restore(verify=lambda:old)['status'],'uncertain')
        self.assertEqual(self.calls,1)
    def test_known_failure_is_throttled_and_does_not_fake_success(self):
        def fail():
            self.calls+=1;return {'http_status':200,'status_code':5,'status_msg':'No restores available'}
        self.assertEqual(self.restore(request=fail)['status'],'failed')
        self.assertEqual(self.restore(request=fail)['status'],'failed')
        self.assertEqual(self.calls,1)
    def test_expired_or_missing_offers_never_post(self):
        self.assertEqual(self.restore(now=172811)['status'],'unavailable')
        self.evidence={}
        self.assertEqual(self.restore()['status'],'unavailable')
        self.assertEqual(self.calls,0)
        self.assertFalse(self.path.exists())
    def test_bad_ledger_fails_before_another_request(self):
        self.path.write_text('not-json')
        with self.assertRaises(ValueError):self.restore()
        self.assertEqual(self.calls,0)
    def test_verification_error_does_not_lose_ack_or_retry(self):
        def unavailable():raise RuntimeError('page loading')
        self.assertEqual(self.restore(verify=unavailable)['status'],'uncertain')
        self.assertEqual(self.restore()['status'],'restored')
        self.assertEqual(self.calls,1)
    def test_individual_transport_uses_form_not_json_and_filters_cookies(self):
        opener=Opener()
        context={'conversation_id':'0:1:10:20','self_id':'10','peer_user_id':'20','is_member':True,'is_group':False}
        cookies=[{'name':'sessionid','value':'fixture-session','domain':'.tiktok.com'},
                 {'name':'tracking','value':'not-needed','domain':'.tiktok.com'},
                 {'name':'sid_tt','value':'unrelated','domain':'foreign.example'}]
        result=restore_request(context,cookies,'fixture-UA',opener=opener)
        self.assertEqual(result['status_code'],0)
        request=opener.requests[0]
        self.assertEqual(request.full_url,RESTORE_URL)
        self.assertEqual(parse_qs(request.data.decode()),{'peer_user_id':['20']})
        self.assertEqual(request.get_header('Content-type'),'application/x-www-form-urlencoded')
        self.assertEqual(request.get_header('Cookie'),'sessionid=fixture-session')
    def test_group_transport_uses_group_short_id(self):
        opener=Opener()
        context={'conversation_id':'0:2:group','self_id':'10','is_member':True,'is_group':True,'conversation_short_id':'12345'}
        restore_request(context,[{'name':'sessionid','value':'fixture','domain':'.tiktok.com'}],'fixture-UA',opener=opener)
        self.assertEqual(parse_qs(opener.requests[0].data.decode()),{'peer_user_id':['0'],'conversation_short_id':['12345']})
    def test_mismatched_target_or_missing_auth_cannot_post(self):
        opener=Opener()
        context={'conversation_id':'0:1:10:30','self_id':'10','peer_user_id':'20','is_member':True}
        with self.assertRaises(ValueError):restore_request(context,[],'fixture-UA',opener=opener)
        context['conversation_id']='0:1:10:20'
        with self.assertRaises(ValueError):restore_request(context,[],'fixture-UA',opener=opener)
        self.assertFalse(opener.requests)

if __name__=='__main__':unittest.main()
