"""Reply to fresh incoming text once; retain uncertain sends across restarts."""
import hashlib
import json
import time
from pathlib import Path
from ai_client import AIClient, DEFAULT_STYLE
from streak import read_json, save_state


class AIReplies:
    def __init__(self, root, emit):
        self.root=Path(root);self.path=self.root/'ai-replies.json';self.emit=emit
        self.next_provider_attempt=0

    def process(self,browser,payload,account_matches,stopped):
        if stopped() or time.time()<self.next_provider_attempt:return
        owner=payload['account_username']
        targets={t['conversation_id']:t for t in payload['targets'] if t.get('conversation_id') and t.get('streak_status') in ('verified','history_confirmed')}
        candidates=browser.reply_candidates(list(targets.values()))
        records=read_json(self.path,{})
        now=time.time()
        if not isinstance(records,dict):raise RuntimeError('Chưa đọc được sổ trả lời AI; đã khóa gửi để tránh lặp.')
        style=payload.get('ai_style',DEFAULT_STYLE);provider=None;handled=0
        for candidate in sorted(candidates,key=lambda c:c['at']):
            if stopped() or handled>=3:break
            now=time.time();at=candidate['at']
            if not max(payload.get('ai_started_at',now),now-86400)<=at<=now-5:continue
            target=targets.get(candidate['conversation_id'])
            if not target:continue
            key=hashlib.sha256(json.dumps([owner.casefold(),candidate['conversation_id'],candidate['id']]).encode()).hexdigest()
            record=records.get(key,{})
            if record.get('status') in ('pending','sent') or record.get('retry_after',0)>now:continue
            if any(r.get('owner')==owner and r.get('conversation_id')==candidate['conversation_id'] and r.get('sent_at',0)>now-60 for r in records.values()):continue
            state_path=self.root/'state.json';common=read_json(state_path,{})
            common_key='gui:'+owner.casefold()+':'+target['key']
            if common.get(common_key,{}).get('status')=='pending' or common.get('gui:'+target['key'],{}).get('status')=='pending':continue
            attempted=False
            try:
                if not account_matches():break
                context=browser.chat_context(candidate['conversation_id'])
                if not self.matches(context,candidate):continue
                self.emit('status',{'busy':True,'operation':'ai_reply'})
                provider=provider or AIClient.from_root(self.root)
                context_signature=self.context_signature(context)
                signature=hashlib.sha256((provider.base_url+provider.model+style+context_signature).encode()).hexdigest()
                text=record.get('text') if record.get('signature')==signature else None
                if not text:
                    text=provider.reply(context['messages'],style,is_group=bool(target.get('is_group')))
                    records[key]={'owner':owner,'conversation_id':candidate['conversation_id'],'trigger_id':candidate['id'],
                                  'status':'draft','text':text,'signature':signature,'created_at':now}
                    save_state(self.path,records)
                if stopped() or not account_matches():break
                fresh=browser.chat_context(candidate['conversation_id'])
                if not self.matches(fresh,candidate) or self.context_signature(fresh)!=context_signature:continue
                browser.prepare(target)
                if stopped() or not account_matches():break
                fresh=browser.chat_context(candidate['conversation_id'])
                if not self.matches(fresh,candidate) or self.context_signature(fresh)!=context_signature:continue
                current=browser.reply_candidates([target])
                if not any(c['id']==candidate['id'] for c in current):continue
                clock=browser.day_clock()
                records[key].update(status='pending',attempt_at=time.time());save_state(self.path,records)
                common[common_key]={'status':'pending','attempt_at':time.time(),'name':target['name'],'source':'ai','trigger_id':candidate['id']}
                save_state(state_path,common);attempted=True
                browser.send(text)
                sent_at=time.time();records[key].update(status='sent',sent_at=sent_at)
                save_state(self.path,records)
                common[common_key]={'status':'sent','sent_at':sent_at,'name':target['name'],'source':'ai'}
                after=browser.day_clock()
                if after['day']==clock['day'] and after['timezone']==clock['timezone']:
                    common[common_key].update(reply_day=after['day'],reply_timezone=after['timezone'])
                    self.emit('reply',{'key':target['key'],'account_username':owner,'reply':{**after,'status':'replied','sent_at':sent_at}})
                save_state(state_path,common)
                self.emit('ai_sent',{'key':target['key'],'at':sent_at})
                self.emit('log',f"AI đã trả lời tin mới trong chat: {target['name']}.")
                handled+=1
            except Exception as error:
                if attempted:
                    self.emit('log',f"Chưa rõ kết quả trả lời AI cho {target['name']}; đã khóa gửi lặp.")
                else:
                    old=records.get(key,{})
                    records[key]={**old,'owner':owner,'conversation_id':candidate['conversation_id'],
                                  'status':'failed','retry_after':time.time()+120,'created_at':old.get('created_at',now)}
                    save_state(self.path,records)
                    self.emit('log',f"AI chưa trả lời được {target['name']}: {str(error).splitlines()[0]}")
                    self.next_provider_attempt=time.time()+30
                break
        # Old completed drafts are unnecessary; uncertain sends remain locked.
        keep={k:r for k,r in records.items() if r.get('status')=='pending' or r.get('sent_at',r.get('created_at',now))>time.time()-7*86400}
        if len(keep)!=len(records):save_state(self.path,keep)

    @staticmethod
    def matches(context,candidate):
        messages=context.get('messages') or []
        return bool(messages and messages[-1]['id']==candidate['id'] and messages[-1]['role']=='user'
                    and messages[-1].get('content','').strip() and messages[-1]['content']!='[Tệp đính kèm]')

    @staticmethod
    def context_signature(context):
        fields=[(m['id'],m['role'],m['content']) for m in context.get('messages',[])]
        return hashlib.sha256(json.dumps(fields,ensure_ascii=False).encode()).hexdigest()
