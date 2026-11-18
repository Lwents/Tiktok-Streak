/* Native video sharing, matching TikTok's own type-8 share composer. Caller journals first. */
async ({conversationId,expectedSelfId,expectedUsername,video,dryRun=false}) => {
  const row=document.querySelector('[data-e2e="dm-new-conversation-item"]');
  if(!row)return {error:'chat_list_missing'};
  let fiber=row[Object.keys(row).find(k=>k.startsWith('__reactFiber$'))],sdk;
  for(let d=0;fiber&&d<16&&!sdk;d++,fiber=fiber.return){let h=fiber.memoizedState;for(let n=0;h&&n<80;n++,h=h.next){const v=h.memoizedState?.current;if(v?.instance&&v?.stateStore&&typeof v.instance.getConversationList==='function'){sdk=v.instance;break;}}}
  const sameOwner=()=>{const link=document.querySelector('a[data-e2e="nav-profile"]');try{return decodeURIComponent(new URL(link.href,location.origin).pathname).replace(/^\/@/,'').replace(/\/$/,'').toLowerCase()===String(expectedUsername).toLowerCase()&&String(sdk.ctx.option.userId)===String(expectedSelfId)}catch{return false}};
  if(!sdk||!sameOwner())return {error:'account_mismatch'};
  const conv=sdk.getConversationList().find(c=>c.id===conversationId);
  const selected=document.querySelector('[data-e2e="dm-new-conversation-item"][aria-selected="true"]');
  if(!conv||conv.isStrangerConversation||conv.isMember===false||(!conv.isSingleChat&&!conv.isGroupChat)||selected?.getAttribute('data-conv-id')!==conversationId)return {error:'recipient_mismatch'};
  if(!/^\d{15,25}$/.test(String(video.id))||typeof sdk.createMessage!=='function'||typeof sdk.sendMessage!=='function')return {error:'video_share_unavailable'};
  const content={aweType:800,itemId:String(video.id),uid:String(video.author_id),secUID:video.author_sec_id||'',
    content_thumb:{url_list:[video.author_avatar||''],uri:video.author_avatar||''},content_name:video.author_name||'',
    cover_url:{url_list:[video.cover||''],uri:video.cover||''},cover_width:video.width||0,cover_height:video.height||0};
  if(dryRun)return {ready:true,conversation_id:conv.id,type:8,video_id:String(video.id),is_group:Boolean(conv.isGroupChat)};
  const message=await sdk.createMessage({conversation:conv,type:8,content:JSON.stringify(content)});
  if(!message)return {error:'create_video_failed'};
  if(!sameOwner())return {error:'account_changed'};
  const result=await Promise.race([sdk.sendMessage({message}),new Promise((_,reject)=>setTimeout(()=>reject(Error('video_ack_timeout')),25000))]);
  const id=[result?.serverMessageId,result?.payload?.serverId,message.serverId].map(x=>String(x??'')).find(x=>/^[1-9]\d*$/.test(x))||'';
  if(result?.success!==true||!id||id==='0')return {error:'video_not_confirmed',status_code:result?.statusCode??null};
  return {sent:true,server_id:id,conversation_id:conv.id,video_id:String(video.id)};
}
