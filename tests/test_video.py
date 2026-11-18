import io,json,unittest
from ai_client import AIClient,AIError
from video_streak import video_url
class Opener:
    def __init__(self,text):self.text=text;self.request=None
    def open(self,request,timeout):
        self.request=request
        return io.BytesIO(json.dumps({'choices':[{'message':{'content':self.text},'finish_reason':'stop'}]}).encode())
class VideoChecks(unittest.TestCase):
    def test_only_public_tiktok_video_links_are_allowed(self):
        valid='https://www.tiktok.com/@fixture/video/7000000000000000001'
        self.assertEqual(video_url(valid+'?tracking=1'),valid)
        for value in ('file:///etc/passwd','https://foreign.example/@x/video/7000000000000000001','https://www.tiktok.com/@user/photo/7000000000000000001'):
            with self.assertRaises(ValueError):video_url(value)
    def test_ai_selects_only_from_inspected_candidates_and_receives_frames(self):
        opener=Opener('{"suitable":true,"video_id":"one","reason":"Video vui vẻ có chữ giữ chuỗi"}')
        client=AIClient({'base_url':'https://ai.example/v1','model':'test','api_key':'fixture-key'},opener=opener)
        result=client.choose_video([{'id':'one','caption':'Chuỗi','duration':6,'frames':['data:image/jpeg;base64,fixture']}])
        self.assertEqual(result['video_id'],'one')
        body=json.loads(opener.request.data)
        self.assertEqual(body['messages'][1]['content'][1]['type'],'image_url')
    def test_uninspected_ai_id_is_rejected(self):
        opener=Opener('{"suitable":true,"video_id":"uninspected","reason":"x"}')
        client=AIClient({'base_url':'https://ai.example/v1','model':'test','api_key':'fixture-key'},opener=opener)
        with self.assertRaises(AIError):client.choose_video([{'id':'one','caption':'chuỗi','duration':6,'frames':[]}])
if __name__=='__main__':unittest.main()
