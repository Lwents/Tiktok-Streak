/* Read-only access to the TikTok client's existing SDK. Never calls send/mark-read. */
async ({conversationId, cursor, limit = 50, cachedOnly = false, sentText, recoveryContext = false}) => {
  const row = document.querySelector('[data-e2e="dm-new-conversation-item"]');
  if (!row) return {error: 'chat_list_missing'};
  let fiber = row[Object.keys(row).find(key => key.startsWith('__reactFiber$'))];
  let sdk;
  for (let depth=0; fiber && depth<16 && !sdk; depth++, fiber=fiber.return) {
    let hook=fiber.memoizedState;
    for (let n=0; hook && n<80; n++,hook=hook.next) {
      const value=hook.memoizedState?.current;
      if (value?.instance && value?.stateStore && typeof value.instance.getConversationList === 'function') {
        sdk=value.instance; break;
      }
    }
  }
  if (!sdk) return {error:'messaging_sdk_unavailable'};
  const convs=sdk.getConversationList();
  const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone;
  const formatter=new Intl.DateTimeFormat('en-CA',{timeZone:timezone,year:'numeric',month:'2-digit',day:'2-digit'});
  const dayOf = at => {
    const parts=Object.fromEntries(formatter.formatToParts(new Date(at*1000)).map(part=>[part.type,part.value]));
    return `${parts.year}-${parts.month}-${parts.day}`;
  };
  const checkedAt=Date.now()/1000;
  if (!conversationId) return {
    timezone,today:dayOf(checkedAt),checked_at:checkedAt,
    conversations:convs.filter(conv=>(conv.isSingleChat || (conv.isGroupChat && conv.isMember !== false)) && !conv.isStrangerConversation).map(conv=>{
      const messages=conv.getMessageList(()=>true);
      return {conversation_id:conv.id,latest_at:Math.max(0,...messages.map(message=>Number(new Date(message.createdAt))/1000)),
        message_count:messages.length,unread_count:Number(conv.unreadCount),
        is_group:Boolean(conv.isGroupChat),participant_count:Number(conv.participantCount)||0};
    })
  };
  const conv=convs.find(conv=>conv.id===conversationId);
  if (!conv || conv.isStrangerConversation || (conv.isGroupChat && conv.isMember === false) ||
      (!conv.isSingleChat && !conv.isGroupChat && typeof sentText !== 'string')) return {error:'conversation_not_available'};
  const self=String(sdk.ctx.option.userId);
  const peer=String(conv.toParticipantUserId);
  const isGroup=Boolean(conv.isGroupChat);
  if (recoveryContext) return {conversation_id:conv.id,self_id:self,peer_user_id:peer,
    conversation_short_id:String(conv.shortId),is_group:isGroup,is_member:conv.isMember!==false};
  const directionOf=sender=>sender===self?'self':(isGroup?/^[1-9]\d*$/.test(sender):sender===peer)?'peer':'system';
  if (typeof sentText === 'string') {
    const matches=[];
    for(const message of conv.getMessageList(()=>true)) {
      if(String(message.sender)!==self || ![7,10001].includes(message.type))continue;
      let text=message.content;
      try { const parsed=JSON.parse(text); text=parsed.text ?? parsed.content ?? text; } catch {}
      if(text!==sentText)continue;
      matches.push({id:String(message.clientId||message.serverId||''),server_id:Boolean(message.serverId),
        state:Number.isFinite(message.flightStatus)?message.flightStatus:null,
        response_status:message.ext?.['s:send_response_status']??null});
    }
    return {matches};
  }
  let messages=[],hasMore=false,nextCursor;
  if(cachedOnly) {
    messages=conv.getMessageList(()=>true).map(message=>({
      id:String(message.serverId||''),type:message.type,
      at:Number(new Date(message.createdAt))/1000,
      sender_id:String(message.sender),direction:directionOf(String(message.sender)),
      scene:message.type===1?message.scene||'':'',
      valid:Boolean(message.serverId)&&message.visible&&!message.isRecalled
    }));
    hasMore=Boolean(conv.hasMoreMessages);
  } else {
    const L=conv.firstMessageIndex.constructor;
    const api=sdk.ctx.resolve('coreApi');
    const response=await api.GetMessagesByConversation({
      conversationId:conv.id,conversationShortId:L.fromString(conv.shortId),conversationType:conv.type,
      anchorIndex:cursor?L.fromString(cursor):conv.lastMessageIndex.add(L.fromNumber(1)),
      direction:1,limit,inboxType:conv.inboxType
    });
    if(response.status_code!==0)return {error:'history_request_failed',code:response.status_code};
    const body=response.body?.messages_in_conversation_body;
    if(!body || !Array.isArray(body.messages))return {error:'history_response_unavailable'};
    if(body.messages_pb?.length && !body.messages.length)return {error:'unsupported_history_encoding'};
    hasMore=Boolean(body.has_more);nextCursor=String(body.next_cursor);
    messages=body.messages.map(message=>{
      const value=Number(message.create_time);
      const at=value>1e12?value/1000:value;
      const sender=String(message.sender);
      return {id:String(message.server_message_id||''),type:message.message_type,at,
        sender_id:sender,direction:directionOf(sender),
        scene:message.message_type===1?message.scene||'':'',
        valid:message.status===0 && String(message.server_message_id||'0')!=='0' && message.ext?.['s:is_recalled']!=='1'};
    });
  }
  const finishedAt=Date.now()/1000;
  const midnight=new Date();midnight.setHours(24,0,0,0);
  return {conversation_id:conv.id,is_group:isGroup,timezone,today:dayOf(finishedAt),checked_at:finishedAt,day_ends_at:midnight.getTime()/1000,
    messages:messages.filter(message=>Number.isFinite(message.at)&&message.at>0).map(message=>({...message,day:dayOf(message.at)})),
    has_more:hasMore,next_cursor:nextCursor};
}
