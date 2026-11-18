"""Find public streak videos, inspect representative frames, and cache one choice per day."""
import json,re,time
from pathlib import Path
from urllib.parse import quote,urlsplit
from ai_client import AIClient,AIError
from streak import read_json,save_state


def video_url(value):
    parsed=urlsplit(value)
    match=re.fullmatch(r'/@[^/]+/video/(\d{15,25})/?',parsed.path)
    if parsed.scheme!='https' or parsed.hostname!='www.tiktok.com' or not match:
        raise ValueError('Link video phải là bài đăng TikTok hợp lệ.')
    return 'https://www.tiktok.com'+parsed.path.rstrip('/')


class VideoSelector:
    def __init__(self,root):self.root=Path(root);self.path=self.root/'video-state.json';self.failed_until=0

    def select(self,browser,owner,clock,query='chuỗi',stop=None,force=False):
        state=read_json(self.path,{})
        if not isinstance(state,dict):state={}
        cached=state.get('current',{})
        if not force and cached.get('owner')==owner and cached.get('day')==clock['day'] and cached.get('query')==query:
            return cached['video']
        if self.failed_until>time.time():raise AIError('Đang chờ trước khi thử tìm video lại.')
        seen={r['id'] for r in state.get('history',[]) if r.get('selected_at',0)>time.time()-7*86400}
        page=browser.context.new_page();page.set_default_timeout(12000)
        candidates=[]
        try:
            page.goto('https://www.tiktok.com/search?q='+quote(query),wait_until='domcontentloaded',timeout=30000)
            if stop is not None and stop.is_set():raise AIError('Đã dừng chọn video.')
            page.locator('a[href*="/video/"]').first.wait_for(state='attached',timeout=25000)
            links=page.locator('a[href*="/video/"]').evaluate_all('els=>[...new Set(els.map(el=>el.href))]')
            started=time.monotonic()
            for link in links[:8]:
                if time.monotonic()-started>90:break
                if stop is not None and stop.is_set():raise AIError('Đã dừng chọn video.')
                try:
                    link=video_url(link)
                    if link.rsplit('/',1)[-1] in seen:continue
                    candidate=self.inspect(page,link,browser,stop)
                    if candidate:candidates.append(candidate)
                except Exception:
                    continue
                if len(candidates)>=3:break
            if not candidates:raise AIError('Chưa đọc được video phù hợp từ kết quả tìm kiếm TikTok.')
            if stop is not None and stop.is_set():raise AIError('Đã dừng chọn video.')
            chosen=AIClient.from_root(self.root).choose_video(candidates)
            found=next((item for item in candidates if item['id']==chosen['video_id']),None)
            if not found:raise AIError('AI chưa chọn được video có trong kết quả đã kiểm tra.')
            video={k:v for k,v in found.items() if k!='frames'};video['reason']=chosen['reason']
            state['current']={'owner':owner,'day':clock['day'],'query':query,'video':video}
            state['history']=[r for r in state.get('history',[]) if r.get('selected_at',0)>time.time()-7*86400]
            state['history'].append({'id':video['id'],'selected_at':time.time()});save_state(self.path,state)
            return video
        except Exception:
            self.failed_until=time.time()+300
            raise
        finally:page.close()

    @staticmethod
    def inspect(page,url,browser=None,stop=None):
        import base64
        page.goto(video_url(url),wait_until='domcontentloaded',timeout=30000)
        if stop is not None and stop.is_set():raise AIError('Đã dừng chọn video.')
        page.locator('video').first.wait_for(state='visible',timeout=15000)
        if stop is not None and stop.is_set():raise AIError('Đã dừng chọn video.')
        if browser:browser.dismiss_sleep_reminder(page)
        data=page.evaluate('''()=>{let d={};try{d=JSON.parse(document.getElementById('__UNIVERSAL_DATA_FOR_REHYDRATION__')?.textContent||'{}')}catch{};const x=d.__DEFAULT_SCOPE__?.['webapp.video-detail']?.itemInfo?.itemStruct;if(!x)return null;return {id:String(x.id),caption:x.desc||'',duration:x.video?.duration||0,cover:x.video?.cover||'',width:x.video?.width||0,height:x.video?.height||0,author_id:String(x.author?.id||''),author_sec_id:x.author?.secUid||'',author_name:x.author?.nickname||'',author_avatar:x.author?.avatarThumb||'',private:Boolean(x.privateItem),ad:Boolean(x.isAd),story:Boolean(x.story)};}''')
        if not data or data['private'] or data['ad'] or data['story'] or not 0<data['duration']<=45:return None
        if data['id']!=url.rsplit('/',1)[-1]:return None
        frames=[];element=page.locator('video').first
        page.wait_for_function("()=>{const v=document.querySelector('video');return v&&v.readyState>=2&&Number.isFinite(v.duration)&&v.duration>0}",timeout=12000)
        for position in (.15,.5,.8):
            if stop is not None and stop.is_set():raise AIError('Đã dừng chọn video.')
            element.evaluate('(el,p)=>{el.muted=true;el.pause();if(Number.isFinite(el.duration))el.currentTime=el.duration*p;}',position)
            page.wait_for_timeout(500)
            frame=element.screenshot(type='jpeg',quality=55)
            if len(frame)>600000:raise AIError('Khung hình video quá lớn để phân tích.')
            frames.append('data:image/jpeg;base64,'+base64.b64encode(frame).decode())
        return {**data,'url':url,'frames':frames}
