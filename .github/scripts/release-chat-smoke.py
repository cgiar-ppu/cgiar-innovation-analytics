"""Exercise the real app WebSocket/model switch/tool path with a synthetic owner."""
import asyncio,json,time
import httpx,websockets
from synapsis.auth.tokens import create_access_token
from synapsis import config

async def main():
 owner='release-chat-qa-'+str(int(time.time()))
 token=create_access_token(owner,'Synthetic release chat QA','researcher',auth_source='sso',lifetime_seconds=900)
 results=[];sid=None
 async with websockets.connect('ws://localhost:7780/ws/chat?token='+token,open_timeout=30,max_size=8*1024*1024) as ws:
  async def until(kind,timeout=240):
   events=[]
   async with asyncio.timeout(timeout):
    while True:
     e=json.loads(await ws.recv());events.append(e)
     if e.get('type')=='error': raise RuntimeError('Application emitted an error: '+str(e.get('message',''))[:400])
     if e.get('type')==kind:return events
  await ws.send(json.dumps({'type':'new_session'}));ev=await until('session',90);sid=ev[-1]['session_id']
  async with httpx.AsyncClient() as c:
   r=await c.patch('http://localhost:7780/api/sessions/'+sid,headers={'Authorization':'Bearer '+token},json={'title':'[QA] September release model/tool verification'});assert r.status_code==200
  for model in ('claude-sonnet-5','claude-opus-5','claude-fable-5-1'):
   await ws.send(json.dumps({'type':'switch_model','model':model}));events=await until('model_switched',90);assert events[-1]['model']==model
   prompt='Release test: reply exactly MODEL_SWITCH_OK. Do not use tools or delegate for this acknowledgement.'
   if model=='claude-sonnet-5':prompt='Release test: use the prms_query tool to run SELECT 17 * 19 AS qa_product, then reply with 323. This is synthetic arithmetic, not an innovation count. Do not delegate.'
   await ws.send(json.dumps({'message':prompt}));events=await until('result')
   texts=''.join(e.get('content','') for e in events if e.get('type')=='text')
   tools=[e.get('tool','') for e in events if e.get('type')=='tool_use']
   assert ('323' if model=='claude-sonnet-5' else 'MODEL_SWITCH_OK') in texts,(model,'expected response missing',[e.get('type') for e in events])
   if model=='claude-sonnet-5':assert any('prms_query' in t for t in tools),(model,'PRMS tool was not called',tools)
   results.append({'model':model,'switch':'confirmed','response':'passed','tools':tools,'cost_usd':events[-1].get('estimated_cost')})
 print(json.dumps({'app_websocket_checks':results,'synthetic_session':sid}))
asyncio.run(main())
